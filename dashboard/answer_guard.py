"""answer_guard.py — EDITH CANNOT STATE A NUMBER THE ENGINE DIDN'T (#165).

The witnessed failure: she answered "net profit margin is 6.9% — $3,400 ÷
$49,396" as fact. The dollars were real context values from a stale rolling
window; the 6.9% was her own arithmetic; and nothing could stop her because
no engine owned the number.

This guard makes that structurally impossible on business turns:

  · every financial number in her reply (a $-amount, a percentage, or a
    money-sized figure) must match a value present in the engine context
    SHE WAS GIVEN THIS TURN — the engines' own output, to normal rounding.
    A derived ratio, a remembered figure, an improvised estimate: blocked.
  · a blocked reply is REWRITTEN to say which figures could not be backed
    and that the metric isn't computed (or is degraded) — never a guess.
  · DEFLECTION is blocked the same way: she never tells the owner to go and
    pull a figure from the dashboard. She pulls it, or says why she can't.

Numbers that are not financial claims pass untouched: years, dates, times,
small bare counts. The guard is deliberately generous about FORMATTING
(cents dropped, rounding to the nearest ten/hundred/thousand, "k"/"m"
shorthand) and deliberately strict about EXISTENCE.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# $1,234.56 · 12.3% · 1,234 · 45k · 1.2m
_NUM_RE = re.compile(
    r"(?P<cur>\$)\s*(?P<curval>\d[\d,]*(?:\.\d+)?)\s*(?P<curk>[kKmM]\b)?"
    r"|(?P<pctval>\d[\d,]*(?:\.\d+)?)\s*%"
    r"|(?<![\d.$%])(?P<plain>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)(?![\d%])"
)

_DEFLECT_RE = re.compile(
    r"pull (?:the )?(?:live|latest|current).{0,30}(?:from|via|on) the "
    r"(?:finance )?dashboard"
    r"|check the (?:finance )?dashboard for"
    r"|go to the dashboard"
    r"|open the dashboard (?:and|to)"
    r"|you can find (?:this|that|it) on the dashboard", re.I)

_YEAR_RANGE = (1990, 2100)


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def extract_financial(text: str) -> list[dict]:
    """Every number in the text that reads as a financial claim."""
    out = []
    for m in _NUM_RE.finditer(text or ""):
        if m.group("cur"):
            v = _to_float(m.group("curval"))
            if v is None:
                continue
            k = (m.group("curk") or "").lower()
            v *= 1000 if k == "k" else 1_000_000 if k == "m" else 1
            out.append({"kind": "money", "value": v, "text": m.group(0).strip()})
        elif m.group("pctval") is not None:
            v = _to_float(m.group("pctval"))
            if v is not None:
                out.append({"kind": "pct", "value": v, "text": m.group(0).strip()})
        else:
            v = _to_float(m.group("plain"))
            if v is None:
                continue
            # a bare 4-digit integer in the year range is a year, not money
            if v == int(v) and _YEAR_RANGE[0] <= v <= _YEAR_RANGE[1]:
                continue
            if v < 1000:
                continue                     # bare small numbers are counts
            out.append({"kind": "money", "value": v, "text": m.group(0).strip()})
    return out


def whitelist(context_text: str) -> list[float]:
    """Every numeric value present in the engine context this turn."""
    vals = []
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", context_text or ""):
        v = _to_float(m.group(0))
        if v is not None:
            vals.append(v)
    return vals


def _backed(v: float, kind: str, wl: list[float]) -> bool:
    for w in wl:
        if abs(v - w) <= (0.055 if kind == "pct" else 0.51):
            return True
        # normal rounding a speaker does: cents dropped, tens/hundreds/
        # thousands, one decimal place on a percentage
        for nd in (0, 1):
            if abs(v - round(w, nd)) <= 0.001:
                return True
        if kind == "money":
            for q in (10, 100, 1000):
                if abs(v - round(w / q) * q) <= 0.51:
                    return True
    return False


def validate(reply: str, context_text: str) -> dict:
    wl = whitelist(context_text)
    unbacked = [n for n in extract_financial(reply)
                if not _backed(n["value"], n["kind"], wl)]
    deflection = bool(_DEFLECT_RE.search(reply or ""))
    return {"ok": not unbacked and not deflection,
            "unbacked": unbacked, "deflection": deflection,
            "whitelist_size": len(wl)}


K_BLOCK_LOG = "answer:guard_blocks"      # ring: every block + what replaced it


def _log_block(question: str | None, nums: str, answered_instead: str) -> None:
    try:
        import kv_store
        from helpers import now_sydney
        ring = kv_store.get(K_BLOCK_LOG) or []
        ring.append({"at": now_sydney().isoformat(),
                     "question": (question or "")[:160],
                     "blocked_figures": nums,
                     "answered_instead": answered_instead[:240]})
        kv_store.put(K_BLOCK_LOG, ring[-200:])
    except Exception:  # noqa: BLE001 — bookkeeping never breaks a reply
        pass


def apply(reply: str, context_text: str | None,
          question: str | None = None) -> tuple[str, dict]:
    """→ (final_reply, report). Context of None means a general (non-business)
    turn — the guard stands down; coffee costs what it costs.

    v2 (#168): a block is not a refusal. The bad number still cannot pass,
    but the QUESTION gets answered — re-composed from the resolver's engine
    values; and when the resolver doesn't own the metric, one honest
    sentence plus the engine's nearest computed figure. The old 'ask me for
    a metric the engine owns' copy is retired."""
    if context_text is None:
        return reply, {"ok": True, "skipped": "general turn"}
    v = validate(reply, context_text)
    if v["ok"]:
        return reply, v
    if v["unbacked"]:
        nums = ", ".join(sorted({n["text"] for n in v["unbacked"]})[:6])
        rewritten = None
        try:
            import answer_engine
            rewritten = answer_engine.recompose_for(question or "")
            if rewritten is None:
                near = answer_engine.nearest_figure()
                rewritten = (
                    f"I can't back {nums} with an engine value, so here's "
                    f"the engine's own nearest read instead: {near}")
        except Exception as e:  # noqa: BLE001
            logger.warning("guard recompose failed: %s", e)
        if rewritten is None:
            rewritten = (f"I can't back {nums} with an engine value — that "
                         f"figure isn't computed this cycle; the next "
                         f"refresh will carry it.")
        v["recomposed"] = True
        logger.warning("answer_guard blocked %d unbacked figure(s): %s — "
                       "answered from the engine instead",
                       len(v["unbacked"]), nums)
        _log_block(question, nums, rewritten)
        return rewritten, v
    rewritten = re.sub(_DEFLECT_RE, "let me pull it", reply)
    logger.warning("answer_guard rewrote a deflection")
    _log_block(question, "(deflection)", rewritten)
    return rewritten, v
