"""
tracker_read.py
---------------
READ-BEFORE-ASSERT for tracker FIELD STATES. The deterministic-recall rule (never invent an
entity/number) extended to cell states: any claim about a field — "blank", "filled", "shows $X" —
must come from a deterministic read of that exact row AT ANSWER TIME, never model inference.

The incident: EDITH said "cash collected is blank for Hung's Chinese / Lost Sheep / Akuna" — the
cells were FILLED ($8,305 / $15,950 / $1,650). No handler read those cells; the model inferred
"blank" from a cash figure's composition and asserted it. This module makes the read happen:
- read_client_row() resyncs recent/stale tabs, reads the row, returns every field VERBATIM + sync time.
- client_context() injects the verbatim row into the model so it can't guess a field state.
- the self-check loop (challenge → resync → re-read → correct/confirm + root cause) lives here too.
"""
from __future__ import annotations

import logging
import re

from helpers import now_sydney, today_sydney
from closes_view import _money, _date

logger = logging.getLogger(__name__)

_KEY = "ltc_tracker"
_TAB = "Lead-to-Cash Tracker"
_RECENT_RESYNC_SECONDS = 10 * 60   # a tab older than this is resynced before a field-state answer


# ── Sync state + resync ──────────────────────────────────────────────────────

def sync_state(key: str = _KEY) -> dict:
    """last_sync_at + age + status for a mirrored tab. Empty dict if DB/mirror unavailable."""
    try:
        import db
        if not db.db_configured():
            return {}
        with db.get_conn() as c:
            st = c.execute("SELECT last_sync_at, last_sync_status, row_count "
                           "FROM sheet_sync_state WHERE tab=%s", (key,)).fetchone()
        if not st or not st.get("last_sync_at"):
            return {}
        age = (now_sydney() - st["last_sync_at"]).total_seconds()
        return {"last_sync_at": st["last_sync_at"], "age_seconds": age,
                "status": st.get("last_sync_status"), "row_count": st.get("row_count")}
    except Exception as e:
        logger.info("sync_state(%s) failed: %s", key, e)
        return {}


def _sync_label(state: dict) -> str:
    ts = state.get("last_sync_at")
    if not ts:
        return "just now (live read)"
    try:
        return ts.strftime("%-I:%M%p").lower() + " today" if ts.date() == today_sydney() else str(ts)[:16]
    except Exception:
        return str(ts)[:16]


def resync(key: str = _KEY) -> dict:
    """Targeted resync of one tab, then return its fresh sync_state. Safe if DB down (no-op)."""
    try:
        import sheet_mirror
        sheet_mirror.sync_tab(key)
    except Exception as e:
        logger.info("resync(%s) failed: %s", key, e)
    return sync_state(key)


def _rows() -> list[list[str]]:
    """Tracker rows — mirror first, live fallback (so it works on Railway AND locally)."""
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name(_TAB)
        if rows:
            return rows
        m = sheet_mirror.MIRRORED_TABS.get(_KEY) or {}
        return sheet_mirror._live_fetch(m.get("book"), _TAB) or []
    except Exception as e:
        logger.info("_rows() failed: %s", e)
        return []


# ── Column detection + row read ──────────────────────────────────────────────

