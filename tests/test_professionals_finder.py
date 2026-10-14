"""End-to-end finder runs with fake Google, Instagram and websites. Offline."""

import httpx
import pytest

from server.collection.collectors.base import CollectorFatalError
from server.professionals.classify import LlmLabel
from server.professionals.finder import ProfessionalFinder
from server.professionals.models import FinderParams
from server.professionals.queries import build_queries, estimate
from server.professionals.web import SiteFetcher
from server.providers.brightdata.serp import BrightDataSerpError, SerpPage, SerpResult
from server.storage import professionals as store


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "finder.db")


# ---- fakes ------------------------------------------------------------------------------------------
def li(slug, name, headline, snippet="Bengaluru, Karnataka, India", followers="460+ followers", rank=1):
    return SerpResult(rank, f"https://in.linkedin.com/in/{slug}", f"{name} - {headline} | LinkedIn", snippet, f"LinkedIn · {name}", followers)


def ig(handle, title, snippet, rank=1):
    return SerpResult(rank, f"https://www.instagram.com/p/{handle}CODE/", title, snippet, f"Instagram · {handle}", "50+ likes · 2 months ago")


def web(url, title, snippet="", source="", rank=1):
    return SerpResult(rank, url, title, snippet, source)


class FakeSerp:
    """Answers each query by platform; counts credits like the real thing (1 per page)."""

    def __init__(self, by_platform, error=None, degraded=False):
        self.by_platform, self.error, self.degraded = by_platform, error, degraded
        self.credits_used, self.queries = 0.0, []

    async def search(self, query, start=0, tbs=None, country=None):
        self.queries.append(query)
        if self.error and len(self.queries) > self.error[0]:
            raise self.error[1]
        platform = "linkedin" if query.startswith("site:linkedin.com/in") else "instagram" if query.startswith("site:instagram.com") else "web"
        self.credits_used += 1
        return SerpPage(query=query, results=list(self.by_platform.get(platform, [])), degraded=self.degraded)


class FakeProfiles:
    def __init__(self, profiles, error=None):
        self.profiles, self.error, self.calls, self.credits_used = profiles, error, [], 0.0

    async def instagram_profile(self, handle):
        self.calls.append(handle)
        if self.error:
            raise self.error
        self.credits_used += 1
        return self.profiles.get(handle)


def prof(bio, links=(), name="", private=False, followers=1200):
    return {"bio": bio, "external_links": list(links), "display_name": name, "followers": followers, "is_private": private}


CONTACT_PAGE = '<html><title>Contact</title><a href="mailto:hello@mindspace.in">mail</a> <a href="tel:+919845012345">call</a><form><textarea></textarea></form></html>'
HOME_PAGE = '<html><head><title>Mind Space | Dr. Isha</title><meta name="description" content="RCI licensed counselling psychologist in Bengaluru"></head><body><a href="/contact">Contact</a></body></html>'


def sites(routes, log):
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host.removeprefix("www.")
        log.append(f"{host}{request.url.path}")
        if request.url.path == "/robots.txt":
            body = routes.get(f"{host}/robots.txt")
            return httpx.Response(200, text=body) if body else httpx.Response(404)
        body = routes.get(f"{host}{request.url.path}")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"}) if body else httpx.Response(404)
    return handler


async def _public_dns(host):
    return ["93.184.216.34"]


def make_fetcher(routes, log):
    return SiteFetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(sites(routes, log)), follow_redirects=True),
                       delay=0, resolver=_public_dns)


