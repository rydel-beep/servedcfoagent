"""
tests/test_intent_router.py
---------------------------
Three-tier intent routing: musings/strategy go to CONVERSATION (Tier 3), data questions still hit
the deterministic handlers (Tier 2), commands still fire (Tier 1). The exact Romano incident is the
acceptance test: a rambling positioning musing must NOT return a payroll row.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import intent_router as ir
import salary_view

# The verbatim failing utterance (transcribed voice musing).
_INCIDENT = ("what we do for Served, complete marketing system, the influencers, everything's there "
             "with the booking system, the angle is more on: they know exactly, dollar in dollar out, "
             "they can see exactly if it's working")

_MUSINGS = [
    _INCIDENT,
    "I'm thinking we should reposition around retention, because the ads only work if the system holds",
    "honestly the influencer stuff is what's separating us, nobody else bundles it like that",
    "we're spending a lot on ads lately and I'm not sure the offer is tight enough to justify it",
    "the revenue is fine but what I really care about is whether clients feel the dollar in dollar out",
    "what we charge should reflect the whole system, not just the ad management piece",
]

_DATA_QS = [
    "how many leads in June?",
    "what's our cash",
    "what do we pay Gabie?",
    "who's the latest lead",
    "biggest deal",
    "what's our ROAS last 30 days",
]


def test_incident_is_a_ramble():
    assert ir.is_conversational_ramble(_INCIDENT) is True


def test_all_musings_route_to_conversation():
    for m in _MUSINGS:
        assert ir.is_conversational_ramble(m) is True, f"musing wrongly gated as data: {m!r}"


def test_data_questions_are_not_rambles():
    for q in _DATA_QS:
        assert ir.is_conversational_ramble(q) is False, f"data question wrongly gated as ramble: {q!r}"


def test_salary_regex_no_longer_matches_the_ramble():
    # The root cause: (what|how much).*(…|on) bridged "what" → "on". Now it must NOT match.
    assert salary_view._PAY_RE.search(_INCIDENT) is None
    # but real salary questions still match
    assert salary_view._PAY_RE.search("what do we pay Gabie?")
    assert salary_view._PAY_RE.search("SMM salaries")
    assert salary_view._PAY_RE.search("total payroll")


def test_salary_handler_silent_on_the_ramble():
    reply, handled = salary_view.handle_salary_command(_INCIDENT)
    assert handled is False and reply is None


def test_entity_relevance_suppresses_unmentioned_person():
    # a single-person payroll row about someone never mentioned → suppressed
    assert ir.entity_relevant("Romano Real, FB ads: $1,050/mo", _INCIDENT) is False
    # a person he DID name → relevant
    assert ir.entity_relevant("Gabie Cruz, SMM: $1,200/mo", "what do we pay Gabie?") is True
    # aggregate/team replies are always relevant (name many by design)
    assert ir.entity_relevant("Team payroll: $18,891/mo across 19 people", "total payroll") is True
    # a reply naming no distinctive entity is fine
    assert ir.entity_relevant("June: 88 leads", "how many leads in June") is True
