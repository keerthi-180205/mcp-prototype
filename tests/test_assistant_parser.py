"""Table-driven unit tests for the assistant rules parser and LLM fallback."""

import pytest
from server.chat.assistant import parse_intent, parse_with_rules, ParsedIntent


# Table of at least 25 distinct phrasings
PARSER_TEST_CASES = [
    # 1. Standard collection request with count and platforms
    (
        "get me 500 comments about Asian Games 2026 from YouTube and Reddit",
        "start_collection",
        "Asian Games 2026",
        ["youtube", "reddit"],
        500,
    ),
    # 2. Number shorthand 1k
    (
        "collect 1k comments on AI agents from x and reddit",
        "start_collection",
        "AI agents",
        ["x", "reddit"],
        1000,
    ),
    # 3. Number shorthand 2.5k
    (
        "fetch 2.5k comments about Electric Vehicles from youtube",
        "start_collection",
        "Electric Vehicles",
        ["youtube"],
        2500,
    ),
    # 4. Number words: a thousand
    (
        "find a thousand comments on Quantum Computing",
        "start_collection",
        "Quantum Computing",
        None,
        1000,
    ),
    # 5. Number words: two hundred
    (
        "get two hundred comments about cricket from yt",
        "start_collection",
        "cricket",
        ["youtube"],
        200,
    ),
    # 6. Number words: five hundred
    (
        "collect five hundred comments regarding climate change",
        "start_collection",
        "climate change",
        None,
        500,
    ),
    # 7. Platform aliases: yt and subreddits
    (
        "get 100 comments on Python from yt and subreddit",
        "start_collection",
        "Python",
        ["youtube", "reddit"],
        100,
    ),
    # 8. Platform alias: twitter / tweets
    (
        "collect 50 comments on SpaceX from twitter",
        "start_collection",
        "SpaceX",
        ["x"],
        50,
    ),
    # 9. Platform alias: tweets
    (
        "find 200 comments about Tesla from tweets",
        "start_collection",
        "Tesla",
        ["x"],
        200,
    ),
    # 10. Platform alias: insta / ig
    (
        "get 300 comments about fashion from insta and yt",
        "start_collection",
        "fashion",
        ["instagram", "youtube"],
        300,
    ),
    # 11. Missing topic
    (
        "get me comments from youtube and reddit",
        "start_collection",
        None,
        ["youtube", "reddit"],
        500,
    ),
    # 12. Missing topic with count
    (
        "collect 500 comments",
        "start_collection",
        None,
        None,
        500,
    ),
    # 13. Confirm: explicit word 'yes'
    (
        "yes",
        "confirm",
        None,
        None,
        None,
    ),
    # 14. Confirm: word 'confirm'
    (
        "confirm",
        "confirm",
        None,
        None,
        None,
    ),
    # 15. Confirm: word 'proceed'
    (
        "proceed",
        "confirm",
        None,
        None,
        None,
    ),
    # 16. Cancel: word 'cancel'
    (
        "cancel",
        "cancel_plan",
        None,
        None,
        None,
    ),
    # 17. Cancel: word 'no'
    (
        "no",
        "cancel_plan",
        None,
        None,
        None,
    ),
    # 18. Status: 'what is the status?'
    (
        "what's the status?",
        "status",
        None,
        None,
        None,
    ),
    # 19. Status: 'status'
    (
        "status",
        "status",
        None,
        None,
        None,
    ),
    # 20. Filter: 'only reddit'
    (
        "only reddit",
        "show_results",
        None,
        None,
        None,
    ),
    # 21. Filter: 'show only youtube'
    (
        "show only youtube",
        "show_results",
        None,
        None,
        None,
    ),
    # 22. Pagination: 'page 2'
    (
        "show page 2",
        "show_results",
        None,
        None,
        None,
    ),
    # 23. Pagination: 'next page'
    (
        "next page",
        "show_results",
        None,
        None,
        None,
    ),
    # 24. Export: 'export json'
    (
        "export json",
        "export",
        None,
        None,
        None,
    ),
    # 25. Export: 'export as csv'
    (
        "export as csv",
        "export",
        None,
        None,
        None,
    ),
    # 26. Explanation: 'why is instagram so low?'
    (
        "why is instagram so low?",
        "explain",
        None,
        None,
        None,
    ),
    # 27. Explanation: 'what does no_more_candidates mean?'
    (
        "what does no_more_candidates mean?",
        "explain",
        None,
        None,
        None,
    ),
    # 28. Platforms query: 'what platforms are available?'
    (
        "what platforms are available?",
        "platforms",
        None,
        None,
        None,
    ),
    # 29. Help query
    (
        "help",
        "help",
        None,
        None,
        None,
    ),
    # 30. Nonsense input
    (
        "xyzzy 12345 blorp",
        "unknown",
        None,
        None,
        None,
    ),
]


@pytest.mark.parametrize("text,expected_intent,expected_topic,expected_platforms,expected_target", PARSER_TEST_CASES)
def test_rules_parser_table_driven(text, expected_intent, expected_topic, expected_platforms, expected_target):
    parsed = parse_with_rules(text)
    assert parsed.intent == expected_intent
    if expected_topic is not None:
        assert parsed.topic == expected_topic
    if expected_platforms is not None:
        assert parsed.platforms == expected_platforms
    if expected_target is not None:
        assert parsed.target == expected_target


def test_rules_parser_export_formats():
    assert parse_with_rules("export json").format == "json"
    assert parse_with_rules("download results as csv").format == "csv"
    assert parse_with_rules("export").format == "csv"


def test_rules_parser_filters_and_pages():
    p1 = parse_with_rules("only reddit")
    assert p1.intent == "show_results"
    assert p1.platform_filter == "reddit"

    p2 = parse_with_rules("filter by x")
    assert p2.intent == "show_results"
    assert p2.platform_filter == "x"

    p3 = parse_with_rules("show page 3")
    assert p3.intent == "show_results"
    assert p3.page == 3


@pytest.mark.asyncio
async def test_gemini_fallback_on_failure():
    """Verify that when Gemini raises an exception, the parser gracefully falls back to rules."""
    class BrokenGeminiClient:
        class models:
            @staticmethod
            def generate_content(*args, **kwargs):
                raise RuntimeError("API quota exceeded / timeout")

    class FakeSettings:
        gemini_api_key = "fake_key_123"
        gemini_model = "gemini-2.5-flash"

    # Should NOT raise RuntimeError; should fall back to rules
    parsed = await parse_intent(
        "get 500 comments about Asian Games 2026 from youtube",
        settings=FakeSettings(),
        client=BrokenGeminiClient(),
    )
    assert parsed.intent == "start_collection"
    assert parsed.topic == "Asian Games 2026"
    assert parsed.platforms == ["youtube"]
    assert parsed.target == 500


@pytest.mark.asyncio
async def test_gemini_fallback_on_invalid_json():
    """Verify that when Gemini returns malformed non-JSON output, rules parser handles it."""
    class BadJsonGeminiClient:
        class models:
            @staticmethod
            def generate_content(*args, **kwargs):
                class Resp:
                    text = "I am a helpful AI. Here is what you asked: {not valid json"
                return Resp()

    class FakeSettings:
        gemini_api_key = "fake_key_123"
        gemini_model = "gemini-2.5-flash"

    parsed = await parse_intent(
        "export json",
        settings=FakeSettings(),
        client=BadJsonGeminiClient(),
    )
    assert parsed.intent == "export"
    assert parsed.format == "json"