LINKEDIN = [
    li("asha-rao", "Asha Rao", "Clinical Psychologist (RCI Licensed)", rank=1),
    li("ben-coach", "Ben Coach", "Life Coach | NLP Practitioner", rank=2),
    li("cara-student", "Cara S", "Aspiring clinical psychologist, final year student", rank=3),
]
INSTAGRAM = [
    ig("mind.space.isha", "Meet our therapist, Isha", "Counselling psychologist. Book a session via the link in bio", rank=1),
    ig("journal.with.jo", "Sunday journaling", "My psychiatrist said I should write more. Feeling hopeful today", rank=2),
]
WEB = [
    web("https://www.practo.com/bangalore/psychologist", "Best psychologists in Bangalore", source="Practo"),
    web("https://www.mindspace.in/", "Mind Space - counselling in Bangalore", "Online therapy", source="Mind Space", rank=2),
    web("https://www.calmhospitals.in/mental-health", "Calm Hospitals - Department of Psychiatry", "Mental health centre, psychiatrists and psychologists", source="Calm Hospitals", rank=3),
]
ROUTES = {
    "mindspace.in/": HOME_PAGE, "mindspace.in/contact": CONTACT_PAGE,
    "calmhospitals.in/mental-health": "<html><title>Calm Hospitals</title><a href='mailto:info@calmhospitals.in'>x</a></html>",
}
PARAMS = dict(city="Bangalore", specialties=["psychologist"], pages=1)


def finder(db, serp=None, profiles=None, routes=None, log=None, llm=None, **kw):
    log = log if log is not None else []
    return ProfessionalFinder(
        serp=serp or FakeSerp({"linkedin": LINKEDIN, "instagram": INSTAGRAM, "web": WEB}),
        profiles=profiles or FakeProfiles({"mind.space.isha": prof("Counselling Psychologist | RCI Licensed | Bengaluru", ["https://www.mindspace.in/"], "Dr. Isha")}),
        fetcher=make_fetcher(routes if routes is not None else ROUTES, log), llm=llm, use_llm=False, db_path=db, **kw,
    )


async def run(db, **kw):
    f = finder(db, **{k: v for k, v in kw.items() if k != "params"})
    return await f.run(FinderParams(**{**PARAMS, **kw.get("params", {})}), run_id="run1")


def stored(db, **kw):
    return {p["name"]: p for p in store.list_professionals(limit=100, db_path=db, **kw)[1]}


# ---- the main flow -----------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_only_real_clinicians_and_clinics_are_stored(db):
    log = []
    result = await finder(db, log=log).run(FinderParams(**PARAMS), run_id="run1")
    pros = stored(db)
    assert "Asha Rao" in pros and "Dr. Isha" in pros
    assert not any(n in pros for n in ("Ben Coach", "Cara S", "journal.with.jo"))           # coach, student, patient caption
    assert {p["entity_type"] for p in pros.values()} == {"person", "organisation"}
    stats = result["stats"]
    assert stats["candidates_linkedin"] == 3 and stats["kept"] == len(pros)
    assert any(k.startswith("dropped:") and "no mental-health profession" in k for k in stats)   # the life coach
    assert any(k.startswith("dropped:") and "caption" in k for k in stats)


@pytest.mark.asyncio
async def test_linkedin_pages_are_never_fetched_and_portals_never_opened(db):
    log = []
    await finder(db, log=log).run(FinderParams(**PARAMS), run_id="run1")
    assert not any("linkedin" in entry for entry in log)
    assert not any("practo" in entry for entry in log)
    assert {e.split("/")[0] for e in log} == {"mindspace.in", "calmhospitals.in"}


@pytest.mark.asyncio
async def test_instagram_bio_leads_to_the_clinicians_website_and_every_channel_has_a_source(db):
    log = []
    await finder(db, log=log).run(FinderParams(**PARAMS), run_id="run1")
    isha = stored(db)["Dr. Isha"]
    assert isha["role"] == "counselling_psychologist" and isha["confidence"] >= 0.9 and isha["website_url"] == "https://www.mindspace.in/"
    by = {(c["kind"], c["value"]): c for c in isha["channels"]}
    assert by[("email", "hello@mindspace.in")]["is_generic"] and by[("email", "hello@mindspace.in")]["source_url"].endswith("/contact")
    assert ("phone", "+919845012345") in by and ("contact_form", "https://www.mindspace.in/contact") in by
    assert ("instagram", "https://www.instagram.com/mind.space.isha/") in by and ("website", "https://www.mindspace.in/") in by
    assert all(c["source_url"] for c in isha["channels"])
    assert isha["licence"]["claim"] and "RCI" in isha["licence"]["claim"] and isha["city_match"]


