"""
sales_analytics_pull.py
-----------------------
Read funnel conversion, per-setter/closer throughput, lead-to-cash velocity,
and setter payout from the Team Scorecard, Setter Deep-Dive, and Lead-to-Cash
Tracker tabs. Commission/cash reads stay in sheets_pull.py — this module adds
only the analyses that were missing.

Privacy: cols 3/4/5 (Lead Name, Email, Phone) NEVER enter the output.
"""
from __future__ import annotations

import csv
import io
import logging
import statistics
from datetime import date, timedelta

import requests

from config import SHEET_CONFIG, HTTP_TIMEOUT, WINDOW_CURRENT
from helpers import today_sydney

logger = logging.getLogger(__name__)


def _fetch_tab(tab: str) -> list[list[str]]:
    """Fetch a tab from the Lead-to-Cash sheet as raw rows."""
    sid = SHEET_CONFIG["sheet_id"]
    url = (
        f"https://docs.google.com/spreadsheets/d/{sid}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab)}"
    )
    try:
        resp = requests.get(url, timeout=(5, HTTP_TIMEOUT))
        if resp.status_code != 200:
            logger.error("Sheet %s fetch failed (status %d)", tab, resp.status_code)
            return []
        return list(csv.reader(io.StringIO(resp.text)))
    except requests.RequestException as e:
        logger.error("Sheet %s request failed: %s", tab, e)
        return []


def _parse_money(val: str) -> float | None:
    val = val.strip().replace("$", "").replace(",", "")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_pct(val: str) -> float | None:
    val = val.strip().replace("%", "")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_int(val: str) -> int | None:
    val = val.strip().replace(",", "")
    if not val:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _parse_date(val: str) -> date | None:
    val = val.strip()
    if not val:
        return None
    if len(val) >= 10 and val[4] == "-":
        try:
            p = val[:10].split("-")
            return date(int(p[0]), int(p[1]), int(p[2]))
        except (ValueError, IndexError):
            pass
    if "/" in val:
        try:
            p = val.split("/")
            if len(p) == 3:
                return date(int(p[2]), int(p[0]), int(p[1]))
        except (ValueError, IndexError):
            pass
    return None


def _cell(row: list[str], idx: int) -> str:
    if idx >= len(row):
        return ""
    return row[idx]


def _read_scorecard_cell(rows: list[list[str]], row_idx: int, col_idx: int = 1) -> str:
    """Safe read from scorecard rows."""
    if row_idx >= len(rows):
        return ""
    row = rows[row_idx]
    if col_idx >= len(row):
        return ""
    return row[col_idx].strip()


# ── Funnel from Team Scorecard ──────────────────────────────────────────────

def _pull_funnel(sc_rows: list[list[str]]) -> dict:
    """Read funnel metrics from Team Scorecard rows 4-11."""
    funnel = {
        "leads_in": _parse_int(_read_scorecard_cell(sc_rows, 4)),
        "sets": _parse_int(_read_scorecard_cell(sc_rows, 5)),
        "shows": _parse_int(_read_scorecard_cell(sc_rows, 6)),
        "closes": _parse_int(_read_scorecard_cell(sc_rows, 7)),
        "lead_to_set_pct": _parse_pct(_read_scorecard_cell(sc_rows, 8)),
        "set_to_show_pct": _parse_pct(_read_scorecard_cell(sc_rows, 9)),
        "show_to_close_pct": _parse_pct(_read_scorecard_cell(sc_rows, 10)),
        "lead_to_close_pct": _parse_pct(_read_scorecard_cell(sc_rows, 11)),
        "source": "Team Scorecard computed cells",
    }
    return funnel


# ── Per-setter / per-closer from Team Scorecard ────────────────────────────

def _pull_per_setter(sc_rows: list[list[str]]) -> list[dict]:
    """Read per-setter rows from Scorecard section 2 (rows 14+)."""
    setters = []
    for i in range(14, len(sc_rows)):
        row = sc_rows[i]
        name = row[0].strip() if row else ""
        if not name or name.startswith(("3 ·", "TOTAL")):
            break
        setters.append({
            "name": name,
            "leads_assigned": _parse_int(_cell(row, 1)),
            "sets": _parse_int(_cell(row, 2)),
            "set_rate_pct": _parse_pct(_cell(row, 3)),
        })
    return setters


def _pull_per_closer(sc_rows: list[list[str]]) -> list[dict]:
    """Read per-closer rows from Scorecard section 3 (rows 18+)."""
    closers = []
    for i in range(18, len(sc_rows)):
        row = sc_rows[i]
        name = row[0].strip() if row else ""
        if not name or name.startswith(("4 ·", "TOTAL")):
            break
        closers.append({
            "name": name,
            "shows": _parse_int(_cell(row, 1)),
            "closes": _parse_int(_cell(row, 2)),
            "close_rate_pct": _parse_pct(_cell(row, 3)),
            "commission_total": _parse_money(_cell(row, 4)),
        })
    return closers


