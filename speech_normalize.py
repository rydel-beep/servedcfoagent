"""
speech_normalize.py — rewrite reply text FOR THE EAR before it reaches ElevenLabs.

Applied server-side in the ONE tts core (dashboard/routes.tts_response), so both
surfaces (CFO dashboard + Timeline widget) get identical pronunciation. The displayed
caption keeps the eye-formatted text — ONLY the TTS input is normalized.

Order matters: strip eye-formatting first, then domain terms, then numbers/dates.
The lexicon is config-extensible (SPEECH_LEXICON env, JSON {"term": "spoken"}), for
names the voice mangles.
"""
from __future__ import annotations

import json
import os
import re

# ── acronym / term conventions (picked once, consistent everywhere) ───────────
# Letters for initialisms; natural words where a spoken form is established.
_BASE_LEXICON = {
    "LTGP": "L T G P",
    "CAC": "C A C",
    "MRR": "M R R",
    "ROAS": "row-ass",
    "LTV": "L T V",
    "CPL": "C P L",
    "CPM": "C P M",
    "CTA": "C T A",
    "SOP": "S O P",
    "EOW": "E O W",
    "MVP": "M V P",
    "GHL": "G H L",
    "SMM": "S M M",
    "Xero": "Zero",
    "EDITH": "Edith",
    "AUD": "Australian dollars",
    "GST": "G S T",
    "BAS": "B A S",
    "POS": "P O S",
    "YT": "YouTube",
    "FY": "financial year ",
}

_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_ORDINAL = {1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth", 9: "ninth", 12: "twelfth"}


def _lexicon() -> dict:
    lex = dict(_BASE_LEXICON)
    try:
        lex.update(json.loads(os.environ.get("SPEECH_LEXICON", "") or "{}"))
    except (ValueError, TypeError):
        pass
    return lex


def _int_words(n: int) -> str:
    if n < 0:
        return "minus " + _int_words(-n)
    if n < 20:
        return _ONES[n] or "zero"
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + (" and " + _int_words(rest) if rest else "")
    for div, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand")):
        if n >= div:
            rest = n % div
            head = _int_words(n // div) + " " + name
            if not rest:
                return head
            joiner = " and " if rest < 100 else ", "
            return head + joiner + _int_words(rest)
    return str(n)


def _num_words(raw: str) -> str:
    """'3050' → words; '4.51' → 'four point five one'."""
    raw = raw.replace(",", "")
    if "." in raw:
        whole, frac = raw.split(".", 1)
        frac = frac.rstrip("0") or "0"
        return _int_words(int(whole or 0)) + " point " + " ".join(_ONES[int(d)] if d != "0" else "zero" for d in frac)
    return _int_words(int(raw))


def _ordinal_words(n: int) -> str:
    if n in _ORDINAL:
        return _ORDINAL[n]
    w = _int_words(n)
    for suffix, repl in (("ty", "tieth"), ("one", "first"), ("two", "second"), ("three", "third"),
                         ("five", "fifth"), ("eight", "eighth"), ("nine", "ninth"), ("twelve", "twelfth")):
        if w.endswith(suffix):
            return w[: -len(suffix)] + repl
    return w + "th"


def _strip_eye_format(t: str) -> str:
    t = re.sub(r"```.*?```", " ", t, flags=re.S)              # code fences
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)              # headers
    t = re.sub(r"\*\*|__|\*|_|`", "", t)                       # emphasis markers
    t = re.sub(r"^\s*[-•▪◦·]\s+", "", t, flags=re.M)          # bullets
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)            # numbered lists
    t = re.sub(r"\|", ", ", t)                                 # table pipes
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿←-⇿⬀-⯿✓✗✅❌⚠️️🔴🟢🟡]", "", t)
    t = re.sub(r"\((?:id|gid|ref)[:\s][^)]*\)", "", t, flags=re.I)   # parenthetical IDs
    t = re.sub(r"\s*\(([^)]{1,40})\)", r", \1,", t)            # short parentheticals → spoken aside
    t = t.replace("—", ", ").replace("–", ", ")
    t = re.sub(r"\s*→\s*", " to ", t)
    return t


def _money(m: re.Match) -> str:
    num, suffix = m.group(1), (m.group(2) or "").lower()
    mult = {"k": 1_000, "m": 1_000_000}.get(suffix, 1)
    val = float(num.replace(",", ""))
    total = val * mult
    if total == int(total):
        return _int_words(int(total)) + " dollars"
    whole = int(total)
    cents = int(round((total - whole) * 100))
    return _int_words(whole) + " dollars" + (" " + _int_words(cents) + " cents" if cents else "")


def normalize_for_speech(text: str) -> str:
    """The full ear-rewrite. Never raises — on any failure returns the original text."""
    try:
        t = _strip_eye_format(text or "")
        lex = _lexicon()
        # ratios BEFORE lexicon eats the parts: "LTGP:CAC" → "LTGP to CAC"
        t = re.sub(r"\b([A-Z]{2,6}):([A-Z]{2,6})\b", r"\1 to \2", t)
        for term, spoken in lex.items():
            t = re.sub(r"\b%s\b" % re.escape(term), spoken, t)
        # money: $3,050 / $172k / $4.51m
        t = re.sub(r"\$\s?([\d,]+(?:\.\d+)?)(?:\s?([kKmM])\b)?", _money, t)
        # multiples: 4.51x / 3x
        t = re.sub(r"\b(\d+(?:\.\d+)?)x\b", lambda m: _num_words(m.group(1)) + " times", t)
        # percentages
        t = re.sub(r"\b(\d+(?:\.\d+)?)\s?%", lambda m: _num_words(m.group(1)) + " percent", t)
        # ISO dates: 2026-07-27 → July twenty-seventh
        def _iso(m):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12:
                return "%s %s" % (_MONTHS[mo], _ordinal_words(d))
            return m.group(0)
        t = re.sub(r"\b(20\d\d)-(\d\d)-(\d\d)\b", _iso, t)
        # big bare numbers with separators: 1,650 → words (plain digits ≤4 left alone —
        # ElevenLabs reads those fine)
        t = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", lambda m: _int_words(int(m.group(0).replace(",", ""))), t)
        # whitespace tidy
        t = re.sub(r"\s{2,}", " ", t).replace(" ,", ",")
        t = re.sub(r",\s*,", ", ", t).strip()
        return t or text
    except Exception:  # noqa: BLE001 — a TTS pre-pass must never break speech
        return text
