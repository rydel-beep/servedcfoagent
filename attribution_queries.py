"""
attribution_queries.py
----------------------
Deterministic EDITH answers over the attribution engine (LTC Scoreboard Part 1.5).
Every figure is read from attribution_engine.compute() — the same cached result the
APIs serve; nothing here computes independently. Entity-gated: an unknown creative or
lead name is REFUSED honestly, never guessed (the deterministic-recall rule).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_SCOREBOARD_RE = re.compile(
    r"(show|give|read)( me)?( the)? (ad |creative )?scoreboard|"
    r"(ad|creative) scoreboard|scoreboard for (the )?(ads|creatives)", re.I)

_WHICH_CREATIVE_RE = re.compile(
    r"which (ad|creative)( |\w)*(brought|got|produced|closed|won)\s+(?P<who>[\w' .&-]{3,40})|"
    r"what (ad|creative) did\s+(?P<who2>[\w' .&-]{3,40})\s+come (from|in on)", re.I)

_QUALIFIED_FOR_RE = re.compile(
    r"how many qualified( leads)? (did|has|from)\s+(?P<cr>[\w' ·.&()\[\]/-]{3,70}?)"
    r"\s*(bring|brought|produce[d]?|generate[d]?|get|got)?\s*\??$", re.I)


def _engine(days: int = 30):
    import attribution_engine
    return attribution_engine.compute(days=days)


def handle_scoreboard_command(text: str) -> tuple[str | None, bool]:
    if not text or not _SCOREBOARD_RE.search(text):
        return None, False
    r = _engine(30)
    t = r.get("totals") or {}
    vl = r.get("verdict_layer") or {}
    ads = [c for c in (r.get("creatives") or []) if c["tier"] == "ad"
           and (c["spend"] or c["leads"] or c["closes"])]
    ads.sort(key=lambda c: (-c["spend"], -c["leads"]))
    lines = []
    for c in ads[:5]:
        v = c.get("verdict") or "—"
        lines.append(f"{c['label'][:38]}: {c['leads']} leads, {c['qualified']} qualified, "
                     f"{c['closes']} closes, ${c['cash']:,.0f} cash on ${c['spend']:,.0f} — {v}")
    un = next((c for c in r.get("creatives") or [] if c["tier"] == "unattributed"), {})
    msg = (f"Ad scoreboard, last 30 days — {t.get('attributed_leads')} of {t.get('leads')} "
           f"leads ad-attributed ({t.get('attribution_rate_pct')}%). Top by spend: "
           + "; ".join(lines) + f". Unattributed: {un.get('leads', 0)} leads, "
           f"{un.get('closes', 0)} closes.")
    cc = (vl.get("constraint_check") or {}).get("read")
    if cc:
        msg += f" Constraint read: {cc}"
    return msg, True


def handle_which_creative_command(text: str) -> tuple[str | None, bool]:
    if not text:
        return None, False
    m = _WHICH_CREATIVE_RE.search(text)
    if not m:
        return None, False
    who = (m.group("who") or m.group("who2") or "").strip().rstrip("?").strip()
    if len(who) < 3:
        return None, False
    r = _engine(365)
    wl = who.lower()
    hits = [row for row in (r.get("rows") or [])
            if wl in (row["name"] or "").lower() or wl in (row["business"] or "").lower()]
    if not hits:
        return (f"I can't find a lead named “{who}” in the tracker window I read — "
                f"I won't guess an attribution."), True
    row = hits[0]
    cr = row["creative"]
    chain = f"came in {row['input_date']}"
    if row.get("set_date"):
        chain += f", set {row['set_date']}"
    if row.get("close_date"):
        chain += f", closed {row['close_date']}"
        if row.get("cash"):
            chain += f" (${row['cash']:,.0f} cash)"
    if cr["tier"] == "ad":
        return (f"{row['name']}{' (' + row['business'] + ')' if row['business'] and row['business'] != row['name'] else ''} "
                f"— {chain} — first-touch creative: {cr['label']}."), True
    if cr["tier"] == "ig_dm":
        return f"{row['name']} — {chain} — came through Instagram DM (channel-level; no ad identity exists for DMs).", True
    return (f"{row['name']} — {chain} — that lead is unattributed: no ad identity was "
            f"captured for them (pre-UTM capture or no GHL match)."), True


def handle_qualified_for_creative_command(text: str) -> tuple[str | None, bool]:
    if not text:
        return None, False
    m = _QUALIFIED_FOR_RE.search(text.strip())
    if not m:
        return None, False
    cr = (m.group("cr") or "").strip()
    if len(cr) < 3:
        return None, False
    r = _engine(30)
    cl = cr.lower()
    ads = [c for c in (r.get("creatives") or []) if c["tier"] == "ad"]
    hits = [c for c in ads if cl in c["label"].lower() or cl in c["creative_key"]]
    if not hits:
        return (f"I don't see a creative matching “{cr}” in this window — "
                f"I won't guess. Ask for the scoreboard to hear the live names."), True
    c = sorted(hits, key=lambda x: -x["leads"])[0]
    qr = (r.get("qualified_rule") or {})
    return (f"{c['label']}: {c['qualified']} qualified of {c['leads']} leads in the last "
            f"30 days ({c.get('revenue_unknown', 0)} revenue-unknown excluded, shown). "
            f"Qualified = setter-finalised, revenue band at or above "
            f"${qr.get('floor_monthly', 20000):,.0f}/month, form answered."), True


_FLAGS_RE = re.compile(
    r"what'?s?\s+flagged(?:\s+on)?(?:\s+the)?(?:\s+ad)?(?:\s+(?:board|dashboard))?|"
    r"any\s+(?:ad\s+)?flags\b|ad\s+flags|flags\s+on\s+the\s+ad", re.I)


def handle_flags_command(text: str) -> tuple[str | None, bool]:
    """'what's flagged on the ad board?' → the scorecard flags, verbatim. Deterministic;
    reads the SAME flags module the /ads dashboard renders — never a second opinion."""
    if not text or not _FLAGS_RE.search(text):
        return None, False
    import attribution_flags
    r = _engine(30)
    trailing = None
    try:
        import nav_router
        r90 = nav_router._cached_result(90)
        trailing = (r90.get("totals") or {}).get("attribution_rate_pct") if r90 else None
    except Exception:
        pass
    sc = attribution_flags.scorecard(r, trailing_attr_rate=trailing)
    fl = sc["flags"]
    if not fl:
        msg = "No flags on the ad board this window — every threshold is clear."
        if sc.get("constraint_line"):
            msg += " " + sc["constraint_line"]
        return msg, True
    lines = []
    for f in fl[:5]:
        who = f.get("creative") or "account-level"
        lines.append(f"{who}: {f['headline']} — {f['question']}")
    msg = f"{len(fl)} flag(s) on the ad board (30 days): " + "; ".join(lines)
    if len(fl) > 5:
        msg += f"; plus {len(fl) - 5} more on the dashboard."
    return msg, True


_TRACKING_ACC_RE = re.compile(
    r"how (accurate|good) is (our|the) (ad )?track|tracking (accuracy|health|quality)|"
    r"how('s| is) (our|the) tracking", re.I)
_SHARED_NAME_RE = re.compile(
    r"which ads? share the name\s+[\"“']?(?P<nm>[\w .·&()\[\]/-]{3,60}?)[\"”']?\s*\??$", re.I)


def handle_tracking_accuracy_command(text: str) -> tuple[str | None, bool]:
    """'how accurate is our ad tracking?' → the identity-health numbers, verbatim."""
    if not text or not _TRACKING_ACC_RE.search(text):
        return None, False
    import attribution_flags
    r = _engine(30)
    ih = attribution_flags.identity_health(r)
    t = r.get("totals") or {}
    msg = (f"Tracking health, last 30 days: {t.get('attribution_rate_pct')}% of leads "
           f"ad-attributed ({t.get('attributed_leads')}/{t.get('leads')}); of those, "
           f"{ih.get('exact_id_rate_pct')}% resolved by EXACT ad id — ids are truth, "
           f"names are labels. {ih.get('ambiguous_leads', 0)} lead(s) quarantined as "
           f"ambiguous-name (never guessed), {ih.get('unattributed_leads', 0)} "
           f"unattributed. Contact→tracker join: "
           f"{(ih.get('hops') or {}).get('hop2_contact_to_tracker', {}).get('match_rate_pct')}% "
           f"matched (email-first).")
    return msg, True


def handle_shared_name_command(text: str) -> tuple[str | None, bool]:
    """'which ads share the name X?' → the register entry, verbatim. Fabricated names
    are refused, never invented."""
    if not text:
        return None, False
    m = _SHARED_NAME_RE.search(text.strip())
    if not m:
        return None, False
    nm = m.group("nm").strip()
    import meta_entities
    cands = meta_entities.candidates_by_name(nm)
    if not cands:
        return (f"No ad in the account carries the name “{nm}” — I won't invent one. "
                f"Ask for the scoreboard to hear the live names."), True
    if len(cands) == 1:
        c = cands[0]
        return (f"“{nm}” is unique: ad {c['ad_id']} in {c.get('campaign_name') or '?'} "
                f"({(c.get('effective_status') or '?').lower()})."), True
    lines = [f"{c['ad_id']} in {c.get('campaign_name') or '?'} "
             f"({(c.get('effective_status') or '?').lower()})" for c in cands]
    return (f"“{nm}” is shared by {len(cands)} ads: " + "; ".join(lines) +
            ". On the board each is its own row, campaign-labelled; name-level view "
            "groups them deliberately."), True


_BASIS_RE = re.compile(
    r"what basis|which (clock|basis)|cohort or activity|basis am i looking at|"
    r"how are (these|the) (windows|numbers) counted", re.I)


def handle_basis_command(text: str) -> tuple[str | None, bool]:
    """'what basis am I looking at?' — the two clocks, plainly, with the worked example."""
    if not text or not _BASIS_RE.search(text):
        return None, False
    return ("The ad board runs ONE clock per view, never mixed. LEAD-COHORT (the "
            "default): leads that entered the window plus everything that later happened "
            "to them — true conversion rates; recent windows show fewer closes because "
            "closes lag. ACTIVITY: events dated in the window — a close from an earlier "
            "lead counts here and its row is annotated. Worked example: a lead enters in "
            "June and closes in August — cohort counts that close in JUNE's window, "
            "activity counts it in AUGUST's. The active clock is labelled in the board's "
            "banner and on every payload."), True


_INVARIANT_RE = re.compile(
    r"(are|is) the (invariants?|integrity checks?)|invariants? (green|status|ok)|"
    r"is this number right|numbers? (check out|coherent)", re.I)


def handle_invariants_command(text: str) -> tuple[str | None, bool]:
    """'are the invariants green?' → the runtime checks from the live result, verbatim."""
    if not text or not _INVARIANT_RE.search(text):
        return None, False
    r = _engine(30)
    inv = r.get("invariants") or []
    bad = [i for i in inv if not i["ok"]]
    rec = r.get("reconciliation") or {}
    msg = (f"Invariants, 30d {r.get('basis', 'cohort')} clock: "
           + ("ALL GREEN — every row coherent, " if not bad else
              f"{len(bad)} VIOLATION(S): " + "; ".join(
                  f"{b.get('row')}: {b['detail']}" for b in bad[:3]) + ". ")
           + f"Cross-checks: reconciliation {'OK' if rec.get('ok') else 'FAILING'} "
           f"(leads/closes/cash/spend vs the one-engine totals). "
           f"Headline closes always equal the tracker authority on the active clock.")
    return msg, True
