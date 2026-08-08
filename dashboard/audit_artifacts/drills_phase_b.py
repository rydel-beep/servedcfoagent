"""Phase B — adversarial data drills (SANDBOX: synthetic inputs through the pure
core + mocked stores; zero prod writes). Each drill states EXPECTED first; an
assertion failure = a register finding. Run: python3 -m pytest dashboard/audit_artifacts/drills_phase_b.py -q
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tests"))
import attribution_engine as eng
import resolution as RES
from tests.test_attribution import HDR, RES_A, W0, W1, contact, resolver, row

RES_C = {"basis": "id", "creative_key": "120000000000000009",
         "ad_ids": ["120000000000000009"], "ad_name": "Creative C",
         "label": "Creative C", "name_norm": "creative c", "history": False,
         "adset_id": "as2", "campaign_id": "c2", "campaign_name": "RT"}


def _reset():
    import kv_store
    for k in ("derived:dates", "ads_truth:flags", "integrity:autofix_log",
              "ads_truth:proposed", "spine:events", "reached:evidence"):
        kv_store.put(k, None)


def _compute(rows, contacts, basis="cohort", spend=None, mapping=None):
    return eng.compute_from_inputs(
        [HDR] + rows, contacts, spend or {},
        resolver(mapping or {"120000000000000001": RES_A,
                             "120000000000000009": RES_C}), W0, W1, basis=basis)


# ── B1: GHL contact MERGE (id changes under the reached cache) ───────────────

def test_b1_contact_merge_reached_evidence_transiently_lost_then_resweepable():
    """EXPECTED: reached evidence keyed to a dead contact id stops matching (the
    count droops silently) BUT the new id is in neither cache, so the next
    incremental sweep re-checks it — self-healing, bounded by sweep cadence.
    OBSERVED = expected → registered as F7 (transient silent undercount)."""
    _reset()
    import kv_store
    kv_store.put("reached:evidence", {"OLD_ID": {"kind": "ghl-appointment"}})
    rows = [row("Merge Case", "m@x.com", setter="", show="")]
    r = _compute(rows, [contact("NEW_ID", "m@x.com", "Merge Case")])
    lead = r["rows"][0]
    assert lead["qualified"] is True
    assert lead["reached"] is False          # the droop: evidence keyed to OLD_ID
    cache = kv_store.get("reached:evidence") or {}
    none = kv_store.get("reached:evidence:none") or {}
    assert "NEW_ID" not in cache and "NEW_ID" not in none   # re-sweepable → heals


# ── B2: one contact, TWO DEALS (the Evan class) ──────────────────────────────

def test_b2_two_distinct_deals_one_identity_both_count_i17_holds():
    """EXPECTED: distinct close dates + distinct contracts = two REAL deals kept
    by dedupe; two closes; members list the person twice; I17 holds."""
    _reset()
    rows = [row("Evan Multi", "e2@x.com", input_date="2026-07-05", closer="won",
                close_date="2026-07-10", contract="5000", cash="2500"),
            row("Evan Multi", "e2@x.com", input_date="2026-07-06", closer="won",
                close_date="2026-07-20", contract="9000", cash="4000")]
    r = _compute(rows, [contact("c9", "e2@x.com", "Evan Multi")])
    a = next(c for c in r["creatives"] if c["creative_key"] == "120000000000000001")
    assert a["closes"] == 2
    assert a["members"]["closes"] == ["evan multi", "evan multi"]
    assert len(a["deals"]) == 2
    assert not any(not i["ok"] for i in r["invariants"])


def test_b2b_same_contract_no_close_date_is_deduped_not_double():
    """EXPECTED (the Nirosha shape): same contract, one dated one blank → ONE
    deal; the blank row voided; flags carry the duplicate."""
    _reset()
    rows = [row("Evan Multi", "e2@x.com", closer="won",
                close_date="2026-07-10", contract="5000", cash="2500"),
            row("Evan Multi", "e2@x.com", closer="won",
                close_date="", contract="5000", cash="2500")]
    r = _compute(rows, [contact("c9", "e2@x.com", "Evan Multi")])
    a = next(c for c in r["creatives"] if c["creative_key"] == "120000000000000001")
    assert a["closes"] == 1
    assert any(f["kind"] == "duplicate_won_row" for f in r["flags"])


# ── B3: re-inquiry under a second creative (first-touch ownership) ───────────

def test_b3_reinquiry_close_credits_first_touch_creative():
    """EXPECTED: attribution is CONTACT-level first-touch — both tracker rows
    (first inquiry, re-inquiry) bucket to the contact's ft ad; the close credits
    the FIRST-touch creative even if the re-inquiry came via another ad.
    This is the #111 doctrine (last-touch stored, never blended) — PROVEN here."""
    _reset()
    rows = [row("Rita Return", "r@x.com", input_date="2026-07-03", setter="", show=""),
            row("Rita Return", "r@x.com", input_date="2026-07-15", closer="won",
                close_date="2026-07-25", contract="4000", cash="2000")]
    c = contact("c10", "r@x.com", "Rita Return",
                ft_ref="120000000000000001", lt_ref="120000000000000009", lt_kind="id")
    r = _compute(rows, [c])
    a = next(x for x in r["creatives"] if x["creative_key"] == "120000000000000001")
    # OBSERVED (stronger than expected): the LT creative gets NO row at all —
    # first-touch owns the lead, the close, and the row; LT is a counter only.
    assert not any(x["creative_key"] == "120000000000000009" for x in r["creatives"])
    assert a["closes"] == 1 and a["leads"] == 2       # FT owns both rows + the close
    assert a["last_touch_differs"] >= 1               # divergence visible, not blended


