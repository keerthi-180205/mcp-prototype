"""Triage of comments on MMTF's own posts + the own-accounts guard. Offline, rules only."""

import pytest

from server.audience.accounts import (
    AccountsError, accounts_for, is_own, normalise_handle, parse_accounts, require_account,
)
from server.audience.triage import triage


# ---- the urgent label: recall matters more than precision ----------------------------------------------------
@pytest.mark.parametrize("text", [
    "I want to die",
    "i just wanna die tbh",
    "I am going to kill myself if I fail this exam",
    "thinking about ending my life",
    "I can't go on like this",
    "there is no reason to live anymore",
    "I don't want to live anymore",
    "dont want to be alive",
    "i wish i was dead",
    "everyone would be better off without me",
    "I've been cutting myself again",
    "self harm is the only thing that helps me",
    "I'm suicidal and nobody knows",
    "my brother is suicidal, what do I do",
    "feeling like dying every day",
    "i want to end it all",
    "I took an overdose last night",
    "I wish I could just not wake up",
    "pleeeease help i want to die",
    "marna chahta hu ab",
    "jeene ka mann nahi karta",
    "mujhe khudkushi ke khayal aate hain",
    "मैं आत्महत्या करना चाहता हूँ",
])
def test_possible_crisis_comments_are_always_flagged(text):
    t = triage(text)
    assert t.label == "crisis" and t.priority == 3, text
    assert t.reasons, "the reviewer must be told which phrase triggered it"


@pytest.mark.parametrize("text", [
    "This exam is going to kill me lol",
    "We all die someday",
    "My grandfather is dying of cancer, praying for him",
    "great post, loved it",
    "Suicide rates among students are rising",           # general talk: still reviewed, but not the urgent lane
    "I could kill for a pizza right now",
    "end of the video was great",
    "let's end this stigma together",
])
def test_ordinary_or_general_comments_are_not_urgent(text):
    assert triage(text).label != "crisis", text


def test_general_talk_about_suicide_still_gets_a_human_look_at_lower_priority():
    t = triage("Suicide rates among students are rising")
    assert t.label == "distress" and t.priority == 1
    assert "no personal statement" in t.reasons[0]


# ---- asking for help ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "please help me",
    "plz help",
    "I need help, I don't know who to talk to",
    "how can I find a therapist in Bangalore?",
    "Can someone please suggest a good counsellor",
    "looking for a psychologist for my sister",
    "who can I talk to about this",
    "need to talk to someone",
    "mujhe help chahiye",
    "therapist ka number batao",
])
def test_comments_asking_for_help_are_queued_as_seeking_help(text):
    t = triage(text)
    assert t.label == "seeking_help" and t.priority == 2, text


# ---- distress: needs a first-person statement --------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "I feel so anxious before every exam",
    "my anxiety is out of control",
    "I'm so stressed with board exams",
    "i can't sleep at night",
    "I feel hopeless and alone",
    "I am completely burnt out",
    "I have been crying every day",
])
def test_first_person_suffering_is_distress(text):
    t = triage(text)
    assert t.label == "distress" and t.priority == 1, text


@pytest.mark.parametrize("text", [
    "Anxiety is real, thanks for talking about it",
    "Stress affects everyone",
    "Great reminder that burnout is serious",
    "Loneliness is an epidemic",
])
def test_general_statements_about_a_topic_are_not_treated_as_distress(text):
    assert triage(text).label not in {"crisis", "seeking_help", "distress"}, text


def test_urgency_order_is_crisis_then_help_then_distress():
    assert triage("I'm so anxious, please help, I want to die").label == "crisis"
    assert triage("I'm so anxious, please help me").label == "seeking_help"


# ---- everything else ---------------------------------------------------------------------------------------------
def test_questions_spam_and_praise():
    assert triage("How much does a session cost?").label == "question"
    assert triage("Where can I book an appointment?").label == "question"
    assert triage("DM me for crypto signals https://spam.example").label == "spam"
    assert triage("Thank you, this was so helpful").label == "positive"
    assert triage("❤️🙏").label == "positive"
    assert triage("first").label == "other"


def test_emoji_only_and_one_word_reactions_are_generic():
    assert triage("❤️❤️❤️").generic
    assert triage("nice").generic
    assert triage("🔥").generic
    assert not triage("I feel so anxious before every exam").generic


def test_possible_minor_is_a_cue_that_never_changes_the_label():
    t = triage("I'm 15 and I feel so anxious about my board exams")
    assert t.possible_minor and t.label == "distress"
    assert triage("I'm in class 10 and I want to die").possible_minor
    assert not triage("I'm 15 minutes late, sorry").possible_minor
    assert not triage("I'm 34 and feel so anxious").possible_minor


def test_reasons_quote_the_phrase_and_are_capped():
    t = triage("please help me, I want to kill myself, I can't go on, no reason to live")
    assert len(t.reasons) <= 3 and any("kill myself" in r for r in t.reasons)


def test_empty_and_odd_input_never_raise():
    for text in ("", "   ", None, "\u0000", "a" * 20000):
        assert triage(text).label in {"other", "positive", "spam", "question", "distress", "crisis", "seeking_help"}


# ---- own accounts guard ---------------------------------------------------------------------------------------------
def test_handles_are_normalised_from_urls_and_prefixes():
    assert normalise_handle("@MyAccount") == "myaccount"
    assert normalise_handle("https://www.instagram.com/MyAccount/") == "myaccount"
    assert normalise_handle("https://www.youtube.com/@Chan.Nel") == "chan.nel"
    assert normalise_handle("u/some_user") == "some_user"


def test_accounts_are_parsed_per_platform(monkeypatch):
    monkeypatch.setenv("MMTF_OWN_ACCOUNTS", "instagram: Foo, @bar ; yt:@Chan\nlinkedin:company/x".replace("company/x", "https://www.linkedin.com/company/mmtf"))
    assert accounts_for("instagram") == ["bar", "foo"]
    assert accounts_for("youtube") == ["chan"] and accounts_for("ig") == ["bar", "foo"]
    assert is_own("instagram", "@FOO") and not is_own("instagram", "someone_else") and not is_own("x", "foo")


@pytest.mark.parametrize("raw", ["instagram", "instagram:", "mastodon:foo", ":foo"])
def test_malformed_configuration_raises_instead_of_silently_weakening_the_guard(raw):
    with pytest.raises(AccountsError):
        parse_accounts(raw)


def test_require_account_refuses_anything_not_configured(monkeypatch):
    monkeypatch.setenv("MMTF_OWN_ACCOUNTS", "instagram:ours")
    assert require_account("instagram") == "ours" and require_account("instagram", "@Ours") == "ours"
    with pytest.raises(AccountsError, match="not one of MMTF's"):
        require_account("instagram", "somebody_else")
    with pytest.raises(AccountsError, match="MMTF_OWN_ACCOUNTS"):
        require_account("youtube")
    monkeypatch.setenv("MMTF_OWN_ACCOUNTS", "instagram:one,two")
    with pytest.raises(AccountsError, match="say which"):
        require_account("instagram")
    monkeypatch.delenv("MMTF_OWN_ACCOUNTS")
    with pytest.raises(AccountsError, match="MMTF_OWN_ACCOUNTS"):
        require_account("instagram")
