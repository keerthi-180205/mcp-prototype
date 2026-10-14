"""Name -> website lookup. Offline: fake Google, fake websites."""

import httpx
import pytest

from server.professionals.enrich import NOTE, build_query, enrich_professionals, name_tokens, pick_site
from server.professionals.models import Channel, ProfessionalRecord
from server.providers.brightdata.serp import BrightDataSerpError, SerpPage, SerpResult
from server.storage import professionals as store
from tests.test_professionals_finder import make_fetcher


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "enrich.db")


def res(url, title="", snippet="", rank=1):
    return SerpResult(rank, url, title, snippet)


# ---- names ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,tokens", [
    ("Dr. Asha Rao, MBBS", ["asha", "rao"]),
    ("SAM THOMAS MATHEW", ["sam", "thomas", "mathew"]),
    ("Kavya Kollody (RCI Licensed)", ["kavya", "kollody"]),
    ("Lyn Georgy | Psychotherapist", ["lyn", "georgy"]),
    ("Clarissa S", ["clarissa"]),            # an initial is not a searchable surname
    ("mind.space.isha", ["mind", "space", "isha"]),
])
def test_name_tokens(raw, tokens):
    assert name_tokens(raw) == tokens


def test_query_quotes_the_name_and_excludes_social_profiles():
    assert build_query(["asha", "rao"], "clinical_psychologist", "Bangalore") == \
        '"asha rao" clinical psychologist Bangalore -site:linkedin.com -site:instagram.com'


# ---- which result is "this person's page" -----------------------------------------------------------------
def test_a_result_needs_every_name_part_and_a_psychology_term():
    toks = ["asha", "rao"]
    site = "https://asharao.in/"
    assert pick_site([res(site, "Dr Asha Rao - Clinical Psychologist", "Bengaluru")], toks, "Bangalore")
    assert pick_site([res(site, "Asha Menon - Clinical Psychologist")], toks, "Bangalore") is None      # only the first name
    assert pick_site([res(site, "Asha Rao - Tax consultant")], toks, "Bangalore") is None               # not a clinician
    assert pick_site([res(site, "Rao and Asha Associates psychology")], ["asha", "rao", "kumar"], "Bangalore") is None


def test_directories_social_networks_and_news_are_never_a_personal_site():
    toks = ["asha", "rao"]
    for url in ("https://www.practo.com/bangalore/doctor/asha-rao", "https://www.linkedin.com/in/asha-rao", "https://www.instagram.com/asharao/",
                "https://www.thehindu.com/asha-rao-psychologist", "https://www.psychologytoday.com/in/asha-rao"):
        assert pick_site([res(url, "Dr Asha Rao Clinical Psychologist")], toks, "Bangalore") is None, url


def test_a_domain_containing_the_name_beats_a_generic_page_and_the_reason_is_recorded():
    toks = ["asha", "rao"]
    hit = pick_site([res("https://www.manyclinics.in/team", "Asha Rao, clinical psychologist", rank=1),
                     res("https://asharao.in/", "Asha Rao | Clinical Psychologist in Bengaluru", rank=2)], toks, "Bangalore")
    assert hit[0].url == "https://asharao.in/" and "name in the domain" in hit[1] and "city matches" in hit[1]


# ---- the whole flow ---------------------------------------------------------------------------------------
class FakeSerp:
    def __init__(self, pages=None, error=None):
        self.pages, self.error, self.queries, self.credits_used = pages or {}, error, [], 0.0

    async def search(self, query, start=0, tbs=None, country=None):
        self.queries.append(query)
        if self.error:
            raise self.error
        self.credits_used += 1
        key = next((k for k in self.pages if k in query), None)
        return SerpPage(query=query, results=self.pages.get(key, []))


def seed(db, name, key, fit=80, **kw):
    rec = ProfessionalRecord(pro_id=store.pro_id_for(key), kind="linkedin", entity_type="person", name=name, role="clinical_psychologist",
                             confidence=0.9, profile_url=f"https://www.linkedin.com/in/{key.split(':')[1]}", city="Bangalore", fit_score=fit,
                             channels=[Channel(kind="linkedin", value=f"https://www.linkedin.com/in/{key.split(':')[1]}", found_via="serp", source_url="s")], **kw)
    store.upsert_professional(rec, "r", db)
    return rec.pro_id


SITE = '<html><title>Asha Rao</title><body>RCI Licensed. Bengaluru. <a href="/contact">Contact</a></body></html>'
CONTACT = '<html><a href="mailto:asha@asharao.in">x</a><a href="mailto:hello@asharao.in">y</a> <a href="tel:+919876543210">call</a><form><textarea></textarea></form></html>'


