"""EDITH ANSWERS THE QUESTION (#168).

Pinned here:
  1 THE REPLAY — the witnessed 24 Sep thread, verbatim: Q1 gets "Yes" and
    both figures; Q2 gets the two dollar figures, no refusal
  2 the resolver rules: basis words, window words, explicit dates, the
    follow-up keeping its window, "answered as" present and honest
  3 the answer contract: first sentence answers the literal question,
    ≤ 3 sentences, financial numbers capped, no doctrine recitals,
    never a three-basis dump
  4 validator v2: the head-arithmetic figure is blocked AND the question
    is still answered; every block is logged
  5 the calc endpoint: derived numbers are a tool call
"""

import datetime as dt
import os
import re

import pytest

import kv_store

ROOT = os.path.join(os.path.dirname(__file__), "..")

WW = "September 2026 (month to date — 1–24 Sep, 24 of 30 days)"

# the witnessed thread, verbatim (24 Sep, the EDITH dock)
Q1 = "are you meaning we are at negative net profit right now? From Sept 1 to 24?"
Q2 = "No I just want the Sept 1 to 24 figures — what's our net profit?"


def _read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def _code_only(src: str) -> str:
    src = re.sub(r'"""(?:.|\n)*?"""', "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in src.splitlines())


def _body(reply: str) -> str:
    return (reply or "").split("Answered as:")[0]


def _fin_count(text: str) -> int:
    from dashboard import answer_guard
    return len(answer_guard.extract_financial(text))


@pytest.fixture
def seeded(monkeypatch):
    """The cache exactly as the loop computes it for 24 Sep."""
    import pl_engine as PL
    kv_store._MEM.clear()
    data = {
        "management_mtd": {
            "ok": True, "basis": "management", "month": "2026-09",
            "window": {"start": "2026-09-01", "end": "2026-09-24"},
            "day_count": {"elapsed": 24, "in_month": 30},
            "window_words": WW, "revenue": 79754.9, "net_revenue": 79754.9,
            "contra_revenue": 0.0, "delivery": 22989.08,
            "acquisition": 17817.5, "overhead": 8530.2,
            "gross_profit": 56765.82, "gross_margin_pct": 71.2,
            "operating_profit": 30418.12, "operating_margin_pct": 38.1,
            "tax_accrual": 7604.53, "net_profit": 22813.59,
            "net_margin_pct": 28.6, "total_costs": 56941.31,
            "as_of": "2026-09-24T17:36:35",
            "projection": {"available": True, "net_profit": 26994,
                           "net_margin_pct": 27.8}},
        "recognised_last_month": {
            "ok": True, "basis": "recognised", "window_words": "August 2026",
            "revenue": 81106.81, "net_revenue": 81106.81,
            "net_profit": 20518.7, "net_margin_pct": 25.3,
            "operating_profit": 20518.7, "operating_margin_pct": 25.3,
            "gross_margin_pct": 58.6, "total_costs": 60588.11,
            "as_of": "2026-09-24"},
        "management_last_month": {
            "ok": True, "basis": "management", "window_words": "August 2026",
            "revenue": 98641.0, "net_revenue": 98641.0,
            "net_profit": 29990.75, "net_margin_pct": 30.4,
            "as_of": "2026-09-24"},
        "collected_last_month": {
            "ok": True, "basis": "collected", "window_words": "August 2026",
            "revenue": 61197.82, "net_revenue": 61197.82,
            "net_profit": 1500.0, "net_margin_pct": 2.4,
            "as_of": "2026-09-24"},
        "run_rate_t3": {
            "ok": True, "basis": "management",
            "window_words": "June 2026 → August 2026",
            "revenue": 241203.0, "net_revenue": 241203.0,
            "net_profit": 42372.0, "net_margin_pct": 17.6,
            "as_of": "2026-09-24"},
        "fy26_baseline": PL.FY26, "as_of": "2026-09-24T17:36:35",
        "contracted_vs_collected": {
            "ok": True,
            "contracted": {"window_words": WW, "revenue": 79754.9,
                           "net_profit": 22813.59, "net_margin_pct": 28.6,
                           "full_month_contracted": 99693.62},
            "collected_mtd": {
                "ok": True, "revenue": 37227.27, "net_profit": -12109.51,
                "net_margin_pct": -32.5, "gross_margin_pct": 38.2,
                "operating_profit": -12109.51, "tax_accrual": 0.0,
                "total_costs": 49336.78,
                "day_count": {"elapsed": 24, "in_month": 30},
                "window_words": WW, "as_of": "2026-09-24T17:35:27"},
            "collected_30d": {
                "revenue": 40000.0, "net_profit": -9000.0,
                "net_margin_pct": -22.5, "gross_margin_pct": 40.0,
                "operating_profit": -9000.0, "tax_accrual": 0.0,
                "total_costs": 49000.0, "window_words": "26 Aug → 24 Sep",
                "as_of": "2026-09-24"},
            "gap": {"amount": 42527.63, "pct_collected": 46.7,
                    "line": "Collected so far this month: $37,227 of "
                            "$79,755 contracted (46.7%)"},
            "ar_reconciliation": {"ok": True, "top_unpaid": [
                {"client": "Client A", "outstanding": 14500.0,
                 "days_overdue": 12},
                {"client": "Client B", "outstanding": 9800.0,
                 "days_overdue": 4}]},
            "projections": {
                "optimistic": {"available": True, "net_margin_pct": 27.8},
                "realistic": {"available": True, "net_margin_pct": 8.1,
                              "collection_rate": 0.78}}},
    }
    kv_store.put(PL.K_SUMMARY, {"computed_at": "2026-09-24T17:36:35",
                                "error": None, "data": data})
    import answer_engine as AE
    monkeypatch.setattr(AE, "today_sydney", lambda: dt.date(2026, 9, 24))
    return data


# ── 1 · THE REPLAY ──────────────────────────────────────────────────────────

def test_replay_q1_yes_first_both_figures_and_the_gap(seeded):
    import answer_engine as AE
    r, h = AE.handle_profit_question(Q1)
    assert h
    body = _body(r)
    assert body.startswith("Yes")                      # the answer word FIRST
    assert "−$12,110" in body and "−32.5%" in body     # collected net $ and %
    assert "$37,227" in body and "collected" in body
    assert "$22,814" in body and "28.6%" in body       # then the contracted line
    assert "$42,528" in body and "owed" in body        # then the gap
    sentences = [s for s in re.split(r"(?<=[.!?]) ", body.strip()) if s]
    assert len(sentences) <= 3
    assert _fin_count(body) <= 6
    assert "Answered as:" in r and "yes/no" in r


def test_replay_q2_two_dollar_figures_no_refusal(seeded):
    import answer_engine as AE
    hist = [{"role": "user", "content": Q1},
            {"role": "assistant", "content": AE.handle_profit_question(Q1)[0]}]
    r, h = AE.handle_profit_question(Q2, hist)
    assert h
    body = _body(r)
    assert "−$12,110" in body and "$22,814" in body    # both nets, dollars first
    assert "refus" not in body.lower() and "can't" not in body.lower()
    assert "won't" not in body.split("Answered")[0].lower()
    assert "1–24 Sep" in body                          # the window, in the words
    assert _fin_count(body) <= 6


def test_bare_net_profit_gets_both_bases_one_line_each(seeded):
    import answer_engine as AE
    r, _ = AE.handle_profit_question("what's our net profit?")
    body = _body(r)
    assert "What actually landed" in body and "If everyone pays" in body
    assert "On the books" not in body                  # never three bases
    assert "month to date" in body                     # the window is stated
    assert "asked without a basis" in r                # the resolution is shown


def test_are_we_profitable_answers_the_word_first(seeded):
    import answer_engine as AE
    r, _ = AE.handle_profit_question("are we profitable this month?")
    assert _body(r).startswith(("Yes", "No"))


def test_why_negative_gives_the_gap_and_the_top_unpaid(seeded):
    import answer_engine as AE
    r, _ = AE.handle_profit_question("why is it negative?")
    body = _body(r)
    assert "46.7%" in body or "$42,528" in body or "$37,227" in body
    assert "Client A" in body and "$14,500" in body


def test_the_decoy_declines_and_gives_the_nearest(seeded):
    import answer_engine as AE
    r, h = AE.handle_profit_question("what's our EBITDA by state?")
    assert h and "isn't a metric the engine computes" in r
    assert "Nearest computed" in r and "$30,418" in r


# ── 2 · THE RESOLVER ────────────────────────────────────────────────────────

def test_basis_words_map_as_ruled():
    import answer_engine as AE
    assert AE.resolve("net margin right now")["bases"][0] == "collected"
    assert AE.resolve("margin in the bank")["bases"][0] == "collected"
    assert AE.resolve("margin if everyone pays")["bases"][0] == "management"
    assert AE.resolve("net margin on the books")["bases"] == ["recognised"]
    assert AE.resolve("net margin per Xero")["bases"] == ["recognised"]
    amb = AE.resolve("what's our net profit")
    assert amb["bases"] == ["collected", "management"]
    assert amb["basis_source"] == "ambiguous"


def test_explicit_dates_win_and_map_to_the_calendar(monkeypatch):
    import answer_engine as AE
    monkeypatch.setattr(AE, "today_sydney", lambda: dt.date(2026, 9, 24))
    assert AE.resolve("net profit Sept 1 to 24")["window"] == "mtd"
    assert AE.resolve("net profit from September 1 to 24")["window"] == "mtd"
    r = AE.resolve("net profit for August")
    assert r["window"] == ("month", "2026-08")
    r2 = AE.resolve("net profit 1 to 31 Aug")
    assert r2["window"] == ("month", "2026-08")
    assert AE.resolve("net profit this month")["window"] == "mtd"
    assert AE.resolve("net margin last month")["window"] == "last_month"
    assert AE.resolve("net margin last 30 days")["window"] == "last_30d"


def test_a_follow_up_keeps_the_resolved_window(seeded):
    import answer_engine as AE
    first, _ = AE.handle_profit_question("net margin for August on the books")
    hist = [{"role": "user", "content": "net margin for August on the books"},
            {"role": "assistant", "content": first}]
    res = AE.resolve("and the gross margin?", hist)
    # August IS last month on 24 Sep — either name is the same window
    assert res["window"] in (("month", "2026-08"), "last_month")
    assert "kept" in res["window_source"]


def test_every_resolution_is_logged_and_shown(seeded):
    import answer_engine as AE
    kv_store._MEM.pop(AE.K_RESOLUTIONS, None) if hasattr(kv_store, "_MEM") else None
    r, _ = AE.handle_profit_question("what's our net profit?")
    ring = kv_store.get(AE.K_RESOLUTIONS)
    assert ring and ring[-1]["metric"] == "net"
    assert "Answered as:" in r


# ── 3 · THE CONTRACT ────────────────────────────────────────────────────────

def test_no_doctrine_recitals_in_any_answer(seeded):
    import answer_engine as AE
    for q in (Q1, Q2, "what's our net profit?", "gross margin last month",
              "why is it negative?"):
        r, h = AE.handle_profit_question(q)
        if h:
            assert "never blended" not in r, q
            assert "Bases are" not in r, q
    src = _code_only(_read("answer_engine.py"))
    assert "never blended" not in src


def test_the_number_cap_is_config_and_enforced(seeded, monkeypatch):
    import answer_engine as AE
    monkeypatch.setenv("ANSWER_NUMBER_CAP", "4")
    r, _ = AE.handle_profit_question("what's our net profit?")
    assert _fin_count(_body(r)) <= 4
    monkeypatch.delenv("ANSWER_NUMBER_CAP")


def test_a_stated_single_basis_stays_single(seeded):
    import answer_engine as AE
    r, _ = AE.handle_profit_question("net margin on the books last month")
    body = _body(r)
    assert "On the books" in body
    assert "If everyone pays" not in body and "What actually landed" not in body


def test_the_scan_decoy_regex_still_matches_the_decline(seeded):
    """triple_scan's DECOY_OK must recognise the new decline copy."""
    import answer_engine as AE
    scan = _read("scripts", "triple_scan.py")
    m = re.search(r'DECOY_OK = re\.compile\(r"([^"]+)"', scan)
    assert m
    r, _ = AE.handle_profit_question("what's our EBITDA by state")
    assert re.search(m.group(1), r, re.I)


# ── 4 · VALIDATOR v2 ────────────────────────────────────────────────────────

_CTX = "PROFIT: management_mtd net_profit 22813.59 revenue 79754.9"


def test_blocked_head_arithmetic_still_answers_the_question(seeded):
    from dashboard import answer_guard as AG
    bad = "That's $57,016 of costs — $79,755 minus $22,739."
    out, v = AG.apply(bad, _CTX, question=Q2)
    assert not v["ok"] and v.get("recomposed")
    assert "$57,016" not in out                       # the bad number never lands
    assert "−$12,110" in out and "$22,814" in out     # the question is answered
    log = kv_store.get(AG.K_BLOCK_LOG)
    assert log and "$57,016" in log[-1]["blocked_figures"]
    assert log[-1]["answered_instead"]


def test_blocked_reply_outside_the_resolver_gets_the_nearest(seeded):
    from dashboard import answer_guard as AG
    out, v = AG.apply("Ad spend ran $99,999 last week.", _CTX,
                      question="how was the week?")
    assert not v["ok"]
    assert "nearest read" in out and "$30,418" in out
    assert "Ask me for" not in out                    # the refusal copy is retired


def test_total_costs_is_now_an_engine_value():
    """The exact figure the guard blocked ($57,016 = revenue − net) is an
    engine rung now — never head arithmetic again."""
    import pl_engine as PL
    r = PL._rungs(79754.9, 0, 22989.08, 17917.5, 8530.2, 7579.53, "")
    assert r["total_costs"] == round(79754.9 - r["net_profit"], 2)
    assert r["total_costs"] == 57016.31


# ── 5 · CALC + WIRING ───────────────────────────────────────────────────────

def test_calc_owns_the_derivations():
    import answer_engine as AE
    kv_store._MEM.clear()
    assert AE.calc("prorata", a=500, days=24, days_in=30)["value"] == 400.0
    assert AE.calc("ratio", a=37227.27, b=79754.9)["value"] == 46.7
    assert AE.calc("difference", a=79754.9, b=37227.27)["value"] == 42527.63
    assert AE.calc("per_day", a=79754.9, days=24)["value"] == 3323.12
    assert AE.calc("sum", values=[1, 2, 3.5])["value"] == 6.5
    assert AE.calc("nonsense")["ok"] is False
    ring = kv_store.get(AE.K_CALC_LOG)
    assert ring and ring[-1]["math"]
    routes = _read("dashboard", "routes.py")
    assert '"/api/calc"' in routes


def test_shaped_carries_pacing_deltas_and_registry_ids(seeded):
    import answer_engine as AE
    s = AE.shaped("management", "mtd")
    assert s["ok"]
    assert s["per_day"]["revenue"] == round(79754.9 / 24, 2)
    assert s["deltas"]["vs_fy26_pp"] == round(28.6 - 11.5, 1)
    assert s["deltas"]["vs_last_month_pp"] == round(28.6 - 30.4, 1)
    assert s["registry"]["total_costs"] == "total_costs"
    assert s["total_costs"] == 56941.31


def test_registry_covers_the_new_outputs():
    from dashboard import definitions as D
    entries = D.load()["entries"]
    for i in ("total_costs", "per_day_pacing", "margin_delta",
              "answered_as", "calc_endpoint"):
        assert i in entries, i
        assert not D.jargon_hits(str(entries[i])), i


def test_voice_path_routes_through_the_same_handler():
    routes = _read("dashboard", "routes.py")
    assert routes.count("handle_profit_question") >= 2