# ── Per-setter activity from Scorecard section 6 ───────────────────────────

def _pull_setter_activity(sc_rows: list[list[str]]) -> list[dict]:
    """Read per-setter dial activity from Scorecard rows 38+."""
    activity = []
    for i in range(38, len(sc_rows)):
        row = sc_rows[i]
        name = row[0].strip() if row else ""
        if not name or name.startswith(("7 ·", "TOTAL")):
            break
        activity.append({
            "name": name,
            "dials": _parse_int(_cell(row, 1)),
            "within_5_min": _parse_int(_cell(row, 2)),
            "leads_worked": _parse_int(_cell(row, 3)),
            "five_min_rate_pct": _parse_pct(_cell(row, 4)),
        })
    return activity


# ── Setter payout from Scorecard section 7 + Payout Log ────────────────────

def _pull_setter_payout(sc_rows: list[list[str]]) -> dict:
    """Read setter payout from Scorecard rows 43+ and totals row 45."""
    per_setter = []
    for i in range(43, len(sc_rows)):
        row = sc_rows[i]
        name = row[0].strip() if row else ""
        if not name or name.startswith("TOTAL"):
            break
        per_setter.append({
            "name": name,
            "qualified_sets": _parse_int(_cell(row, 1)),
            "rate": _parse_money(_cell(row, 2)),
            "owed": _parse_money(_cell(row, 3)),
        })

    # Read total row
    total_row = sc_rows[45] if len(sc_rows) > 45 else []
    total_sets = _parse_int(_cell(total_row, 1))
    total_owed = _parse_money(_cell(total_row, 3))

    return {
        "per_setter": per_setter,
        "total_qualified_sets": total_sets,
        "total_owed": total_owed,
    }


def _pull_payout_log_footer() -> dict:
    """Read footer totals from Setter Payout Log tab."""
    rows = _fetch_tab("Setter Payout Log")
    result = {"total_owed": None, "total_paid": None, "pending": None}
    for row in rows:
        label = row[0].strip() if row else ""
        if "Total setter owed" in label:
            result["total_owed"] = _parse_money(_cell(row, 8))
        elif "Total PAID" in label:
            result["total_paid"] = _parse_money(_cell(row, 8))
        elif "PENDING" in label:
            result["pending"] = _parse_money(_cell(row, 8))
    return result


# ── Speed-to-lead from Scorecard ───────────────────────────────────────────

def _pull_speed_to_lead(sc_rows: list[list[str]]) -> dict:
    """Read speed-to-lead metrics from Scorecard rows 32-35."""
    return {
        "calls_within_5_min": _parse_int(_read_scorecard_cell(sc_rows, 32)),
        "total_dials": _parse_int(_read_scorecard_cell(sc_rows, 33)),
        "leads_worked": _parse_int(_read_scorecard_cell(sc_rows, 34)),
        "five_min_rate_pct": _parse_pct(_read_scorecard_cell(sc_rows, 35)),
    }


# ── Velocity from raw Lead-to-Cash rows ────────────────────────────────────

def _pull_velocity(ltc_rows: list[list[str]], cutoff: date) -> dict:
    """Compute median/avg days Input Date→Close Date for won deals in window."""
    deltas = []
    for row in ltc_rows[1:]:  # skip header
        if len(row) <= 27:
            continue
        outcome = _cell(row, 23).strip().lower()
        if outcome != "won":
            continue
        close_dt = _parse_date(_cell(row, 27))
        if not close_dt or close_dt < cutoff:
            continue
        input_dt = _parse_date(_cell(row, 1))
        if not input_dt:
            continue
        days = (close_dt - input_dt).days
        if days >= 0:
            deltas.append(days)

    if not deltas:
        return {
            "days_lead_to_cash_median": None,
            "days_lead_to_cash_avg": None,
            "won_deals_with_dates": 0,
        }

    return {
        "days_lead_to_cash_median": statistics.median(deltas),
        "days_lead_to_cash_avg": round(statistics.mean(deltas), 1),
        "won_deals_with_dates": len(deltas),
    }


# ── Setter Deep-Dive extended funnel ───────────────────────────────────────

def _pull_deep_dive() -> dict | None:
    """Read the extended setting funnel from Setter Deep-Dive tab."""
    rows = _fetch_tab("Setter Deep-Dive")
    if not rows or len(rows) < 9:
        return None

    funnel = {
        "dials": _parse_int(_cell(rows[4], 1)),
        "connects": _parse_int(_cell(rows[5], 1)),
        "connect_rate_pct": _parse_pct(_cell(rows[5], 2)),
        "sets_booked": _parse_int(_cell(rows[6], 1)),
        "sets_from_connects_pct": _parse_pct(_cell(rows[6], 2)),
        "showed": _parse_int(_cell(rows[7], 1)),
        "show_rate_pct": _parse_pct(_cell(rows[7], 2)),
        "closed": _parse_int(_cell(rows[8], 1)),
        "close_from_show_pct": _parse_pct(_cell(rows[8], 2)),
    }

    # Per-setter efficiency (rows 11-12)
    per_setter = []
    for i in range(11, len(rows)):
        row = rows[i]
        name = row[0].strip() if row else ""
        if not name or name.startswith(("3 ·", "TOTAL")):
            break
        per_setter.append({
            "name": name,
            "dials": _parse_int(_cell(row, 1)),
            "sets": _parse_int(_cell(row, 2)),
            "dials_per_set": round(float(_cell(row, 3)), 1) if _cell(row, 3).strip() else None,
            "set_rate_pct": _parse_pct(_cell(row, 4)),
        })

    funnel["per_setter_efficiency"] = per_setter
    return funnel


