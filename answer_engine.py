"""answer_engine.py — EDITH ANSWERS THE QUESTION (#168).

The witnessed thread (24 Sep): asked "are we at negative net profit from
Sept 1 to 24?", EDITH returned a three-basis wall and never said yes or no;
asked again for the plain figures, she computed $79,755 − $22,739 in her
head, the guard rightly blocked the $57,016, and she REFUSED a question the
engine could answer — while the tile on screen held both numbers.

Three fixes live here:

  THE RESOLVER   a deterministic map from the question to {metric, basis,
                 window, shape} BEFORE any composition. "right now /
                 landed / in the bank" → collected; "if everyone pays / on
                 contract" → management; "the books / Xero" → recognised;
                 ambiguous → collected AND management, one line each —
                 never three bases, never sub-metrics unasked. Explicit
                 dates win; "this month" → month to date; no window given
                 → month to date, stated. Every answer logs and SHOWS the
                 resolution ("Answered as: …") so a wrong read is visible.

  ANSWER-SHAPED  every figure an answer could need is an ENGINE value —
  OUTPUTS        net profit $ AND %, TOTAL COSTS (the exact figure she
                 once derived by hand), the gap, collected % of
                 contracted, per-day pacing, deltas vs last month and the
                 FY26 baseline — so she never subtracts. calc() turns any
                 remaining derivation (pro-rata, ratio, difference) into a
                 tool call.

  THE CONTRACT   sentence 1 answers the literal question — yes/no
                 questions get the word first; "net profit" leads with
                 dollars, "margin" leads with %. Then ≤2 sentences of
                 context (the other basis, the gap). Financial numbers per
                 answer capped (ANSWER_NUMBER_CAP, default 6) unless a
                 breakdown is asked. No doctrine recitals. Follow-ups keep
                 the resolved window unless the user changes it.

Everything reads pl_engine's loop-computed summary (the same cache the
Today tile reads), so EDITH, the tile and the Money page state one set of
numbers under one set of window words.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re

import kv_store
import pl_engine
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_RESOLUTIONS = "answer:resolutions"     # ring: every resolution logged
K_CALC_LOG = "answer:calc_log"           # ring: every calc() call

BASIS_LABEL = {
    "collected": "What actually landed",
    "management": "If everyone pays",
    "recognised": "On the books (Xero)",
    "cash": "Cash in minus cash out",
}
BASIS_NOUN = {"collected": "collected", "management": "contracted",
              "recognised": "recognised", "cash": "banked"}

# registry ids for the shaped values — the definitions registry explains
# each once, and every surface points at the same entry
REGISTRY_IDS = {
    "net_profit": "net_margin", "net_margin_pct": "net_margin",
    "gross_margin_pct": "gross_margin",
    "contribution_margin_pct": "contribution_margin",
    "total_costs": "total_costs", "gap": "margin_gap",
    "per_day": "per_day_pacing", "deltas": "margin_delta",
}


def _cap() -> int:
    try:
        return max(3, int(os.environ.get("ANSWER_NUMBER_CAP", "6")))
    except ValueError:
        return 6


# ── THE RESOLVER ────────────────────────────────────────────────────────────

# order matters: "in the bank" (collected) must win before "bank" (cash)
_BASIS_RULES = [
    ("collected", re.compile(
        r"right now|actually landed|\blanded\b|in the bank|\bactual\b|"
        r"\bactually\b|\breal\b|\bcollected\b", re.I)),
    ("management", re.compile(
        r"if everyone pays|contract(?:ed)?\b|on contract", re.I)),
    ("recognised", re.compile(
        r"the books|\bxero\b|recognised|recognized", re.I)),
    ("cash", re.compile(r"cash basis|\bbank\b", re.I)),
]

_MONTH_TOKENS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH_ALT = ("jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
              "jun[e]?|jul[y]?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|"
              "nov(?:ember)?|dec(?:ember)?")
_RANGE_RE = re.compile(
    rf"(?:(?P<m1>{_MONTH_ALT})\.?\s+)?(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?"
    rf"\s*(?:to|through|until|thru|[-–—])\s*(?:the\s+)?"
    rf"(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(?:of\s+)?(?P<m2>{_MONTH_ALT})\b)?",
    re.I)
_BARE_MONTH_RE = re.compile(rf"\b(?P<m>{_MONTH_ALT})\b\.?(?:\s+(?P<y>20\d\d))?",
                            re.I)

_WINDOW_KEYWORDS = [
    ("mtd", re.compile(r"this month|month to date|\bmtd\b|so far this month", re.I)),
    ("last_month", re.compile(r"last month", re.I)),
    ("last_30d", re.compile(r"(last|past|trailing)\s*(30|thirty)\s*days", re.I)),
    ("t3", re.compile(r"trailing (3|three)|last (3|three) months|this quarter", re.I)),
    ("t12", re.compile(r"trailing (12|twelve)|last (12|twelve) months|past year", re.I)),
    ("fytd", re.compile(r"financial year|\bfy\s?(to date|td)?\b|fytd", re.I)),
    ("projection", re.compile(r"month.?end|project(?:ed|ion)|finish the month", re.I)),
]

_SEGMENT_RE = re.compile(
    r"\bby state\b|\bby city\b|\bper region\b|\bby region\b|\bby client\b"
    r"|\bby channel\b", re.I)
_UNKNOWN_METRIC_RE = re.compile(r"\bebitda\b|\bebit\b|\bnpat\b", re.I)

_YESNO_RE = re.compile(
    r"^\s*(are|is|am|was|were|do|does|did|have|has|will|would|can|could)\b",
    re.I)
_NEGATIVE_SIDE_RE = re.compile(r"negative|in the red|losing|loss|below zero",
                               re.I)

_METRIC_RULES = [
    ("why_negative", re.compile(r"why.{0,30}negative|why.{0,25}(in the red|"
                                r"losing money|a loss)", re.I)),
    ("gap", re.compile(r"\bthe gap\b|money (?:we'?re|we are|you'?re)? ?owed|"
                       r"still owed|how much .{0,15}owed", re.I)),
    ("gross", re.compile(r"gross (margin|profit)", re.I)),
    ("operating", re.compile(r"operating (margin|profit)|\bpbt\b", re.I)),
    ("contribution", re.compile(r"contribution (margin|profit)?", re.I)),
    ("total_costs", re.compile(r"total costs?\b|costs? in total", re.I)),
    ("revenue", re.compile(r"\brevenue\b(?!.{0,12}margin)", re.I)),
    ("net", re.compile(r"net (profit|margin)|profit margin|\bmargins?\b|"
                       r"profitab|\bprofit\b|negative|in the red|"
                       r"losing money|break.?even|if everyone pays|"
                       r"actually landed|\blanded\b", re.I)),
]

_PCT_FIRST_RE = re.compile(r"margin|profitab|\bpercent|%", re.I)

_ANSWERED_AS_RE = re.compile(r"Answered as: (?P<metric>[^·]+) · "
                             r"(?P<bases>[^·]+) · (?P<window>[^·]+) ·")


def _explicit_window(text: str):
    """Explicit dates win. → (window, note) or None."""
    t = today_sydney()
    m = _RANGE_RE.search(text or "")
    if m:
        mon_tok = (m.group("m1") or m.group("m2") or "").lower()[:4].rstrip(".")
        mon = _MONTH_TOKENS.get(mon_tok) or _MONTH_TOKENS.get(mon_tok[:3])
        if mon:
            d1, d2 = int(m.group("d1")), int(m.group("d2"))
            year = t.year if mon <= t.month else t.year - 1
            mkey = f"{year}-{mon:02d}"
            if mkey == f"{t.year}-{t.month:02d}" and d1 == 1 and d2 == t.day:
                return ("mtd", None)
            _, end_s = pl_engine.month_bounds(mkey)
            if d1 == 1 and d2 == int(end_s[8:10]):
                return (("month", mkey), None)
            near = ("mtd" if mkey == f"{t.year}-{t.month:02d}"
                    else ("month", mkey))
            return (near, f"asked {d1}–{d2}; the nearest computed window is "
                          f"the calendar one shown")
    for name, rx in _WINDOW_KEYWORDS:
        if rx.search(text or ""):
            return (name, None)
    bm = _BARE_MONTH_RE.search(text or "")
    if bm:
        mon = _MONTH_TOKENS.get(bm.group("m").lower()[:4].rstrip(".")) or \
            _MONTH_TOKENS.get(bm.group("m").lower()[:3])
        if mon:
            year = int(bm.group("y") or (t.year if mon <= t.month else t.year - 1))
            mkey = f"{year}-{mon:02d}"
            if mkey == f"{t.year}-{t.month:02d}":
                return ("mtd", None)
            return (("month", mkey), None)
    return None


def _window_from_words(words: str):
    """Read a window back out of an earlier 'Answered as:' line, so a
    follow-up keeps the window it was answered in."""
    w = (words or "").strip()
    if "(month to date" in w:
        return "mtd"
    m = re.match(r"([A-Z][a-z]+) (20\d\d)$", w)
    if m:
        mon = _MONTH_TOKENS.get(m.group(1).lower()[:3])
        if mon:
            mkey = f"{m.group(2)}-{mon:02d}"
            prior = pl_engine.months_back(1)[0]
            return "last_month" if mkey == prior else ("month", mkey)
    if re.search(r"\d+ \w+ → \d+ \w+", w):
        return "last_30d"
    return None


def _prior_resolution(history) -> dict | None:
    for msg in reversed(history or []):
        if not (isinstance(msg, dict) and msg.get("role") == "assistant"):
            continue
        m = _ANSWERED_AS_RE.search(msg.get("content") or "")
        if m:
            win = _window_from_words(m.group("window"))
            return {"window": win,
                    "bases": [b.strip() for b in
                              m.group("bases").replace("(asked without a basis)", "")
                              .split("+")],
                    "metric": m.group("metric").strip()}
    return None


def resolve(text: str, history=None) -> dict:
    """The deterministic map: question → {metric, bases, window, shape}."""
    t = text or ""

    # UNKNOWN METRIC / SEGMENTATION the engine doesn't compute
    if _UNKNOWN_METRIC_RE.search(t) or _SEGMENT_RE.search(t):
        seg = _SEGMENT_RE.search(t)
        name = (_UNKNOWN_METRIC_RE.search(t).group(0).upper()
                if _UNKNOWN_METRIC_RE.search(t) else "that split")
        if seg:
            name += f" {seg.group(0).lower()}"
        res = {"metric": "not_computed", "asked": name.strip(),
               "bases": ["management"], "window": "mtd",
               "shape": "not_computed", "window_note": None,
               "window_source": "default"}
        _log_resolution(t, res)
        return res

    # METRIC
    metric = "net"
    for name, rx in _METRIC_RULES:
        if rx.search(t):
            metric = name
            break

    # BASIS
    bases = [b for b, rx in _BASIS_RULES if rx.search(t)]
    basis_source = "stated"
    if not bases:
        bases, basis_source = ["collected", "management"], "ambiguous"
    elif len(bases) > 2:
        bases = bases[:2]

    # the two MTD panels travel together: a net-profit ask on one of them
    # gets the other as its one context line (the tile shows both; so do we)
    if metric == "net" and len(bases) == 1 and \
            bases[0] in ("collected", "management"):
        bases = bases + (["management"] if bases[0] == "collected"
                         else ["collected"])

    # WINDOW — explicit dates win; then keywords; then the follow-up's
    # window; then month-to-date, stated.
    window, note, source = "mtd", None, "default"
    exp = _explicit_window(t)
    if exp:
        window, note = exp
        source = "stated"
    else:
        prior = _prior_resolution(history)
        if prior and prior.get("window"):
            window, source = prior["window"], "kept from your last question"

    # SHAPE
    if _YESNO_RE.search(t):
        shape = "yesno"
    elif metric in ("why_negative", "gap"):
        shape = metric
    elif re.search(r"breakdown|the ladder|full table|line by line", t, re.I):
        shape = "breakdown"
    elif _PCT_FIRST_RE.search(t) and "profit" not in t.lower():
        shape = "pct_first"
    else:
        shape = "dollars_first"

    res = {"metric": metric, "bases": bases, "window": window,
           "shape": shape, "window_note": note, "window_source": source,
           "basis_source": basis_source}
    _log_resolution(t, res)
    return res


def _log_resolution(q: str, res: dict) -> None:
    try:
        ring = kv_store.get(K_RESOLUTIONS) or []
        ring.append({"at": now_sydney().isoformat(), "q": (q or "")[:160],
                     **{k: str(res.get(k)) for k in
                        ("metric", "bases", "window", "shape")}})
        kv_store.put(K_RESOLUTIONS, ring[-200:])
    except Exception:  # noqa: BLE001 — logging never breaks an answer
        pass


# ── ANSWER-SHAPED ENGINE VALUES ─────────────────────────────────────────────

def shaped(basis: str, window, d: dict | None = None) -> dict:
    """One basis × one window → every value an answer could need, engine-
    owned. Reads the loop-computed cache first (the tile's own numbers);
    falls to the engine's stored calendar months for rarer windows."""
    if d is None:
        d = (pl_engine.cached_summary() or {}).get("data") or {}
    cvc = d.get("contracted_vs_collected") or {}
    # a named month that IS last month reads last month's cache
    if isinstance(window, tuple) and window[0] == "month":
        try:
            if window[1] == pl_engine.months_back(1)[0]:
                window = "last_month"
            elif window[1] == f"{today_sydney().year}-{today_sydney().month:02d}":
                window = "mtd"
        except Exception:  # noqa: BLE001
            pass
    r = None
    if window == "mtd":
        r = {"management": d.get("management_mtd"),
             "collected": cvc.get("collected_mtd"),
             }.get(basis)
        if basis == "collected" and r:
            r = {**r, "basis": "collected", "ok": True}
    elif window == "last_30d":
        if basis != "collected":
            return {"ok": False, "basis": basis,
                    "reason": "a dated 30-day window is computed on the "
                              "collected basis only — the nearest for this "
                              "basis is month to date"}
        r = cvc.get("collected_30d")
        if r:
            r = {**r, "basis": "collected", "ok": True}
    elif window == "last_month":
        r = {"recognised": d.get("recognised_last_month"),
             "management": d.get("management_last_month"),
             "collected": d.get("collected_last_month"),
             }.get(basis)
    elif window == "t3" and basis == "management":
        r = d.get("run_rate_t3")
    if r is None:
        try:
            if isinstance(window, tuple) and window[0] == "month":
                fn = {"management": pl_engine.management,
                      "recognised": pl_engine.recognised,
                      "cash": pl_engine.cash,
                      "collected": pl_engine.collected_month}[basis]
                r = fn(window[1])
                r.setdefault("window_words", pl_engine._mword(window[1]))
            else:
                r = pl_engine.window(basis, window if isinstance(window, str)
                                     else "mtd")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "basis": basis, "reason": str(e)[:120]}
    if not (r or {}).get("ok"):
        return {"ok": False, "basis": basis,
                "reason": (r or {}).get("reason") or "not computed yet"}
    out = dict(r)
    out["basis"] = basis
    # the gap + collected share ride on every MTD read
    gap = cvc.get("gap") or {}
    if window == "mtd" and gap.get("amount") is not None:
        out["gap"] = gap["amount"]
        out["pct_collected"] = gap.get("pct_collected")
    # per-day pacing from the window's own day count
    dc = out.get("day_count") or {}
    if dc.get("elapsed"):
        out["per_day"] = {
            "revenue": round((out.get("revenue") or 0) / dc["elapsed"], 2),
            "net": round((out.get("net_profit") or 0) / dc["elapsed"], 2)}
    # deltas vs last month (same basis, from the cache) and FY26
    lm = {"recognised": d.get("recognised_last_month"),
          "management": d.get("management_last_month"),
          "collected": d.get("collected_last_month")}.get(basis) or {}
    deltas = {}
    if (lm.get("ok") and lm.get("net_margin_pct") is not None
            and out.get("net_margin_pct") is not None):
        deltas["vs_last_month_pp"] = round(
            out["net_margin_pct"] - lm["net_margin_pct"], 1)
    fy = (d.get("fy26_baseline") or {}).get("net")
    if fy is not None and out.get("net_margin_pct") is not None:
        deltas["vs_fy26_pp"] = round(out["net_margin_pct"] - fy, 1)
    if deltas:
        out["deltas"] = deltas
    out["registry"] = REGISTRY_IDS
    return out