@pytest.mark.asyncio
async def test_a_site_that_belongs_to_an_instagram_clinician_is_not_stored_twice(db):
    await finder(db).run(FinderParams(**PARAMS), run_id="run1")
    pros = stored(db)
    assert not any(p["kind"] == "website" and "mindspace" in p["profile_url"] for p in pros.values())   # merged into the Instagram record
    assert pros["Calm Hospitals"]["entity_type"] == "organisation"


@pytest.mark.asyncio
async def test_records_are_saved_for_review_never_approved(db):
    await finder(db).run(FinderParams(**PARAMS), run_id="run1")
    assert {p["review_status"] for p in stored(db).values()} == {"new"}
    assert store.export_rows(["approved"], db) == []                       # nothing is exportable until a person approves it
    asha = stored(db)["Asha Rao"]
    assert [c["kind"] for c in asha["channels"]] == ["linkedin"] and asha["fit_score"] > 0


@pytest.mark.asyncio
async def test_individuals_rank_above_clinics(db):
    await finder(db).run(FinderParams(**PARAMS), run_id="run1")
    _, items = store.list_professionals(limit=10, db_path=db)
    assert items[-1]["entity_type"] == "organisation"


# ---- budgets and failures --------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_search_credit_cap_is_a_hard_stop(db):
    serp = FakeSerp({"linkedin": LINKEDIN, "instagram": INSTAGRAM, "web": WEB})
    result = await finder(db, serp=serp).run(FinderParams(**{**PARAMS, "max_serp_credits": 2}), run_id="r")
    assert serp.credits_used == 2 and len(serp.queries) == 2
    assert any("max_serp_credits" in n for n in result["notes"]) and result["stats"]["serp_credits"] == 2


@pytest.mark.asyncio
async def test_a_fatal_search_error_stops_searching_but_keeps_what_was_found(db):
    serp = FakeSerp({"linkedin": LINKEDIN, "instagram": INSTAGRAM, "web": WEB}, error=(1, CollectorFatalError("daily limit of 150 credits reached")))
    result = await finder(db, serp=serp).run(FinderParams(**PARAMS), run_id="r")
    assert len(serp.queries) == 2 and result["stats"]["search_fatal"] == 1
    assert "Asha Rao" in stored(db) and any("daily limit" in n for n in result["notes"])


@pytest.mark.asyncio
async def test_a_failed_query_is_skipped_and_the_rest_continue(db):
    class Flaky(FakeSerp):
        async def search(self, query, start=0, tbs=None, country=None):
            if query.startswith("site:instagram.com"):
                raise BrightDataSerpError("captcha")
            return await super().search(query, start, tbs, country)

    result = await finder(db, serp=Flaky({"linkedin": LINKEDIN, "web": WEB})).run(FinderParams(**PARAMS), run_id="r")
    assert result["stats"]["queries_failed"] == 1 and "Asha Rao" in stored(db)


@pytest.mark.asyncio
async def test_degraded_pages_are_counted(db):
    serp = FakeSerp({"linkedin": LINKEDIN}, degraded=True)
    result = await finder(db, serp=serp).run(FinderParams(**{**PARAMS, "platforms": ["linkedin"]}), run_id="r")
    assert result["stats"]["degraded_pages"] == 1


@pytest.mark.asyncio
async def test_instagram_lookup_cap_leaves_unread_accounts_flagged_not_dropped(db):
    insta = [ig("a.one", "About me", "I'm a counselling psychologist in Bangalore, book a session", 1), ig("b.two", "About me", "I'm a clinical psychologist in Bangalore, book a session", 2)]
    profiles = FakeProfiles({"a.one": prof("Counselling psychologist | RCI licensed"), "b.two": prof("Clinical psychologist | RCI licensed")})
    result = await finder(db, serp=FakeSerp({"instagram": insta}), profiles=profiles).run(
        FinderParams(**{**PARAMS, "platforms": ["instagram"], "max_profile_lookups": 1}), run_id="r")
    pros = stored(db)
    assert profiles.calls == ["a.one"] and result["stats"]["instagram_bios_not_read"] == 1
    assert "Instagram bio not read" in pros["b.two"]["needs_review_reason"] and pros["b.two"]["confidence"] <= 0.65
    assert pros["a.one"]["confidence"] >= 0.9


