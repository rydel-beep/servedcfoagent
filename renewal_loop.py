"""
renewal_loop.py — THE RENEWAL & CHURN TRUTH LOOP (DECISIONS #135).

THE RULED BOUNDARY: EDITH NEVER WRITES THE MRR CONTRACT SHEET. One writer per
surface — the owner declares on the dashboard; Piolo maintains the sheet; this
module's whole job is CONVERGENCE WITH RECEIPTS. The boundary is architectural
(two writers on one document turns every disagreement into a clobber-war), not
a missing feature; it holds even if a Sheets write capability ever appears.

Three legs, one loop:
  SCAN — pull the Health tab (the MRR contract sheet) FRESH, hash it, diff it
    against the last scan, and reconcile against dashboard declarations.
    Verdict lanes: CONVERGED (sheet now matches a pending declaration → the
    override marks reconciled, journaled, its Piolo feed item self-retires) ·
    SHEET-ORIGINATED (sheet changed with no declaration → labelled with the
    "source: sheet" chip, journaled — Piolo editing first is equally
    legitimate) · CONFLICT (declared ≠ sheet → LOUD lane, both values +
    provenance, Rydel resolves — never silently reconciled) · UNLINKED
    (sheet rows matching no known client / clients missing from the sheet).
  DECLARE — extends client_overrides (the existing confirmation-gated
    write-back): adds the RENEWED declaration kind; the dashboard routes call
    into it. Declarations are owner-only, journaled, reversible.
  CONVERGE — pending declarations surface as Piolo-queue items (action-feed →
    collab.queue) carrying the EXACT sheet edit; the next scan that finds the
    sheet matching auto-clears them.

SCHEMA-DRIFT GUARD: parsing is HEADER-ANCHORED with a checksum — a moved or
renamed column fails LOUD ("sheet layout changed — column X not found"), zero
rows are read. Humans edit sheets; columns WILL move.

Read-only against Google. Freshness = content hash + scan stamps (no Drive
metadata scope exists — stated, not faked). All dates today_sydney discipline.
"""
from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

_KV_LAST_SCAN = "renewal:last_scan"       # {at, content_hash, header_checksum, rows}
_KV_JOURNAL = "renewal:journal"           # capped — same entry schema as the ads journal
_KV_SCHEMA_TRIP = "renewal:schema_drift"  # set while the layout is broken; cleared on a clean parse
_JOURNAL_CAP = 500

# The header anchors — the REAL names probed live 2026-08-10 (D1). Order-free:
# each is located by exact (case/space-insensitive) match in the header row.
EXPECTED_HEADERS = ("Client Name", "Status", "Package Type", "Service Term",
                    "Start Date", "End Date", "Contract Value", "Monthly Recognized Revenue")

SCAN_STALE_DAYS = 7        # sentinel: no scan in >7d → feed nudge
PENDING_AGE_DAYS = 5       # sentinel: a declaration unconverged >5d → hygiene item


def _norm(name: str) -> str:
    """SAME normal form as client_overrides — one linkage key, not a third."""
    import client_overrides
    return client_overrides._norm(name)


def journal(rule: str, detail: str) -> None:
    """The loop's journal — same entry schema as the resolution journal
    ({rule, detail, ts}), its own stream (finance domain)."""
    try:
        import kv_store
        from helpers import today_sydney
        j = kv_store.get(_KV_JOURNAL) or []
        j.append({"rule": rule, "detail": detail[:200], "ts": str(today_sydney())})
        kv_store.put(_KV_JOURNAL, j[-_JOURNAL_CAP:])
    except Exception as e:
        logger.info("renewal journal failed: %s", e)


def journal_entries() -> list[dict]:
    import kv_store
    return kv_store.get(_KV_JOURNAL) or []


# ── the sheet pull (LIVE, bytes-hashed — never a stale verdict) ──────────────

def _fetch_sheet_bytes() -> bytes | None:
    """The Health tab CSV, LIVE (the scan's whole point is freshness — the
    mirror is bypassed here). None = unreachable (callers render DEGRADED)."""
    import requests
    from config import FINANCE_SHEET_CONFIG, HTTP_TIMEOUT
    from finance_sheets_pull import _HEALTH_TAB_GID
    sid = FINANCE_SHEET_CONFIG["sheet_id"]
    url = (f"https://docs.google.com/spreadsheets/d/{sid}"
           f"/export?format=csv&gid={_HEALTH_TAB_GID}")
    try:
        r = requests.get(url, timeout=(5, HTTP_TIMEOUT))
        if r.status_code != 200:
            logger.warning("renewal scan: sheet fetch status %s", r.status_code)
            return None
        return r.content
    except requests.RequestException as e:
        logger.warning("renewal scan: sheet fetch failed: %s", e)
        return None