# ── Cross-check: compute funnel from raw rows vs Scorecard ─────────────────

def _cross_check_funnel(ltc_rows: list[list[str]], scorecard_funnel: dict, cutoff: date, today: date) -> dict:
    """Compute funnel counts from raw rows and compare to Scorecard cells."""
    leads_in = 0
    sets = 0
    shows = 0
    closes = 0

    for row in ltc_rows[1:]:
        input_dt = _parse_date(_cell(row, 1))
        if not input_dt or input_dt < cutoff or input_dt > today:
            continue
        leads_in += 1

        setter_outcome = _cell(row, 16).strip().upper()
        if setter_outcome == "SET":
            sets += 1

        show_status = _cell(row, 22).strip().lower()
        if show_status in ("showed", "show"):
            shows += 1

        closer_outcome = _cell(row, 23).strip().lower()
        if closer_outcome == "won":
            closes += 1

    checks = {"computed": {"leads_in": leads_in, "sets": sets, "shows": shows, "closes": closes}}

    # Compare to scorecard
    mismatches = []
    for key in ("leads_in", "sets", "shows", "closes"):
        sc_val = scorecard_funnel.get(key)
        raw_val = checks["computed"][key]
        if sc_val is not None and raw_val > 0:
            if sc_val > 0:
                diff_pct = abs(raw_val - sc_val) / sc_val
                if diff_pct > 0.02:
                    mismatches.append(f"{key}: computed {raw_val} vs scorecard {sc_val}")

    checks["scorecard_match"] = len(mismatches) == 0
    if mismatches:
        checks["mismatches"] = mismatches

    return checks


# ── LAYER 1: Setter Performance ────────────────────────────────────────────

def _layer_setter_performance(
    ltc_rows: list[list[str]], cutoff: date, today: date,
    sc_setters: list[dict] | None, sc_activity: list[dict] | None,
) -> tuple[list[dict], list[dict]]:
    """Per-setter efficiency, quality, speed from raw LTC rows (Input Date window)."""
    degraded: list[dict] = []
    # Accumulate per-setter stats from raw rows
    buckets: dict[str, dict] = {}

    for row in ltc_rows[1:]:
        input_dt = _parse_date(_cell(row, 1))
        if not input_dt or input_dt < cutoff or input_dt > today:
            continue
        setter = _cell(row, 10).strip() or "Unattributed"
        if setter not in buckets:
            buckets[setter] = {
                "dials": 0, "sets": 0, "shows": 0, "closes": 0,
                "speed_yes": 0, "speed_total": 0,
                "quality_sum": 0.0, "quality_count": 0,
            }
        b = buckets[setter]

        attempts = _parse_int(_cell(row, 15))
        if attempts and attempts > 0:
            b["dials"] += attempts

        setter_outcome = _cell(row, 16).strip().upper()
        if setter_outcome == "SET":
            b["sets"] += 1

        show_status = _cell(row, 22).strip().lower()
        if show_status == "showed":
            b["shows"] += 1

        closer_outcome = _cell(row, 23).strip().lower()
        if closer_outcome == "won":
            b["closes"] += 1

        within5 = _cell(row, 14).strip().upper()
        if within5 in ("YES", "NO"):
            b["speed_total"] += 1
            if within5 == "YES":
                b["speed_yes"] += 1

        # Lead quality grade (col 19) — only count for sets
        if setter_outcome == "SET":
            quality_raw = _cell(row, 19).strip()
            if quality_raw and quality_raw[0].isdigit():
                try:
                    grade = int(quality_raw[0])
                    b["quality_sum"] += grade
                    b["quality_count"] += 1
                except ValueError:
                    pass

    result = []
    for name, b in sorted(buckets.items()):
        sets = b["sets"]
        dials_per_set = round(b["dials"] / sets, 1) if sets > 0 else None
        show_pct = round(b["shows"] / sets * 100, 1) if sets > 0 else None
        close_pct = round(b["closes"] / sets * 100, 1) if sets > 0 else None
        speed_pct = round(b["speed_yes"] / b["speed_total"] * 100, 1) if b["speed_total"] > 0 else None
        avg_quality = round(b["quality_sum"] / b["quality_count"], 1) if b["quality_count"] > 0 else None
        graded_pct = round(b["quality_count"] / sets * 100, 1) if sets > 0 else 0.0

        entry = {
            "name": name,
            "dials": b["dials"],
            "sets": sets,
            "dials_per_set": dials_per_set,
            "speed_to_lead_pct": speed_pct,
            "show_pct": show_pct,
            "close_pct": close_pct,
            "avg_quality": avg_quality,
            "graded_pct": graded_pct,
            "date_key": "Input Date (cohort)",
        }
        if graded_pct < 50.0 and sets > 0:
            entry["quality_flag"] = f"Only {graded_pct}% of sets graded — data sparse"
        result.append(entry)

    # Cross-check against scorecard per-setter totals
    if sc_setters:
        sc_map = {s["name"]: s for s in sc_setters}
        for entry in result:
            sc = sc_map.get(entry["name"])
            if sc and sc.get("sets") is not None and entry["sets"] > 0:
                sc_sets = sc["sets"]
                if sc_sets > 0:
                    diff = abs(entry["sets"] - sc_sets) / sc_sets
                    if diff > 0.02:
                        entry["scorecard_sets_mismatch"] = f"computed {entry['sets']} vs scorecard {sc_sets}"

    return result, degraded