def calc(op: str, a=None, b=None, values=None, days=None, days_in=None) -> dict:
    """Derived numbers as a TOOL CALL, never head arithmetic: pro-rata,
    ratio, difference, sum, per-day. Logged."""
    try:
        if op == "prorata":
            v = round(float(a) * int(days) / int(days_in), 2)
            math = f"{a} × {days}/{days_in}"
        elif op == "ratio":
            v = round(float(a) / float(b) * 100, 1)
            math = f"{a} ÷ {b} × 100"
        elif op == "difference":
            v = round(float(a) - float(b), 2)
            math = f"{a} − {b}"
        elif op == "sum":
            v = round(sum(float(x) for x in (values or [])), 2)
            math = " + ".join(str(x) for x in (values or []))
        elif op == "per_day":
            v = round(float(a) / int(days), 2)
            math = f"{a} ÷ {days}"
        else:
            return {"ok": False, "error": f"unknown op {op!r}"}
    except (TypeError, ValueError, ZeroDivisionError) as e:
        return {"ok": False, "error": str(e)[:80]}
    out = {"ok": True, "op": op, "value": v, "math": math}
    try:
        ring = kv_store.get(K_CALC_LOG) or []
        ring.append({"at": now_sydney().isoformat(), **out})
        kv_store.put(K_CALC_LOG, ring[-200:])
    except Exception:  # noqa: BLE001
        pass
    return out


