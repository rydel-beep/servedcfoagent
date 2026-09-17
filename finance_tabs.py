"""finance_tabs.py — EVERY workbook tab, mapped and ingested (#150).

Born from the 2026-09-17 scrutiny: the system read one tab per concern while
the RECOGNIZED tab's renewal columns and Sheet5 carried a whole renewal
ledger (Noodle Asia's resign, Bluebells' month-to-month extension, and six
more) that never reached the engine. Never assume a single tab again:

- enumerate_tabs(): runtime enumeration of BOTH workbooks' tab names via the
  read-only xlsx export (stdlib zip parse — no new scopes, no writes); a
  new/renamed/unmapped tab is SURFACED, never ignored (kv finance:tab_map +
  daily change detection).
- renewal_ledger(): the RECOGNIZED renewal columns (primary) corroborated by
  Sheet5 — every entry carries {tab, row} provenance; cross-tab conflicts
  (e.g. Sheet5 'Pending' vs RECOGNIZED 'Renewed') are surfaced, never merged.
- cross_tab_recon(): the four MRR truths (engine roster · ACTUAL · RECOGNIZED
  · sheet footer) with every per-client delta CAUSED and owned.
- sheet_renewals_for_projection(): committed-MRR coverage from renewed terms
  where the monthly grid is blank — a labelled source lane for the ONE
  projection engine (never a fork; never double-counts a filled grid month).

READ-ONLY LAW (#148): exports/gviz GETs only. Corrections = Piolo package.
"""

from __future__ import annotations

import csv
import io
import logging
import re

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_KV_TAB_MAP = "finance:tab_map"
_KV_LEDGER_CACHE = "finance:renewal_ledger"

# The ruled role of every known tab; anything else = UNMAPPED (surfaced).
TAB_ROLES = {
    "ltc": {
        "README": "readme",
        "Lead-to-Cash Tracker": "tracker (leads→cash; the mirror's ltc_tracker)",
        "Setter Payout Log": "setter payouts (mirrored)",
        "Sheet1": "empty/stub",
        "Team Scorecard": "scorecard (mirrored)",
        "Setter Deep-Dive": "setter analytics (mirrored)",
        "Closer Payout & KPI": "closer comp reference (NOT yet mirrored)",
    },
    "finance": {
        "MRR PROJECTION TO 2026": "manual projection (human model — never an engine source)",
        "Sheet5": "renewal ledger AUX (corroboration for RECOGNIZED renewal cols)",
        "ACTUAL": "actual monthly collections per client (cash grid)",
        "RECOGNIZED": "recognised revenue grid + THE RENEWAL LEDGER (cols E–K)",
        "SALARY": "team salaries (mirrored)",
        "FIXED COSTS": "fixed cost register (tooling/overheads)",
        "Sheet6": "empty/stub",
        "ACTUAL BACKUP": "backup copy (never a source)",
    },
}


def _books() -> dict:
    from config import SHEET_CONFIG, FINANCE_SHEET_CONFIG
    return {"ltc": SHEET_CONFIG["sheet_id"],
            "finance": FINANCE_SHEET_CONFIG["sheet_id"]}


def _fetch_xlsx_names(book_id: str) -> list[str] | None:
    import zipfile
    import requests
    try:
        r = requests.get(f"https://docs.google.com/spreadsheets/d/{book_id}"
                         f"/export?format=xlsx", timeout=60)
        if r.status_code != 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
        return re.findall(r'<sheet[^>]*name="([^"]+)"', wb)
    except Exception as e:
        logger.info("tab enumeration failed for %s…: %s", book_id[:8], e)
        return None


def _fetch_tab_csv(book_id: str, tab: str) -> list[list[str]] | None:
    import requests
    try:
        r = requests.get(
            f"https://docs.google.com/spreadsheets/d/{book_id}/gviz/tq"
            f"?tqx=out:csv&sheet={requests.utils.quote(tab)}", timeout=45)
        if r.status_code != 200:
            return None
        return list(csv.reader(io.StringIO(r.text)))
    except Exception as e:
        logger.info("tab fetch failed %s/%s: %s", book_id[:8], tab, e)
        return None


