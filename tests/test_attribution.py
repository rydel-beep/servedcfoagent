"""
Adversarial tests for the ad attribution engine (Phases 1-2, DECISIONS #111).

Everything here is pure/injected — no network, no DB. The rails under test:
  - id-first resolution preference (utmAdId beats utm_content names)
  - tier classification (ad / ig_dm / other / none)
  - the dedupe rule for duplicate won rows (+ the reconciliation term it creates)
  - reconciliation identities (leads / closes / cash / spend) fail loudly on drift
  - min-n gates (KILL needs 30 leads; scale may fire on 3 closes; watch below)
  - the unattributed + IG-DM rows are always present (coverage never hidden)
  - validation flags flag, never reclassify
  - ads_read only: no Meta write verbs anywhere in the new modules
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import attribution_engine as eng
import attribution_join as join

W0, W1 = dt.date(2026, 7, 1), dt.date(2026, 7, 31)

HDR = ["1 · LEAD INTAKE Lead ID", "Input Date", "Input Time", "Lead Name", "Email", "Phone",
       "Lead Source", "Business Name", "Revenue Range", "Market",
       "2 · SETTER FUNNEL Setter", "First Date Called", "First Time Called",
       "Recent Time Called", "Called Within 5 Mins?", "Attempts", "Call Outcome",
       "DQ Reason", "Set Date", "Lead Quality", "Setter Notes",
       "3 · CLOSER FUNNEL Closer", "Show Status", "Call Outcome", "Loss Reason",
       "Offer Pitched", "Offer Sold", "Close Date",
       "4 · MONEY (update from Stripe) Contract Value", "Payment Type", "Deposit Amount",
       "Deposit Date", "Cash Collected"]


def row(name, email, input_date="2026-07-10", setter="set", show="Showed",
        closer="", close_date="", contract="", cash="", notes="", source="Facebook"):
    r = [""] * len(HDR)
    r[1], r[3], r[4], r[6], r[7] = input_date, name, email, source, name + " Biz"
    r[16], r[18], r[20] = setter, "2026-07-11" if setter == "set" else "", notes
    r[22], r[23], r[27], r[28], r[32] = show, closer, close_date, contract, cash
    return r


def contact(cid, email, name, tier="ad", ft_ref="120000000000000001", ft_kind="id",
            lt_ref=None, lt_kind=None, medium="facebook", tags=None,
            date_added=dt.datetime(2026, 7, 10)):
    return {"id": cid, "email": email, "name": name, "tier": tier,
            "ft_ad_ref": ft_ref, "ft_ref_kind": ft_kind,
            "lt_ad_ref": lt_ref or ft_ref, "lt_ref_kind": lt_kind or ft_kind,
            "medium": medium, "tags": tags or [], "source": None,
            "date_added": date_added, "first_touch": {}, "last_touch": {}}


def resolver(mapping):
    def fn(ref, kind):
        if ref in mapping:
            return mapping[ref]
        return {"basis": "unresolved", "creative_key": None, "ad_ids": []}
    return fn


RES_A = {"basis": "id", "creative_key": "creative a", "ad_ids": ["120000000000000001"],
         "ad_name": "Creative A", "adset_id": "as1", "campaign_id": "c1",
         "campaign_name": "TOF"}
RES_B = {"basis": "name_ambiguous", "creative_key": "creative b",
         "ad_ids": ["120000000000000002", "120000000000000003"],
         "ad_name": "Creative B", "adset_id": None, "campaign_id": None,
         "campaign_name": "ambiguous"}


# ── join-layer pure classification ───────────────────────────────────────────

def test_ad_ref_prefers_utm_ad_id_over_name():
    touch = {"utmAdId": "120249363416150167",
             "utmContent": "C G3 Q326 Served Graphics July 2026 2nd Batch - Graphic 3"}
    ref, kind = join.ad_ref_from_touch(touch)
    assert (ref, kind) == ("120249363416150167", "id")


def test_ad_ref_id_style_utm_content_is_id():
    ref, kind = join.ad_ref_from_touch({"utmContent": "120246302209490167"})
    assert (ref, kind) == ("120246302209490167", "id")


def test_ad_ref_name_fallback_and_none():
    assert join.ad_ref_from_touch({"utmContent": "Retargeting NEW VSL"}) == ("Retargeting NEW VSL", "name")
    assert join.ad_ref_from_touch({"medium": "facebook"}) == (None, None)


def test_tier_classification():
    assert join.classify_tier({}, {}, "x", None) == "ad"
    assert join.classify_tier({"medium": "instagram"}, {}, None, None) == "ig_dm"
    assert join.classify_tier({"medium": "facebook"}, {}, None, None) == "other"
    assert join.classify_tier({}, {}, None, None) == "none"


def test_classify_contact_from_list_payload_attributions_array():
    c = {"id": "c1", "email": "A@B.com", "contactName": "Jane Doe",
         "dateAdded": "2026-07-01T00:00:00Z",
         "attributions": [{"isFirst": "true", "utmAdId": "120000000000000009",
                           "medium": "facebook"},
                          {"isLast": "true", "utmContent": "Some Ad Name"}]}
    out = join.classify_contact(c)
    assert out["tier"] == "ad" and out["email"] == "a@b.com"
    assert out["ft_ad_ref"] == "120000000000000009" and out["ft_ref_kind"] == "id"
    assert out["lt_ad_ref"] == "Some Ad Name" and out["lt_ref_kind"] == "name"


# ── dedupe rule ──────────────────────────────────────────────────────────────

def test_duplicate_won_rows_counted_once_and_flagged():
    rows = [HDR,
            row("John Tamayo", "jt@x.com", closer="won", close_date="2026-07-20",
                contract="24000", cash="8000"),
            row("John Tamayo", "jt@x.com", closer="won", close_date="2026-07-20",
                contract="24000", cash="")]
    contacts = [contact("c1", "jt@x.com", "John Tamayo")]
    out = eng.compute_from_inputs(rows, contacts, {}, resolver({"120000000000000001": RES_A}),
                                  W0, W1, canonical={"closes": 2, "cash": 8000.0})
    assert out["totals"]["closes"] == 1
    assert any(f["kind"] == "duplicate_won_row" for f in out["flags"])
    # reconciliation balances via the explicit duplicates term
    assert out["reconciliation"]["checks"]["closes"]["ok"]
    assert out["reconciliation"]["checks"]["closes"]["duplicates_removed"] == 1
    assert out["reconciliation"]["checks"]["cash"]["ok"]


def test_distinct_second_deal_is_not_deduped():
    rows = [HDR,
            row("Nirosha D", "n@x.com", closer="won", close_date="2026-07-05",
                contract="10000", cash="5000"),
            row("Nirosha D", "n@x.com", closer="won", close_date="2026-07-25",
                contract="18300", cash="6000")]
    out = eng.compute_from_inputs(rows, [contact("c1", "n@x.com", "Nirosha D")], {},
                                  resolver({"120000000000000001": RES_A}), W0, W1,
                                  canonical={"closes": 2})
    assert out["totals"]["closes"] == 2
    assert not any(f["kind"] == "duplicate_won_row" for f in out["flags"])


# ── reconciliation honesty ───────────────────────────────────────────────────

def test_lead_total_reconciles_and_tiers_partition_the_universe():
    rows = [HDR,
            row("Ad Lead", "ad@x.com"),
            row("IG Lead", "ig@x.com"),
            row("Mystery Lead", "none@x.com"),
            row("Ghost Lead", "ghost@x.com")]  # no GHL contact at all
    contacts = [contact("c1", "ad@x.com", "Ad Lead"),
                contact("c2", "ig@x.com", "IG Lead", tier="ig_dm", ft_ref=None, ft_kind=None,
                        medium="instagram"),
                contact("c3", "none@x.com", "Mystery Lead", tier="other", ft_ref=None,
                        ft_kind=None)]
    out = eng.compute_from_inputs(rows, contacts, {}, resolver({"120000000000000001": RES_A}),
                                  W0, W1, canonical={"leads": 4})
    assert out["reconciliation"]["checks"]["leads"]["ok"]
    tiers = {r["tier"]: r["leads"] for r in out["creatives"] if r["leads"]}
    assert tiers == {"ad": 1, "ig_dm": 1, "unattributed": 2}
    assert any(f["kind"] == "lead_unmatched_in_ghl" for f in out["flags"])


def test_reconciliation_fails_loudly_on_drift():
    rows = [HDR, row("Solo Lead", "s@x.com")]
    out = eng.compute_from_inputs(rows, [contact("c1", "s@x.com", "Solo Lead")], {},
                                  resolver({"120000000000000001": RES_A}), W0, W1,
                                  canonical={"leads": 99})
    assert out["reconciliation"]["ok"] is False
    assert out["reconciliation"]["checks"]["leads"]["ok"] is False


def test_spend_reconciles_against_account_total_and_zero_lead_ads_appear():
    spend = {"120000000000000005": {"name": "Burner Ad", "spend": 500.0,
                                    "impressions": 1000, "clicks": 10}}
    rows = [HDR, row("Ad Lead", "ad@x.com")]
    out = eng.compute_from_inputs(rows, [contact("c1", "ad@x.com", "Ad Lead")], spend,
                                  resolver({"120000000000000001": RES_A}), W0, W1,
                                  canonical={"account_spend": 500.0})
    assert out["reconciliation"]["checks"]["spend"]["ok"]
    burner = next(r for r in out["creatives"] if r["label"] == "Burner Ad")
    assert burner["spend"] == 500.0 and burner["leads"] == 0   # the kill signal is visible


# ── min-n gates ──────────────────────────────────────────────────────────────

def test_min_n_gates_kill_needs_30_leads_scale_fires_on_3_closes():
    rows = [HDR]
    for i in range(5):
        rows.append(row(f"L{i}", f"l{i}@x.com",
                        closer="won" if i < 3 else "", contract="10000" if i < 3 else "",
                        close_date="2026-07-2%d" % i if i < 3 else ""))
    contacts = [contact(f"c{i}", f"l{i}@x.com", f"L{i}") for i in range(5)]
    out = eng.compute_from_inputs(rows, contacts, {}, resolver({"120000000000000001": RES_A}),
                                  W0, W1)
    r = next(x for x in out["creatives"] if x["creative_key"] == "creative a")
    assert r["gates"]["sufficient_for_scale"] is True      # 3 closes
    assert r["gates"]["sufficient_for_kill"] is False      # only 5 leads < 30
    assert r["gates"]["gate"] == "ok"


def test_watch_gate_below_both_thresholds():
    rows = [HDR, row("Only Lead", "o@x.com")]
    out = eng.compute_from_inputs(rows, [contact("c1", "o@x.com", "Only Lead")], {},
                                  resolver({"120000000000000001": RES_A}), W0, W1)
    r = next(x for x in out["creatives"] if x["creative_key"] == "creative a")
    assert r["gates"]["gate"].startswith("watch — insufficient data")


# ── channel rows + flags ─────────────────────────────────────────────────────

def test_ig_and_unattributed_rows_always_present_even_at_zero():
    out = eng.compute_from_inputs([HDR], [], {}, resolver({}), W0, W1)
    keys = {r["creative_key"] for r in out["creatives"]}
    assert {"__ig_dm__", "__unattributed__"} <= keys


def test_qualified_inquiry_disagreement_flags_but_never_reclassifies():
    rows = [HDR, row("Flagged Lead", "f@x.com", notes="influencer collab inquiry")]
    out = eng.compute_from_inputs(rows, [contact("c1", "f@x.com", "Flagged Lead")], {},
                                  resolver({"120000000000000001": RES_A}), W0, W1)
    assert any(f["kind"] == "qualified_but_inquiry_signals" for f in out["flags"])
    r = next(x for x in out["creatives"] if x["creative_key"] == "creative a")
    assert r["qualified"] == 1        # still counted — flags never silently reclassify


def test_dq_but_progressed_flags():
    rows = [HDR, row("Weird Lead", "w@x.com", setter="dq", closer="won",
                     close_date="2026-07-15", contract="9000")]
    out = eng.compute_from_inputs(rows, [contact("c1", "w@x.com", "Weird Lead")], {},
                                  resolver({"120000000000000001": RES_A}), W0, W1)
    assert any(f["kind"] == "dq_but_progressed" for f in out["flags"])


def test_ig_non_lead_inquiries_bucket_excludes_tracker_entrants():
    leads, _ = eng.parse_tracker([HDR, row("IG Lead", "ig@x.com")])
    contacts = [
        contact("c1", "ig@x.com", "IG Lead", tier="ig_dm", ft_ref=None, ft_kind=None),
        contact("c2", "dm@x.com", "Photographer Dan", tier="ig_dm", ft_ref=None,
                ft_kind=None, tags=["photographer"]),
        contact("c3", "dm2@x.com", "Random DM", tier="ig_dm", ft_ref=None, ft_kind=None),
    ]
    out = eng.ig_non_lead_inquiries(contacts, leads, W0, W1)
    assert out["count"] == 2                       # ig@x.com entered the tracker
    assert any(b["signal"] == "photographer" for b in out["borderline_for_review"])


# ── money metrics ────────────────────────────────────────────────────────────

def test_money_metrics_close_date_basis_and_ltgp_cac():
    rows = [HDR,
            row("Old Lead", "old@x.com", input_date="2026-05-01", closer="won",
                close_date="2026-07-15", contract="15000", cash="5000")]
    spend = {"120000000000000001": {"name": "Creative A", "spend": 1000.0,
                                    "impressions": 0, "clicks": 0}}
    out = eng.compute_from_inputs(rows, [contact("c1", "old@x.com", "Old Lead")], spend,
                                  resolver({"120000000000000001": RES_A}), W0, W1,
                                  margin_pct=80.0, closer_comm=500.0, setter_comm=100.0)
    r = next(x for x in out["creatives"] if x["creative_key"] == "creative a")
    assert r["leads"] == 0 and r["closes"] == 1    # entered before window, closed inside
    assert r["roas_contracted"] == 15.0 and r["roas_cash"] == 5.0
    assert r["cost_per_close"] == 1000.0
    assert r["cost_per_close_loaded"] == 1600.0    # 1000 + all comms (only close)
    assert r["ltgp"] == 12000.0 and r["ltgp_cac"] == 7.5
    assert "labelled" in out["attribution_model"] or "last-touch" in out["attribution_model"]


def test_ambiguous_name_groups_at_creative_level_with_member_ids():
    rows = [HDR, row("Amb Lead", "amb@x.com")]
    c = contact("c1", "amb@x.com", "Amb Lead", ft_ref="Creative B", ft_kind="name")
    out = eng.compute_from_inputs(rows, [c], {}, resolver({"Creative B": RES_B}), W0, W1)
    r = next(x for x in out["creatives"] if x["creative_key"] == "creative b")
    assert len(r["ad_ids"]) == 2 and r["leads"] == 1
    assert r["first_touch_basis"] == {"name_ambiguous": 1}


# ── structural safety: ads_read only ─────────────────────────────────────────

def test_no_meta_write_calls_in_new_modules():
    root = Path(__file__).resolve().parent.parent
    for mod in ("meta_entities.py", "attribution_join.py", "attribution_engine.py"):
        src = (root / mod).read_text()
        assert "requests.post" not in src, f"{mod} must never POST"
        assert "requests.delete" not in src, f"{mod} must never DELETE"
        assert "requests.put" not in src, f"{mod} must never PUT"
