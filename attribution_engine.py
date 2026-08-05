"""
attribution_engine.py
---------------------
Per-CREATIVE full-funnel attribution: ad → lead → qualified → set → show → close → cash
(Phases 1-2 of the ad attribution engine; DECISIONS #111).

THE LEAD UNIVERSE IS THE TRACKER (clean view — test leads excluded), the same one-engine
definition leads_view counts. Every tracker lead in the window lands in EXACTLY ONE tier:
  ad-level creative row · IG-DM channel row · UNATTRIBUTED row
so the visible rows always sum to the canonical lead total — reconciliation is structural.
IG contacts that never entered the tracker are the separate, visible "IG non-lead
inquiries" bucket (excluded from lead math — Rydel's Phase-0 confirmation).

Money metrics per creative are CLOSE-DATE basis (parity with unit_economics); the cohort
lead→set→show funnel (by Input Date) is shown for diagnostics, labelled. First-touch is
the credit default; last-touch resolution is stored alongside, labelled, never blended.

HONESTY RAILS (test-enforced):
  - reconciliation{} proves leads/spend/closes/cash against the canonical engines; ok=False
    on drift — the attribution view can never silently disagree with the dashboard.
  - duplicate won rows (same identity + same close date/value) are counted ONCE, the
    removed duplicates surfaced as data-quality flags AND carried as an explicit term in
    the closes reconciliation, so canonical totals still balance to the penny.
  - min-n gates: no verdict eligibility under 30 attributed leads (KILL bar) / 3 closes
    (scale bar); below both → "watch — insufficient data (n=…)". Verdict TEXT is Phase 3;
    this engine only emits the gate truth.
  - validation flags (qualified-vs-notes disagreements, DQ-but-progressed, unmatched
    leads) FLAG for review — nothing is silently reclassified.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time

logger = logging.getLogger(__name__)

MIN_N_LEADS_KILL = 30      # KILL verdicts require this many attributed leads (Rydel)
MIN_N_CLOSES_SCALE = 3     # scale verdicts may fire on this many closes (Rydel)

_IG_KEY = "__ig_dm__"
_UNATTR_KEY = "__unattributed__"

_INQUIRY_RE = re.compile(
    r"influencer|photographer|videographer|vendor|collab|supplier|partnership|"
    r"content creator|ugc|media kit|sponsor", re.I)

_cache: dict = {}          # {(start,end): (built_epoch, result)} — in-process, 30 min
_CACHE_TTL_S = 1800


# ── Tracker parsing (header-name detection, the proven repo pattern) ─────────

def tracker_cols(header: list[str]) -> dict:
    idx: dict = {}
    outcome_cols = []
    for k, c in enumerate(header):
        cl = (c or "").lower()
        if "input date" in cl and "input_date" not in idx:
            idx["input_date"] = k
        elif "lead name" in cl and "name" not in idx:
            idx["name"] = k
        elif "email" in cl and "email" not in idx:
            idx["email"] = k
        elif "lead source" in cl and "source" not in idx:
            idx["source"] = k
        elif "business name" in cl and "business" not in idx:
            idx["business"] = k
        elif "call outcome" in cl:
            outcome_cols.append(k)
        elif "dq reason" in cl and "dq_reason" not in idx:
            idx["dq_reason"] = k
        elif "set date" in cl and "set_date" not in idx:
            idx["set_date"] = k
        elif "setter notes" in cl and "setter_notes" not in idx:
            idx["setter_notes"] = k
        elif "show status" in cl and "show" not in idx:
            idx["show"] = k
        elif "close date" in cl and "close_date" not in idx:
            idx["close_date"] = k
        elif "contract value" in cl and "contract" not in idx:
            idx["contract"] = k
        elif "cash collected" in cl and "cash" not in idx:
            idx["cash"] = k
        elif "offer sold" in cl and "offer" not in idx:
            idx["offer"] = k
    if outcome_cols:
        idx["setter_outcome"] = min(outcome_cols)      # SETTER funnel column (earlier)
        if len(outcome_cols) > 1:
            idx["closer_outcome"] = max(outcome_cols)  # CLOSER funnel column (later)
    return idx


def _date(s) -> dt.date | None:
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(s or ""))
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(s or ""))
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _money(s) -> float | None:
    v = str(s or "").replace("$", "").replace(",", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 @.]", "", str(s or "").lower()).strip()


def parse_tracker(rows: list[list[str]]) -> tuple[list[dict], dict]:
    """Clean tracker rows → lead dicts. Caller passes the CLEAN view (test leads gone)."""
    if not rows:
        return [], {}
    hi = next((i for i, r in enumerate(rows[:8])
               if any("lead name" in (c or "").lower() for c in r)), 0)
    cm = tracker_cols(rows[hi])
    leads = []
    for r in rows[hi + 1:]:
        def g(key):
            i = cm.get(key)
            return r[i].strip() if (i is not None and i < len(r)) else ""
        name = g("name")
        input_date = _date(g("input_date"))
        if not name or input_date is None:
            continue
        setter_out = g("setter_outcome").lower()
        closer_out = g("closer_outcome").lower()
        leads.append({
            "name": name, "name_norm": _norm(name),
            "email": _norm(g("email")),
            "business": g("business"), "lead_source": g("source"),
            "input_date": input_date,
            "setter_outcome": setter_out,
            "qualified": setter_out != "dq",           # Rydel: deterministic core
            "dq_reason": g("dq_reason"),
            "set": setter_out == "set",
            "set_date": _date(g("set_date")),
            "setter_notes": g("setter_notes"),
            "show": g("show").lower() == "showed",
            "closer_outcome": closer_out,
            "won": closer_out == "won",
            "close_date": _date(g("close_date")),
            "contract": _money(g("contract")),
            "cash": _money(g("cash")),
            "offer": g("offer"),
        })
    return leads, cm


# ── Dedupe rule for duplicate WON rows (DECISIONS #111) ──────────────────────

def dedupe_won(leads: list[dict]) -> tuple[list[dict], list[dict]]:
    """Same identity (email, else name) + same close date OR same contract value →
    ONE deal. Keeps the most money-complete row (cash populated wins, then first).
    Returns (leads_with_dupes_voided, duplicate_flags). Non-won rows untouched."""
    won = [l for l in leads if l["won"]]
    groups: dict[str, list[dict]] = {}
    for l in won:
        ident = l["email"] or l["name_norm"]
        groups.setdefault(ident, []).append(l)
    dupes = []
    for ident, rows in groups.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda l: (l["cash"] is None, str(l["close_date"] or "9999")))
        kept = [rows[0]]
        for cand in rows[1:]:
            dup_of = next((k for k in kept if
                           (cand["close_date"] and cand["close_date"] == k["close_date"])
                           or (cand["contract"] is not None and cand["contract"] == k["contract"])), None)
            if dup_of is not None:
                cand["won"] = False
                cand["_dup_removed"] = True
                dupes.append({"kind": "duplicate_won_row", "name": cand["name"],
                              "close_date": str(cand["close_date"] or ""),
                              "contract": cand["contract"],
                              "kept": dup_of["name"],
                              "detail": "counted once; fix at source in the tracker"})
            else:
                kept.append(cand)     # genuinely distinct second deal (re-sign) — kept
    return leads, dupes


# ── The pure core (all inputs injected — unit-testable, no I/O) ──────────────

def compute_from_inputs(
    tracker_rows: list[list[str]],
    contacts: list[dict],
    spend_by_ad: dict,
    resolve_fn,
    w0: dt.date,
    w1: dt.date,
    *,
    margin_pct: float | None = None,
    closer_comm: float = 0.0,
    setter_comm: float = 0.0,
    canonical: dict | None = None,
) -> dict:
    """contacts: attr_contacts rows. spend_by_ad: {ad_id: {name, spend, impressions,
    clicks}} for the window. resolve_fn(ref, kind) → resolution dict (attribution_join).
    canonical: {leads, closes, cash, contract, account_spend} for reconciliation."""
    leads, _cm = parse_tracker(tracker_rows)
    leads, dupe_flags = dedupe_won(leads)
    flags: list[dict] = list(dupe_flags)

    by_email = {c["email"]: c for c in contacts if c.get("email")}
    by_name: dict[str, dict] = {}
    for c in contacts:
        if c.get("name"):
            by_name.setdefault(_norm(c["name"]), c)

    def join_contact(lead: dict) -> tuple[dict | None, str | None]:
        if lead["email"] and lead["email"] in by_email:
            return by_email[lead["email"]], "email"
        if lead["name_norm"] in by_name:
            return by_name[lead["name_norm"]], "name"
        return None, None

    resolution_cache: dict = {}

    def resolve(ref, kind):
        if not ref:
            return {"basis": "unresolved", "creative_key": None, "ad_ids": []}
        k = (ref, kind)
        if k not in resolution_cache:
            resolution_cache[k] = resolve_fn(ref, kind)
        return resolution_cache[k]

    # ── walk every window lead into exactly one tier ─────────────────────────
    creatives: dict[str, dict] = {}

    def bucket(key: str, label: str) -> dict:
        return creatives.setdefault(key, {
            "creative_key": key, "label": label, "ad_ids": set(),
            "campaigns": set(), "adset_ids": set(),
            "leads": 0, "qualified": 0, "sets": 0, "shows": 0, "closes_cohort": 0,
            "closes": 0, "contract": 0.0, "cash": 0.0, "deals": [],
            "spend": 0.0, "impressions": 0, "clicks": 0,
            "last_touch_differs": 0, "basis_counts": {},
        })

    def lead_bucket_key(lead: dict) -> tuple[str, dict | None]:
        if "_bucket_key" in lead:                 # memoized — a lead that both enters and
            return lead["_bucket_key"], lead.get("_contact")   # closes in-window joins once
        contact, how = join_contact(lead)
        lead["_contact"] = contact
        lead["_joined_via"] = how
        key = _UNATTR_KEY
        if contact is None:
            flags.append({"kind": "lead_unmatched_in_ghl", "name": lead["name"],
                          "detail": "no GHL contact by email or name — lands in Unattributed"})
        elif contact.get("tier") == "ad":
            res = resolve(contact.get("ft_ad_ref"), contact.get("ft_ref_kind"))
            if res["basis"] != "unresolved" and res.get("creative_key"):
                lead["_res"] = res
                key = res["creative_key"]
            # else: an ad ref that can't be resolved stays Unattributed — honest
        elif contact.get("tier") == "ig_dm":
            key = _IG_KEY
        lead["_bucket_key"] = key
        return key, contact

    # the channel rows are ALWAYS visible, even at zero — the coverage is never hidden
    bucket(_IG_KEY, "IG DM (channel)")
    bucket(_UNATTR_KEY, "Unattributed")

    window_leads = [l for l in leads if w0 <= l["input_date"] <= w1]
    window_closes = [l for l in leads if l["won"] and l["close_date"]
                     and w0 <= l["close_date"] <= w1]
    dupes_in_window = [l for l in leads if l.get("_dup_removed") and l["close_date"]
                       and w0 <= l["close_date"] <= w1]

    for lead in window_leads:
        key, contact = lead_bucket_key(lead)
        label = (lead.get("_res", {}).get("ad_name") or key) if key not in (_IG_KEY, _UNATTR_KEY) \
            else ("IG DM (channel)" if key == _IG_KEY else "Unattributed")
        b = bucket(key, label)
        b["leads"] += 1
        if lead["qualified"]:
            b["qualified"] += 1
        if lead["set"]:
            b["sets"] += 1
        if lead["show"]:
            b["shows"] += 1
        if lead["won"]:
            b["closes_cohort"] += 1
        res = lead.get("_res")
        if res:
            b["ad_ids"].update(res.get("ad_ids") or [])
            if res.get("campaign_name") and res["campaign_name"] != "ambiguous":
                b["campaigns"].add(res["campaign_name"])
            if res.get("adset_id"):
                b["adset_ids"].add(res["adset_id"])
            b["basis_counts"][res["basis"]] = b["basis_counts"].get(res["basis"], 0) + 1
        c = contact
        if c and c.get("tier") == "ad" and c.get("lt_ad_ref") and \
                c.get("lt_ad_ref") != c.get("ft_ad_ref"):
            b["last_touch_differs"] += 1
        # validation sweep: flag, never reclassify (Rydel)
        blob = " ".join([lead.get("setter_notes") or "", lead.get("dq_reason") or "",
                         lead.get("lead_source") or "",
                         " ".join((c or {}).get("tags") or []) if isinstance((c or {}).get("tags"), list) else ""])
        if lead["qualified"] and _INQUIRY_RE.search(blob):
            flags.append({"kind": "qualified_but_inquiry_signals", "name": lead["name"],
                          "detail": f"counted qualified (outcome ≠ DQ) but notes/tags read "
                                    f"like a non-lead inquiry: '{_INQUIRY_RE.search(blob).group(0)}' — review"})
        if not lead["qualified"] and (lead["set"] or lead["set_date"] or lead["won"]):
            flags.append({"kind": "dq_but_progressed", "name": lead["name"],
                          "detail": "DQ'd by setter outcome but has a set/close — review"})

    # closes on the CLOSE-DATE basis (money metrics; unit_economics parity)
    for lead in window_closes:
        key, _contact = lead_bucket_key(lead)
        label = (lead.get("_res", {}).get("ad_name") or key) if key not in (_IG_KEY, _UNATTR_KEY) \
            else ("IG DM (channel)" if key == _IG_KEY else "Unattributed")
        b = bucket(key, label)
        b["closes"] += 1
        b["contract"] += lead["contract"] or 0.0
        b["cash"] += lead["cash"] or 0.0
        deal = {"name": lead["name"], "close_date": str(lead["close_date"]),
                "contract": lead["contract"], "cash": lead["cash"]}
        if lead["contract"] is None:
            deal["note"] = "closed but contract value blank in tracker — value unknown"
        b["deals"].append(deal)

    # ── spend joins the table (ads with spend but no leads MUST appear) ──────
    for ad_id, srow in (spend_by_ad or {}).items():
        import meta_entities
        key = meta_entities.norm_name(srow.get("name")) or f"id:{ad_id}"
        b = bucket(key, srow.get("name") or key)
        b["ad_ids"].add(ad_id)
        b["spend"] += float(srow.get("spend") or 0)
        b["impressions"] += int(srow.get("impressions") or 0)
        b["clicks"] += int(srow.get("clicks") or 0)

    # ── per-row derived metrics + min-n gates ────────────────────────────────
    def ratio(a, b):
        return round(a / b, 2) if b else None

    rows_out = []
    for key, b in creatives.items():
        is_channel = key in (_IG_KEY, _UNATTR_KEY)
        spend = round(b["spend"], 2)
        row = {
            "creative_key": key, "label": b["label"], "tier":
                ("ig_dm" if key == _IG_KEY else "unattributed" if key == _UNATTR_KEY else "ad"),
            "ad_ids": sorted(b["ad_ids"]), "campaigns": sorted(b["campaigns"]),
            "leads": b["leads"], "qualified": b["qualified"], "sets": b["sets"],
            "shows": b["shows"], "closes_cohort": b["closes_cohort"],
            "closes": b["closes"], "contract": round(b["contract"], 2),
            "cash": round(b["cash"], 2), "deals": b["deals"],
            "spend": spend, "impressions": b["impressions"], "clicks": b["clicks"],
            "cost_per_lead": ratio(spend, b["leads"]) if not is_channel else None,
            "cost_per_qualified": ratio(spend, b["qualified"]) if not is_channel else None,
            "cost_per_set": ratio(spend, b["sets"]) if not is_channel else None,
            "cost_per_close": ratio(spend, b["closes"]) if not is_channel else None,
            "cost_basis": "ad spend only" if not is_channel else None,
            "roas_contracted": ratio(b["contract"], spend) if not is_channel else None,
            "roas_cash": ratio(b["cash"], spend) if not is_channel else None,
            "first_touch_basis": b["basis_counts"],
            "last_touch_differs": b["last_touch_differs"],
        }
        # loaded cost-per-close: creative spend + comms allocated pro-rata by closes
        total_closes_attr = sum(x["closes"] for k2, x in creatives.items()
                                if k2 not in (_IG_KEY, _UNATTR_KEY))
        if not is_channel and b["closes"] and total_closes_attr:
            alloc = (closer_comm + setter_comm) * (b["closes"] / total_closes_attr)
            loaded = spend + alloc
            row["cost_per_close_loaded"] = round(loaded / b["closes"], 2)
            row["loaded_basis"] = "ad spend + closer/setter comms allocated by close share"
            if margin_pct is not None and b["contract"]:
                ltgp = b["contract"] * (margin_pct / 100.0)
                row["ltgp"] = round(ltgp, 2)
                row["ltgp_cac"] = round(ltgp / loaded, 2) if loaded else None
        # min-n gate truth (verdict text is Phase 3)
        n_leads, n_closes = b["leads"], b["closes"]
        row["gates"] = {
            "n_leads": n_leads, "n_closes": n_closes,
            "sufficient_for_scale": n_closes >= MIN_N_CLOSES_SCALE,
            "sufficient_for_kill": n_leads >= MIN_N_LEADS_KILL,
            "gate": ("ok" if (n_closes >= MIN_N_CLOSES_SCALE or n_leads >= MIN_N_LEADS_KILL)
                     else f"watch — insufficient data (n={n_leads} leads, {n_closes} closes)"),
        }
        rows_out.append(row)
    rows_out.sort(key=lambda r: (-r["spend"], -r["leads"]))

    # ── reconciliation (the anti-contradiction guarantee) ────────────────────
    canonical = canonical or {}
    sum_leads = sum(r["leads"] for r in rows_out)
    sum_closes = sum(r["closes"] for r in rows_out)
    sum_cash = round(sum(r["cash"] for r in rows_out), 2)
    sum_contract = round(sum(r["contract"] for r in rows_out), 2)
    sum_spend = round(sum(r["spend"] for r in rows_out), 2)
    dup_n = len(dupes_in_window)
    checks = {}
    if canonical.get("leads") is not None:
        checks["leads"] = {"engine": sum_leads, "canonical": canonical["leads"],
                           "ok": sum_leads == canonical["leads"]}
    if canonical.get("closes") is not None:
        checks["closes"] = {"engine": sum_closes, "duplicates_removed": dup_n,
                            "canonical": canonical["closes"],
                            "ok": sum_closes + dup_n == canonical["closes"]}
    if canonical.get("cash") is not None:
        dup_cash = round(sum(l["cash"] or 0 for l in dupes_in_window), 2)
        checks["cash"] = {"engine": sum_cash, "duplicates_removed_cash": dup_cash,
                          "canonical": canonical["cash"],
                          "ok": abs(sum_cash + dup_cash - canonical["cash"]) < 0.01}
    if canonical.get("account_spend") is not None:
        drift = abs(sum_spend - canonical["account_spend"])
        pct = (100 * drift / canonical["account_spend"]) if canonical["account_spend"] else \
            (0.0 if drift == 0 else 100.0)
        checks["spend"] = {"engine": sum_spend, "canonical": canonical["account_spend"],
                           "drift_pct": round(pct, 2), "ok": pct <= 1.0}
    recon_ok = all(c["ok"] for c in checks.values()) if checks else False

    attributed_leads = sum(r["leads"] for r in rows_out if r["tier"] == "ad")
    return {
        "window": {"start": str(w0), "end": str(w1), "days": (w1 - w0).days + 1},
        "attribution_model": "first-touch (default; last-touch stored + labelled, never blended)",
        "creatives": rows_out,
        "totals": {"leads": sum_leads, "attributed_leads": attributed_leads,
                   "attribution_rate_pct": round(100 * attributed_leads / sum_leads, 1) if sum_leads else None,
                   "closes": sum_closes, "contract": sum_contract, "cash": sum_cash,
                   "spend": sum_spend},
        "reconciliation": {"ok": recon_ok, "checks": checks},
        "flags": flags,
        "min_n": {"kill_requires_leads": MIN_N_LEADS_KILL,
                  "scale_requires_closes": MIN_N_CLOSES_SCALE},
    }


# ── IG non-lead inquiries (visible, excluded from lead math) ─────────────────

def ig_non_lead_inquiries(contacts: list[dict], leads: list[dict],
                          w0: dt.date, w1: dt.date) -> dict:
    """IG-DM contacts added in the window that never entered the tracker (any date):
    counted + shown, excluded from lead denominators. Borderline (inquiry-keyword)
    contacts listed for review — flagged, never silently classified."""
    tracker_emails = {l["email"] for l in leads if l["email"]}
    tracker_names = {l["name_norm"] for l in leads}
    n = 0
    borderline = []
    for c in contacts:
        if c.get("tier") != "ig_dm":
            continue
        da = c.get("date_added")
        d = da.date() if hasattr(da, "date") else _date(da)
        if d is None or not (w0 <= d <= w1):
            continue
        in_tracker = (c.get("email") and c["email"] in tracker_emails) or \
                     (_norm(c.get("name") or "") in tracker_names)
        if in_tracker:
            continue
        n += 1
        blob = " ".join([(c.get("source") or "")] +
                        (c.get("tags") if isinstance(c.get("tags"), list) else []))
        if _INQUIRY_RE.search(blob):
            borderline.append({"name": c.get("name"), "signal": _INQUIRY_RE.search(blob).group(0)})
    return {"count": n, "borderline_for_review": borderline[:50],
            "definition": "IG-DM contacts added in window, never entered the tracker — "
                          "excluded from lead math, shown here"}


# ── The wrapper: gather live inputs, compute, cache ──────────────────────────

def _tracker_rows_clean() -> list[list[str]]:
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name("Lead-to-Cash Tracker")
    except Exception:
        rows = None
    if rows is None:
        try:
            from sales_analytics_pull import _fetch_tab
            rows = _fetch_tab("Lead-to-Cash Tracker")
        except Exception:
            rows = None
    rows = rows or []
    try:
        import test_leads
        return test_leads.clean_tracker_rows(rows)
    except Exception:
        return rows


def compute(days: int = 30, start: str | None = None, end: str | None = None,
            force: bool = False) -> dict:
    """The live per-creative attribution read for a window. Cached 30 min in-process."""
    from helpers import today_sydney
    if start and end:
        try:
            w0, w1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        except ValueError:
            return {"error": "invalid range"}
    else:
        w1 = today_sydney()
        w0 = w1 - dt.timedelta(days=int(days) - 1)
    ck = (str(w0), str(w1))
    hit = _cache.get(ck)
    if hit and not force and time.time() - hit[0] < _CACHE_TTL_S:
        return hit[1]

    import attribution_join
    import meta_entities
    sync = attribution_join.sync_contacts()
    contacts = attribution_join.load_contacts()
    entity_store = meta_entities.refresh_entity_map()
    meta_entities.refresh_ad_spend_daily()
    spend = meta_entities.spend_by_ad_in_range(str(w0), str(w1))

    def resolve_fn(ref, kind):
        return attribution_join.resolve_ref(ref, kind, entity_store=entity_store,
                                            allow_recovery=True)

    rows = _tracker_rows_clean()
    # canonical anchors — the same engines the dashboard quotes
    canonical: dict = {}
    try:
        import leads_view
        canonical["leads"] = leads_view.count_leads(w0, w1).get("count")
    except Exception as e:
        logger.warning("canonical lead count unavailable: %s", e)
    closer_comm = setter_comm = 0.0
    margin = None
    input_degraded: list[dict] = []
    try:
        import range_unit_economics as rue
        ltc = rue._ltc_in_window(w0, w1)
        canonical["closes"] = ltc["closes"]
        canonical["cash"] = ltc["cash"]
        closer_comm = ltc["closer_comm"]
        setter_comm = rue._setter_comm_in_window(w0, w1)
        margin = rue._gross_margin()
    except Exception as e:
        logger.warning("canonical close/comm inputs unavailable: %s", e)
        input_degraded.append({"metric": "attribution_loaded_inputs",
                               "reason": f"comm/close inputs unavailable ({type(e).__name__}) "
                                         "— loaded cost-per-close understated"})
    if margin is None:
        input_degraded.append({"metric": "attribution_ltgp_cac",
                               "reason": "gross margin unavailable — LTGP/LTGP:CAC omitted, "
                                         "never guessed"})
    try:
        import meta_spend
        canonical["account_spend"] = meta_spend.spend_in_range(str(w0), str(w1)).get("spend")
    except Exception as e:
        logger.warning("canonical spend unavailable: %s", e)

    result = compute_from_inputs(rows, contacts, spend.get("ads") or {}, resolve_fn,
                                 w0, w1, margin_pct=margin, closer_comm=closer_comm,
                                 setter_comm=setter_comm, canonical=canonical)
    leads, _cm = parse_tracker(rows)
    result["ig_non_lead_inquiries"] = ig_non_lead_inquiries(contacts, leads, w0, w1)
    result["freshness"] = {
        "contacts_synced": sync.get("at") and dt.datetime.fromtimestamp(sync["at"]).isoformat(),
        "contacts_total": sync.get("total"),
        "spend_source": spend.get("source"),
        "entity_ads": len(entity_store.get("ads") or {}),
    }
    # ── Phase 3: the verdict layer (floor from the registry; capacity for the
    # constraint check; crossings → salience; dupe flags → the action feed/Piolo queue)
    try:
        import attribution_verdicts
        try:
            import manual_targets
            floor = float((manual_targets.get_resolved() or {}).get("ltgp_cac_target") or 3.0)
        except Exception:
            floor = 3.0
        capacity_note = None
        try:
            from snapshot import load_persisted
            cap = (load_persisted() or {}).get("capacity") or {}
            dl = (cap.get("department_load") or {})
            worst = max((d for d in (dl.get("departments") or []) if d.get("load_pct")),
                        key=lambda d: d["load_pct"], default=None)
            if worst:
                capacity_note = f"{worst.get('name')} at {worst.get('load_pct')}% load"
        except Exception:
            pass
        attribution_verdicts.apply(result, floor, capacity_note)
        _record_verdict_crossings(result)
    except Exception as e:
        logger.warning("verdict layer failed: %s", e)
        result.setdefault("degraded", []).append(
            {"metric": "attribution_verdicts", "reason": f"verdict layer failed ({type(e).__name__})"})
    _publish_data_quality_flags(result)

    degraded = list(spend.get("degraded") or []) + input_degraded
    if not contacts:
        degraded.append({"metric": "attribution", "reason": "attr_contacts empty — sync pending"})
    result["degraded"] = degraded
    result["ok"] = result["reconciliation"]["ok"] and not degraded
    _cache[ck] = (time.time(), result)
    return result


# ── Phase 3 plumbing: crossings → salience; dupe flags → Piolo's queue ───────

def _record_verdict_crossings(result: dict) -> None:
    """A creative NEWLY becoming DOUBLE DOWN or KILL at sufficient n is greeting-worthy.
    State + pending events live in kv; salience reads the pending list and watermarks via
    its own told-set. Watch/insufficient states never announce."""
    try:
        import kv_store
        prev = kv_store.get("attr:verdict_state") or {}
        pending = kv_store.get("attr:verdict_crossings") or []
        cur = {}
        for r in (result.get("creatives") or []):
            if r.get("tier") != "ad" or not r.get("verdict"):
                continue
            cur[r["creative_key"]] = r["verdict"]
            if r["verdict"] in ("DOUBLE DOWN", "KILL") and prev.get(r["creative_key"]) != r["verdict"]:
                pending.append({
                    "id": f"attr-verdict:{r['creative_key']}:{r['verdict']}",
                    "creative": r.get("label"), "verdict": r["verdict"],
                    "driver": r.get("verdict_driver"),
                    "window": result.get("window", {}).get("end"),
                })
        kv_store.put("attr:verdict_state", cur)
        kv_store.put("attr:verdict_crossings", pending[-20:])
    except Exception as e:
        logger.info("verdict crossing record failed: %s", e)


def _publish_data_quality_flags(result: dict) -> None:
    """Persist the engine's data-quality flags (duplicate won rows, unmatched leads) to kv
    so the action feed — and therefore PIOLO'S QUEUE — carries them with zero network.
    Self-retiring: each compute overwrites; a clean tracker leaves the list empty."""
    try:
        import kv_store
        dupes = [f for f in (result.get("flags") or []) if f.get("kind") == "duplicate_won_row"]
        kv_store.put("attr:data_quality_flags", [
            {"metric": "attribution_duplicate_won_row",
             "reason": f"Duplicate won row in the Lead-to-Cash tracker: {f.get('name')} "
                       f"(contract ${f.get('contract') or 0:,.0f}) — engine counts it once; "
                       f"fix at source and the explicit-duplicates term retires",
             "name": f.get("name")}
            for f in dupes])
    except Exception as e:
        logger.info("data-quality flag publish failed: %s", e)


# ── Background recompute (keeps the contact sync + spend store warm) ─────────

_loop_started = False
_loop_lock = None


def start_loop(interval_s: int = 6 * 3600) -> None:
    """Periodic recompute of the default window. Fail-quiet daemon (the engine also
    computes lazily on request — this only keeps freshness stamps honest overnight)."""
    global _loop_started
    if _loop_started:
        return
    _loop_started = True
    import threading

    def _loop():
        while True:
            time.sleep(interval_s)
            try:
                compute(30, force=True)
            except Exception as e:
                logger.warning("attribution loop recompute failed: %s", e)

    threading.Thread(target=_loop, daemon=True, name="attribution-recompute").start()
