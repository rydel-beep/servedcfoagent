"""
conversation.py
--------------
THREAD STATE + ANAPHORA + ADVISORY for the chat/voice pipeline. Runs BEFORE the recital handlers so
a strategy question gets analysis (not a figure dump) and an anaphoric follow-up ("3 more closes")
resolves against the active metric via the deterministic scenario engine — not a context-blind
handler re-fire.

- THREAD STATE: the active metric under discussion, derived from recent turns (no separate store —
  history is already carried across text + voice).
- ADVISORY: "how do we reduce/improve X" → driver decomposition + ranked levers, grounded in the
  engine figures + Rydel's documented principles (never invented policy).
- ANAPHORA/SCENARIO: follow-ups resolve to the active metric and run the scenario engine; results
  are LABELLED hypothetical; "what IS X" returns the actual.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# metric aliases → canonical key
_METRIC_ALIASES = [
    ("ltgp_cac", re.compile(r"ltgp[\s:/-]*cac|ltgp[\s-]*to[\s-]*cac", re.I)),
    ("roas", re.compile(r"\broas\b|return on ad spend", re.I)),
    ("cac", re.compile(r"\bcac\b|loaded cac|acquisition cost", re.I)),
]
_METRIC_LABEL = {"cac": "loaded CAC", "roas": "ROAS", "ltgp_cac": "LTGP:CAC"}

_ADVISORY_RE = re.compile(
    r"\bhow (can|do|could|might|should) (we|i|you)\b.*\b(reduce|lower|cut|drop|improve|lift|raise|"
    r"grow|increase|boost|bring down|get .* down|optimi[sz]e)\b", re.I)
_WHATIS_RE = re.compile(r"\bwhat('?s| is| are)\b.*\b(cac|roas|ltgp|actual|current)\b|\bactuals?\b", re.I)
_RESET_RE = re.compile(r"\bback to (actuals?|reality|the real)\b|\bforget (that|the scenario)\b", re.I)
# anaphoric scenario follow-ups (no explicit metric needed)
_FOLLOWUP_RE = re.compile(
    r"\b(\d+)\s*(more|extra|additional|fewer|less)\s*closes?\b"
    r"|\b(an? )?(extra|another)\s*(\d+)\s*closes?\b"
    r"|\bwhat (if|about|does that|would that)\b"
    r"|\band (over|in) (the )?(last )?\d+\s*days?\b"
    r"|\b(double|halve|half|triple)\b.*\b(spend|ad|closes?|budget)\b"
    r"|\band the (ratio|cac|roas)\b", re.I)


def active_metric(history: list) -> str | None:
    """The metric currently under discussion, from the most recent turns (assistant + user)."""
    for m in reversed(history or []):
        txt = m.get("content") or ""
        for key, rx in _METRIC_ALIASES:
            if rx.search(txt):
                return key
    return None


def _fmt(v, kind):
    if v is None:
        return "n/a"
    if kind == "cac":
        return f"${v:,.0f}"
    return f"{v:.2f}x"


# ── Anaphora / scenario ──────────────────────────────────────────────────────

def _parse_deltas(text: str) -> tuple[dict, int, str | None]:
    """Extract (deltas, window_days, explicit_metric) from a follow-up utterance."""
    t = text.lower()
    deltas = {}
    # closes ± N
    m = re.search(r"(\d+)\s*(?:more|extra|additional)\s*closes?|\b(?:an?\s+)?(?:extra|another)\s*(\d+)\s*closes?", t)
    if m:
        deltas["closes_add"] = int(m.group(1) or m.group(2))
    m2 = re.search(r"(\d+)\s*(?:fewer|less)\s*closes?", t)
    if m2:
        deltas["closes_add"] = -int(m2.group(1))
    m3 = re.search(r"\bat\s+(\d+)\s+closes?\b|\bwith\s+(\d+)\s+closes?\b", t)
    if m3 and "closes_add" not in deltas:
        deltas["closes_set"] = int(m3.group(1) or m3.group(2))
    # ad spend multipliers
    if re.search(r"\b(double|2x|twice)\b.*\b(spend|ad|budget)\b|\bspend\b.*\bdoubl", t):
        deltas["ad_mult"] = 2.0
    if re.search(r"\b(halve|half|cut in half)\b.*\b(spend|ad|budget)\b|\bspend\b.*\bhalv", t):
        deltas["ad_mult"] = 0.5
    m4 = re.search(r"(?:ad spend|spend|budget)\s*(?:to|of|=)?\s*\$?([\d,]+)\s*k?\b", t)
    if m4 and "ad_mult" not in deltas:
        val = float(m4.group(1).replace(",", "")) * (1000 if "k" in t[m4.end()-1:m4.end()+1] else 1)
        deltas["ad_set"] = val
    # window
    window_days = 30
    mw = re.search(r"\b(?:over|in|last)\s+(\d+)\s*days?\b", t)
    if mw:
        window_days = int(mw.group(1))
    elif re.search(r"\b(60|sixty)\s*days?\b", t):
        window_days = 60
    elif re.search(r"\b(90|ninety)\s*days?\b|\bquarter\b", t):
        window_days = 90
    # explicit metric switch in the follow-up
    exp = None
    if re.search(r"\bratio\b|\bltgp\b", t):
        exp = "ltgp_cac"
    elif re.search(r"\broas\b", t):
        exp = "roas"
    return deltas, window_days, exp


def _actual_reply(metric: str, window_days: int, note: str) -> tuple[str, bool]:
    import scenario_engine
    b = scenario_engine.base_components(window_days)
    if not b:
        return None, False
    val = {"cac": b.get("cac_loaded"), "roas": b.get("roas"), "ltgp_cac": b.get("ltgp_cac")}.get(metric)
    win = f"last {window_days} days" if window_days != 30 else "last 30 days"
    return f"The actual {_METRIC_LABEL[metric]} is {_fmt(val, metric)} ({win}) — {note}", True


def handle_anaphora(user_msg: str, history: list) -> tuple[str | None, bool]:
    """Resolve a scenario follow-up against the active metric. Deterministic (scenario engine)."""
    if not user_msg or not (_FOLLOWUP_RE.search(user_msg) or _RESET_RE.search(user_msg) or _WHATIS_RE.search(user_msg)):
        return None, False
    metric = active_metric(history)
    deltas, window_days, exp = _parse_deltas(user_msg)
    if exp:
        metric = exp
    # No active metric to resolve against. Only claim the turn when there's a CONCRETE scenario delta
    # (e.g. "3 more closes") — then ask one clarifier. A vague "what if..." with no delta belongs to
    # the forecast/model path, so fall through (never hijack an MRR/runway what-if).
    if not metric:
        if deltas:
            return ("Happy to run that — which metric, CAC, ROAS, or LTGP:CAC?"), True
        return None, False
    # "back to actuals" / "what IS X" → the real number, labelled (scenarios never overwrite actuals).
    if _RESET_RE.search(user_msg) or (_WHATIS_RE.search(user_msg) and not deltas):
        return _actual_reply(metric, window_days, "that's the real number, not a scenario.")
    # Explicit metric switch with no delta ("and the ratio?") → that metric's actual.
    if exp and not deltas and window_days == 30:
        return _actual_reply(metric, window_days, "the current actual.")
    # Window-only change ("and over 60 days?") with no delta → the actual at that window.
    if not deltas and window_days != 30:
        return _actual_reply(metric, window_days, "the actual over that window.")
    if not deltas:
        return None, False   # a vague "what about..." with no parseable delta → let the model handle

    import scenario_engine
    res = scenario_engine.compute(metric, deltas, window_days=window_days, scale_comms=False)
    if not res or not res.get("scenario_value"):
        return None, False
    lbl = _METRIC_LABEL[metric]
    base_v, scen_v, pct = res.get("base_value"), res["scenario_value"], res.get("pct_change")
    line = f"{lbl} would be {_fmt(scen_v, metric)} — {res['formula']}"
    if base_v and pct is not None:
        direction = "down" if pct < 0 else "up"
        line += f", {direction} ~{abs(pct):.0f}% from the actual {_fmt(base_v, metric)}"
    line += f" ({res['assumption']})."
    # second-order note for closes-driven CAC (comms would scale per-close in reality)
    if metric == "cac" and res.get("base", {}).get("closer_comm") and deltas.get("closes_add"):
        alt = scenario_engine.compute(metric, deltas, window_days=window_days, scale_comms=True)
        if alt and alt.get("scenario_value") and abs(alt["scenario_value"] - scen_v) > 1:
            line += f" If commissions scale per close instead, it's {_fmt(alt['scenario_value'], metric)}."
    return line, True


# ── Advisory mode ────────────────────────────────────────────────────────────

def _principle_for(metric: str) -> str | None:
    """Cite a documented principle from memory (never invent policy). Returns a short clause or None."""
    try:
        import memory
        recall = memory.build_recall_context(f"{metric} commission re-sign pricing principle", conversation_id=None)
        blk = (recall or {}).get("block") or ""
        for line in blk.splitlines():
            low = line.lower()
            if ("commission" in low or "re-sign" in low or "resign" in low or "renewal" in low) and metric == "cac":
                return line.strip("-• ").strip()[:200]
    except Exception:
        pass
    return None


def handle_advisory(user_msg: str) -> tuple[str | None, bool]:
    """'How do we reduce/improve X' → decomposition + ranked levers (analysis, not recital)."""
    if not user_msg or not _ADVISORY_RE.search(user_msg):
        return None, False
    metric = None
    for key, rx in _METRIC_ALIASES:
        if rx.search(user_msg):
            metric = key
            break
    if metric is None:
        return None, False   # advisory needs a known metric; else let the model field it

    import scenario_engine
    b = scenario_engine.base_components(30)
    if not b:
        return None, False

    if metric == "cac":
        ad, closer, setter = b.get("ad_spend") or 0, b.get("closer_comm") or 0, b.get("setter_comm") or 0
        cac, closes = b.get("cac_loaded"), b.get("closes")
        tot = ad + closer + setter or 1
        comps = sorted([("closer commissions", closer), ("ad spend", ad), ("setter commissions", setter)],
                       key=lambda x: -x[1])
        rank = ", ".join(f"{n} ${v:,.0f} ({round(100*v/tot)}%)" for n, v in comps)
        # lever 1: volume
        s3 = scenario_engine.compute("cac", {"closes_add": 3}, 30)
        vol = (f"more closes against those semi-fixed costs — +3 takes it to ~{_fmt(s3['scenario_value'],'cac')} "
               f"({s3.get('pct_change'):+.0f}%)" if s3 and s3.get("scenario_value") else "more closes dilute the fixed cost base")
        principle = _principle_for("cac")
        comm_lever = ("your biggest line is " + comps[0][0] + " — "
                      + (principle if principle else "worth reviewing the commission structure (re-signs vs new-client rates)"))
        reply = (f"{_METRIC_LABEL[metric]} is {_fmt(cac,'cac')} on {closes} closes, and it's driven by: {rank}. "
                 f"Three levers by impact: (1) volume — {vol}, no extra spend; "
                 f"(2) commission structure — {comm_lever}; "
                 f"(3) ad efficiency — CPL and close-rate on the ${ad:,.0f} ad line. "
                 "Want me to quantify any of these?")
        return reply, True

    if metric == "roas":
        roas, ad = b.get("roas"), b.get("ad_spend") or 0
        reply = (f"{_METRIC_LABEL[metric]} is {_fmt(roas,'roas')} (contracted ÷ ad spend). Two levers: "
                 f"(1) close more from the same ${ad:,.0f} spend — every extra close lifts the numerator; "
                 "(2) lift average contract value (offer/pricing). Want me to run either?")
        return reply, True

    if metric == "ltgp_cac":
        v = b.get("ltgp_cac"); gm = b.get("gross_margin_pct")
        reply = (f"{_METRIC_LABEL[metric]} is {_fmt(v,'ltgp_cac')}. It lifts three ways: lower CAC (volume or "
                 f"commissions), higher average contract, or better gross margin (currently {gm}%). "
                 "Which lever do you want quantified?")
        return reply, True
    return None, False


# ── Entry point (advisory first, then anaphora) ──────────────────────────────

def handle(user_msg: str, history: list, actor: dict | None = None) -> tuple[str | None, bool]:
    if not user_msg:
        return None, False
    r, h = handle_advisory(user_msg)
    if h:
        return r, h
    return handle_anaphora(user_msg, history)