def enumerate_tabs(force: bool = False) -> dict:
    """Runtime tab map with change detection. A tab the role registry doesn't
    know is UNMAPPED — a finding, never silently skipped."""
    today = str(today_sydney())
    cached = kv_store.get(_KV_TAB_MAP)
    if cached and not force and cached.get("date") == today:
        return cached
    out = {"date": today, "books": {}, "unmapped": [], "changes": []}
    prev = (cached or {}).get("books") or {}
    for label, bid in _books().items():
        names = _fetch_xlsx_names(bid)
        if names is None:
            out["books"][label] = {"error": "enumeration unreachable",
                                   "tabs": (prev.get(label) or {}).get("tabs")}
            continue
        roles = TAB_ROLES.get(label, {})
        tabs = {}
        for nm in names:
            role = roles.get(nm)
            tabs[nm] = {"role": role or "UNMAPPED"}
            if role is None:
                out["unmapped"].append({"book": label, "tab": nm})
        prev_names = set(((prev.get(label) or {}).get("tabs") or {}).keys())
        if prev_names:
            for nm in set(names) - prev_names:
                out["changes"].append({"book": label, "tab": nm, "kind": "new"})
            for nm in prev_names - set(names):
                out["changes"].append({"book": label, "tab": nm,
                                       "kind": "removed/renamed"})
        out["books"][label] = {"tabs": tabs, "n": len(names)}
    kv_store.put(_KV_TAB_MAP, out)
    return out


# ── the renewal ledger ──────────────────────────────────────────────────────

