"""Professionals store: upsert rules, review, suppression, export, scoring. Offline."""

import pytest

from server.professionals.models import Channel, Licence, ProfessionalRecord
from server.professionals.scoring import fit_score
from server.storage import professionals as store


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "pros.db")


def rec(key="linkedin:asha", name="Asha Rao", role="clinical_psychologist", conf=0.9, channels=None, **kw):
    base = dict(pro_id=store.pro_id_for(key), kind=key.split(":")[0], entity_type="person", name=name, role=role,
                confidence=conf, profile_url=f"https://www.linkedin.com/in/{key.split(':')[1]}", city="Bangalore",
                city_match=True, headline="Clinical Psychologist", channels=channels or [])
    base.update(kw)
    return ProfessionalRecord(**base)


def email(value, generic=False, src="https://clinic.in/contact"):
    return Channel(kind="email", value=value, is_generic=generic, found_via="mailto", source_url=src)


# ---- upsert ---------------------------------------------------------------------------------------
def test_upsert_is_idempotent_and_never_resets_a_human_decision(db):
    r = rec(channels=[email("asha@clinic.in")])
    assert store.upsert_professional(r, "run1", db) is True
    store.set_review(r.pro_id, "approved", "verified on RCI site", db)
    assert store.upsert_professional(r, "run2", db) is False        # seen again
    p = store.get_professional(r.pro_id, db)
    assert p["review_status"] == "approved" and p["review_note"] == "verified on RCI site"
    assert len(p["channels"]) == 1 and p["first_run_id"] == "run1"


def test_a_weaker_rerun_cannot_downgrade_the_classification_but_new_facts_are_merged(db):
    store.upsert_professional(rec(conf=0.9, role="clinical_psychologist", evidence="RCI Licensed"), "r1", db)
    weaker = rec(conf=0.5, role="counsellor", evidence="counsellor", website_url="https://asharao.in/", followers=900,
                 licence=Licence(claim="RCI Licensed", numbers=[{"body": "RCI", "number": "A12345", "context": "x"}]),
                 channels=[email("hello@asharao.in", True)])
    store.upsert_professional(weaker, "r2", db)
    p = store.get_professional(weaker.pro_id, db)
    assert p["role"] == "clinical_psychologist" and p["confidence"] == 0.9 and p["evidence"] == "RCI Licensed"
    assert p["website_url"] == "https://asharao.in/" and p["followers"] == 900
    assert p["licence"]["numbers"][0]["number"] == "A12345" and p["licence"]["verified"] is None
    again = rec(licence=Licence(numbers=[{"body": "RCI", "number": "A12345", "context": "x"}]))
    store.upsert_professional(again, "r3", db)
    assert len(store.get_professional(again.pro_id, db)["licence"]["numbers"]) == 1   # no duplicates


def test_channels_are_unique_per_person_and_keep_their_source(db):
    r = rec(channels=[email("a@clinic.in"), email("a@clinic.in", src="https://other"), Channel(kind="phone", value="+919845012345", source_url="https://clinic.in")])
    store.upsert_professional(r, None, db)
    chans = store.get_professional(r.pro_id, db)["channels"]
    assert sorted(c["kind"] for c in chans) == ["email", "phone"]
    assert next(c for c in chans if c["kind"] == "email")["source_url"] == "https://clinic.in/contact"


def test_licence_verification_is_a_human_flag(db):
    r = rec()
    store.upsert_professional(r, None, db)
    for value in (True, False, None):
        store.set_licence_verified(r.pro_id, value, db)
        assert store.get_professional(r.pro_id, db)["licence"]["verified"] is value


