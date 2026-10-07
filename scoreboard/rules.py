"""rules.py — the small, pure rules every number shares.

  windows      This month (default) · Last month · Last 7 / 30 / 90 days ·
               Custom — Sydney calendar days, inclusive, named in words.
  money        cents-exact Decimal; ex-GST = inc ÷ 1.1 rounded half-up to
               the cent ($3,355 → $3,050.00).
  deal form    what the Closed Deal Form STATES. A figure is read only when
               the form writes it out (a stated total, a stated term, "Set
               by X", "Closed by X"). Anything else is left blank for a
               human — never worked out from other numbers.
  ad leads     a GHL contact counts as an ad lead only when its own record
               says it came from an ad (ad attribution, or a Facebook /
               Instagram / Meta lead-form source). The reason is shown.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal

from helpers import SYDNEY_TZ

CENT = Decimal("0.01")
GST = Decimal("1.1")


# ── windows ─────────────────────────────────────────────────────────────────

WINDOW_KEYS = ("month", "last_month", "last7", "last30", "last90", "custom")


def window(key: str, today: dt.date, start: str | None = None, end: str | None = None) -> dict:
    if key == "last_month":
        e = today.replace(day=1) - dt.timedelta(days=1)
        s = e.replace(day=1)
        label = f"Last month ({s:%B %Y})"
    elif key in ("last7", "last30", "last90"):
        n = int(key[4:])
        s, e = today - dt.timedelta(days=n - 1), today
        label = f"Last {n} days ({s:%-d %b} – {e:%-d %b %Y})"
    elif key == "custom" and start and end:
        s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        if e < s:
            s, e = e, s
        label = f"{s:%-d %b %Y} – {e:%-d %b %Y}"
    else:
        key = "month"
        s, e = today.replace(day=1), today
        label = f"This month ({s:%B %Y}, to {e:%-d %b})"
    return {"key": key, "start": s, "end": e, "label": label,
            "days": (e - s).days + 1, "boundaries": "Sydney time, midnight to midnight"}


def parse_when(v) -> dt.datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v / (1000 if v > 1e11 else 1), tz=dt.timezone.utc)
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        try:
            return dt.datetime.combine(dt.date.fromisoformat(str(v)[:10]), dt.time(0), tzinfo=SYDNEY_TZ)
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=SYDNEY_TZ)
    return d


def syd_date(v) -> dt.date | None:
    d = parse_when(v)
    return d.astimezone(SYDNEY_TZ).date() if d else None


def in_window(day: dt.date | None, w: dict) -> bool:
    return day is not None and w["start"] <= day <= w["end"]


# ── money ───────────────────────────────────────────────────────────────────

def money(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def ex_gst(inc) -> Decimal:
    return (Decimal(str(inc)) / GST).quantize(CENT, rounding=ROUND_HALF_UP)


def f2(d) -> float:
    return float(Decimal(str(d)).quantize(CENT, rounding=ROUND_HALF_UP))


# ── people / identity ───────────────────────────────────────────────────────

def norm_email(e) -> str | None:
    e = str(e or "").strip().lower()
    return e if "@" in e else None


def norm_phone(p) -> str | None:
    d = re.sub(r"\D", "", str(p or ""))
    if not d:
        return None
    if d.startswith("0") and len(d) == 10:
        d = "61" + d[1:]
    return d if len(d) >= 9 else None


def norm_name(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


# ── ad leads ────────────────────────────────────────────────────────────────



def ad_lead_reason(contact: dict) -> str | None:
    """Counted as an ad lead only when GHL recorded a PAID visit (Paid Social,
    an ad id, a click id or a campaign id) or a lead-form source. 'Social
    media' in GHL is organic Instagram/Facebook — not an ad."""
    for a in contact.get("attributions") or []:
        sess = str(a.get("utmSessionSource") or "").lower()
        if sess == "paid social" or a.get("adId") or a.get("fbclid") or a.get("utmCampaignId"):
            camp = (a.get("utmCampaign") or "").strip()
            return f"ad visit recorded ({a.get('utmSessionSource') or 'ad id'})" + (f" · campaign “{camp}”" if camp else "")
    src = str(contact.get("source") or "").lower()
    if "lead form" in src or "lead ad" in src:
        return f"GHL source: {contact.get('source')}"
    return None


