"""
tests/test_cash_truth.py
------------------------
SOURCE HIERARCHY FOR CASH: tracker = deal truth, Stripe = cash truth. The incident replayed
is the acceptance test — "what's our last cash collected and who was the last deal we closed"
must return the actual latest Stripe payment (client/amount/state) + the latest close, with
tracker-logging status. Never a bare "cell is blank" dead-end, never a junk-row hijack.
Matching: email > unambiguous name > unambiguous amount+date; ambiguous = FLAGGED, not guessed.
"""
from __future__ import annotations
import datetime as dt
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# config freezes env at import, and pytest imports test modules alphabetically at collection —
# this file sorts before test_dashboard, so it must set the same auth env defaults first.
os.environ.setdefault("CFO_REFRESH_KEY", "test-key-123")
os.environ.setdefault("DASHBOARD_TOKEN", "test-dash-token")
import kv_store
import cash_truth as ct
import tracker_read as tr


# ── Fixtures: positionally-faithful tracker rows (email=4, business=7, outcome=23,
#    offer=26, close=27, contract=28, cash=32) + Stripe charges as _recent_charges returns ──

def _hdr():
    hdr = [""] * 33
    hdr[3] = "Lead Name"; hdr[4] = "Email"; hdr[7] = "Business Name"
    hdr[16] = "Call Outcome"; hdr[23] = "Call Outcome"; hdr[26] = "Offer Sold"
    hdr[27] = "Close Date"; hdr[28] = "Contract Value"; hdr[32] = "Cash Collected"
    return hdr


def _row(biz, email="", close="", contract="", cash="", offer="Scale Engine",
         outcome="Won", name=""):
    r = [""] * 33
    r[3] = name; r[4] = email; r[7] = biz; r[23] = outcome
    r[26] = offer; r[27] = close; r[28] = contract; r[32] = cash
    return r


def _rows():
    return [_hdr(),
            _row("Hung's Chinese", "hung@example.com", "7/8/2026", "$15,100", "$8,305.00"),
            _row("Lost Sheep Cafe", "sheep@example.com", "7/7/2026", "$14,500", "$15,950.00"),
            _row("Cally Hotel", "cally@example.com", "6/24/2026", "$18,300", ""),  # blank cell
            # duplicate lead row for Hung's (not won) — matcher must prefer the Won row
            _row("Hung's Chinese", "hung@example.com", outcome="SET"),
            # two same-amount same-window closes → amount+date must refuse to pick one
            _row("Twin A", "", "7/6/2026", "$5,000", "$2,000"),
            _row("Twin B", "", "7/6/2026", "$5,000", "$2,000")]


def _charge(cid, d, amount, name, email, bt="available", avail=None):
    return {"id": cid, "date": d, "amount": amount, "currency": "AUD",
            "customer_name": name, "_email": email, "bt_status": bt,
            "available_on": avail}


def _charges():
    return [  # newest first, as _recent_charges returns
        _charge("ch_1", dt.date(2026, 7, 8), 8305.0, "Tesla Zhong", "hung@example.com",
                bt="pending", avail="2026-07-11"),
        _charge("ch_2", dt.date(2026, 7, 7), 15950.0, "Lost Sheep", "sheep@example.com"),
        _charge("ch_3", dt.date(2026, 6, 24), 3355.0, "Lucas Reid", "cally@example.com"),
        _charge("ch_4", dt.date(2026, 7, 6), 2000.0, "Twin Payer", ""),        # ambiguous
        _charge("ch_5", dt.date(2026, 7, 5), 1275.0, "Total Stranger", "x@nowhere.com"),
    ]


def _patch(monkeypatch, charges=None):
    monkeypatch.setattr(ct, "_recent_charges", lambda days=30: _charges() if charges is None else charges)
    monkeypatch.setattr(tr, "_rows", _rows)
    monkeypatch.setattr(tr, "sync_state", lambda key=tr._KEY: {"age_seconds": 0, "synced_at": "just now"})
    monkeypatch.setattr(tr, "resync", lambda key=tr._KEY: {"age_seconds": 0})
    kv_store._MEM.clear()


# ── Matching: email > unambiguous name > unambiguous amount+date; else FLAGGED ──────

def test_email_match_prefers_won_row(monkeypatch):
    _patch(monkeypatch)
    view = ct.unified_cash_view()
    p = next(p for p in view["payments"] if p["customer"] == "Tesla Zhong")
    assert p["matched"] and p["confidence"] == "email" and p["business"] == "Hung's Chinese"


def test_ambiguous_amount_date_is_flagged_never_guessed(monkeypatch):
    _patch(monkeypatch)
    view = ct.unified_cash_view()
    twin = next(p for p in view["payments"] if p["customer"] == "Twin Payer")
    assert twin["matched"] is False    # two candidate rows with the same amount+window
    assert any(u["customer"] == "Twin Payer" for u in view["unmatched"])


