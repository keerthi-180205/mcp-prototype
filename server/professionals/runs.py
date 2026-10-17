"""Background finder runs: start, poll, read results. One run at a time, because every run spends credits."""

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, Optional

from pydantic import ValidationError

from server.professionals.finder import ProfessionalFinder
from server.professionals.models import FinderParams
from server.professionals.queries import estimate
from server.storage import professionals as store

logger = logging.getLogger("mcp_server.professionals.runs")


class RunError(ValueError):
    """Invalid request or a run is already in progress."""


class ProfessionalRunManager:
    def __init__(self, db_path: Optional[str] = None, finder_factory: Optional[Callable[[Optional[str]], ProfessionalFinder]] = None):
        self.db_path = db_path
        self.finder_factory = finder_factory or (lambda db: ProfessionalFinder(db_path=db))
        self._tasks: Dict[str, "asyncio.Task[None]"] = {}

    # ---- lifecycle ---------------------------------------------------------------------------
    def start(self, **params: Any) -> Dict[str, Any]:
        try:
            p = FinderParams(**params)
        except ValidationError as exc:
            raise RunError("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from exc
        if any(not t.done() for t in self._tasks.values()):
            raise RunError("a finder run is already in progress; wait for it to finish (runs spend search credits)")
        run_id = f"pro_{uuid.uuid4().hex[:10]}"
        store.create_run(run_id, p.model_dump(), self.db_path)
        self._tasks[run_id] = asyncio.create_task(self._run(run_id, p))
        return {
            "run_id": run_id,
            "status": "running",
            "params": p.model_dump(),
            "estimate": estimate(p),
            "message": "Search started in the background. Poll the run status, then review the results; "
                       "nothing is exportable until a person approves it.",
        }

    async def wait(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task:
            await task

    async def _run(self, run_id: str, p: FinderParams) -> None:
        def on_progress(info: Dict[str, Any]) -> None:
            try:
                store.update_run(run_id, progress=info, db_path=self.db_path)
            except Exception:  # progress is cosmetic
                logger.debug("could not store progress", exc_info=True)

        try:
            result = await self.finder_factory(self.db_path).run(p, run_id=run_id, on_progress=on_progress)
            stats, notes = result["stats"], result["notes"]
            nothing = stats.get("candidates", 0) == 0
            failed = nothing and bool(stats.get("search_fatal") or stats.get("queries_failed"))
            store.update_run(
                run_id, status="failed" if failed else "completed", progress={"phase": "done"},
                stats={**stats, "notes": notes}, error=(notes[0] if notes else "no search succeeded") if failed else None,
                db_path=self.db_path,
            )
        except Exception as exc:
            logger.exception("Finder run %s crashed", run_id)
            store.update_run(run_id, status="failed", error=f"{type(exc).__name__}: {str(exc)[:240]}", db_path=self.db_path)

    # ---- queries ---------------------------------------------------------------------------------
    def status(self, run_id: str) -> Dict[str, Any]:
        run = store.get_run(run_id, self.db_path)
        if run is None:
            raise RunError(f"unknown run_id: {run_id}")
        task = self._tasks.get(run_id)
        active = task is not None and not task.done()
        if run["status"] == "running" and not active:
            run["status"] = "interrupted"   # the server restarted while it was running
        run["finished"] = run["status"] != "running"
        run["counts_by_review_status"] = store.counts_by_status(self.db_path)
        return run
