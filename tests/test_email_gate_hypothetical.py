"""Proof-gate hypothetical-math refinement (Rydel's decision 2026-08-04) +
the S0–S5 segment ladder. A held draft is a trivial unhold; a fabricated
fact-looking number in a sent email is a credibility hit — so ambiguity holds."""
import email_pipeline as ep
import segments as sg

G = {"wins": [{"title": "Rung Brisbane", "body": "spent $853 and got 445 directions"}],
     "voice_examples": [], "content_piece": None}


def _fails(text):
    return ep.proof_gate(text, G)


def test_hypothetical_if_framing_allowed():
    r = _fails("If a $90 table no-shows twice a week, that's $780 a month walking out.")
    assert r["ok"], r["failures"]
    assert len(r["hypothetical_allowed"]) >= 1


def test_buildup_math_allowed():
    r = _fails("A $90 table x 10 no-shows = $900 gone.")
    assert r["ok"], r["failures"]


def test_achieved_result_still_held():
    r = _fails("We recovered $234,000 for clients last quarter.")
    assert not r["ok"]
    assert "untraceable figure" in r["failures"][0]


def test_client_seen_result_still_held():
    r = _fails("Clients see $4,500 back in 60 days.")
    assert not r["ok"]


def test_traceable_figure_passes_without_framing():
    r = _fails("Rung Brisbane spent $853 and got 445 directions.")
    assert r["ok"], r["failures"]


def test_hypothetical_framing_does_not_launder_client_names():
    # a NAMED client with an untraceable dollar result holds even under 'if' framing
    r = _fails("If Casa De Amor made $50,000 from this, imagine your venue.")
    assert not r["ok"]


def test_trigger_must_be_same_sentence():
    r = _fails("Imagine the difference. Venues make $9,999 with this.")
    assert not r["ok"]          # trigger in a DIFFERENT sentence doesn't launder the figure


# ── ladder ────────────────────────────────────────────────────────────────────
def _c(**kw):
    base = {"id": "c1", "email": "x@y.com", "tags": [], "dateAdded": None,
            "lastActivity": None, "dateUpdated": None, "dnd": False}
    base.update(kw)
    return base


def _cls(c, active=frozenset(), churned=frozenset(), frozen=frozenset()):
    return sg.classify_contact(c, active_client_emails=set(active),
                               churned_emails=set(churned), frozen_contact_ids=set(frozen))


def _iso(days_ago):
    from helpers import now_sydney
    from datetime import timedelta
    return (now_sydney() - timedelta(days=days_ago)).isoformat()


def test_s0_beats_everything():
    assert _cls(_c(dnd=True, email="a@b.co"), active={"a@b.co"}) == ("S0", None)
    assert _cls(_c(tags=["Unsubscribed"]))[0] == "S0"
    assert _cls(_c(email=""))[0] == "S0"


def test_s1_s2_s3_order():
    assert _cls(_c(email="a@b.co"), active={"a@b.co"}) == ("S1", None)
    assert _cls(_c(id="c9"), frozen={"c9"}) == ("S2", None)
    assert _cls(_c(email="gone@b.co"), churned={"gone@b.co"}) == ("S3", None)


def test_s4_tiers_and_s5():
    assert _cls(_c(dateAdded=_iso(5))) == ("S4", "HOT")
    assert _cls(_c(lastActivity=_iso(45))) == ("S4", "WARM")
    assert _cls(_c(lastActivity=_iso(100))) == ("S4", "COLD")
    assert _cls(_c(lastActivity=_iso(200))) == ("S5", None)
    assert _cls(_c()) == ("S5", None)     # no recency signal at all → suppressed


def test_discount_lock():
    assert not sg.discount_lock_check("Grab 20% off this week only!")["ok"]
    assert not sg.discount_lock_check("use promo code SERVED")["ok"]
    assert sg.discount_lock_check("we'll build the audit in as a bonus")["ok"]


def test_sendable_rules():
    assert not sg.sendable_check("S1", None, is_convert_ask=False)["ok"]
    assert not sg.sendable_check("S5", None, is_convert_ask=False)["ok"]
    assert sg.sendable_check("S4", "HOT", is_convert_ask=True)["ok"]
    assert not sg.sendable_check("S4", "WARM", is_convert_ask=True)["ok"]
    assert sg.sendable_check("S4", "WARM", is_convert_ask=True, click_triggered=True)["ok"]
    assert not sg.sendable_check("S4", "COLD", is_convert_ask=True, click_triggered=True)["ok"]
    assert sg.sendable_check("S4", "COLD", is_convert_ask=False)["ok"]
