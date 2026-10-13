"""Async collection jobs: start in the background, poll progress, read results."""

import asyncio
import datetime
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from server.collection.collectors.base import PlatformCollector
from server.collection.harvester import harvest_platform
from server.collection.models import (
    SUPPORTED_PLATFORMS,
    CollectionLimits,
    CommentRow,
    PlatformProgress,
    QueryPlan,
)
from server.collection.planner import plan_query
from server.collection.registry import get_collector, normalize_platforms
from server.storage import comments as store

logger = logging.getLogger("mcp_server.collection.jobs")

MAX_RUNNING_JOBS = 3
MAX_TARGET = 5000

_FINISHED = {"completed", "partial", "failed"}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class JobError(ValueError):
    """Invalid request (bad arguments, unknown job, too many running jobs)."""


class _Job:
    def __init__(self, job_id: str, topic: str, platforms: List[str], limits: CollectionLimits):
        self.job_id = job_id
        self.topic = topic
        self.platforms = platforms
        self.limits = limits
        self.status = "running"
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.plan: Optional[QueryPlan] = None
        self.progress: Dict[str, PlatformProgress] = {
            p: PlatformProgress(platform=p, target=limits.target_comments) for p in platforms
        }
        self.usage: Dict[str, Any] = {}
        self.task: Optional["asyncio.Task[None]"] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "topic": self.topic,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "plan": self.plan.model_dump() if self.plan else None,
            "usage": self.usage,
            "platforms": {p: pr.model_dump() for p, pr in self.progress.items()},
        }