# ── LAYER 2: Lead Quality ─────────────────────────────────────────────────

def _layer_lead_quality(
    ltc_rows: list[list[str]], cutoff: date, today: date,
) -> tuple[dict, list[dict]]:
    """By source and revenue range: leads, sets, closes, close rate, DQ rate."""
    degraded: list[dict] = []

    # By Lead Source
    src_buckets: dict[str, dict] = {}
    # By Revenue Range
    rev_buckets: dict[str, dict] = {}

    for row in ltc_rows[1:]:
        input_dt = _parse_date(_cell(row, 1))
        if not input_dt or input_dt < cutoff or input_dt > today:
            continue

        source = _cell(row, 6).strip() or "Unknown"
        rev_range = _cell(row, 8).strip() or "Unknown"
        setter_outcome = _cell(row, 16).strip().upper()
        closer_outcome = _cell(row, 23).strip().lower()
        is_set = setter_outcome == "SET"
        is_won = closer_outcome == "won"
        is_dq = setter_outcome == "DQ"

        contract = _parse_money(_cell(row, 28))

        # Source bucket
        if source not in src_buckets:
            src_buckets[source] = {"leads": 0, "sets": 0, "closes": 0, "dqs": 0}
        sb = src_buckets[source]
        sb["leads"] += 1
        if is_set:
            sb["sets"] += 1
        if is_won:
            sb["closes"] += 1
        if is_dq:
            sb["dqs"] += 1

        # Revenue range bucket
        if rev_range not in rev_buckets:
            rev_buckets[rev_range] = {"leads": 0, "closes": 0, "contracts": []}
        rb = rev_buckets[rev_range]
        rb["leads"] += 1
        if is_won:
            rb["closes"] += 1
            if contract is not None:
                rb["contracts"].append(contract)

    by_source = []
    for src, sb in sorted(src_buckets.items()):
        close_rate = round(sb["closes"] / sb["leads"] * 100, 1) if sb["leads"] > 0 else 0.0
        dq_rate = round(sb["dqs"] / sb["leads"] * 100, 1) if sb["leads"] > 0 else 0.0
        by_source.append({
            "source": src,
            "leads": sb["leads"],
            "sets": sb["sets"],
            "closes": sb["closes"],
            "close_rate_pct": close_rate,
            "dq_rate_pct": dq_rate,
        })

    by_rev_range = []
    for rng, rb in sorted(rev_buckets.items()):
        close_rate = round(rb["closes"] / rb["leads"] * 100, 1) if rb["leads"] > 0 else 0.0
        avg_contract = round(sum(rb["contracts"]) / len(rb["contracts"]), 2) if rb["contracts"] else None
        entry = {
            "range": rng,
            "leads": rb["leads"],
            "closes": rb["closes"],
            "close_rate_pct": close_rate,
            "avg_contract_value": avg_contract,
        }
        # Targeting signal: high volume, near-zero close
        if rb["leads"] >= 5 and close_rate == 0.0:
            wasted_pct = round(rb["leads"] / sum(s["leads"] for s in rev_buckets.values()) * 100, 1)
            entry["targeting_flag"] = f"{rb['leads']} leads ({wasted_pct}% of volume), 0 closes — consider targeting adjustment"
        by_rev_range.append(entry)

    return {"by_source": by_source, "by_revenue_range": by_rev_range}, degraded


# ── LAYER 3: Loss Intelligence ────────────────────────────────────────────