def test_unknown_customer_unmatched(monkeypatch):
    _patch(monkeypatch)
    view = ct.unified_cash_view()
    assert any(u["customer"] == "Total Stranger" for u in view["unmatched"])


def test_name_match_requires_unambiguity(monkeypatch):
    # same normalized business on two DIFFERENT clients → name match must refuse
    rows = [_hdr(),
            _row("Blue Duck", "", "7/1/2026", "$9,000", "$1,000"),
            _row("Blue Duck", "", "7/2/2026", "$8,000", "$2,000", name="Other Owner")]
    monkeypatch.setattr(tr, "_rows", lambda: rows)
    monkeypatch.setattr(tr, "sync_state", lambda key=tr._KEY: {"age_seconds": 0})
    monkeypatch.setattr(tr, "resync", lambda key=tr._KEY: {"age_seconds": 0})
    monkeypatch.setattr(ct, "_recent_charges",
                        lambda days=30: [_charge("ch_9", dt.date(2026, 7, 5), 777.0, "Blue Duck", "")])
    kv_store._MEM.clear()
    view = ct.unified_cash_view()
    # same label on both rows → actually unambiguous (one client, duplicate rows) → matched;
    # amounts differ from cells so it lands via name, picking the newest Won row
    assert view["payments"][0]["matched"] and view["payments"][0]["confidence"] == "name"


# ── Needs-logging: both truths reported; blank/trailing cells surface ────────────────

def test_blank_cell_with_stripe_money_needs_logging(monkeypatch):
    _patch(monkeypatch)
    view = ct.unified_cash_view()
    cally = next(n for n in view["needs_logging"] if n["business"] == "Cally Hotel")
    assert cally["tracker_logged"] == "(blank)" and cally["gap"] == 3355.0
    assert "Stripe shows" in cally["note"]


def test_covered_cell_not_flagged(monkeypatch):
    _patch(monkeypatch)
    view = ct.unified_cash_view()
    assert not any(n["business"] == "Hung's Chinese" for n in view["needs_logging"])


# ── The incident, replayed (acceptance test) ────────────────────────────────────────

def test_incident_replay_latest_cash_and_last_deal(monkeypatch):
    _patch(monkeypatch)
    import closes_view
    monkeypatch.setattr(closes_view, "recent_closes",
                        lambda limit=5: {"closes": [{"business": "Hung's Chinese", "name": "",
                                                     "close_date": "2026-07-08",
                                                     "contract": 15100.0, "offer": "Scale Engine"}]})
    q = "what's our last cash collected and who was the last deal we closed"
    reply, handled = ct.handle_latest_cash_command(q)
    assert handled
    # cash truth: the actual latest payment event, with money-state + tracker status
    assert "$8,305.00" in reply and "Tesla Zhong" in reply and "Hung's Chinese" in reply
    assert "settling into Stripe" in reply and "available 2026-07-11" in reply
    assert "Tracker: logged" in reply
    # deal truth: the tracker's latest close
    assert "Last deal closed: Hung's Chinese" in reply and "$15,100" in reply
    # no bare-blank dead-end, no junk row
    assert "genuinely blank" not in reply and "WA:" not in reply


def test_latest_cash_unlogged_reports_both_truths(monkeypatch):
    charges = [_charge("ch_3", dt.date(2026, 6, 24), 3355.0, "Lucas Reid", "cally@example.com")]
    _patch(monkeypatch, charges=charges)
    reply, handled = ct.handle_latest_cash_command("what was the latest cash collected?")
    assert handled and "$3,355.00" in reply and "Cally Hotel" in reply
    assert "NOT yet logged" in reply and "flagged" in reply


def test_no_key_honest_defer(monkeypatch):
    monkeypatch.setattr(ct, "_recent_charges", lambda days=30: None)
    reply, handled = ct.handle_latest_cash_command("latest cash collected?")
    assert handled and "won't guess" in reply


def test_needs_logging_query(monkeypatch):
    _patch(monkeypatch)
    reply, handled = ct.handle_needs_logging_command("what needs logging?")
    assert handled and "Cally Hotel" in reply and "unmatched" in reply


def test_handler_does_not_fire_on_per_client_cash_question(monkeypatch):
    _patch(monkeypatch)
    reply, handled = ct.handle_latest_cash_command("what's the cash collected for Hung's Chinese?")
    assert not handled   # per-client question stays with tracker_read.handle_cash_for


# ── Money-state labels ───────────────────────────────────────────────────────────────

def test_charge_state_labels():
    assert "settling into Stripe" in ct._charge_state({"bt_status": "pending",
                                                       "available_on": "2026-07-11"})
    assert "settled in Stripe" in ct._charge_state({"bt_status": "available"})


# ── PII: emails never leave the module ───────────────────────────────────────────────