def _header_key(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def parse_sheet(raw: bytes) -> tuple[dict | None, str | None]:
    """Header-anchored parse. Returns ({norm: row}, None) or (None, loud_error).
    Every value kept as displayed (strings + parsed money/dates) — the scan
    reports the sheet AS IT IS; interpretation stays in the one engine."""
    import csv
    import io
    from finance_sheets_pull import _parse_money
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8", errors="replace"))))
    except Exception as e:
        return None, f"sheet unparseable as CSV: {e}"
    if not rows:
        return None, "sheet is empty"
    header = rows[0]
    hmap = {_header_key(h): i for i, h in enumerate(header) if (h or "").strip()}
    cols = {}
    for want in EXPECTED_HEADERS:
        i = hmap.get(_header_key(want))
        if i is None:
            return None, (f"sheet layout changed — column '{want}' not found in the "
                          f"header row (columns move when humans edit; refusing to "
                          f"misread rows)")
        cols[want] = i
    out = {}
    for ridx, row in enumerate(rows[1:], start=2):   # 1-based sheet rows, +header
        def cell(w):
            i = cols[w]
            return row[i].strip() if i < len(row) else ""
        name = cell("Client Name")
        if not name or name.upper().startswith("TOTAL"):
            continue
        out[_norm(name)] = {
            "name": name, "sheet_row": ridx,
            "status": cell("Status"),
            "package": cell("Package Type"),
            "term": cell("Service Term"),
            "start": cell("Start Date"),
            "end": cell("End Date"),
            "contract_value": _parse_money(cell("Contract Value")),
            "monthly_recognized": _parse_money(cell("Monthly Recognized Revenue")),
        }
    checksum = hashlib.sha1(
        "|".join(_header_key(h) for h in header if (h or "").strip()).encode()
    ).hexdigest()[:12]
    return {"rows": out, "header_checksum": checksum}, None


# ── declaration semantics (what "the sheet reflects it" means, per kind) ─────

def _sheet_reflects(ov: dict, srow: dict | None) -> tuple[bool, str | None]:
    """(converged?, conflict_detail). A conflict = the sheet CHANGED on the
    declared field but to a DIFFERENT value than declared — surfaced, never
    merged. A missing row after a churn declaration counts as converged
    (Piolo removes churned rows sometimes — the client is gone either way)."""
    from finance_sheets_pull import _parse_date_mmddyyyy
    kind = ov["change_type"]
    old_end = str(ov.get("old_end") or "")   # the sheet's End Date AT declare time
    if kind == "churn":
        if srow is None or (srow.get("status") or "").strip().lower() not in ("active", ""):
            return True, None
        # still Active AND the end date MOVED since the declaration → the sheet
        # is telling a different story (e.g. Piolo renewed them) — loud conflict
        sheet_end = _parse_date_mmddyyyy(srow.get("end") or "")
        if sheet_end and old_end and str(sheet_end) != old_end:
            return False, (f"declared CHURN (effective {ov.get('effective_date')}) but "
                           f"the sheet moved End Date {old_end} → {sheet_end} and kept "
                           f"Active — two different truths")
        return False, None
    if srow is None:
        return False, f"declared {kind} but the sheet row is GONE — verify with Piolo"
    if kind == "renewal":
        declared = str(ov.get("effective_date") or "")
        sheet_end = _parse_date_mmddyyyy(srow.get("end") or "")
        if sheet_end and str(sheet_end) == declared:
            if ov.get("new_mrr") is not None:
                smrr = srow.get("monthly_recognized")
                if smrr is None or abs(smrr - float(ov["new_mrr"])) > 0.01:
                    return False, (f"sheet End Date matches the renewal ({declared}) but "
                                   f"Monthly Recognized is {smrr} vs declared "
                                   f"${float(ov['new_mrr']):,.0f}")
            return True, None
        # end date changed to something ELSE than declared → loud conflict
        if sheet_end and old_end and str(sheet_end) != old_end \
                and str(sheet_end) != declared:
            return False, (f"declared renewal to {declared} but the sheet End Date "
                           f"moved to {sheet_end} — two different truths")
        return False, None
    if kind == "downgrade":
        smrr = srow.get("monthly_recognized")
        if smrr is not None and ov.get("new_mrr") is not None \
                and abs(smrr - float(ov["new_mrr"])) <= 0.01:
            return True, None
        return False, None
    return False, None


def piolo_edit_text(ov: dict) -> str:
    """The EXACT sheet edit a pending declaration needs — what the queue item says."""
    nm = ov["client_name"]
    if ov["change_type"] == "churn":
        return (f"MRR contract sheet (Health tab), row '{nm}': set Status=Finished, "
                f"End Date={ov.get('effective_date')} — declared churn"
                + (f" ({ov.get('reason')})" if ov.get("reason") else ""))
    if ov["change_type"] == "renewal":
        base = (f"MRR contract sheet (Health tab), row '{nm}': set End Date="
                f"{ov.get('effective_date')} (renewal)")
        if ov.get("new_mrr") is not None:
            base += f", Monthly Recognized=${float(ov['new_mrr']):,.0f}"
        return base
    return (f"MRR contract sheet (Health tab), row '{nm}': set Monthly Recognized="
            f"${float(ov.get('new_mrr') or 0):,.0f} (downgrade), keep Active")


# ── THE SCAN ─────────────────────────────────────────────────────────────────

_WATCH_FIELDS = ("status", "end", "start", "monthly_recognized", "contract_value")


def scan(trigger: str = "manual", actor: str = "rydel") -> dict:
    """Pull fresh → diff vs last scan → reconcile declarations → verdict lanes.
    Idempotent: an unchanged sheet is a clean no-op verdict. Journaled."""
    import kv_store
    from helpers import now_sydney
    raw = _fetch_sheet_bytes()
    if raw is None:
        return {"ok": False,
                "degraded": [{"metric": "renewal_scan",
                              "reason": "MRR contract sheet unreachable — NO verdict "
                                        "(a stale verdict labelled fresh is a lie)"}]}
    parsed, err = parse_sheet(raw)
    if err:
        kv_store.put(_KV_SCHEMA_TRIP, {"at": now_sydney().isoformat()[:16], "error": err})
        journal("scan schema-drift", err)
        return {"ok": False, "schema_drift": err,
                "degraded": [{"metric": "renewal_scan", "reason": err}]}
    kv_store.delete(_KV_SCHEMA_TRIP)
    content_hash = hashlib.sha256(raw).hexdigest()[:16]
    last = kv_store.get(_KV_LAST_SCAN) or {}
    prev_rows = last.get("rows") or {}
    changed = bool(last) and last.get("content_hash") != content_hash

    # per-client diffs vs the last scan
    diffs = []
    cur_rows = parsed["rows"]
    if last:
        for nm, cur in cur_rows.items():
            old = prev_rows.get(nm)
            if old is None:
                diffs.append({"client": cur["name"], "kind": "row_added"})
                continue
            for f in _WATCH_FIELDS:
                if (old.get(f) or None) != (cur.get(f) or None):
                    diffs.append({"client": cur["name"], "kind": "field_changed",
                                  "field": f, "old": old.get(f), "new": cur.get(f)})
        for nm, old in prev_rows.items():
            if nm not in cur_rows:
                diffs.append({"client": old.get("name") or nm, "kind": "row_removed"})

    # reconcile declarations (the convergence leg)
    import client_overrides
    converged, pending, conflicts = [], [], []
    for ov in client_overrides.active_overrides():
        srow = cur_rows.get(_norm(ov["client_name"]))
        ok, conflict = _sheet_reflects(ov, srow)
        if ok:
            if not client_overrides.mark_reconciled(ov["id"]):
                pending.append({**_pend_view(ov), "note": "sheet matches but the "
                                                          "reconcile write failed — retry"})
                continue
            converged.append({"client": ov["client_name"], "kind": ov["change_type"],
                              "declared": ov.get("effective_date"),
                              "verdict": "CONVERGED — sheet now matches the declaration; "
                                         "Piolo item auto-cleared"})
            journal("scan converged",
                    f"{ov['client_name']}: {ov['change_type']} declaration now reflected "
                    f"in the sheet — Piolo item cleared (scan by {actor}, {trigger})")
        elif conflict:
            conflicts.append({"client": ov["client_name"], "kind": ov["change_type"],
                              "declared": {"date": str(ov.get("effective_date") or ""),
                                           "mrr": ov.get("new_mrr"),
                                           "source": "owner declaration "
                                                     f"({str(ov.get('created_at') or '')[:10]})"},
                              "sheet": {"status": (srow or {}).get("status"),
                                        "end": (srow or {}).get("end"),
                                        "mrr": (srow or {}).get("monthly_recognized"),
                                        "source": "sheet (Piolo)"},
                              "detail": conflict})
            journal("scan CONFLICT", f"{ov['client_name']}: {conflict}")
        else:
            pending.append(_pend_view(ov))

    # sheet-originated changes: diffs on clients with NO active declaration
    declared_norms = {_norm(o["client_name"]) for o in client_overrides.active_overrides()}
    sheet_originated = []
    for d in diffs:
        if d["kind"] == "field_changed" and _norm(d["client"]) not in declared_norms \
                and d["field"] in ("status", "end", "monthly_recognized"):
            sheet_originated.append({**d, "source": "sheet",
                                     "note": "sheet-originated (Piolo edited first) — "
                                             "ingested via the one engine, chip: source:sheet"})
            journal("scan sheet-originated",
                    f"{d['client']}: {d['field']} {d.get('old')} → {d.get('new')} "
                    f"(sheet-first change, no declaration)")

    # unlinked (D2 remainder) — surfaced, never swallowed
    roster_norms, roster_names = _roster_norms()
    unlinked_sheet = [r["name"] for nm, r in cur_rows.items()
                      if (r.get("status") or "").strip() == "Active"
                      and nm not in roster_norms]
    unlinked_clients = [n for n in roster_names if _norm(n) not in cur_rows]

    stamp = now_sydney().isoformat()[:16]
    kv_store.put(_KV_LAST_SCAN, {"at": stamp, "content_hash": content_hash,
                                 "header_checksum": parsed["header_checksum"],
                                 "rows": cur_rows})
    journal("scan", f"by {actor} ({trigger}): {'CHANGED' if changed else 'no change'}"
                    f"{' (first scan — baseline recorded)' if not last else ''} · "
                    f"{len(diffs)} diff(s) · {len(converged)} converged · "
                    f"{len(conflicts)} CONFLICT(s) · {len(pending)} pending")
    return {
        "ok": True,
        "freshness": {"scanned_at": stamp, "content_hash": content_hash,
                      "changed_since_last_scan": changed if last else None,
                      "previous_scan_at": last.get("at"),
                      "first_scan": not bool(last),
                      "method": "content-hash (no Drive metadata scope — stated, "
                                "not faked)"},
        "verdict": ("first scan — baseline recorded" if not last else
                    "sheet CHANGED since last scan" if changed else
                    "no changes since last scan — clean"),
        "diffs": diffs,
        "converged": converged, "pending": pending, "conflicts": conflicts,
        "sheet_originated": sheet_originated,
        "unlinked": {"sheet_rows_without_client": unlinked_sheet,
                     "clients_without_sheet_row": unlinked_clients},
        "degraded": [],
    }


def _pend_view(ov: dict) -> dict:
    from helpers import today_sydney
    import datetime as dt
    age = None
    try:
        age = (today_sydney() - dt.date.fromisoformat(str(ov["created_at"])[:10])).days
    except Exception:
        pass
    return {"client": ov["client_name"], "kind": ov["change_type"],
            "declared": str(ov.get("effective_date") or ""),
            "age_days": age, "edit": piolo_edit_text(ov),
            "chip": "declared · pending sheet"}


def _roster_norms() -> tuple[set, list]:
    try:
        from snapshot import load_persisted
        clients = ((load_persisted() or {}).get("client_health") or {}).get("clients") or []
        names = [c.get("name", "") for c in clients if c.get("name")]
        return {_norm(n) for n in names}, names
    except Exception:
        return set(), []


def last_scan_meta() -> dict:
    import kv_store
    last = kv_store.get(_KV_LAST_SCAN) or {}
    return {"at": last.get("at"), "content_hash": last.get("content_hash"),
            "schema_drift": kv_store.get(_KV_SCHEMA_TRIP)}


# ── Piolo-queue feed items (the EXISTING queue, via the action feed) ─────────

def feed_items() -> list[dict]:
    """Pending-sheet declarations + conflicts as action-feed items.
    category=data_quality → they land in collab.queue (Piolo's queue) with the
    resolve/verify overlay; convergence retires them by NOT generating them
    (A5 self-retiring). Conflicts are S2 — the loud lane."""
    items = []
    try:
        import client_overrides
        for ov in client_overrides.active_overrides():
            pv = _pend_view(ov)
            age = f" — pending {pv['age_days']}d" if (pv.get("age_days") or 0) >= 1 else ""
            items.append({
                "severity": "S2" if (pv.get("age_days") or 0) > PENDING_AGE_DAYS else "S3",
                "category": "data_quality",
                "title": f"Sheet edit needed: {ov['client_name']} "
                         f"({ov['change_type']} declared){age}",
                "action": pv["edit"] + " — the dashboard already reflects it; "
                                       "the next scan auto-clears this once the sheet matches",
            })
    except Exception as e:
        logger.info("renewal feed items failed: %s", e)
    try:
        import kv_store
        trip = kv_store.get(_KV_SCHEMA_TRIP)
        if trip:
            items.append({"severity": "S1", "category": "data_quality",
                          "title": "MRR sheet layout changed — renewal scan REFUSING to read",
                          "action": f"{trip.get('error')} (tripped {trip.get('at')}) — "
                                    f"restore the column or tell EDITH the new layout"})
    except Exception:
        pass
    return items


# ── sentinel watches (ride ad_sentinel.nightly_extras — the L2 leg) ──────────

def sentinel_watch() -> dict:
    """Scan staleness · pending-sheet ageing · conflict presence · schema trip.
    Returns the watch block; LOUD findings go to the feed channel."""
    import datetime as dt
    import kv_store
    from helpers import today_sydney
    out = {"scan_stale": False, "pending_aged": [], "conflicts": 0,
           "schema_drift": bool(kv_store.get(_KV_SCHEMA_TRIP))}
    last = kv_store.get(_KV_LAST_SCAN) or {}
    if last.get("at"):
        try:
            age = (today_sydney() - dt.date.fromisoformat(last["at"][:10])).days
            out["last_scan_age_days"] = age
            out["scan_stale"] = age > SCAN_STALE_DAYS
        except Exception:
            pass
    else:
        out["scan_stale"] = True
        out["last_scan_age_days"] = None
    try:
        import client_overrides
        for ov in client_overrides.active_overrides():
            pv = _pend_view(ov)
            if (pv.get("age_days") or 0) > PENDING_AGE_DAYS:
                out["pending_aged"].append({"client": ov["client_name"],
                                            "age_days": pv["age_days"]})
    except Exception:
        pass
    _flag = None
    try:
        import kv_store as _kv
        flags = _kv.get("ads_truth:flags") or []
        if out["scan_stale"]:
            flags.append({"metric": "ads_truth",
                          "reason": f"renewal loop: no sheet scan in "
                                    f"{out.get('last_scan_age_days')}d (>7d) — scan it"})
        for p in out["pending_aged"]:
            flags.append({"metric": "ads_truth",
                          "reason": f"renewal loop: {p['client']}'s declaration is "
                                    f"{p['age_days']}d unconverged — Piolo's sheet edit "
                                    f"is outstanding"})
        if out["schema_drift"]:
            flags.append({"metric": "ads_truth_action",
                          "reason": "renewal loop: SHEET LAYOUT CHANGED — scans refusing "
                                    "to read until the columns are restored"})
        _kv.put("ads_truth:flags", flags[-60:])
    except Exception:
        pass
    return out


def nightly_scan() -> dict:
    """The cheap nightly leg (pull + diff); the button stays for on-demand.
    Conflicts found here go LOUD via the feed channel."""
    try:
        result = scan(trigger="nightly", actor="sentinel")
        if result.get("ok") and result.get("conflicts"):
            import kv_store
            flags = kv_store.get("ads_truth:flags") or []
            for cf in result["conflicts"]:
                flags.append({"metric": "ads_truth_action",
                              "reason": f"renewal CONFLICT: {cf['client']} — "
                                        f"{cf['detail'][:120]} (Rydel resolves; never "
                                        f"silently merged)"})
            kv_store.put("ads_truth:flags", flags[-60:])
        return result
    except Exception as e:
        logger.warning("nightly renewal scan failed: %s", e)
        return {"ok": False, "error": str(e)[:120]}