class CollectionJobManager:
    def __init__(
        self,
        db_path: Optional[str] = None,
        collector_factory: Callable[[str], PlatformCollector] = get_collector,
        use_llm_planner: bool = True,
    ):
        self.db_path = db_path
        self.collector_factory = collector_factory
        self.use_llm_planner = use_llm_planner
        self._jobs: Dict[str, _Job] = {}

    # ---- lifecycle -----------------------------------------------------------------
    def start(
        self,
        topic: str,
        platforms: Optional[List[str]] = None,
        target_comments: int = 500,
        max_posts: int = 30,
        max_minutes: float = 10.0,
    ) -> Dict[str, Any]:
        topic = " ".join((topic or "").split())
        if not topic:
            raise JobError("topic must not be empty")
        if len(topic) > 200:
            raise JobError("topic is too long (max 200 characters)")
        chosen = normalize_platforms(platforms)
        if not chosen:
            raise JobError(f"no supported platform requested; choose from {SUPPORTED_PLATFORMS}")
        if sum(1 for j in self._jobs.values() if j.status == "running") >= MAX_RUNNING_JOBS:
            raise JobError(f"too many collection jobs running (max {MAX_RUNNING_JOBS}); wait for one to finish")

        limits = CollectionLimits(
            target_comments=max(1, min(int(target_comments), MAX_TARGET)),
            max_posts=max(1, min(int(max_posts), 100)),
            max_seconds=max(30.0, min(float(max_minutes), 30.0) * 60.0),
        )
        job = _Job(f"job_{uuid.uuid4().hex[:10]}", topic, chosen, limits)
        self._jobs[job.job_id] = job
        store.create_job(
            job.job_id, topic, job.created_at,
            {"platforms": chosen, **limits.model_dump()}, db_path=self.db_path,
        )
        job.task = asyncio.create_task(self._run(job))
        return {
            "job_id": job.job_id,
            "status": job.status,
            "topic": topic,
            "platforms": chosen,
            "target_comments_per_platform": limits.target_comments,
            "message": "Collection started in the background. Poll get_collection_status(job_id); "
                       "it usually takes a few minutes.",
        }

    async def wait(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job and job.task:
            await job.task

    def _persist(self, job: _Job) -> None:
        try:
            store.update_job(job.job_id, job.status, job.snapshot()["platforms"], job.finished_at, db_path=self.db_path)
        except Exception:  # persistence must never break a collection
            logger.exception("Could not persist job %s", job.job_id)

    async def _run(self, job: _Job) -> None:
        try:
            job.plan = await plan_query(job.topic, use_llm=self.use_llm_planner)
            self._persist(job)
            await asyncio.gather(*[self._run_platform(job, p) for p in job.platforms])
        except Exception:
            logger.exception("Collection job %s crashed", job.job_id)
        finally:
            statuses = [pr.status for pr in job.progress.values()]
            if all(s == "done" for s in statuses):
                job.status = "completed"
            elif any(s == "done" for s in statuses):
                job.status = "partial"
            else:
                job.status = "failed"
            job.finished_at = _now()
            self._persist(job)

    async def _run_platform(self, job: _Job, platform: str) -> None:
        progress = job.progress[platform]
        started = time.monotonic()

        def _sink(post_url: str, rows: List[CommentRow]) -> None:
            store.save_comments(job.job_id, rows, db_path=self.db_path)
            self._persist(job)

        try:
            collector = self.collector_factory(platform)
        except Exception as exc:
            progress.status, progress.stop_reason, progress.error = "failed", "error", str(exc)[:200]
            return
        try:
            await harvest_platform(collector, job.plan or QueryPlan(topic=job.topic), job.limits, progress, on_rows=_sink)
        finally:
            progress.elapsed_seconds = round(time.monotonic() - started, 1)
            usage = getattr(collector, "usage", None)
            if callable(usage):
                job.usage[platform] = usage()
            self._persist(job)

    # ---- queries -------------------------------------------------------------------
    def _state(self, job_id: str) -> Dict[str, Any]:
        job = self._jobs.get(job_id)
        if job:
            return job.snapshot()
        saved = store.get_job(job_id, db_path=self.db_path)
        if not saved:
            raise JobError(f"unknown job_id: {job_id}")
        status = saved["status"]
        if status == "running":  # server restarted while it was running
            status = "interrupted"
        return {
            "job_id": job_id, "topic": saved["topic"], "status": status,
            "created_at": saved["created_at"], "finished_at": saved["finished_at"],
            "platforms": saved["progress"], "plan": None, "usage": {},
        }

    def status(self, job_id: str) -> Dict[str, Any]:
        state = self._state(job_id)
        counts = store.count_by_platform(job_id, db_path=self.db_path)
        lines = []
        for plat, pr in state["platforms"].items():
            pr["comments_collected"] = counts.get(plat, pr.get("comments_collected", 0))
            tail = f" - {pr.get('stop_reason')}" if pr.get("stop_reason") else ""
            err = f" ({pr['error']})" if pr.get("error") else ""
            lines.append(f"{plat}: {pr['comments_collected']}/{pr.get('target', 0)} [{pr['status']}{tail}]{err}")
        state["total_comments"] = sum(counts.values())
        state["finished"] = state["status"] in _FINISHED or state["status"] == "interrupted"
        state["summary"] = " | ".join(lines)
        return state

    def results(self, job_id: str, page: int = 1, page_size: int = 25, platform: Optional[str] = None) -> Dict[str, Any]:
        state = self.status(job_id)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        platform = normalize_platforms([platform])[0] if platform else None
        counts = store.count_by_platform(job_id, db_path=self.db_path)
        total = counts.get(platform, 0) if platform else sum(counts.values())
        rows = store.get_comments(job_id, platform, (page - 1) * page_size, page_size, db_path=self.db_path)

        def _short(r: Dict[str, Any]) -> Dict[str, Any]:
            return {**r, "comment": r["comment"] if len(r["comment"]) <= 300 else r["comment"][:297] + "..."}

        shortfalls = {
            p: {"collected": counts.get(p, 0), "target": pr.get("target"), "reason": pr.get("stop_reason"), "error": pr.get("error")}
            for p, pr in state["platforms"].items()
            if counts.get(p, 0) < (pr.get("target") or 0)
        }
        return {
            "job_id": job_id,
            "topic": state["topic"],
            "status": state["status"],
            "finished": state["finished"],
            "summary": state["summary"],
            "counts_per_platform": counts,
            "total_comments": sum(counts.values()),
            "below_target": shortfalls,
            "top_comments": {p: [_short(r) for r in rs] for p, rs in store.top_comments(job_id, 3, db_path=self.db_path).items()},
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
            "rows": [_short(r) for r in rows],
        }
