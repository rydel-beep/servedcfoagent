"""
intent_router.py
----------------
Three-tier intent gating with a DEFAULT-TO-CONVERSATION rule.

A voice/text turn is one of:
  TIER 1  explicit COMMANDS (set target, mark churned, resync) — strict phrasing, run first.
  TIER 2  factual DATA questions ("how many leads in June", "what's our cash") — deterministic.
  TIER 3  EVERYTHING ELSE — conversation (musing, strategising, venting). The DEFAULT.

The incident this fixes: a rambling voice musing ("...what we do for Served... the angle is more
on: dollar in dollar out...") tripped a data handler (a loose regex bridged "what" → "on") and
returned a random payroll row. The asymmetry rule: when unsure, prefer CONVERSATION — a slightly
generic reply beats a jarring data non-sequitur.

This module gates TIER 2: a long declarative ramble with no data-request structure SKIPS the
deterministic data handlers entirely and goes to the model. It also provides an entity-relevance
filter so a lookup about an entity never mentioned cannot reach the reply.
"""
from __future__ import annotations

import re

# Unambiguous data-request phrasing — fires TIER 2 at any length.
_EXPLICIT_DATA = re.compile(
    r"\b(how many|how much (is|are|do|does|did|'?s)|what'?s (our|the|my|it)|what is (our|the|my)|"
    r"what do we (pay|charge|owe|make|spend|have)|show me|list (the|our|all|my)|number of|count of|"
    r"who'?s the (latest|newest|biggest|last|top)|pull (the|our|up)|breakdown of|give me (the|our)|"
    r"how'?s our|what are our)\b", re.I)

# Terse metric/entity asks (a few words) are legitimate data requests even without a question frame.
_METRIC_WORD = re.compile(
    r"\b(cash|runway|burn|mrr|roas|ltgp|ltv|cac|payback|leads?|closes?|deals?|clients?|sets?|"
    r"appointments?|amex|payroll|salary|salaries|revenue|margin|spend|churn)\b", re.I)


def is_conversational_ramble(u: str) -> bool:
    """True when the utterance reads as a musing/strategy/vent with NO data-request structure —
    route it to conversation (TIER 3) and SKIP the deterministic data handlers."""
    if not u:
        return False
    t = u.strip()
    if _EXPLICIT_DATA.search(t):        # an explicit data ask, any length → NOT a ramble
        return False
    if t.endswith("?"):                 # a question → give the data handlers a chance
        return False
    words = t.split()
    if len(words) <= 6:                 # terse ("cash?", "june leads") → let handlers try
        return False
    # Long + declarative + no explicit data phrasing → a ramble. Even if it name-drops a metric
    # word mid-sentence ("...dollar in dollar out..."), the SHAPE is conversational.
    return True


# ── Entity-relevance output filter (the "Romano rule") ───────────────────────
# Proper-noun-ish tokens a deterministic reply might name (a person/client). If the reply names a
# specific entity that appears NOWHERE in the utterance/thread, the lookup is a non-sequitur → suppress.
_CAP_TOKEN = re.compile(r"\b([A-Z][a-z]{2,})\b")
_STOPWORDS = {"The", "For", "Meta", "Stripe", "Xero", "Amex", "Active", "Churned", "Status",
              "Latest", "Cash", "Team", "Whose", "Which", "Health", "Google", "Rydel", "Served",
              "Input", "Date", "Close", "Contract", "Loaded", "Note", "Gross", "Setter", "Closer",
              "Implied", "Team", "Total", "Payroll"}
# Aggregate/team replies name many people by design — never a single-entity misfire.
_AGGREGATE = re.compile(r"\b(team|payroll|total|across \d+ people|headcount|implied fx)\b", re.I)


def entity_relevant(reply: str, utterance: str, thread: str = "") -> bool:
    """Guard against the 'Romano rule': an ENTITY-SCOPED lookup (a person's salary) that names a
    person absent from what he said is a non-sequitur → suppress. A reply is relevant if it names
    NO distinctive entity, is an aggregate/team reply, or ANY named token appears in the thread.
    (Superlative/recency lookups like 'biggest deal' are exempted at the call site, not here.)"""
    if not reply:
        return True
    if _AGGREGATE.search(reply):
        return True
    ctx = _norm(utterance) + " " + _norm(thread)
    toks = [t for t in _CAP_TOKEN.findall(reply) if t not in _STOPWORDS]
    if not toks:
        return True                 # no named entity in the reply → always fine
    return any(_norm(t) in ctx for t in toks)   # a misfire names NONE of what he said


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower())