# ── B4: creative renamed in Meta mid-window (hybrid keying) ──────────────────

def test_b4_rename_same_ad_id_one_row_name_level_groups():
    """EXPECTED: the ad ID is the row key — a rename cannot split or double a
    row; name-level grouping still unites ids sharing name_norm."""
    _reset()
    spend = {"120000000000000001": {"name": "Creative A — RENAMED",
                                    "spend": 100, "impressions": 10, "clicks": 1}}
    rows = [row("Ann Alpha", "a@x.com", closer="won", close_date="2026-07-20",
                contract="5000", cash="3000")]
    r = _compute(rows, [contact("c1", "a@x.com", "Ann Alpha")], spend=spend,
                 mapping={"120000000000000001": RES_A})
    keys = [c["creative_key"] for c in r["creatives"] if c["tier"] == "ad"]
    assert keys.count("120000000000000001") == 1      # one row, id-keyed
    a = next(c for c in r["creatives"] if c["creative_key"] == "120000000000000001")
    assert a["closes"] == 1 and a["spend"] == 100.0   # lead + spend joined despite rename


# ── B6/B7: money drills — refund, partial, USD (date-rung semantics) ─────────

def test_b6_full_refund_still_yields_first_payment_date():
    """OBSERVED (needs RULING): a fully-refunded succeeded charge still carries
    its created date; the ruling rung derives a close date from it. Cash is
    tracker-authority so money is safe — but is a refunded first charge still
    close EVIDENCE? → gate question R1. This test pins CURRENT behavior."""
    _reset()
    import cash_truth

    def fake_charges(days=365):
        return [{"id": "ch_refunded", "date": dt.date(2026, 7, 1), "amount": 0.0,
                 "currency": "AUD", "customer_name": "Refund Case",
                 "_email": "rf@x.com", "bt_status": "available", "available_on": None}]
    orig = cash_truth._recent_charges
    cash_truth._recent_charges = fake_charges
    try:
        out = RES._stripe_first_payment_dates()
    finally:
        cash_truth._recent_charges = orig
    hit = out.get(RES._norm("rf@x.com"))
    assert hit and str(hit["date"]) == "2026-07-01"   # refund does NOT retire the date
    assert hit["charge_id"] == "ch_refunded"


def test_b7_partial_and_usd_do_not_disturb_the_date_rung():
    _reset()
    import cash_truth
    def fake_charges(days=365):
        return [{"id": "ch_usd", "date": dt.date(2026, 7, 2), "amount": 120.5,
                 "currency": "USD", "customer_name": "Usd Case",
                 "_email": "us@x.com", "bt_status": "pending", "available_on": None}]
    orig = cash_truth._recent_charges
    cash_truth._recent_charges = fake_charges
    try:
        out = RES._stripe_first_payment_dates()
    finally:
        cash_truth._recent_charges = orig
    hit = out.get(RES._norm("us@x.com"))
    assert hit and hit["via"] == "email"              # currency-agnostic, ID-exact


# ── B8: exact window boundaries ──────────────────────────────────────────────

def test_b8_boundary_rows_inclusive_both_ends_and_compare_window_contiguous():
    """EXPECTED: w0 and w1 are both INCLUSIVE on every clock; the headline
    compare window (prev) is contiguous and non-overlapping."""
    _reset()
    rows = [row("Edge Start", "es@x.com", input_date=str(W0)),
            row("Edge End", "ee@x.com", input_date=str(W1)),
            row("Edge Close", "ec@x.com", input_date=str(W0), closer="won",
                close_date=str(W1), contract="1000", cash="500")]
    cs = [contact("b1", "es@x.com", "Edge Start"),
          contact("b2", "ee@x.com", "Edge End"),
          contact("b3", "ec@x.com", "Edge Close")]
    for basis in ("cohort", "activity"):
        r = _compute(rows, cs, basis=basis)
        assert r["totals"]["leads"] == 3, basis
        assert r["totals"]["closes"] == 1, basis
    # compare window contiguity (dashboard/ads.py): prev = [w0-days, w0-1]
    days = (W1 - W0).days + 1
    prev_end = W0 - dt.timedelta(days=1)
    prev_start = W0 - dt.timedelta(days=days)
    assert (W0 - prev_end).days == 1                  # contiguous
    assert (prev_end - prev_start).days + 1 == days   # equal length