@pytest.mark.asyncio
async def test_out_of_profile_credits_stops_lookups_without_losing_candidates(db):
    insta = [ig("a.one", "About me", "I'm a counselling psychologist in Bangalore, book a session", 1)]
    profiles = FakeProfiles({}, error=CollectorFatalError("TrueScrape out of credits"))
    result = await finder(db, serp=FakeSerp({"instagram": insta}), profiles=profiles).run(
        FinderParams(**{**PARAMS, "platforms": ["instagram"]}), run_id="r")
    assert "a.one" in stored(db) and any("out of credits" in n for n in result["notes"])


@pytest.mark.asyncio
async def test_private_instagram_accounts_are_not_used(db):
    insta = [ig("p.rivate", "About me", "I'm a counselling psychologist in Bangalore, book a session", 1)]
    profiles = FakeProfiles({"p.rivate": prof("Counselling psychologist | RCI licensed", private=True)})
    result = await finder(db, serp=FakeSerp({"instagram": insta}), profiles=profiles).run(
        FinderParams(**{**PARAMS, "platforms": ["instagram"]}), run_id="r")
    assert result["stats"]["profile_unavailable"] == 1
    assert stored(db)["p.rivate"]["confidence"] <= 0.65                          # still just the caption evidence


@pytest.mark.asyncio
async def test_robots_disallowed_sites_are_counted_and_left_alone(db):
    routes = dict(ROUTES, **{"mindspace.in/robots.txt": "User-agent: *\nDisallow: /"})
    log = []
    result = await finder(db, routes=routes, log=log).run(FinderParams(**PARAMS), run_id="r")
    assert result["stats"]["site_robots"] == 1
    assert "mindspace.in/" not in log and "mindspace.in/contact" not in log


# ---- re-runs and Gemini ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_second_run_updates_without_duplicating_or_undoing_review(db):
    first = await finder(db).run(FinderParams(**PARAMS), run_id="r1")
    asha = stored(db)["Asha Rao"]
    store.set_review(asha["pro_id"], "approved", "checked RCI register", db)
    second = await finder(db).run(FinderParams(**PARAMS), run_id="r2")
    assert second["stats"]["new_records"] == 0 and second["stats"]["already_known"] == first["stats"]["kept"]
    again = stored(db)["Asha Rao"]
    assert again["review_status"] == "approved" and again["review_note"] == "checked RCI register" and again["first_run_id"] == "r1"
    assert store.list_professionals(db_path=db)[0] == first["stats"]["kept"]


@pytest.mark.asyncio
async def test_gemini_settles_ambiguous_profiles_only_with_a_real_quote(db):
    vague = [li("dee-vague", "Dee V", "Therapist | anxiety and relationships | trained in CBT")]
    asked = []

    async def llm(items):
        asked.extend(i["id"] for i in items)
        return [LlmLabel(id=items[0]["id"], verdict="clinician", role="psychotherapist", evidence="trained in CBT")]

    result = await finder(db, serp=FakeSerp({"linkedin": vague}), llm=llm).run(FinderParams(**{**PARAMS, "platforms": ["linkedin"]}), run_id="r")
    dee = stored(db)["Dee V"]
    assert asked == ["linkedin:dee-vague"] and dee["classified_by"] == "gemini" and dee["confidence"] >= 0.8
    assert result["stats"]["llm_asked"] == 1


@pytest.mark.asyncio
async def test_without_gemini_the_vague_profile_is_stored_but_flagged(db):
    vague = [li("dee-vague", "Dee V", "Therapist | anxiety and relationships | trained in CBT")]
    await finder(db, serp=FakeSerp({"linkedin": vague})).run(FinderParams(**{**PARAMS, "platforms": ["linkedin"]}), run_id="r")
    dee = stored(db)["Dee V"]
    assert dee["classified_by"] == "rules" and dee["needs_review_reason"]