# ── COMPOSITION (the answer contract) ───────────────────────────────────────

def _money(v) -> str:
    if v is None:
        return "—"
    sign = "−" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{'−' if v < 0 else ''}{abs(v)}%"


def _count_financial(text: str) -> int:
    from dashboard import answer_guard
    return len(answer_guard.extract_financial(text))


_METRIC_KEYS = {"net": ("net_profit", "net_margin_pct", "net"),
                "gross": ("gross_profit", "gross_margin_pct", "gross"),
                "operating": ("operating_profit", "operating_margin_pct",
                              "operating"),
                "contribution": ("contribution", "contribution_margin_pct",
                                 "contribution"),
                "revenue": ("revenue", None, "revenue"),
                "total_costs": ("total_costs", None, "total costs")}


def _figure_line(s: dict, metric: str, shape: str, full: bool,
                 with_window: bool) -> str:
    dol_key, pct_key, word = _METRIC_KEYS.get(metric, _METRIC_KEYS["net"])
    label = BASIS_LABEL.get(s.get("basis"), s.get("basis", ""))
    words = s.get("window_words") or s.get("month") or "window unnamed"
    noun = BASIS_NOUN.get(s.get("basis"), "")
    dol = _money(s.get(dol_key))
    pct = _pct(s.get(pct_key)) if pct_key else None
    head = f"{label} — {words}: " if with_window else f"{label}: "
    if metric in ("revenue", "total_costs"):
        return f"{head}{word} {dol}."
    if shape == "pct_first" and pct is not None:
        body = (f"{pct} {word} margin ({dol} on "
                f"{_money(s.get('revenue'))} {noun})" if full
                else f"{pct} {word} margin ({dol})")
    else:
        body = (f"{word} {dol} ({pct} on {_money(s.get('revenue'))} {noun})"
                if full and pct is not None else
                f"{word} {dol}" + (f" ({pct})" if pct is not None else ""))
    return head + body + "."