def _layer_loss_intelligence(
    ltc_rows: list[list[str]], cutoff: date, today: date,
) -> tuple[dict, list[dict]]:
    """DQ reasons, loss reasons, no-show/cancel rate, refunds, recoverable pipeline."""
    degraded: list[dict] = []

    dq_counts: dict[str, int] = {}
    loss_counts: dict[str, int] = {}
    total_sets = 0
    no_shows = 0
    cancels = 0
    refund_count = 0
    refund_amount = 0.0
    recoverable_working = 0
    recoverable_followup = 0

    # Per-setter no-show tracking
    setter_noshows: dict[str, dict] = {}

    for row in ltc_rows[1:]:
        input_dt = _parse_date(_cell(row, 1))
        if not input_dt or input_dt < cutoff or input_dt > today:
            continue

        setter = _cell(row, 10).strip() or "Unattributed"
        setter_outcome = _cell(row, 16).strip().upper()
        show_status = _cell(row, 22).strip().lower()
        closer_outcome = _cell(row, 23).strip().lower()
        dq_reason = _cell(row, 17).strip()
        loss_reason = _cell(row, 24).strip()
        refund_status = _cell(row, 35).strip()
        refund_amt = _parse_money(_cell(row, 37))

        # DQ reasons
        if setter_outcome == "DQ" and dq_reason:
            dq_counts[dq_reason] = dq_counts.get(dq_reason, 0) + 1

        # Sets and show outcomes
        if setter_outcome == "SET":
            total_sets += 1
            if setter not in setter_noshows:
                setter_noshows[setter] = {"sets": 0, "no_shows": 0, "cancels": 0}
            setter_noshows[setter]["sets"] += 1

            if show_status == "no-show":
                no_shows += 1
                setter_noshows[setter]["no_shows"] += 1
            elif show_status == "cancelled":
                cancels += 1
                setter_noshows[setter]["cancels"] += 1

        # Loss reasons (for shows that didn't close)
        if show_status == "showed" and closer_outcome in ("lost",) and loss_reason:
            loss_counts[loss_reason] = loss_counts.get(loss_reason, 0) + 1

        # Refunds
        if refund_status and refund_status.lower() not in ("", "none", "n/a"):
            refund_count += 1
            if refund_amt and refund_amt > 0:
                refund_amount += refund_amt

        # Recoverable pipeline
        if setter_outcome == "WORKING ON":
            recoverable_working += 1
        if closer_outcome in ("follow-up", "pending"):
            recoverable_followup += 1

    # Rank DQ reasons
    dq_total = sum(dq_counts.values())
    dq_reasons = []
    for reason, count in sorted(dq_counts.items(), key=lambda x: -x[1]):
        dq_reasons.append({
            "reason": reason,
            "count": count,
            "pct": round(count / dq_total * 100, 1) if dq_total > 0 else 0.0,
        })

    # Loss reasons
    loss_total = sum(loss_counts.values())
    loss_reasons = []
    for reason, count in sorted(loss_counts.items(), key=lambda x: -x[1]):
        loss_reasons.append({
            "reason": reason,
            "count": count,
            "pct": round(count / loss_total * 100, 1) if loss_total > 0 else 0.0,
        })

    no_show_pct = round(no_shows / total_sets * 100, 1) if total_sets > 0 else 0.0
    cancel_pct = round(cancels / total_sets * 100, 1) if total_sets > 0 else 0.0

    # Per-setter no-show rates
    per_setter_noshow = []
    for name, sn in sorted(setter_noshows.items()):
        if sn["sets"] > 0:
            per_setter_noshow.append({
                "name": name,
                "sets": sn["sets"],
                "no_shows": sn["no_shows"],
                "cancels": sn["cancels"],
                "no_show_pct": round(sn["no_shows"] / sn["sets"] * 100, 1),
                "cancel_pct": round(sn["cancels"] / sn["sets"] * 100, 1),
            })

    result = {
        "dq_reasons": dq_reasons,
        "dq_total": dq_total,
        "loss_reasons": loss_reasons,
        "loss_reasons_note": "Currently unpopulated in sheet" if not loss_reasons else None,
        "no_show_pct": no_show_pct,
        "cancel_pct": cancel_pct,
        "no_shows": no_shows,
        "cancels": cancels,
        "total_sets": total_sets,
        "per_setter_noshow": per_setter_noshow,
        "refunds": {"count": refund_count, "amount": round(refund_amount, 2)},
        "refunds_note": "Currently unpopulated in sheet" if refund_count == 0 else None,
        "recoverable_pipeline": {
            "working_on": recoverable_working,
            "followup_pending": recoverable_followup,
            "total": recoverable_working + recoverable_followup,
            "note": "Still live — not lost",
        },
        "date_key": "Input Date (cohort window)",
    }

    return result, degraded


# ── LAYER 4: Money Behaviour ──────────────────────────────────────────────