# ---- planning ------------------------------------------------------------------------------------------------------------
def test_query_plan_and_estimate_before_any_credit_is_spent():
    p = FinderParams(city="Bangalore", specialties=["clinical psychologist", "psychiatrist"], pages=2)
    qs = build_queries(p)
    assert len(qs) == 6 and {q.platform for q in qs} == {"linkedin", "instagram", "web"}
    assert all("site:" in q.q for q in qs if q.platform != "web")
    web_q = next(q.q for q in qs if q.platform == "web")
    assert web_q.count("-site:") == 2 and "practo" not in web_q          # long exclusion lists get the query rejected by Google
    est = estimate(p)
    assert est == {"queries": 6, "serp_credits_max": 12, "instagram_profile_credits_max": 15, "websites_to_open_max": 25}
    assert estimate(FinderParams(city="Pune", pages=3, max_serp_credits=5))["serp_credits_max"] == 5


def test_user_input_cannot_inject_search_operators():
    p = FinderParams(city='Bangalore" site:evil.com', specialties=['psychologist -site:linkedin.com "x"'], focus="anxiety (OR) inurl:admin")
    joined = " ".join(q.q for q in build_queries(p))
    assert "evil.com" in joined                      # kept as harmless words
    assert 'site:evil' not in joined and "inurl:admin" not in joined and "(OR)" not in joined


# ---- findings from the first live run ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_clinic_account_introducing_a_doctor_is_an_organisation_not_that_doctor(db):
    clinic = [ig("hope.trust", "Introducing Dr. Vidhya", "Dr Vidhya holds a PhD and M.Phil (Clinical Psychology). Meet our new psychologist!", 1)]
    profiles = FakeProfiles({"hope.trust": prof("Hope Trust. We offer therapy, psychiatry and de-addiction care. Book now", name="Hope Trust India")})
    await finder(db, serp=FakeSerp({"instagram": clinic}), profiles=profiles).run(FinderParams(**{**PARAMS, "platforms": ["instagram"]}), run_id="r")
    p = stored(db)["Hope Trust India"]
    assert p["entity_type"] == "organisation" and p["role"] == "organisation"


@pytest.mark.asyncio
async def test_unread_clinic_style_captions_become_a_flagged_organisation(db):
    insta = [ig("meet.my.therapist", "Meet our therapist", "Book your psychotherapy session with us. Clinical psychologists available", 1)]
    profiles = FakeProfiles({})
    await finder(db, serp=FakeSerp({"instagram": insta}), profiles=profiles).run(
        FinderParams(**{**PARAMS, "platforms": ["instagram"], "max_profile_lookups": 0}), run_id="r")
    p = stored(db)["meet.my.therapist"]
    assert p["entity_type"] == "organisation" and "bio not read" in p["needs_review_reason"]


@pytest.mark.asyncio
async def test_someone_with_no_sign_of_practising_in_the_city_is_flagged(db):
    far = [li("perth-doc", "Pat Doc", "Psychiatrist at Royal Perth", snippet="Perth, Western Australia, Australia | M.D. Psychiatrist")]
    await finder(db, serp=FakeSerp({"linkedin": far})).run(FinderParams(**{**PARAMS, "platforms": ["linkedin"]}), run_id="r")
    p = stored(db)["Pat Doc"]
    assert not p["city_match"] and "no sign they practise in Bangalore" in p["needs_review_reason"]
    local = [li("blr-doc", "Lou Doc", "Psychiatrist", snippet="Bengaluru, Karnataka, India")]
    await finder(db, serp=FakeSerp({"linkedin": local})).run(FinderParams(**{**PARAMS, "platforms": ["linkedin"]}), run_id="r2")
    assert "no sign" not in stored(db)["Lou Doc"]["needs_review_reason"]


@pytest.mark.asyncio
async def test_an_instagram_bio_linking_to_an_internal_address_is_never_opened(db):
    insta = [ig("evil.bio", "About me", "I'm a counselling psychologist in Bangalore, book a session", 1)]
    profiles = FakeProfiles({"evil.bio": prof("Counselling psychologist | RCI licensed", ["http://169.254.169.254/latest/meta-data/"], "Evil Bio")})
    log = []
    result = await finder(db, serp=FakeSerp({"instagram": insta}), profiles=profiles, log=log).run(
        FinderParams(**{**PARAMS, "platforms": ["instagram"]}), run_id="r")
    assert log == [] and result["stats"].get("site_error") == 1       # refused, recorded, nothing requested
    assert "Evil Bio" in stored(db)                                   # the person is still listed, just without that "website"