def _gap_sentence(s: dict) -> str | None:
    if s.get("gap") is None:
        return None
    return f"The gap is {_money(s['gap'])} still owed."


def _unavailable_line(basis: str, s: dict) -> str:
    return (f"{BASIS_LABEL.get(basis, basis)}: not computed for that window "
            f"({s.get('reason') or 'no engine value'}).")


def _nearest_line(d: dict | None = None) -> str:
    """The nearest metric the engine DOES own, given immediately."""
    s = shaped("management", "mtd", d)
    if s.get("ok"):
        return _figure_line(s, "operating", "dollars_first", True, True)
    s2 = shaped("collected", "mtd", d)
    if s2.get("ok"):
        return _figure_line(s2, "net", "dollars_first", True, True)
    return ("the engine hasn't computed this cycle's summary yet — it will "
            "on the next refresh.")


def _answered_as(res: dict, shapes: list[dict]) -> str:
    metric_words = {"net": "net profit", "gross": "gross margin",
                    "operating": "operating profit",
                    "contribution": "contribution margin",
                    "revenue": "revenue", "total_costs": "total costs",
                    "gap": "the gap", "why_negative": "why negative",
                    "not_computed": f"not computed ({res.get('asked')})",
                    }.get(res["metric"], res["metric"])
    if res.get("shape") == "yesno":
        metric_words = "yes/no on " + metric_words
    bases = " + ".join(res["bases"])
    if res.get("basis_source") == "ambiguous":
        bases += " (asked without a basis)"
    win = res["window"]
    fallback = (pl_engine._mword(win[1]) if isinstance(win, tuple)
                else str(win))
    words = next((s.get("window_words") for s in shapes
                  if s.get("window_words")), None) or fallback
    asof = next((str(s.get("as_of"))[:16] for s in shapes if s.get("as_of")),
                str(now_sydney())[:16])
    tail = f" · window {res['window_source']}" if \
        res.get("window_source") not in (None, "stated", "default") else ""
    return f"Answered as: {metric_words} · {bases} · {words} · as of {asof}.{tail}"