# ---- listing -----------------------------------------------------------------------------------------
@pytest.fixture
def seeded(db):
    store.upsert_professional(rec("linkedin:a", "Asha Rao", conf=0.92, fit_score=80, channels=[email("asha@clinic.in")]), "r", db)
    store.upsert_professional(rec("linkedin:b", "Ben Joseph", role="psychiatrist", conf=0.7, fit_score=40,
                                  needs_review_reason="weak evidence", channels=[email("info@bj.in", True)]), "r", db)
    store.upsert_professional(rec("instagram:c", "carla", role="counsellor", conf=0.5, fit_score=20, city="Mumbai",
                                  channels=[Channel(kind="instagram", value="https://www.instagram.com/carla/", source_url="x")]), "r", db)
    store.upsert_professional(rec("website:d.in", "D Clinic", entity_type="organisation", role="organisation", conf=0.7, fit_score=55,
                                  channels=[Channel(kind="phone", value="+918023456789", source_url="https://d.in")]), "r", db)
    return db


def names(db, **kw):
    total, items = store.list_professionals(db_path=db, **kw)
    return total, [i["name"] for i in items]


def test_filters_and_sorting(seeded):
    db = seeded
    assert names(db) == (4, ["Asha Rao", "D Clinic", "Ben Joseph", "carla"])                       # fit_score desc
    assert names(db, role="psychiatrist")[1] == ["Ben Joseph"]
    assert names(db, entity_type="organisation")[1] == ["D Clinic"]
    assert names(db, city="mumbai")[1] == ["carla"]                                                 # case-insensitive
    assert names(db, min_confidence=0.7)[1] == ["Asha Rao", "D Clinic", "Ben Joseph"]
    assert names(db, needs_review=True)[1] == ["Ben Joseph"]
    assert names(db, q="joseph")[1] == ["Ben Joseph"]
    assert names(db, sort="name")[1] == ["Asha Rao", "Ben Joseph", "carla", "D Clinic"]


def test_channel_filters(seeded):
    db = seeded
    assert names(db, has_channel="personal_email")[1] == ["Asha Rao"]
    assert names(db, has_channel="email")[1] == ["Asha Rao", "Ben Joseph"]
    assert names(db, has_channel="phone")[1] == ["D Clinic"]
    assert names(db, has_channel="any")[1] == ["Asha Rao", "D Clinic", "Ben Joseph"]               # Instagram-only is not "direct"
    with pytest.raises(ValueError):
        names(db, has_channel="telepathy")


def test_pagination_reports_the_full_total(seeded):
    total, items = store.list_professionals(limit=2, offset=2, db_path=seeded)
    assert total == 4 and len(items) == 2


# ---- review + suppression ---------------------------------------------------------------------------------
def test_review_validates_status(seeded):
    pid = store.pro_id_for("linkedin:a")
    with pytest.raises(ValueError):
        store.set_review(pid, "maybe", "", seeded)
    assert store.set_review("nope", "approved", "", seeded) is None
    assert store.set_review(pid, "rejected", "not a clinician", seeded)["review_status"] == "rejected"


def test_do_not_contact_suppresses_the_person_everywhere(seeded):
    db = seeded
    pid = store.pro_id_for("linkedin:a")
    store.set_review(pid, "do_not_contact", "asked to be removed", db)
    sup = {(s["kind"], s["value"]) for s in store.list_suppression(db)}
    assert ("email", "asha@clinic.in") in sup and ("profile_url", "https://www.linkedin.com/in/a") in sup
    # a different record that carries the same address (e.g. found again through another profile) is also blocked
    twin = rec("instagram:asha", "asha_psych", channels=[email("asha@clinic.in")])
    store.upsert_professional(twin, "r2", db)
    store.set_review(twin.pro_id, "approved", "", db)
    assert store.get_professional(twin.pro_id, db)["suppressed"] == "email"
    assert twin.pro_id not in [r["pro_id"] for r in store.export_rows(["approved"], db)]