def _layer_money_behaviour(
    ltc_rows: list[list[str]], cutoff: date, today: date,
) -> tuple[dict, list[dict]]:
    """Offer mix, payment type, collection gap, commission sanity — keyed on Close Date."""
    degraded: list[dict] = []

    offer_counts: dict[str, int] = {}
    payment_counts: dict[str, int] = {}
    contracts: list[float] = []
    cashes: list[float] = []
    total_setter_comm = 0.0
    total_closer_comm = 0.0
    total_cash = 0.0
    wins = 0

    for row in ltc_rows[1:]:
        closer_outcome = _cell(row, 23).strip().lower()
        if closer_outcome != "won":
            continue
        close_dt = _parse_date(_cell(row, 27))
        if not close_dt or close_dt < cutoff or close_dt > today:
            continue

        wins += 1
        offer = _cell(row, 26).strip() or "Unknown"
        payment = _cell(row, 29).strip() or "Unknown"
        contract = _parse_money(_cell(row, 28))
        cash = _parse_money(_cell(row, 32))
        setter_comm = _parse_money(_cell(row, 39))
        closer_comm = _parse_money(_cell(row, 40))

        offer_counts[offer] = offer_counts.get(offer, 0) + 1

        payment_counts[payment] = payment_counts.get(payment, 0) + 1

        if contract is not None and contract >= 0:
            contracts.append(contract)
        if cash is not None and cash >= 0:
            cashes.append(cash)
            total_cash += cash
        if setter_comm is not None and setter_comm >= 0:
            total_setter_comm += setter_comm
        if closer_comm is not None and closer_comm >= 0:
            total_closer_comm += closer_comm

    # Offer mix
    offer_mix = []
    for offer, count in sorted(offer_counts.items(), key=lambda x: -x[1]):
        offer_mix.append({
            "offer": offer,
            "count": count,
            "pct": round(count / wins * 100, 1) if wins > 0 else 0.0,
        })

    # Custom share flag
    custom_count = offer_counts.get("Custom", 0)
    custom_share_pct = round(custom_count / wins * 100, 1) if wins > 0 else 0.0

    # Payment split
    payment_split = []
    for ptype, count in sorted(payment_counts.items(), key=lambda x: -x[1]):
        payment_split.append({
            "type": ptype,
            "count": count,
            "pct": round(count / wins * 100, 1) if wins > 0 else 0.0,
        })

    avg_contract = round(sum(contracts) / len(contracts), 2) if contracts else None
    avg_cash = round(sum(cashes) / len(cashes), 2) if cashes else None

    # Commission as % of cash
    total_comm = round(total_setter_comm + total_closer_comm, 2)
    commission_pct = round(total_comm / total_cash * 100, 1) if total_cash > 0 else None

    result = {
        "wins_in_window": wins,
        "offer_mix": offer_mix,
        "custom_share_pct": custom_share_pct,
        "payment_split": payment_split,
        "avg_contract": avg_contract,
        "avg_cash": avg_cash,
        "total_commission": total_comm,
        "commission_pct_of_cash": commission_pct,
        "date_key": "Close Date (money window)",
    }

    # Range checks
    if commission_pct is not None and commission_pct > 30:
        degraded.append({
            "metric": "commission_pct",
            "reason": f"Commission {commission_pct}% of cash — unusually high, verify",
        })
    if avg_contract is not None and avg_cash is not None and avg_cash > avg_contract:
        degraded.append({
            "metric": "collection_gap",
            "reason": f"Avg cash ${avg_cash:,.2f} > avg contract ${avg_contract:,.2f} — data issue",
        })

    return result, degraded


# ── Leak Flags ─────────────────────────────────────────────────────────────

# Targets: adjust these as the business evolves
_TARGETS = {
    "lead_to_set_pct": 25.0,
    "set_to_show_pct": 70.0,
    "show_to_close_pct": 35.0,
    "speed_to_lead_5min_pct": 50.0,
    "custom_share_max_pct": 20.0,
    "commission_max_pct": 25.0,
    "no_show_max_pct": 15.0,
}


def _build_leak_flags(
    funnel: dict | None,
    setter_perf: list[dict],
    lead_quality: dict,
    loss: dict,
    money: dict,
) -> list[str]:
    """Surface the handful of metrics that are off-target, ordered by severity."""
    flags: list[str] = []

    # Funnel conversion targets
    if funnel:
        s2sh = funnel.get("set_to_show_pct")
        if s2sh is not None and s2sh < _TARGETS["set_to_show_pct"]:
            flags.append(f"Set→Show {s2sh}% vs target {_TARGETS['set_to_show_pct']}% — show-up leak")

        sh2c = funnel.get("show_to_close_pct")
        if sh2c is not None and sh2c < _TARGETS["show_to_close_pct"]:
            flags.append(f"Show→Close {sh2c}% vs target {_TARGETS['show_to_close_pct']}% — closing leak")

        l2s = funnel.get("lead_to_set_pct")
        if l2s is not None and l2s < _TARGETS["lead_to_set_pct"]:
            flags.append(f"Lead→Set {l2s}% vs target {_TARGETS['lead_to_set_pct']}% — setting leak")

    # Speed-to-lead
    for sp in setter_perf:
        if sp.get("speed_to_lead_pct") is not None and sp["speed_to_lead_pct"] < _TARGETS["speed_to_lead_5min_pct"]:
            flags.append(
                f"{sp['name']} speed-to-lead {sp['speed_to_lead_pct']}% vs target "
                f"{_TARGETS['speed_to_lead_5min_pct']}%"
            )

    # No-show rate
    ns = loss.get("no_show_pct", 0)
    if ns > _TARGETS["no_show_max_pct"]:
        flags.append(f"No-show rate {ns}% vs max {_TARGETS['no_show_max_pct']}%")

    # Revenue range wasted leads
    for rng in lead_quality.get("by_revenue_range", []):
        if rng.get("targeting_flag"):
            flags.append(f"{rng['range']}: {rng['targeting_flag']}")

    # Custom offer share
    cs = money.get("custom_share_pct", 0)
    if cs > _TARGETS["custom_share_max_pct"]:
        flags.append(
            f"Custom offers = {cs}% of wins — commission leak "
            f"(target <{_TARGETS['custom_share_max_pct']}%)"
        )

    # Commission % of cash
    cp = money.get("commission_pct_of_cash")
    if cp is not None and cp > _TARGETS["commission_max_pct"]:
        flags.append(f"Commission {cp}% of cash vs max {_TARGETS['commission_max_pct']}%")

    return flags