def compose(res: dict, d: dict | None = None) -> str:
    """Template-filled from engine values only — the composer formats, it
    never derives. Sentence 1 answers the literal question."""
    if d is None:
        d = (pl_engine.cached_summary() or {}).get("data") or {}

    if res["metric"] == "not_computed":
        near = _nearest_line(d)
        body = (f"{res['asked']} isn't a metric the engine computes — I "
                f"won't improvise it. Nearest computed figure: {near}")
        return body + "\n\n" + _answered_as(res, [shaped("management", "mtd", d)])

    shapes = [shaped(b, res["window"], d) for b in res["bases"]]
    good = [s for s in shapes if s.get("ok")]
    cvc = d.get("contracted_vs_collected") or {}

    if not good:
        near = _nearest_line(d)
        why = "; ".join(s.get("reason") or "" for s in shapes if not s.get("ok"))
        body = (f"That window isn't computed ({why or 'no engine value'}). "
                f"Nearest computed figure: {near}")
        return body + "\n\n" + _answered_as(res, shapes)

    sentences: list[str] = []
    primary = good[0]
    metric = res["metric"] if res["metric"] in _METRIC_KEYS else "net"
    shape = res["shape"]

    if res["metric"] == "why_negative" or res["metric"] == "gap":
        gap = cvc.get("gap") or {}
        recon = cvc.get("ar_reconciliation") or {}
        if gap.get("amount") is None:
            sentences.append("The gap isn't computed for that window — it "
                             "lives on the month-to-date read. "
                             + _nearest_line(d))
        else:
            if res["metric"] == "why_negative":
                gl = gap.get("line") or ("the collected total trails the "
                                         "contracted total")
                gl = gl[0].lower() + gl[1:]
                sentences.append(f"Negative because {gl} — the window's "
                                 f"costs don't shrink while you wait.")
            else:
                sentences.append(f"{gap.get('line', 'The gap')} — "
                                 f"{_money(gap.get('amount'))} still owed.")
            top = (recon.get("top_unpaid") or [])[:2]
            if top:
                sentences.append("Top unpaid: " + "; ".join(
                    f"{u.get('client')} {_money(u.get('outstanding'))}"
                    + (f" ({u['days_overdue']}d overdue)"
                       if u.get("days_overdue") else "") for u in top) + ".")
            sentences.append("Collect those and the landed margin follows — "
                             "say 'show receivables' for the full list.")
        body = " ".join(sentences)
        return body + "\n\n" + _answered_as(res, shapes)

    if shape == "yesno":
        neg = bool(_NEGATIVE_SIDE_RE.search(res.get("_question", ""))) or \
            res.get("_negative_side", False)
        val = primary.get(_METRIC_KEYS[metric][0]) or 0
        cond = (val < 0) if neg else (val > 0)
        word = "Yes" if cond else "No"
        first = _figure_line(primary, metric, shape, True, True)
        first = first[0].lower() + first[1:]
        sentences.append(f"{word} — {first}")
    else:
        sentences.append(_figure_line(primary, metric, shape, True, True))

    # context: the other basis (one line), then the gap — never a third basis
    for s in good[1:2]:
        sentences.append(_figure_line(s, metric, shape, False, False))
    for s in shapes:
        if not s.get("ok"):
            sentences.append(_unavailable_line(s.get("basis", ""), s))
    gap_s = _gap_sentence(primary) or (
        _gap_sentence(good[1]) if len(good) > 1 else None)
    if gap_s and res["window"] == "mtd" and metric == "net":
        sentences.append(gap_s)

    # the number cap: trim optional context until the cap holds
    cap = _cap()
    if shape != "breakdown":
        while len(sentences) > 1 and \
                _count_financial(" ".join(sentences)) > cap:
            sentences.pop()
        sentences = sentences[:3]

    if shape == "breakdown":
        lines = [_figure_line(primary, m, "dollars_first", True, m == "net")
                 for m in ("revenue", "gross", "operating", "total_costs",
                           "net")]
        sentences = [sentences[0]] + lines

    if res.get("window_note"):
        sentences.append(f"({res['window_note']}.)")

    body = " ".join(sentences)
    return body + "\n\n" + _answered_as(res, shapes)