def test_domain_suppression_blocks_clinic_staff_but_never_a_shared_mail_provider(seeded):
    db = seeded
    store.add_suppression("domain", "https://www.bj.in/", "clinic asked to opt out", db)
    store.set_review(store.pro_id_for("linkedin:b"), "approved", "", db)
    assert store.get_professional(store.pro_id_for("linkedin:b"), db)["suppressed"] == "domain"
    with pytest.raises(ValueError, match="shared mail provider"):
        store.add_suppression("domain", "gmail.com", "", db)
    with pytest.raises(ValueError):
        store.add_suppression("telepathy", "x", "", db)
    assert store.remove_suppression("domain", "bj.in", db) is True


# ---- export ---------------------------------------------------------------------------------------------------------
def test_export_contains_only_approved_unsuppressed_people_with_provenance(seeded):
    db = seeded
    for key in ("linkedin:a", "linkedin:b", "instagram:c"):
        store.set_review(store.pro_id_for(key), "approved", "ok", db)
    store.set_review(store.pro_id_for("linkedin:b"), "do_not_contact", "no", db)
    rows = store.export_rows(["approved", "do_not_contact"], db)
    assert {r["name"] for r in rows} == {"Asha Rao", "carla"}                                  # DNC never exported, even if asked for
    asha = next(r for r in rows if r["name"] == "Asha Rao")
    assert asha["best_channel"] == "email" and asha["best_channel_value"] == "asha@clinic.in"
    assert asha["best_channel_source"] == "https://clinic.in/contact" and asha["email_is_generic"] is False
    assert next(r for r in rows if r["name"] == "carla")["best_channel"] == "instagram"
    assert store.export_rows(["new"], db)[0]["review_status"] == "new"


def test_best_channel_prefers_a_personal_email_over_a_clinic_inbox_over_a_form():
    chans = [
        {"kind": "contact_form", "value": "u", "is_generic": False, "source_url": ""},
        {"kind": "email", "value": "info@x.in", "is_generic": True, "source_url": ""},
        {"kind": "email", "value": "asha@x.in", "is_generic": False, "source_url": ""},
    ]
    assert store.best_channel(chans)["value"] == "asha@x.in"
    assert store.best_channel(chans[:2])["value"] == "info@x.in"
    assert store.best_channel(chans[:1])["kind"] == "contact_form"
    assert store.best_channel([]) is None


def test_run_lifecycle(db):
    store.create_run("run_1", {"city": "Bangalore"}, db)
    store.update_run("run_1", progress={"phase": "searching"}, db_path=db)
    assert store.get_run("run_1", db)["status"] == "running" and store.get_run("run_1", db)["finished_at"] is None
    store.update_run("run_1", status="completed", stats={"kept": 3}, db_path=db)
    r = store.get_run("run_1", db)
    assert r["status"] == "completed" and r["stats"] == {"kept": 3} and r["finished_at"] and r["params"] == {"city": "Bangalore"}
    assert store.get_run("missing", db) is None


# ---- scoring ------------------------------------------------------------------------------------------------------------
def test_fit_score_orders_the_review_queue_sensibly():
    strong = rec(conf=0.92, credentials=["RCI", "Licensed"], licence=Licence(numbers=[{"body": "RCI", "number": "A1", "context": ""}]),
                 channels=[email("asha@x.in")], followers=2000)
    clinic_inbox = rec(conf=0.92, credentials=["RCI"], channels=[email("info@x.in", True)])
    profile_only = rec(conf=0.92, credentials=["RCI"], channels=[Channel(kind="linkedin", value="https://l", source_url="s")])
    weak = rec(conf=0.4, city_match=False)
    org = rec("website:o.in", conf=0.7, entity_type="organisation", role="organisation", channels=[email("info@o.in", True)])
    scores = [fit_score(x) for x in (strong, clinic_inbox, profile_only, weak)]
    assert scores == sorted(scores, reverse=True) and scores[0] > 85
    assert fit_score(org) < fit_score(clinic_inbox)
    assert 0 <= fit_score(weak) <= 100