# ── Multi-window analysis ──────────────────────────────────────────────────

_WINDOWS = [7, 14, 30, 60, 90]


def _compute_window_metrics(
    ltc_rows: list[list[str]], today: date, window_days: int,
) -> dict:
    """Compute funnel + money metrics for a specific trailing window."""
    cutoff = today - timedelta(days=window_days)

    leads = 0
    sets = 0
    shows = 0
    closes = 0
    dqs = 0
    contracts: list[float] = []
    cashes: list[float] = []
    setter_comms = 0.0
    closer_comms = 0.0
    deltas: list[int] = []

    for row in ltc_rows[1:]:
        input_dt = _parse_date(_cell(row, 1))
        if not input_dt or input_dt < cutoff or input_dt > today:
            continue

        leads += 1
        setter_outcome = _cell(row, 16).strip().upper()
        show_status = _cell(row, 22).strip().lower()
        closer_outcome = _cell(row, 23).strip().lower()

        if setter_outcome == "SET":
            sets += 1
        if setter_outcome == "DQ":
            dqs += 1
        if show_status in ("showed", "show"):
            shows += 1
        if closer_outcome == "won":
            closes += 1
            contract = _parse_money(_cell(row, 28))
            cash = _parse_money(_cell(row, 32))
            if contract and contract > 0:
                contracts.append(contract)
            if cash and cash > 0:
                cashes.append(cash)
            sc = _parse_money(_cell(row, 39))
            cc = _parse_money(_cell(row, 40))
            if sc and sc > 0:
                setter_comms += sc
            if cc and cc > 0:
                closer_comms += cc
            close_dt = _parse_date(_cell(row, 27))
            if close_dt and input_dt:
                d = (close_dt - input_dt).days
                if d >= 0:
                    deltas.append(d)

    lead_to_set = round(sets / leads * 100, 1) if leads > 0 else None
    set_to_show = round(shows / sets * 100, 1) if sets > 0 else None
    show_to_close = round(closes / shows * 100, 1) if shows > 0 else None
    lead_to_close = round(closes / leads * 100, 1) if leads > 0 else None
    avg_contract = round(sum(contracts) / len(contracts), 2) if contracts else None
    avg_cash = round(sum(cashes) / len(cashes), 2) if cashes else None
    total_cash = round(sum(cashes), 2)
    total_commission = round(setter_comms + closer_comms, 2)
    commission_pct = round(total_commission / total_cash * 100, 1) if total_cash > 0 else None
    median_days = statistics.median(deltas) if deltas else None
    dq_rate = round(dqs / leads * 100, 1) if leads > 0 else None

    return {
        "window_days": window_days,
        "window_start": str(cutoff),
        "leads": leads,
        "sets": sets,
        "shows": shows,
        "closes": closes,
        "dqs": dqs,
        "lead_to_set_pct": lead_to_set,
        "set_to_show_pct": set_to_show,
        "show_to_close_pct": show_to_close,
        "lead_to_close_pct": lead_to_close,
        "dq_rate_pct": dq_rate,
        "avg_contract": avg_contract,
        "avg_cash": avg_cash,
        "total_cash": total_cash,
        "total_commission": total_commission,
        "commission_pct": commission_pct,
        "median_days_to_close": median_days,
    }


def _compute_multi_window(ltc_rows: list[list[str]], today: date) -> list[dict]:
    """Compute metrics across all standard windows."""
    return [_compute_window_metrics(ltc_rows, today, w) for w in _WINDOWS]


# ── Main pull ──────────────────────────────────────────────────────────────