# ── THE HANDLER (both chat paths route here before the model) ───────────────

_TRIGGER_RE = re.compile(
    r"net (?:profit|margin)|profit margin|gross margin|operating margin|"
    r"contribution margin|\bmargins?\b|profitab|\bnet profit\b|"
    r"\bprofit\b|in the red|losing money|break.?even|"
    r"if everyone pays|actually landed|collected margin|"
    r"money (?:we'?re|we are|you'?re) owed|still owed|"
    r"why.{0,30}negative|\bnegative\b.{0,30}(profit|margin|net)|"
    r"(profit|margin|net).{0,30}\bnegative\b|"
    r"\bebitda\b|\bnpat\b|total costs?\b", re.I)
# leave scenarios, advisory and the lifecycle board to their own handlers
_EXCLUDE_RE = re.compile(
    r"\bwhat if\b|\bpath to\b|\bimprove\b|\bincrease\b|\bdouble\b|"
    r"\bscenario\b|\bsimulate\b|\bwhy did we (kill|pause)\b|"
    r"\bcommission\b|\broas\b", re.I)


def handle_profit_question(text: str, history: list | None = None):
    """The resolver-first profit/margin drill: resolve → shaped engine
    values → the answer contract. Replaces the #165 three-basis wall."""
    t = text or ""
    if not _TRIGGER_RE.search(t) or _EXCLUDE_RE.search(t):
        return None, False
    try:
        res = resolve(t, history)
        res["_question"] = t
        reply = compose(res)
    except Exception as e:  # noqa: BLE001
        logger.warning("answer_engine failed for %r: %s", t[:60], e)
        return None, False
    return reply, True


def recompose_for(question: str) -> str | None:
    """Validator v2's road back: when a model reply is blocked, answer the
    QUESTION from the engine instead of refusing."""
    r, h = handle_profit_question(question or "")
    return r if h else None


def nearest_figure() -> str:
    """For blocked replies outside the resolver's reach: the engine's own
    nearest read, given immediately."""
    return _nearest_line(None)