@pytest.mark.asyncio
async def test_finds_the_site_reads_its_contact_page_and_flags_it_for_confirmation(db):
    pid = seed(db, "Dr. Asha Rao", "linkedin:asha-rao")
    log = []
    serp = FakeSerp({"asha rao": [res("https://asharao.in/", "Dr Asha Rao - Clinical Psychologist Bengaluru")]})
    fetcher = make_fetcher({"asharao.in/": SITE, "asharao.in/contact": CONTACT}, log)
    out = await enrich_professionals(serp=serp, fetcher=fetcher, db_path=db)
    assert out["stats"]["found"] == 1 and out["stats"]["found_direct_channel"] == 1 and out["stats"]["search_credits"] == 1
    p = store.get_professional(pid, db)
    assert p["website_url"] == "https://asharao.in/" and NOTE in p["needs_review_reason"]
    by = {(c["kind"], c["value"]): c for c in p["channels"]}
    assert ("email", "asha@asharao.in") in by and ("phone", "+919876543210") in by and ("website", "https://asharao.in/") in by
    assert by[("email", "asha@asharao.in")]["is_generic"] is False             # the domain carries her name: her own site, judged per address
    assert by[("email", "hello@asharao.in")]["is_generic"] is True             # ...and hello@ is still just an inbox
    assert by[("website", "https://asharao.in/")]["found_via"] == "name_search"
    assert all(c["source_url"] for c in p["channels"]) and ("linkedin", "https://www.linkedin.com/in/asha-rao") in by   # the old channel is kept
    assert p["fit_score"] == 75.0                                                # recomputed: 45 role + 15 city + 3 licence claim + 12 personal email
    assert p["licence"]["claim"] and p["city_match"] and p["review_status"] == "new"


@pytest.mark.asyncio
async def test_a_shared_hospital_page_gives_shared_lines_not_the_persons_own(db):
    pid = seed(db, "Priya Nair", "linkedin:priya-nair")
    serp = FakeSerp({"priya nair": [res("https://bigcare.in/doctors/priya", "Priya Nair - Consultant Psychiatrist", "Bengaluru")]})
    fetcher = make_fetcher({"bigcare.in/doctors/priya": '<html><a href="tel:+918023456789">x</a><a href="mailto:priya.nair@bigcare.in">m</a></html>'}, [])
    await enrich_professionals(serp=serp, fetcher=fetcher, db_path=db)
    chans = store.get_professional(pid, db)["channels"]
    assert all(c["is_generic"] for c in chans if c["kind"] in ("email", "phone"))


@pytest.mark.asyncio
async def test_no_confident_match_is_recorded_and_not_paid_for_twice(db):
    pid = seed(db, "Kavya Kollody", "linkedin:kavya")
    serp = FakeSerp({"kavya kollody": [res("https://other.in/", "Kavya K - psychologist")]})
    fetcher = make_fetcher({}, [])
    first = await enrich_professionals(serp=serp, fetcher=fetcher, db_path=db)
    assert first["stats"]["no_match"] == 1 and store.last_enrich_attempt(pid, db)["outcome"] == "no_match"
    second = await enrich_professionals(serp=serp, fetcher=fetcher, db_path=db)
    assert second["stats"].get("skipped_already_tried") == 1 and len(serp.queries) == 1       # no second credit
    forced = await enrich_professionals(serp=serp, fetcher=fetcher, db_path=db, force=True)
    assert forced["stats"]["searched"] == 1 and len(serp.queries) == 2


@pytest.mark.asyncio
async def test_only_eligible_people_are_searched_best_first_within_the_limits(db):
    seed(db, "Asha Rao", "linkedin:a", fit=90)
    seed(db, "Ben Joseph", "linkedin:b", fit=70)
    seed(db, "Cara Dsouza", "linkedin:c", fit=60)
    seed(db, "Clarissa S", "linkedin:short", fit=99)                                  # too short a name to search for
    rejected = seed(db, "Dan Rejected", "linkedin:d", fit=95)
    store.set_review(rejected, "rejected", "", db)
    dnc = seed(db, "Eve Optout", "linkedin:e", fit=95)
    store.set_review(dnc, "do_not_contact", "", db)
    has_site = seed(db, "Finn Hassite", "linkedin:f", fit=95, website_url="https://finn.in/")
    serp = FakeSerp()
    out = await enrich_professionals(serp=serp, fetcher=make_fetcher({}, []), db_path=db, limit=2)
    assert [q.split('"')[1] for q in serp.queries] == ["asha rao", "ben joseph"]                    # best-ranked first, limit 2
    assert out["stats"]["skipped_name_too_short"] == 1
    serp2 = FakeSerp()
    await enrich_professionals(serp=serp2, fetcher=make_fetcher({}, []), db_path=db, limit=10, max_credits=1)
    assert len(serp2.queries) == 1                                                                   # the credit cap is a hard stop


@pytest.mark.asyncio
async def test_search_problems_stop_or_skip_without_crashing(db):
    from server.collection.collectors.base import CollectorFatalError
    seed(db, "Asha Rao", "linkedin:a")
    seed(db, "Ben Joseph", "linkedin:b")
    out = await enrich_professionals(serp=FakeSerp(error=CollectorFatalError("daily limit reached")), fetcher=make_fetcher({}, []), db_path=db)
    assert "daily limit" in out["notes"][0] and out["stats"].get("searched") == 2             # the group in flight finishes, then it stops
    out = await enrich_professionals(serp=FakeSerp(error=BrightDataSerpError("captcha")), fetcher=make_fetcher({}, []), db_path=db, force=True)
    assert out["stats"]["search_failed"] == 2                                                  # a transient failure skips that person only