def pull_sales_analytics() -> dict:
    """
    Pull funnel, throughput, velocity, and payout analytics.
    Returns dict ready to merge into snapshot under 'sales' key.
    """
    degraded = []
    today = today_sydney()
    cutoff = today - timedelta(days=30)

    # Fetch tabs in sequence (they're lightweight CSV reads)
    sc_rows = _fetch_tab("Team Scorecard")
    ltc_rows = _fetch_tab(SHEET_CONFIG["tab_name"])

    if not sc_rows:
        degraded.append({"metric": "sales_scorecard", "reason": "Failed to fetch Team Scorecard tab"})
    if not ltc_rows:
        degraded.append({"metric": "sales_tracker", "reason": "Failed to fetch Lead-to-Cash Tracker tab"})

    if not sc_rows and not ltc_rows:
        return {"sales": None, "degraded": degraded}

    # Funnel (from Scorecard)
    funnel = _pull_funnel(sc_rows) if sc_rows else None

    # Per-setter / per-closer (from Scorecard)
    per_setter = _pull_per_setter(sc_rows) if sc_rows else None
    per_closer = _pull_per_closer(sc_rows) if sc_rows else None
    setter_activity = _pull_setter_activity(sc_rows) if sc_rows else None

    # Speed-to-lead (from Scorecard)
    speed = _pull_speed_to_lead(sc_rows) if sc_rows else None

    # Setter payout (from Scorecard + Payout Log)
    payout_scorecard = _pull_setter_payout(sc_rows) if sc_rows else None
    payout_log = _pull_payout_log_footer()

    payout = None
    if payout_scorecard:
        payout = {
            **payout_scorecard,
            "payout_log": payout_log,
        }
        # Cross-check: scorecard total vs payout log total
        sc_owed = payout_scorecard.get("total_owed")
        log_owed = payout_log.get("total_owed")
        if sc_owed is not None and log_owed is not None:
            # They measure different things: scorecard = $50/set, log = $50+5% per won deal
            # Just surface both, flag if wildly different
            payout["note"] = "Scorecard=$50/qualified-set; Payout Log=$50+5%/won-deal — different formulas"

    # Velocity (from raw Lead-to-Cash rows)
    velocity = None
    if ltc_rows:
        velocity = _pull_velocity(ltc_rows, cutoff)
        if speed:
            velocity["speed_to_lead_5min_pct"] = speed.get("five_min_rate_pct")
            velocity["calls_within_5_min"] = speed.get("calls_within_5_min")
            velocity["total_dials"] = speed.get("total_dials")

    # Setter Deep-Dive
    deep_dive = _pull_deep_dive()

    # Cross-check funnel
    validation = {}
    if funnel and ltc_rows:
        validation = _cross_check_funnel(ltc_rows, funnel, cutoff, today)
        if not validation.get("scorecard_match"):
            degraded.append({
                "metric": "funnel_cross_check",
                "reason": f"Funnel mismatch: {validation.get('mismatches', [])}",
            })

    # ── Deep analytics (all four layers) ──────────────────────────────────
    deep = None
    if ltc_rows:
        # Layer 1: Setter Performance
        setter_perf, sp_deg = _layer_setter_performance(
            ltc_rows, cutoff, today, per_setter, setter_activity,
        )
        degraded.extend(sp_deg)

        # Layer 2: Lead Quality
        lead_quality, lq_deg = _layer_lead_quality(ltc_rows, cutoff, today)
        degraded.extend(lq_deg)

        # Layer 3: Loss Intelligence
        loss, loss_deg = _layer_loss_intelligence(ltc_rows, cutoff, today)
        degraded.extend(loss_deg)

        # Layer 4: Money Behaviour
        money, money_deg = _layer_money_behaviour(ltc_rows, cutoff, today)
        degraded.extend(money_deg)

        # Leak flags — surfaced FIRST
        leak_flags = _build_leak_flags(funnel, setter_perf, lead_quality, loss, money)

        deep = {
            "leak_flags": leak_flags,
            "setter_performance": setter_perf,
            "lead_quality": lead_quality,
            "loss": loss,
            "money": money,
        }

    # ── Multi-window analysis ───────────────────────────────────────────
    windows = _compute_multi_window(ltc_rows, today) if ltc_rows else []

    # ── Extract won businesses for reconciliation ────────────────────────
    won_businesses = []
    if ltc_rows:
        for row in ltc_rows[1:]:
            outcome = _cell(row, 23).strip().lower()
            if outcome != "won":
                continue
            biz = _cell(row, 7).strip()
            close_dt = _parse_date(_cell(row, 27))
            offer = _cell(row, 26).strip()
            contract = _parse_money(_cell(row, 28))
            if biz:  # only include if business name is populated
                won_businesses.append({
                    "name": biz,
                    "close_date": str(close_dt) if close_dt else None,
                    "offer": offer,
                    "contract_value": contract,
                })

    sales = {
        "window_days": 30,
        "window_start": str(cutoff),
        "window_end": str(today),
        "funnel": funnel,
        "per_setter": per_setter,
        "per_closer": per_closer,
        "setter_activity": setter_activity,
        "setter_deep_dive": deep_dive,
        "velocity": velocity,
        "payout": payout,
        "validation": validation,
        "deep": deep,
        "windows": windows,
        "won_businesses": won_businesses,
    }

    return {"sales": sales, "degraded": degraded}
