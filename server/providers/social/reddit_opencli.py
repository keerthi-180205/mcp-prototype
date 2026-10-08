"""Reddit provider using OpenCLI."""

import asyncio
import json
import logging
import shutil
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from server.models import (
    NormalizedSocialRecord,
    SocialAuthor,
    SocialInteraction,
    SocialContent,
    SocialEngagement,
    ProvenanceMetadata,
)
from server.providers.social.base import SocialDataProvider

logger = logging.getLogger("mcp_server.providers.social.reddit")

class RedditOpenCLIProvider(SocialDataProvider):
    """Reddit provider using OpenCLI to fetch data."""
    
    platform_name = "reddit"
    provider_name = "opencli"

    def is_available(self) -> bool:
        """Check if opencli is installed and configured."""
        return shutil.which("opencli") is not None

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        if not self.is_available():
            logger.warning("opencli not installed, cannot search reddit")
            return []

        try:
            cmd = ["opencli", "reddit", "search", query, "-f", "json"]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8.0)
            
            if proc.returncode != 0:
                err_msg = stderr.decode().strip()
                logger.error(f"opencli reddit search failed (code {proc.returncode}): {err_msg}")
                return []
                
            out_str = stdout.decode().strip()
            if not out_str:
                return []
                
            data = json.loads(out_str)
            records = []
            
            for item in data[:limit]:
                post_id = item.get("id")
                
                # Convert UTC timestamp if available
                created_utc = item.get("created_utc")
                pub_time = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat() if created_utc else datetime.now(timezone.utc).isoformat()
                
                record = NormalizedSocialRecord(
                    record_id=f"reddit:{post_id}",
                    platform=self.platform_name,
                    content_type="post",
                    source_url=item.get("url", f"https://reddit.com/comments/{post_id}"),
                    content_id=post_id,
                    published_at=pub_time,
                    author=SocialAuthor(
                        username=item.get("author", ""),
                        display_name=item.get("author", ""),
                    ),
                    content=SocialContent(
                        title=item.get("title", ""),
                        text=item.get("selftext", ""),
                    ),
                    engagement=SocialEngagement(
                        likes=item.get("score", 0),
                        comments=item.get("comments", 0),
                    ),
                    metadata=ProvenanceMetadata(
                        source_platform=self.platform_name,
                        source_provider=self.provider_name,
                        backend_tool="opencli",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        source_url=item.get("url", ""),
                        provider_metadata={"subreddit": item.get("subreddit", "")}
                    )
                )
                records.append(record)
                
            return records
            
        except asyncio.TimeoutError:
            logger.error("opencli reddit search timed out")
            return []
        except Exception as e:
            logger.error(f"Exception executing opencli reddit search: {e}")
            return []

    async def get_content(self, content_url_or_id: str) -> Optional[NormalizedSocialRecord]:
        return None

    async def get_comments(
        self, content_url_or_id: str, limit: int = 20
    ) -> List[SocialInteraction]:
        if not self.is_available():
            return []
            
        try:
            cmd = ["opencli", "reddit", "read", content_url_or_id, "-f", "json"]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8.0)
            
            if proc.returncode != 0:
                err_msg = stderr.decode().strip()
                logger.error(f"opencli reddit read failed (code {proc.returncode}): {err_msg}")
                return []
                
            out_str = stdout.decode().strip()
            if not out_str:
                return []
                
            data = json.loads(out_str)
            interactions = []
            count = 0
            
            for item in data:
                # OpenCLI read outputs tree levels as L0, L1, L2
                if item.get("type") in ["L0", "L1", "L2", "L3", "L4", "L5"]:
                    author = item.get("author", "").strip()
                    text = item.get("text", "").strip()
                    
                    if not author:
                        continue
                        
                    interaction = SocialInteraction(
                        type="comment",
                        text=text,
                        author=SocialAuthor(
                            username=author,
                            display_name=author,
                        ),
                        created_at=datetime.now(timezone.utc).isoformat(),
                        likes=item.get("score", 0),
                    )
                    interactions.append(interaction)
                    count += 1
                    
                    if count >= limit:
                        break
                        
            return interactions
            
        except asyncio.TimeoutError:
            logger.error("opencli reddit read timed out")
            return []
        except Exception as e:
            logger.error(f"Exception executing opencli reddit read: {e}")
            return []

    async def get_profile(self, identifier: str) -> Optional[SocialAuthor]:
        return None