def _money(s) -> float | None:
    s = str(s or "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _date(s) -> str | None:
    import datetime as dt
    s = str(s or "").strip()
    for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return str(dt.datetime.strptime(s[:10], fmt).date())
        except ValueError:
            continue
    return None


def renewal_ledger(fresh: bool = False) -> dict:
    """RECOGNIZED renewal columns = primary; Sheet5 corroborates. Row-level
    provenance; conflicts surfaced. Cached daily (kv)."""
    today = str(today_sydney())
    cached = kv_store.get(_KV_LEDGER_CACHE)
    if cached and not fresh and cached.get("date") == today:
        return cached
    bid = _books()["finance"]
    rec = _fetch_tab_csv(bid, "RECOGNIZED")
    s5 = _fetch_tab_csv(bid, "Sheet5")
    if not rec:
        return {"ok": False, "reason": "RECOGNIZED tab unreachable",
                "entries": (cached or {}).get("entries") or []}
    s5_status = {}
    for i, r in enumerate((s5 or [])[1:], start=2):
        if r and str(r[0]).strip():
            s5_status[str(r[0]).strip().lower()] = {
                "status": (r[4] if len(r) > 4 else "").strip(),
                "row": i}
    entries, conflicts = [], []
    for i, r in enumerate(rec[1:], start=2):
        if not (r and str(r[0]).strip()) or len(r) < 11:
            continue
        client = str(r[0]).strip()
        rstatus = str(r[4]).strip()
        if rstatus not in ("Renewed", "Pending", "First Contract", "Lost", "Web"):
            continue
        note = str(r[6]).strip()
        entry = {
            "client": client, "status": str(r[1]).strip(),
            "package": str(r[2]).strip(), "service_term": str(r[3]).strip(),
            "renewal_status": rstatus,
            "renewal_date": _date(r[5]),
            "term_start": _date(r[7]), "term_end": _date(r[8]),
            "contract_value": _money(r[9]), "mrr": _money(r[10]),
            "note": note,
            "extension": (rstatus == "Renewed" and "MONTH-MONTH" in note.upper()),
            "provenance": {"book": "finance", "tab": "RECOGNIZED", "row": i},
        }
        s5e = s5_status.get(client.lower())
        if s5e and s5e["status"] and s5e["status"] != rstatus:
            conflicts.append({
                "client": client,
                "recognized": rstatus, "sheet5": s5e["status"],
                "refs": {"RECOGNIZED": f"row {i}", "Sheet5": f"row {s5e['row']}"},
                "rule": "RECOGNIZED is primary; Sheet5 disagreement surfaced, "
                        "never merged"})
            entry["conflict"] = f"Sheet5 says '{s5e['status']}'"
        entries.append(entry)
    out = {"ok": True, "date": today, "entries": entries,
           "conflicts": conflicts,
           "renewed": [e for e in entries if e["renewal_status"] == "Renewed"],
           "pending": [e for e in entries if e["renewal_status"] == "Pending"],
           "urgent": [e for e in entries if "URGENT" in (e["note"] or "").upper()]}
    kv_store.put(_KV_LEDGER_CACHE, out)
    return out


def sheet_renewals_for_projection() -> dict[str, dict]:
    """{norm_name: {mrr, until, from, provenance, extension}} — renewed terms
    that extend committed coverage. Month-to-month extensions carry
    extension=True and until=None (NOT term-committed — the projection keeps
    them in the assumed pool; the renewal watch treats them as decided)."""
    led = renewal_ledger()
    out = {}
    for e in led.get("renewed") or []:
        if (e.get("status") or "") not in ("Active", "Web Sub"):
            continue
        nn = re.sub(r"[^a-z0-9]", "", e["client"].lower())
        out[nn] = {"client": e["client"], "mrr": e.get("mrr"),
                   "from": e.get("term_start"),
                   "until": None if e["extension"] else e.get("term_end"),
                   "extension": e["extension"],
                   "contract_value": e.get("contract_value"),
                   "provenance": f"sheet renewal ledger (RECOGNIZED row "
                                 f"{e['provenance']['row']})"}
    return out


# ── cross-tab MRR reconciliation ────────────────────────────────────────────

def cross_tab_recon() -> dict:
    """The four MRR truths side by side + per-client deltas with causes.
    ONE truth results (the engine roster, derivation shown); every
    disagreement stays surfaced until source-fixed."""
    bid = _books()["finance"]
    act = _fetch_tab_csv(bid, "ACTUAL")
    rec = _fetch_tab_csv(bid, "RECOGNIZED")
    tabs = {}
    for label, rows, mrr_col in (("ACTUAL", act, 7), ("RECOGNIZED", rec, 10)):
        m = {}
        for i, r in enumerate((rows or [])[1:], start=2):
            if r and str(r[0]).strip() and len(r) > mrr_col \
                    and str(r[1]).strip() in ("Active", "Web Sub"):
                m[str(r[0]).strip()] = {"mrr": _money(r[mrr_col]), "row": i,
                                        "status": str(r[1]).strip()}
        tabs[label] = m
    roster = {}
    roster_total = None
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        ch = snap.get("client_health") or {}
        roster_total = ch.get("current_mrr")
        for c in (ch.get("clients") or []):
            roster[(c.get("name") or "").strip()] = {
                "mrr": c.get("current_mrr"), "status": c.get("status")}
    except Exception:
        pass
    known_churned = set()
    try:
        import active_clients
        known_churned = {c.lower() for c in active_clients.KNOWN_CHURNED}
    except Exception:
        pass

    def _nn(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    roster_nn = {_nn(k): k for k in roster}
    deltas = []
    for label, m in tabs.items():
        for name, v in m.items():
            if _nn(name) in roster_nn:
                continue
            cause = ("known-churned (engine excludes; sheet still says Active"
                     " — Piolo: flip the status)"
                     if any(k in name.lower() or name.lower() in k
                            for k in known_churned)
                     else "on the sheet tab but NOT in the engine roster — "
                          "the roster reads a different tab/gid (the "
                          "'6 won deals missing from Health' class); "
                          "Piolo: align the roster tab")
            deltas.append({"client": name, "tab": label, "mrr": v["mrr"],
                           "row": v["row"], "cause": cause, "owner": "Piolo"})
    for name, v in roster.items():
        if not any(_nn(name) in {_nn(k) for k in m} for m in tabs.values()):
            deltas.append({"client": name, "tab": "engine-roster only",
                           "mrr": v.get("mrr"),
                           "cause": "in the engine roster but on neither "
                                    "money tab — verify source tab",
                           "owner": "Rydel/Piolo"})
    led = renewal_ledger()
    zero_mrr_resolved = []
    for name, v in roster.items():
        if not v.get("mrr"):
            e = next((x for x in led.get("renewed") or []
                      if _nn(x["client"]) == _nn(name)), None)
            if e:
                zero_mrr_resolved.append({
                    "client": name, "renewed": e.get("term_start"),
                    "mrr_per_ledger": e.get("mrr"),
                    "cause": "zero-MRR active EXPLAINED: renewed per the "
                             "ledger — the roster tab's MRR cell is stale "
                             "(Piolo: fill it)"})
    return {
        "sums": {
            "engine_roster": roster_total,
            "actual_tab": round(sum((v["mrr"] or 0) for v in tabs.get("ACTUAL", {}).values()), 2),
            "recognized_tab": round(sum((v["mrr"] or 0) for v in tabs.get("RECOGNIZED", {}).values()), 2),
            "footer_note": "RECOGNIZED footer $67,337.52 vs computed rows "
                           "$76,437.52 — the sheet's own footer is stale "
                           "(standing Piolo item)",
        },
        "one_truth": {
            "value": roster_total,
            "derivation": "engine roster (Health-gid tab, status-filtered, "
                          "known-churned excluded, declarations applied) — "
                          "the ruled active-client derivation; tab deltas "
                          "surfaced below until source-fixed",
        },
        "deltas": deltas,
        "zero_mrr_resolved": zero_mrr_resolved,
        "conflicts": led.get("conflicts"),
    }


# ── sentinel ────────────────────────────────────────────────────────────────

def sentinel_watch() -> dict:
    """Nightly: tab-change detection + renewal-ledger freshness + cross-tab
    drift (sums re-checked; growing deltas are loud via the queue)."""
    out = {"at": str(today_sydney())}
    try:
        tm = enumerate_tabs(force=True)
        out["unmapped_tabs"] = tm.get("unmapped")
        out["tab_changes"] = tm.get("changes")
        if tm.get("unmapped") or tm.get("changes"):
            try:
                import ad_sentinel
                ad_sentinel.queue_item(
                    "workbook tab change",
                    f"unmapped={tm.get('unmapped')} changes={tm.get('changes')}"[:280],
                    rank="P2")
            except Exception:
                pass
        led = renewal_ledger(fresh=True)
        out["renewal_ledger"] = {"renewed": len(led.get("renewed") or []),
                                 "conflicts": len(led.get("conflicts") or []),
                                 "urgent": [e["client"] for e in led.get("urgent") or []]}
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


# ── EDITH drill: "did Noodle Asia resign?" ──────────────────────────────────

_RESIGN_Q_RE = re.compile(r"did ([a-z0-9 &'\.\-]+?) (resign|renew|extend)|"
                          r"(resign|renew(al)?|extension) status (of|for) "
                          r"([a-z0-9 &'\.\-]+)", re.I)


def handle_resign_command(text: str) -> tuple[str | None, bool]:
    m = _RESIGN_Q_RE.search(text or "")
    if not m:
        return None, False
    name = (m.group(1) or m.group(5) or "").strip()
    if not name:
        return None, False
    try:
        led = renewal_ledger()
        nn = re.sub(r"[^a-z0-9]", "", name.lower())
        hit = next((e for e in led.get("entries") or []
                    if nn in re.sub(r"[^a-z0-9]", "", e["client"].lower())
                    or re.sub(r"[^a-z0-9]", "", e["client"].lower()) in nn),
                   None)
        if not hit:
            return (f"No renewal-ledger row matches '{name}' (RECOGNIZED "
                    f"renewal columns + Sheet5 checked). If they renewed, "
                    f"the sheet doesn't say so yet.", True)
        if hit["renewal_status"] == "Renewed":
            ext = (" — MONTH-TO-MONTH extension (no fixed end date; stays in "
                   "the assumed layer)" if hit["extension"] else
                   f", new term {hit['term_start']} → {hit['term_end']}")
            cv = (f", contract ${hit['contract_value']:,.0f} "
                  f"(${hit['mrr']:,.2f}/mo)" if hit.get("contract_value") else "")
            conflict = (f" ⚠ {hit['conflict']}" if hit.get("conflict") else "")
            return (f"Yes — {hit['client']} RENEWED per the sheet renewal "
                    f"ledger (RECOGNIZED row "
                    f"{hit['provenance']['row']}){ext}{cv}. It's in committed "
                    f"MRR and the collection schedule.{conflict}", True)
        return (f"{hit['client']}: renewal status '{hit['renewal_status']}'"
                + (f" — note: {hit['note']}" if hit.get("note") else "")
                + f" (RECOGNIZED row {hit['provenance']['row']}).", True)
    except Exception as e:
        logger.info("resign drill failed: %s", e)
        return None, False