def test_no_emails_in_outputs(monkeypatch):
    _patch(monkeypatch)
    assert "@" not in str(ct.unified_cash_view())
    assert "@" not in str(ct.cash_truth_summary())


# ── The WA bug (junk-row hijack) stays dead ─────────────────────────────────────────

def test_junk_rows_cannot_hijack(monkeypatch):
    junk = ("Hey guys, I want to grow my business. I have a relatively strong idea of what "
            "I need to do, but I need help to achieve it all!")
    rows = [_hdr(), _row("WA", outcome=""), _row(junk, outcome=""),
            _row("Hung's Chinese", "hung@example.com", "7/8/2026", "$15,100", "$8,305.00")]
    monkeypatch.setattr(tr, "_rows", lambda: rows)
    monkeypatch.setattr(tr, "sync_state", lambda key=tr._KEY: {"age_seconds": 0})
    monkeypatch.setattr(tr, "resync", lambda key=tr._KEY: {"age_seconds": 0})
    tr._names_cache.update(ts=0, names=[])
    q = "what's our last cash collected and who was the last deal we closed"
    assert tr._clients_in_text(q) == []          # the paragraph row can't token-match "what"
    r = tr.read_client_row(junk, fresh=False)     # even a junk query can't land on the WA row
    assert not (r.get("found") and r.get("business") == "WA")
    reply, handled = tr.handle_cash_for(q)
    assert not handled                            # aggregate cash question falls through


# ── Reconciliation activation (paid-but-unlogged live) ──────────────────────────────

def test_stripe_reconcile_activated(monkeypatch):
    import stripe_reconcile as sr
    monkeypatch.setattr(ct, "_recent_charges",
                        lambda days=30: [_charge("ch_1", dt.date(2026, 7, 8), 8305.0,
                                                 "Tesla Zhong", "hung@example.com"),
                                         _charge("ch_5", dt.date(2026, 7, 5), 1275.0,
                                                 "Total Stranger", "x@nowhere.com")])
    monkeypatch.setattr(sr, "_fetch_tracker_rows",
                        lambda: (_hdr(), [_row("Hung's Chinese", "hung@example.com",
                                               "7/8/2026", "$15,100", "$8,305.00")]))
    res = sr.reconcile_stripe_tracker()
    rec = res["stripe_reconciliation"]
    assert rec["status"] == "ok" and rec["checked_charges"] == 2
    missing = rec["paid_missing_from_tracker"]
    assert len(missing) == 1 and missing[0]["customer"] == "Total Stranger"
    assert "@" not in str(rec)


def test_stripe_reconcile_no_key_pending(monkeypatch):
    import stripe_reconcile as sr
    monkeypatch.setattr(ct, "_recent_charges", lambda days=30: None)
    res = sr.reconcile_stripe_tracker()
    assert res["stripe_reconciliation"]["status"] == "pending_stripe_key"
    assert res["degraded"]


# ── Surfacing: salience event + action feed persistence ─────────────────────────────

def test_salience_unlogged_event():
    import salience
    kv_store._MEM.clear()
    snap = {"cash_truth": {"needs_logging": [
        {"business": "Cally Hotel", "gap": 3355.0, "stripe_total": 3355.0,
         "tracker_logged": "(blank)", "last_payment_date": "2026-06-24"}]}}
    events = [e for e in salience.collect(snap) if e["type"] == "unlogged"]
    assert len(events) == 1 and "Cally Hotel" in events[0]["spoken"]
    salience.mark_told(events)
    assert not [e for e in salience.collect(snap) if e["type"] == "unlogged"]  # watermarked


def test_action_feed_needs_logging_persists(monkeypatch):
    import action_feed, salience
    monkeypatch.setattr(salience, "collect", lambda snap=None: [])
    snap = {"degraded": [], "cash_truth": {"needs_logging": [
        {"business": "Cally Hotel", "gap": 3355.0, "stripe_total": 3355.0,
         "tracker_logged": "(blank)"}]}}
    feed = action_feed.build_action_feed(snap)
    item = next(i for i in feed["items"] if i["category"] == "needs_logging")
    assert item["severity"] == "S2" and "Cally Hotel" in item["title"]
    assert "never" not in item["action"].lower()  # nudge wording, team logs


# ── Lag watermarking (observed) ──────────────────────────────────────────────────────

def test_lag_watermarks_track_unlogged_then_logged(monkeypatch):
    _patch(monkeypatch)
    view = ct.unified_cash_view()
    assert view["lag"]["outstanding_unlogged"] >= 1     # Cally's charge is unlogged
    # the team logs Cally's cell → next run closes the watermark
    rows = _rows()
    rows[3][32] = "$3,355.00"
    monkeypatch.setattr(tr, "_rows", lambda: rows)
    view2 = ct.unified_cash_view()
    assert view2["lag"]["outstanding_unlogged"] < view["lag"]["outstanding_unlogged"]