def _cols(hdr: list[str]) -> dict:
    def find(*kws):
        for i, c in enumerate(hdr):
            cl = (c or "").lower()
            if all(k in cl for k in kws):
                return i
        return None
    cols = {
        "business": find("business", "name") or find("business"),
        "offer": find("offer", "sold") or find("offer"),
        "close": find("close", "date"),
        "contract": find("contract", "value") or find("contract"),
        "cash": find("cash", "collect"),
        "set_date": find("set", "date"),
        "source": find("lead", "source") or find("source"),
    }
    # CLOSER outcome = the "Call Outcome" at/before Close Date (a setter one sits earlier).
    outs = [i for i, c in enumerate(hdr) if "call outcome" in (c or "").lower()]
    if outs:
        cd = cols.get("close")
        before = [k for k in outs if cd is None or k <= cd]
        cols["outcome"] = max(before) if before else max(outs)
    return cols


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def read_client_row(name: str, fresh: bool = True) -> dict:
    """Deterministic read of a client's tracker row — resyncs first if the tab is stale/recent-row.
    Returns every relevant field VERBATIM (as it sits in the cell) + the sync time. found=False if
    the client isn't in the tracker. NEVER infers — a blank cell is reported as blank because it IS."""
    st = sync_state()
    if fresh and (not st or st.get("age_seconds", 1e9) > _RECENT_RESYNC_SECONDS):
        st = resync() or st

    rows = _rows()
    if not rows:
        return {"found": False, "degraded": True, "reason": "tracker unavailable",
                "sync_label": _sync_label(st)}
    hi = next((i for i, r in enumerate(rows[:6]) if any("close date" in (c or "").lower() for c in r)), 0)
    cols = _cols(rows[hi])
    bcol = cols.get("business")
    q = _norm(name)
    match = None
    for r in rows[hi + 1:]:
        if bcol is not None and bcol < len(r):
            bn = _norm(r[bcol])
            if bn and (bn == q or q in bn or bn in q):
                match = r
                break
    if not match:
        return {"found": False, "name": name, "sync_label": _sync_label(st)}

    def cell(k):
        i = cols.get(k)
        return (match[i].strip() if i is not None and i < len(match) else "")

    return {
        "found": True,
        "business": cell("business"),
        "offer": cell("offer"),
        "close_date": cell("close"),
        "contract_value": cell("contract"),
        "cash_collected": cell("cash"),          # VERBATIM — blank means the cell is blank
        "outcome": cell("outcome"),
        "set_date": cell("set_date"),
        "source": cell("source"),
        "cash_is_blank": cell("cash") == "",
        "sync_label": _sync_label(st),
        "sync_age_seconds": st.get("age_seconds"),
    }


def _fmt_row(row: dict) -> str:
    """One verbatim line for a found row."""
    biz = row.get("business") or "?"
    cash = row.get("cash_collected")
    cash_str = f"{cash}" if cash else "(blank)"
    bits = [f"offer {row['offer']}" if row.get("offer") else None,
            f"closed {row['close_date']}" if row.get("close_date") else None,
            f"contract {row['contract_value']}" if row.get("contract_value") else None,
            f"cash collected {cash_str}",
            f"outcome {row['outcome']}" if row.get("outcome") else None]
    return f"{biz}: " + ", ".join(b for b in bits if b)


# ── Client-name detection (from the live roster of tracker business names) ────

_names_cache: dict = {"ts": 0.0, "names": []}


def _client_names() -> list[str]:
    import time
    if _names_cache["names"] and time.time() - _names_cache["ts"] < 300:
        return _names_cache["names"]
    rows = _rows()
    names = []
    if rows:
        hi = next((i for i, r in enumerate(rows[:6]) if any("close date" in (c or "").lower() for c in r)), 0)
        bcol = _cols(rows[hi]).get("business")
        seen = set()
        for r in rows[hi + 1:]:
            if bcol is not None and bcol < len(r):
                nm = (r[bcol] or "").strip()
                if nm and _norm(nm) not in seen and len(nm) > 2:
                    seen.add(_norm(nm))
                    names.append(nm)
    _names_cache.update(ts=time.time(), names=names)
    return names


# Words too common to identify a business on their own — never match on these alone.
_COMMON = {"cafe", "café", "bar", "restaurant", "the", "and", "co", "group", "kitchen", "lounge",
           "grill", "that", "this", "our", "pty", "ltd", "house", "room", "club", "hotel", "eatery",
           "bistro", "pub", "coffee", "food", "brewing", "beach", "street", "road", "venue", "bakery",
           "deli", "diner", "tavern", "wine", "beer", "thai", "chinese", "italian", "indian"}


def _distinctive_tokens(name: str) -> set[str]:
    toks = set()
    for t in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split():
        if len(t) >= 4 and t not in _COMMON:
            toks.add(t)
            if t.endswith("s"):          # de-possessive/plural: "hungs" → also "hung"
                toks.add(t[:-1])
    return toks


