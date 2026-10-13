"""Gemini-powered natural language query processor and social intelligence synthesizer.

Processes user queries into structured discovery parameters, extracts clean topics,
search keywords, target platforms, and intent, and synthesizes multi-platform findings.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from server.config import get_settings

logger = logging.getLogger("mcp_server.services.query_processor")

SUPPORTED_PLATFORMS = ["youtube", "reddit", "instagram", "twitter", "linkedin"]


class ProcessedQuery(BaseModel):
    clean_topic: str = Field(description="Clean, normalized topic/entity without filler words")
    search_keywords: List[str] = Field(default_factory=list, description="Targeted keywords/hashtags for searching social media APIs")
    target_platforms: List[str] = Field(default_factory=lambda: ["youtube", "reddit", "instagram", "twitter", "linkedin"], description="Platforms explicitly requested or best suited for query")
    intent: str = Field(default="trend_analysis", description="Detected intent: customer_pain_points | reviews_and_feedback | lead_generation | trend_analysis | general_chat")
    user_goal: str = Field(default="", description="Concise explanation of what the user is trying to discover")
    ai_response: str = Field(default="", description="Conversational AI response acknowledging the request and research plan")
    qualification_tags: List[str] = Field(default_factory=list, description="Criteria tags to score relevant comments/profiles")


class GeminiQueryProcessor:
    """Intelligent query understanding and social synthesis powered by Google Gemini API."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
        self.preferred_model = model or settings.gemini_model or os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
        self._candidate_models = [
            self.preferred_model,
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-3.8-flash",
        ]
        # Deduplicate while preserving order
        seen = set()
        self.models_to_try = [m for m in self._candidate_models if not (m in seen or seen.add(m))]
        self._client = None

    def _get_client(self):
        if not self.api_key:
            return None
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning("Failed to initialize google.genai Client: %s", e)
                return None
        return self._client

    async def process_user_query(
        self,
        query: str,
        fallback_field: str = "",
        connected_platforms: Optional[List[str]] = None,
    ) -> ProcessedQuery:
        """
        Process user natural language query using Gemini LLM into structured discovery plan.
        Falls back seamlessly to smart rule-based extraction if Gemini is unavailable.
        """
        raw_text = (query or "").strip()
        if not raw_text and fallback_field:
            raw_text = fallback_field.strip()

        if not raw_text:
            return ProcessedQuery(
                clean_topic="Trending Discussions",
                search_keywords=["trending"],
                target_platforms=connected_platforms or SUPPORTED_PLATFORMS,
                intent="trend_analysis",
                user_goal="Discover trending social media conversations",
                ai_response="I'm ready to research trending topics and public discussions across platforms.",
            )

        client = self._get_client()
        if client:
            try:
                processed = await self._call_gemini_query_parser(raw_text, connected_platforms)
                if processed and processed.clean_topic:
                    return processed
            except Exception as exc:
                logger.warning("Gemini query parser encountered error (%s), using rule-based fallback", exc)

        return self._fallback_rule_processing(raw_text, connected_platforms)

    async def _call_gemini_query_parser(
        self,
        query: str,
        connected_platforms: Optional[List[str]] = None,
    ) -> Optional[ProcessedQuery]:
        """Call Gemini to extract topic, keywords, platforms, intent, and generate AI response."""
        client = self._get_client()
        if not client:
            return None

        available_plat_str = ", ".join(connected_platforms) if connected_platforms else "YouTube, Reddit, Instagram, Twitter/X, LinkedIn"

        system_prompt = (
            "You are the Social Intelligence & Query Processing AI for SocialRadar.\n"
            "Your role is to deeply understand user search prompts and social media data requests.\n"
            f"Available platforms: {available_plat_str}.\n\n"
            "Analyze the user's message and output ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "clean_topic": "concise core entity or topic name (e.g. \\"iPhone 16 Thermals\\", \\"Electric Vehicles\\", \\"Fitness Motivation\\")",\n'
            '  "search_keywords": ["keyword 1", "keyword 2", "hashtag"],\n'
            '  "target_platforms": ["youtube", "reddit", "instagram", "twitter", "linkedin"],\n'
            '  "intent": "customer_pain_points" | "reviews_and_feedback" | "lead_generation" | "trend_analysis" | "general_chat",\n'
            '  "user_goal": "A single sentence stating what the user wants to understand or find",\n'
            '  "ai_response": "An articulate, friendly 1-2 sentence response explaining what data we will explore",\n'
            '  "qualification_tags": ["Tag 1", "Tag 2"]\n'
            "}\n\n"
            "Rules:\n"
            "- If the user explicitly mentions specific platforms (e.g. 'on reddit and youtube'), target ONLY those in target_platforms.\n"
            "- If no platforms are mentioned, include all relevant platforms.\n"
            "- 'clean_topic' MUST be clean and free of request filler (NO 'find comments on', 'what are people saying about', etc.).\n"
            f"User query: \"{query}\"\n\n"
            "JSON:"
        )

        def _sync_call(model_name: str) -> str:
            resp = client.models.generate_content(model=model_name, contents=system_prompt)
            return resp.text or ""

        for model_name in self.models_to_try:
            try:
                raw_out = await asyncio.wait_for(asyncio.to_thread(_sync_call, model_name), timeout=15.0)
                json_match = re.search(r"\{.*\}", raw_out, re.DOTALL)
                if not json_match:
                    continue
                data = json.loads(json_match.group(0))

                clean_topic = str(data.get("clean_topic") or "").strip()
                if not clean_topic:
                    continue

                platforms = [p.lower().strip() for p in data.get("target_platforms", []) if p.lower().strip() in SUPPORTED_PLATFORMS]
                if not platforms:
                    platforms = connected_platforms or SUPPORTED_PLATFORMS

                return ProcessedQuery(
                    clean_topic=clean_topic,
                    search_keywords=[str(k).strip() for k in data.get("search_keywords", [clean_topic]) if str(k).strip()],
                    target_platforms=platforms,
                    intent=str(data.get("intent", "trend_analysis")),
                    user_goal=str(data.get("user_goal", f"Research {clean_topic} discussions")),
                    ai_response=str(data.get("ai_response", f"Analyzing public discussions about {clean_topic}.")),
                    qualification_tags=[str(t).strip() for t in data.get("qualification_tags", []) if str(t).strip()],
                )
            except Exception as e:
                logger.debug("Gemini query parse attempt with model %s failed: %s", model_name, e)
                continue

        return None

    def _fallback_rule_processing(
        self,
        query: str,
        connected_platforms: Optional[List[str]] = None,
    ) -> ProcessedQuery:
        """Heuristic rule-based fallback when LLM is unavailable."""
        q_lower = query.lower()

        # Detect platforms mentioned
        target_platforms = []
        if "youtube" in q_lower or "yt" in q_lower:
            target_platforms.append("youtube")
        if "reddit" in q_lower or "subreddit" in q_lower:
            target_platforms.append("reddit")
        if "instagram" in q_lower or "reel" in q_lower or "insta" in q_lower:
            target_platforms.append("instagram")
        if "twitter" in q_lower or " x " in f" {q_lower} " or "tweet" in q_lower:
            target_platforms.append("twitter")
        if "linkedin" in q_lower:
            target_platforms.append("linkedin")

        if not target_platforms:
            target_platforms = connected_platforms or SUPPORTED_PLATFORMS

        # Clean topic: remove common prompt preambles
        cleaned = re.sub(
            r"^(find|show|tell|search|get|collect|analyze|look for|what are people saying about|who commented on|give me comments on|fetch comments for)\s+",
            "",
            query,
            flags=re.IGNORECASE,
        ).strip()

        # Remove platform mentions from topic
        cleaned = re.sub(r"\b(on|from|across)\s+(youtube|reddit|instagram|twitter|x|linkedin|all platforms?)\b", "", cleaned, flags=re.IGNORECASE).strip()

        # Remove trailing/leading punctuation
        cleaned = re.sub(r"^[\s\"']+|[\s\"'\?!.]+$", "", cleaned).strip()

        if not cleaned:
            cleaned = "Trending Topics"

        # Determine intent
        intent = "trend_analysis"
        if any(w in q_lower for w in ["complain", "hate", "issue", "problem", "broken", "worst", "bug"]):
            intent = "customer_pain_points"
        elif any(w in q_lower for w in ["review", "opinion", "rating", "think", "good", "pros", "cons"]):
            intent = "reviews_and_feedback"
        elif any(w in q_lower for w in ["buy", "hire", "pricing", "cost", "lead", "client"]):
            intent = "lead_generation"

        plat_str = ", ".join(p.capitalize() for p in target_platforms)
        return ProcessedQuery(
            clean_topic=cleaned.title(),
            search_keywords=[cleaned, cleaned.replace(" ", "")],
            target_platforms=target_platforms,
            intent=intent,
            user_goal=f"Collect and analyze public conversations about {cleaned.title()}",
            ai_response=f"Analyzing trending posts and comments for '{cleaned.title()}' across {plat_str}.",
            qualification_tags=[f"{cleaned.title()} Discussion", intent.replace("_", " ").title()],
        )

    async def synthesize_social_insights(
        self,
        topic: str,
        comments: List[Dict[str, Any]],
        user_query: str = "",
    ) -> str:
        """
        Use Gemini to synthesize collected multi-platform comments into an intelligent,
        executive summary covering sentiment, themes, and community voices.
        """
        client = self._get_client()
        if not client or not comments:
            return self._fallback_summary(topic, comments)

        # Prepare sanitized samples of comments (up to 15 comments)
        sample_snippets = []
        for c in comments[:15]:
            plat = c.get("platform", "Social")
            u = c.get("user_name") or c.get("username", "user")
            txt = (c.get("comment") or c.get("comment_text", "")).strip()
            if txt:
                # Truncate comment text safely
                sample_snippets.append(f"[{plat}] {u}: \"{txt[:180]}\"")

        comments_block = "\n".join(sample_snippets)

        prompt = (
            "You are SocialRadar AI, an elite social media intelligence analyst.\n"
            f"Subject: {topic}\n"
            f"User Query: {user_query or topic}\n\n"
            "Below is a curated sample of live, real public comments and reactions gathered across social platforms:\n"
            f"{comments_block}\n\n"
            "Provide a concise, highly insightful executive briefing (2 to 3 paragraphs):\n"
            "1. **Core Sentiment & Community Mood**: What is the overall pulse and tone?\n"
            "2. **Dominant Themes & Key Points**: What are the top arguments, praises, or complaints?\n"
            "3. **Key Takeaway**: A crisp conclusion for a researcher, marketer, or product owner.\n\n"
            "Write in a sharp, professional, and engaging tone. Avoid generic fluff."
        )

        def _sync_summarize(model_name: str) -> str:
            res = client.models.generate_content(model=model_name, contents=prompt)
            return res.text or ""

        for model_name in self.models_to_try:
            try:
                summary = await asyncio.wait_for(asyncio.to_thread(_sync_summarize, model_name), timeout=20.0)
                if summary and len(summary.strip()) > 50:
                    return summary.strip()
            except Exception as e:
                logger.debug("Gemini summary with model %s failed: %s", model_name, e)
                continue

        return self._fallback_summary(topic, comments)

    def _fallback_summary(self, topic: str, comments: List[Dict[str, Any]]) -> str:
        count = len(comments)
        platforms = list({c.get("platform", "Social") for c in comments})
        plat_str = ", ".join(platforms) if platforms else "connected platforms"
        return (
            f"Analyzed {count} recent public comments and discussions on '{topic}' across {plat_str}. "
            f"Discussions highlight active community engagement, user feedback, and peer interactions within the last 3-4 months."
        )


_query_processor: Optional[GeminiQueryProcessor] = None


def get_query_processor() -> GeminiQueryProcessor:
    """Singleton getter for GeminiQueryProcessor."""
    global _query_processor
    if _query_processor is None:
        _query_processor = GeminiQueryProcessor()
    return _query_processor