# ── B9: UTC date-slice on GHL timestamps (the DST/timezone drill) ────────────

def test_b9_ghl_timestamp_slicing_uses_utc_day_not_sydney_day():
    """OBSERVED (register F8): _date_of / event derivations slice ISO UTC
    timestamps to a date. A Sydney-morning booking (e.g. 08:30 AEST = 22:30 UTC
    the PREVIOUS day) derives the wrong Sydney day. today_sydney() doctrine is
    violated at the derivation boundary. This test pins the defect shape."""
    import ads_truth
    utc_ts = "2026-07-09T22:30:00.000Z"   # = 2026-07-10 08:30 AEST
    assert ads_truth._date_of(utc_ts) == "2026-07-09"   # UTC day ≠ Sydney day


# ── B12: cancel-then-rebook → PROPOSED, never a silent double ────────────────

def test_b12_two_appointments_propose_never_auto():
    _reset()
    import kv_store
    import ads_truth
    from helpers import today_sydney
    kv_store.put("ghl:appt_cache", {"cX": {
        "expires": str(today_sydney() + dt.timedelta(days=7)),
        "appts": [
            {"id": "a1", "dateAdded": "2026-07-01T00:00:00Z",
             "startTime": "2026-07-05T00:00:00Z", "appointmentStatus": "cancelled"},
            {"id": "a2", "dateAdded": "2026-07-02T00:00:00Z",
             "startTime": "2026-07-08T00:00:00Z", "appointmentStatus": "confirmed"},
        ]}})
    appts = ads_truth._cached_appointments("cX")
    assert len(appts) == 2       # event_sweep sees 2 → PROPOSED lane (candidates)
    # and record_derived_date is never called with a guess — enforced by the
    # event_sweep branch (len==1 only); pinned structurally:
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "ads_truth.py")).read()
    assert "if len(appts) == 1:" in src


# ── B13: Stripe pagination failure mid-stream → partial data risk ────────────

def test_b13_partial_stripe_page_with_error_is_absorbed_silently():
    """OBSERVED (register F9): _recent_charges returns PARTIAL data when a later
    page errors with prior data in hand (error+data → falls through, has_more
    absent → break). A first-payment date derived from partial data can be
    wrong SILENTLY. Pinned by inspection."""
    import cash_truth, inspect
    src = inspect.getsource(cash_truth._recent_charges)
    assert 'r.get("error") is not None and not r.get("data")' in src
    # no branch marks partial-success as degraded → the silent-partial class


# ── B14: crash between store-write and journal-write ─────────────────────────

def test_b14_crash_after_put_before_journal_loses_the_journal_line_forever():
    """OBSERVED (register F10): record_derived_date puts the store, then
    journals. A crash between leaves an UNJOURNALED derivation; the idempotent
    re-run skips the journal. 'Every application logged' fails under crash."""
    _reset()
    import kv_store
    calls = {"n": 0}
    orig = RES.log_autofix
    def boom(rule, detail):
        calls["n"] += 1
        raise RuntimeError("crash before journal")
    RES.log_autofix = boom
    try:
        import pytest
        with pytest.raises(RuntimeError):
            RES.record_derived_date("crash case", "set_date", "2026-07-01",
                                    "derived:ghl-appt", {"appointment_id": "a9"})
    finally:
        RES.log_autofix = orig
    # OBSERVED: the crash propagates (loud at call time) but the STORE write
    # already landed — the derivation exists unjournaled, and the idempotent
    # re-run below never back-fills the journal line:
    assert "crash case" in RES.derived_dates()
    ok2 = RES.record_derived_date("crash case", "set_date", "2026-07-01",
                                  "derived:ghl-appt", {"appointment_id": "a9"})
    assert ok2 is True
    lg = kv_store.get("integrity:autofix_log") or []
    assert not any("crash case" in (e.get("detail") or "") for e in lg)   # gone forever


# ── B15: tracker row deleted after a derivation referenced it ────────────────

def test_b15_orphan_derivation_is_inert_but_immortal():
    """EXPECTED: engine merge no-ops for a vanished row (safe); OBSERVED: the
    orphan store entry never retires (register F11 — hygiene, excluded≠deleted
    needs a visible bucket, not an invisible immortal)."""
    _reset()
    RES.record_derived_date("ghost row", "set_date", "2026-07-01",
                            "derived:ghl-appt", {"appointment_id": "g1"})
    r = _compute([row("Ann Alpha", "a@x.com")], [contact("c1", "a@x.com", "Ann Alpha")])
    assert r["totals"]["leads"] == 1                  # merge unaffected
    assert "ghost row" in RES.derived_dates()          # …and the orphan persists