def _clients_in_text(text: str) -> list[str]:
    """Which tracker businesses are named in the text — matched ONLY on distinctive whole words
    (never on 'cafe'/'bar'/'the'), so 'that's wrong' can't match 'That Bakery'."""
    words = set(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
    norm_text = _norm(text)
    hits = []
    for nm in sorted(_client_names(), key=len, reverse=True):
        dts = _distinctive_tokens(nm)
        if (dts and (dts & words)) or (len(_norm(nm)) >= 8 and _norm(nm) in norm_text):
            if nm not in hits:
                hits.append(nm)
    return hits[:5]


# ── Field-state / tracker intent ─────────────────────────────────────────────

_FIELD_WORDS = re.compile(
    r"\b(cash|collected|collection|blank|empty|filled|missing|shows?|logged|offer|contract|"
    r"close date|closed|status|outcome|tracker|cell|field|value)\b", re.I)
_CHECK_RE = re.compile(r"\bcheck (the )?(tracker|sheet|row|deal)\b|\bpull up\b.*\b(tracker|row|deal)|"
                       r"\bwhat does the (tracker|sheet) (say|show)\b|\blook up\b.*\b(in the )?(tracker|sheet)", re.I)
_CHALLENGE_RE = re.compile(
    r"\b(that'?s|thats) (wrong|incorrect|not right|not true)\b|\bit'?s not (blank|empty|missing)\b|"
    r"\b(i just|i) checked\b|\bthe (sheet|tracker|cell) says\b|\byou'?re wrong\b|"
    r"\bthey'?re (filled|not blank)\b|\bit is (filled|there)\b|\bthat'?s not (blank|empty|right)\b|"
    r"\bare you sure\b|\bdouble.?check\b|\bcheck again\b|\bis that (right|correct|true)\b|"
    r"\bre-?check\b", re.I)
_WHY_EXCLUDE_RE = re.compile(r"\bwhy (doesn'?t|does not|isn'?t|is not).*(include|count|have|show|reflect)\b|"
                            r"\bwhy (is|are)\b.*\b(not (in|counted|included)|excluded|missing)\b", re.I)
_VERIFY_RE = re.compile(r"\b(verify your data|diagnose yourself|self.?diagnose|check your (sync|data)|"
                        r"data (integrity|health) check|are you (synced|up to date))\b", re.I)


def client_context(text: str) -> str:
    """READ-BEFORE-ASSERT injection: if the turn asks about a client's field state, read the exact
    row(s) NOW and hand the model the VERBATIM cells so it can never infer 'blank'. '' if N/A."""
    if not text or not _FIELD_WORDS.search(text):
        return ""
    clients = _clients_in_text(text)
    if not clients:
        return ""
    lines, sync = [], None
    for nm in clients:
        row = read_client_row(nm, fresh=True)
        sync = row.get("sync_label", sync)
        if row.get("found"):
            lines.append("- " + _fmt_row(row))
        elif "reason" not in row:
            lines.append(f"- {nm}: not found in the tracker")
    if not lines:
        return ""
    return ("VERIFIED TRACKER ROWS (read just now from the Lead-to-Cash Tracker, synced "
            f"{sync}; use THESE exact cell values — a cash-collected value shown here is FILLED, "
            "state field contents ONLY from this, never infer 'blank' from a figure):\n" + "\n".join(lines))


def _read_and_report(clients: list[str], preamble: str) -> str:
    lines, sync = [], None
    for nm in clients:
        row = read_client_row(nm, fresh=True)
        sync = row.get("sync_label", sync)
        if row.get("found"):
            lines.append(_fmt_row(row))
        else:
            lines.append(f"{nm}: not found in the tracker")
    tail = f" (checked just now, synced {sync})." if sync else "."
    return preamble + "\n".join(lines) + tail


def handle_tracker_check(text: str) -> tuple[str | None, bool]:
    """'check the tracker for [client]' → resync + read that row, every field VERBATIM + sync time."""
    if not text or not _CHECK_RE.search(text):
        return None, False
    clients = _clients_in_text(text)
    if not clients:
        return "Which client's row — name the business and I'll pull its tracker cells.", True
    return _read_and_report(clients, "Straight from the tracker — "), True


def handle_cash_for(text: str) -> tuple[str | None, bool]:
    """'cash collected for X' + 'why doesn't cash collected include X' → read the exact cell(s)."""
    if not text:
        return None, False
    low = text.lower()
    is_why = bool(_WHY_EXCLUDE_RE.search(low))
    is_cash = ("cash" in low and ("collect" in low or "for " in low)) or is_why
    if not is_cash:
        return None, False
    clients = _clients_in_text(text)
    if not clients:
        return None, False   # let the aggregate cash handler / model take a general cash question
    lines, sync = [], None
    for nm in clients:
        row = read_client_row(nm, fresh=True)
        sync = row.get("sync_label", sync)
        if not row.get("found"):
            lines.append(f"{nm}: not in the tracker")
            continue
        cash = row.get("cash_collected")
        if cash:
            lines.append(f"{row['business']}: cash collected {cash} (filled)")
        else:
            lines.append(f"{row['business']}: cash-collected cell is genuinely blank")
    pre = ("Here's what the tracker actually holds — " if not is_why
           else "Checked the cells directly — ")
    note = ("" if not is_why else
            " If a value is filled here, it IS counted in tracker cash-collected; the only thing "
            "that excludes a row is a genuinely blank cell.")
    return pre + "; ".join(lines) + f" (synced {sync})." + note, True


def handle_verify_data(text: str) -> tuple[str | None, bool]:
    """'verify your data' / 'diagnose yourself' → sync-state + integrity summary, conversational."""
    if not text or not _VERIFY_RE.search(text):
        return None, False
    st = sync_state()
    if not st:
        return ("I can't reach the mirror's sync state right now — reads are falling back to a live "
                "sheet fetch, so they're current but I can't show per-tab sync times."), True
    age_min = (st.get("age_seconds") or 0) / 60
    status = st.get("status") or "?"
    fresh = "fresh" if age_min < 15 else ("aging" if age_min < 60 else "STALE — resync recommended")
    resynced = ""
    if age_min >= 15:
        st2 = resync()
        resynced = f" I just resynced it — now {_sync_label(st2)}."
    return (f"Tracker mirror: last synced {_sync_label(st)} ({age_min:.0f} min ago), status {status}, "
            f"{st.get('row_count', '?')} rows — {fresh}.{resynced} Ask me to 'check the tracker for "
            "[client]' and I'll read any row's cells verbatim."), True


def handle_self_check(text: str, thread: str = "") -> tuple[str | None, bool]:
    """CHALLENGE trigger: Rydel contradicts a data claim → resync, re-read the exact rows, and
    CORRECT with root cause (or CONFIRM with verbatim cells — truth, not appeasement). Recomputes
    the affected figure. Logs a code incident if a filled cell was claimed blank (not staleness)."""
    if not text or not _CHALLENGE_RE.search(text):
        return None, False
    # Who is this about? The current message first, then the recent thread (where the claim was made).
    clients = _clients_in_text(text) or _clients_in_text(thread)
    if not clients:
        # A challenge with no identifiable tracker row (e.g. "are you sure about runway?") isn't a
        # field-state re-read — let the model handle it conversationally rather than ask "which row?".
        if re.search(r"\b(blank|empty|cash|collected|tracker|cell|filled|the sheet|the row)\b",
                     (text + " " + (thread or "")), re.I):
            return ("Which row should I re-check? Name the client and I'll resync and read its "
                    "cells right now."), True
        return None, False

    prior_said_blank = bool(re.search(r"\b(blank|empty|missing|not (filled|logged|there))\b",
                                      thread or "", re.I))
    rows = [read_client_row(nm, fresh=True) for nm in clients]     # resync + re-read
    found = [r for r in rows if r.get("found")]
    sync = next((r.get("sync_label") for r in rows if r.get("sync_label")), "just now")

    filled = [r for r in found if r.get("cash_collected")]
    corrected = prior_said_blank and filled   # claimed blank, but cells are filled → I was wrong

    parts = []
    if corrected:
        parts.append(f"You're right — I asserted that without reading the cells. Resynced ({sync}) "
                     "and read them directly now:")
    else:
        parts.append(f"Re-checked against the tracker ({sync}):")
    for r in found:
        parts.append("• " + _fmt_row(r))
    for r in rows:
        if not r.get("found"):
            parts.append(f"• {r.get('name', '?')}: not found in the tracker")

    # Recompute the affected figure: total tracker cash-collected across the named rows.
    total = 0.0
    any_cash = False
    for r in filled:
        v = _money(r.get("cash_collected"))
        if v is not None:
            total += v
            any_cash = True
    if any_cash and len(filled) > 1:
        parts.append(f"Combined cash collected across these: ${total:,.2f}.")

    if corrected:
        try:
            import incident_log
            incident_log.log_incident(
                asked="cash-collected state for " + ", ".join(clients),
                claimed="cells were blank",
                truth="; ".join(_fmt_row(r) for r in filled),
                trace=f"re-read after resync ({sync}); cells were filled — no read occurred before "
                      "the original claim (model inferred 'blank' from a cash figure)",
                suspected="no per-row cash-collected read path fed the answer; field state was inferred",
            )
            parts.append("Logged this as an incident — the underlying gap (asserting a field state "
                         "without reading it) is a code-level thing; say 'show me the incident' for "
                         "the copy-ready fix request.")
        except Exception:
            pass
    return " ".join(parts), True