@pytest.mark.asyncio
async def test_a_blocked_site_still_records_the_website_and_a_human_can_open_it(db):
    pid = seed(db, "Asha Rao", "linkedin:a")
    def handler(request):
        return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(403)
    from server.professionals.web import SiteFetcher

    async def dns(host):
        return ["93.184.216.34"]

    fetcher = SiteFetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), delay=0, resolver=dns)
    serp = FakeSerp({"asha rao": [res("https://asharao.in/", "Dr Asha Rao - Clinical Psychologist")]})
    out = await enrich_professionals(serp=serp, fetcher=fetcher, db_path=db)
    assert out["stats"]["found"] == 1 and out["stats"]["found_no_channel"] == 1 and out["stats"]["site_blocked"] == 1
    assert store.get_professional(pid, db)["website_url"] == "https://asharao.in/"


@pytest.mark.asyncio
async def test_work_is_done_three_at_a_time_and_progress_is_reported(db):
    for i in range(7):
        seed(db, f"Person{i} Surname{i}", f"linkedin:p{i}", fit=90 - i)
    serp = FakeSerp()
    messages = []
    out = await enrich_professionals(serp=serp, fetcher=make_fetcher({}, []), db_path=db, limit=7, max_credits=5, on_progress=messages.append)
    assert len(serp.queries) == 5 and out["stats"]["search_credits"] == 5 and "max_credits=5" in out["notes"][-1]   # cap holds across groups
    assert any(m.startswith("looking up 1-3") for m in messages) and any(m.startswith("looking up 4-5") for m in messages)


# ---- whose site is it? (first live run: most "name matches" were data brokers, directories and apps) ---------------------
@pytest.mark.parametrize("host,expect", [
    ("asharao.in", "personal"), ("www.drasha.com", "personal"),
    ("calmhospitals.in", "organisation"), ("mindspace.clinic", "organisation"), ("nimhans.ac.in", "organisation"),
    # contact-data brokers are never a source
    ("rocketreach.co", None), ("www.zoominfo.com", None), ("aeroleads.com", None), ("lusha.com", None), ("apollo.io", None),
    # directories, competitor platforms, health apps and journals: their lines are not the clinician's
    ("amahahealth.com", None), ("catexhealth.com", None), ("rockethealth.app", None), ("medipract.com", None),
    ("nectarplus.health", None), ("unifers.ai", None), ("ijneronline.com", None), ("practo.com", None),
])
def test_only_a_personal_domain_or_a_hospital_or_clinic_host_is_accepted(host, expect):
    from server.professionals.enrich import acceptable_host
    assert acceptable_host(host, ["asha", "rao"]) == expect


def test_a_broker_page_is_not_chosen_even_when_it_matches_the_name_and_role_perfectly():
    hit = pick_site([res("https://rocketreach.co/asha-rao-email_123", "Asha Rao - Clinical Psychologist email & phone"),
                     res("https://www.zoominfo.com/p/Asha-Rao/1", "Asha Rao Clinical Psychologist contact")], ["asha", "rao"], "Bangalore")
    assert hit is None


def test_audit_undoes_stored_websites_the_current_rules_reject_and_keeps_good_ones(db):
    from server.professionals.enrich import audit_enrichments
    from server.storage import professionals as st

    def enriched(name, key, site, host_for_channels):
        pid = seed(db, name, key)
        rec = ProfessionalRecord(pro_id=pid, kind="linkedin", entity_type="person", name=name, role="clinical_psychologist", confidence=0.9,
                                 profile_url=f"https://www.linkedin.com/in/{key.split(':')[1]}", city="Bangalore", website_url=site,
                                 needs_review_reason=NOTE, channels=[
                                     Channel(kind="website", value=site, found_via="name_search", source_url=site),
                                     Channel(kind="email", value=f"info@{host_for_channels}", is_generic=True, found_via="mailto", source_url=f"https://{host_for_channels}/contact"),
                                     Channel(kind="phone", value="+919876543210", found_via="tel", source_url=f"https://{host_for_channels}/contact")])
        st.upsert_professional(rec, None, db)
        st.log_enrich_attempt(pid, "found", "x", db)
        return pid

    bad = enriched("Asha Rao", "linkedin:bad", "https://rocketreach.co/asha-rao", "rocketreach.co")
    good = enriched("Ben Joseph", "linkedin:good", "https://benjoseph.in/", "benjoseph.in")
    assert audit_enrichments(db) == {"checked": 2, "reset": 1}
    b = st.get_professional(bad, db)
    assert b["website_url"] is None and NOTE not in b["needs_review_reason"] and st.last_enrich_attempt(bad, db) is None
    assert [c["kind"] for c in b["channels"]] == ["linkedin"]                           # only the original profile channel remains
    g = st.get_professional(good, db)
    assert g["website_url"] == "https://benjoseph.in/" and len(g["channels"]) == 4 and st.last_enrich_attempt(good, db)