def facebook_source_without_ad(contact: dict) -> bool:
    """GHL's source says Facebook but no paid visit is recorded — shown
    beside the lead count, never counted."""
    return "facebook" in str(contact.get("source") or "").lower() and not ad_lead_reason(contact)


def is_test(*texts) -> bool:
    return any(re.search(r"\btest\b", str(t or "").lower()) for t in texts)


# ── the Closed Deal Form ────────────────────────────────────────────────────

_NUM = r"\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
_NOT_A_TOTAL = r"(?!\s*(?:per\b|every\b|/|a\s+month|monthly|each\b|fortnight|×|x\s*\d))"
_TOTAL_PATTERNS = (
    re.compile(r"(?:^|\n)\s*[·\-•]?\s*(?:price|total investment|total contract value|total|investment)\s*[:\t ]\s*"
               + _NUM + r"\s*\+\s*gst" + _NOT_A_TOTAL, re.I),
    re.compile(_NUM + r"\s*\+\s*gst\s*(?:in total|total)\b", re.I),
)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_TERM = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)[\s-]month"
                   r"(?:s)?\b(?!\s*(?:review|mark|payoff)\b)", re.I)
_TERM_CONTEXT = re.compile(r"agreement|term|contract|engine|package|growth pro", re.I)


def stated_total_ex_gst(summary: str | None) -> tuple[Decimal | None, str | None]:
    """A contract total the form writes out as '$X + GST' beside 'Price/Total/
    Investment', or '$X + GST in total'. Several different stated totals →
    None (a human decides)."""
    if not summary:
        return None, None
    found = []
    for p in _TOTAL_PATTERNS:
        for m in p.finditer(summary):
            found.append((money(m.group(1).replace(",", "")), m.group(0).strip()))
    vals = {v for v, _ in found}
    if len(vals) == 1:
        return found[0]
    return None, (f"the form states {len(vals)} different totals" if len(vals) > 1 else None)


def stated_term_months(summary: str | None) -> tuple[int | None, str | None]:
    """The term the form states. Several different month figures (e.g. 'six
    month agreement' + 'waived at three months') → the one written beside
    agreement / term / contract / package; still ambiguous → None."""
    if not summary:
        return None, None
    found = []
    for m in _TERM.finditer(summary):
        t = m.group(1).lower()
        n = int(t) if t.isdigit() else _WORDNUM[t]
        around = summary[max(0, m.start() - 12): m.end() + 30]
        found.append((n, m.group(0), bool(_TERM_CONTEXT.search(around))))
    for pool in (found, [f for f in found if f[2]]):
        vals = {n for n, _, _ in pool}
        if len(vals) == 1:
            n, q, _ = pool[0]
            return n, q
    return None, None


_PEOPLE = re.compile(r"(set and closed by|set by|closed by)\s*:?\s*([A-Z][a-z]+)", re.I)


def stated_closer_setter(summary: str | None) -> dict:
    out = {}
    for m in _PEOPLE.finditer(summary or ""):
        who, name = m.group(1).lower(), m.group(2).capitalize()
        if who == "set and closed by":
            out.setdefault("setter", name); out.setdefault("closer", name)
        elif who == "set by":
            out.setdefault("setter", name)
        else:
            out.setdefault("closer", name)
    return out


def fee_times_term_proposal(summary: str | None, term: int | None) -> tuple[Decimal | None, str | None]:
    """A PROPOSAL only (never counted until confirmed): a single stated
    '$X + GST per month' or '… per fortnight / every two weeks' × the stated
    term."""
    if not summary or not term:
        return None, None
    m = re.findall(_NUM + r"\s*\+\s*gst\s*(?:/|per|every)\s*(month|fortnight|two weeks)", summary, re.I)
    fees = {(money(a.replace(",", "")), b.lower()) for a, b in m}
    if len(fees) != 1:
        return None, None
    (fee, per), = fees
    if per == "month":
        n, how = term, f"{term} months"
    else:
        # fortnightly: only a payment count the form itself states
        c = re.search(r"(?:number of payments|payments)\s*:?\s*(\d{1,2})\b", summary, re.I)
        if not c:
            return None, None
        n, how = int(c.group(1)), f"{c.group(1)} payments stated"
    return (fee * n).quantize(CENT), f"${fee:,.2f} + GST per {per} × {how} = ${fee * n:,.2f} + GST"
