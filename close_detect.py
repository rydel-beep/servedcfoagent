"""close_detect.py — A CLOSE BECOMES VISIBLE THE MOMENT ANY SOURCE SHOWS IT.

Koji closed on a Tuesday and the dashboard did not know on Wednesday. Not
because anything crashed — because every path to "there is a new client"
waited on something:

  · the tracker's close columns have been empty since 24 July (R-GAP),
  · the gap ledger that reads GHL instead only rebuilds when the owner
    presses a button,
  · and even when it runs, a close is only APPLIED when a Stripe payment can
    be matched to the person's own name — so money that lands under a
    different payer name (Koji's did) leaves the close sitting as PROPOSED.

Three links, each waiting on the one behind it. This module inverts that:
whichever source moves FIRST makes the close visible, with its provenance on
it and the others listed as corroboration-pending.

  THE SOURCES, in the order they usually move
    1 the stage recorder's closed-won transition  (watching since 21 Sep)
    2 a GHL opportunity sitting in a closed stage (the mirror, any date)
    3 a payment matched to a client with no close on file
    4 a tracker close row                          (the authority when filled)

  WHAT IT NEVER DOES
    · invent a close: every entry names the evidence that produced it,
    · guess a package from a payment amount,
    · call something CONFIRMED on one source alone.

R-CASH is untouched: cash still comes from Stripe/Xero receipts only. A
detection is a CLOSE EVENT, not money.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re

import kv_store
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_DETECTED = "closes:detected"          # the standing ledger
K_SEEN = "closes:announced"             # what the feed has already said
K_LAST_SCAN = "closes:last_scan"

# a close is CONFIRMED with two independent sources, or with the tracker
# (the standing authority) alone.
_AUTHORITY = "tracker"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


# ── the sources ─────────────────────────────────────────────────────────────

def _from_ghl() -> list[dict]:
    """Opportunities sitting in a closed stage, whenever they got there.
    Unlike the gap ledger this is NOT limited to a detected window — a close
    today is a close today."""
    import db
    out = []
    try:
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT id, contact_id, name, monetary_value, status, "
                "stage_name, source, created_at, last_stage_change_at, raw "
                "FROM ghl_opportunities WHERE deleted=FALSE "
                "AND lower(stage_name) LIKE '%%closed%%'").fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning("close_detect: GHL mirror unreachable: %s", e)
        return []
    for r in rows:
        raw = r["raw"] if isinstance(r["raw"], dict) else json.loads(r["raw"] or "{}")
        ct = raw.get("contact") or {}
        d = str(r["last_stage_change_at"] or r["created_at"] or "")[:10]
        if not d:
            continue
        out.append({
            "person": (ct.get("name") or (r["name"] or "").split(":")[0]).strip(),
            "close_date": d,
            "source": "ghl stage",
            "provenance": f"GHL opportunity in stage '{r['stage_name']}'",
            "evidence": {"opp_id": r["id"], "contact_id": r["contact_id"],
                         "stage": r["stage_name"],
                         "stage_changed": str(r["last_stage_change_at"] or "")[:16]},
            "email": (ct.get("email") or "").lower() or None,
            "opp_value": r["monetary_value"],
            "owner_id": raw.get("assignedTo") or (raw.get("assignedUser") or {}).get("id"),
        })
    return out


def _from_stage_recorder() -> list[dict]:
    """The recorder's own captured transitions into a closed stage. It has
    been watching since it started; before that there is nothing to read and
    it says so rather than implying silence means no closes."""
    try:
        import stage_history
        started = stage_history.started_at()
    except Exception as e:  # noqa: BLE001
        logger.info("close_detect: stage recorder unavailable: %s", e)
        return []
    out = []
    try:
        import stage_history
        by_opp = _opp_index()
        for r in kv_store.get(stage_history.K_TRANSITIONS) or []:
            to = (r.get("to") or "").lower()
            if not any(c in to for c in ("closed", "won")):
                continue
            opp = by_opp.get(r.get("opportunity_id")) or {}
            out.append({
                "person": opp.get("person") or "",
                "close_date": str(r.get("first_seen") or "")[:10],
                "source": "stage recorder",
                "provenance": (f"recorded move into '{r.get('to')}' "
                               f"(watching since {started})"),
                "evidence": {"opp_id": r.get("opportunity_id"),
                             "contact_id": r.get("contact_id"),
                             "observed_at": str(r.get("first_seen") or "")[:16],
                             "kind": r.get("kind")},
                "email": opp.get("email"),
            })
    except Exception as e:  # noqa: BLE001
        logger.info("close_detect: stage events unreadable: %s", e)
    return out


def _opp_index() -> dict:
    """opportunity id → person/email, from the mirror the recorder watches."""
    idx = {}
    try:
        import ghl_mirror
        for o in ghl_mirror.read_opportunities(open_only=False) or []:
            raw = o.get("raw") if isinstance(o.get("raw"), dict) else {}
            ct = (raw or {}).get("contact") or {}
            idx[o.get("id")] = {
                "person": (ct.get("name") or (o.get("name") or "").split(":")[0]).strip(),
                "email": (ct.get("email") or "").lower() or None}
    except Exception as e:  # noqa: BLE001
        logger.info("close_detect: opp index unavailable: %s", e)
    return idx


def _from_tracker() -> list[dict]:
    """Close rows on the tracker — the standing authority when it is filled."""
    out = []
    try:
        import attribution_engine as AE
        import sheet_mirror
        rows = sheet_mirror.read_tab("ltc_tracker") or []
        if not rows:
            return []
        cols = AE.tracker_cols(rows[0])
        for r in rows[1:]:
            def cell(key):
                i = cols.get(key)
                return (r[i] if i is not None and i < len(r) else "") or ""
            d = _date(cell("close_date"))
            if not d:
                continue
            out.append({
                "person": cell("name").strip(),
                "close_date": d,
                "source": "tracker",
                "provenance": "tracker close row",
                "evidence": {"business": cell("business"),
                             "contract": cell("contract"), "cash": cell("cash")},
                "email": cell("email").lower() or None,
            })
    except Exception as e:  # noqa: BLE001
        logger.info("close_detect: tracker unreadable: %s", e)
    return out


def _client_to_person() -> dict:
    """business name → the tracker's person for that row. A payment names a
    CLIENT; a close is keyed by the PERSON who signed. Without this bridge a
    matched payment for Grappino reads as a second, separate close beside
    Harman singh's."""
    idx = {}
    try:
        import attribution_engine as AE
        import sheet_mirror
        rows = sheet_mirror.read_tab("ltc_tracker") or []
        if not rows:
            return idx
        cols = AE.tracker_cols(rows[0])
        bi, ni = cols.get("business"), cols.get("name")
        for r in rows[1:]:
            b = (r[bi] if bi is not None and bi < len(r) else "") or ""
            n = (r[ni] if ni is not None and ni < len(r) else "") or ""
            if b and n:
                idx.setdefault(_norm(b), n.strip())
    except Exception as e:  # noqa: BLE001
        logger.info("close_detect: client→person bridge unavailable: %s", e)
    return idx


def _from_payments() -> list[dict]:
    """Money matched to a client that has no close on file. Cash cannot
    create a close on its own — it is a candidate with the charge as its
    evidence, and it says what is missing."""
    out = []
    bridge = _client_to_person()
    try:
        import unmatched_payments as UP
        for m in UP.matched_without_close():
            client = m.get("client") or m.get("payer")
            out.append({
                "person": bridge.get(_norm(client)) or client,
                "close_date": m.get("date"),
                "source": "payment",
                "provenance": (f"payment matched to {m.get('client')} with no "
                               f"close on file"),
                "client": m.get("client"),
                "evidence": {"charge_ids": [m.get("charge_id")],
                             "payer": m.get("payer"), "amount": m.get("amount")},
                "email": None,
            })
    except Exception as e:  # noqa: BLE001
        logger.info("close_detect: payment candidates unavailable: %s", e)
    return out


def _date(v) -> str | None:
    """The tracker writes dates US-first (9/23/2026 is September). My first
    version read that as day-first, raised on month 23, swallowed it and
    dropped THIRTEEN close rows — including Koji's — while reporting a
    healthy-looking row count. Same order as the rest of the estate now."""
    v = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return str(dt.datetime.strptime(v[:10], fmt).date())
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if m:
        try:
            return str(dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return None
    return None


# ── the merge ───────────────────────────────────────────────────────────────

def scan(days: int = 60) -> dict:
    """Every close any source can see in the last `days`, merged by person.

    A person with two sources is CONFIRMED. One source is DETECTED, and the
    entry names what is still missing rather than pretending it is complete."""
    cutoff = str(today_sydney() - dt.timedelta(days=days))
    found: dict[str, dict] = {}
    by_source = {}
    for fn, label in ((_from_tracker, "tracker"), (_from_ghl, "ghl stage"),
                      (_from_stage_recorder, "stage recorder"),
                      (_from_payments, "payment")):
        try:
            rows = fn() or []
        except Exception as e:  # noqa: BLE001
            logger.warning("close_detect source %s failed: %s", label, e)
            rows = []
        by_source[label] = len(rows)
        for row in rows:
            if not row.get("close_date") or row["close_date"] < cutoff:
                continue
            key = _norm(row.get("person")) or _norm(
                (row.get("evidence") or {}).get("contact_id"))
            if not key:
                continue
            e = found.setdefault(key, {
                "person": row.get("person") or "", "close_date": row["close_date"],
                "sources": [], "evidence": {}, "email": row.get("email")})
            if row.get("person") and not e["person"]:
                e["person"] = row["person"]
            e["email"] = e["email"] or row.get("email")
            e["sources"].append({"source": row["source"],
                                 "provenance": row["provenance"],
                                 "close_date": row["close_date"]})
            e["evidence"].update(row.get("evidence") or {})
            if row["source"] == _AUTHORITY:
                e["close_date"] = row["close_date"]      # the authority dates it
            elif row["close_date"] < e["close_date"]:
                e["close_date"] = row["close_date"]

    entries = []
    for key, e in found.items():
        names = {s["source"] for s in e["sources"]}
        e["state"] = ("CONFIRMED" if (_AUTHORITY in names or len(names) >= 2)
                      else "DETECTED")
        e["corroboration_pending"] = sorted(
            {"tracker", "ghl stage", "payment"} - names)
        e["missing"] = _missing(e)
        e["key"] = key
        entries.append(e)
    entries.sort(key=lambda x: x["close_date"], reverse=True)

    out = {"at": now_sydney().isoformat(), "window_days": days,
           "entries": entries,
           "confirmed": sum(1 for e in entries if e["state"] == "CONFIRMED"),
           "detected": sum(1 for e in entries if e["state"] == "DETECTED"),
           "source_rows": by_source,
           "note": ("a close is visible as soon as ANY source shows it; the "
                    "others are listed as corroboration-pending")}
    kv_store.put(K_DETECTED, out)
    kv_store.put(K_LAST_SCAN, {"at": out["at"], "entries": len(entries)})
    return out


def _missing(e: dict) -> list[str]:
    ev = e.get("evidence") or {}
    missing = []
    if not str(ev.get("contract") or "").strip():
        missing.append("contract value")
    if not ev.get("charge_ids"):
        missing.append("a matched payment")
    if not ev.get("opp_id") and not ev.get("contact_id"):
        missing.append("the CRM record")
    return missing


def latest() -> dict:
    return kv_store.get(K_DETECTED) or {"entries": []}


# ── the feed: "new close detected" ──────────────────────────────────────────

def new_since_last_look() -> list[dict]:
    """Entries the feed has not announced yet — announced once, watermarked."""
    seen = set(kv_store.get(K_SEEN) or [])
    fresh = [e for e in latest().get("entries") or []
             if f"{e['key']}|{e['close_date']}" not in seen]
    return fresh


def mark_announced(entries: list[dict]) -> None:
    seen = set(kv_store.get(K_SEEN) or [])
    for e in entries or []:
        seen.add(f"{e['key']}|{e['close_date']}")
    kv_store.put(K_SEEN, sorted(seen)[-500:])


def feed_items() -> list[dict]:
    """Feed rows for closes nobody has acknowledged — each names the source
    that saw it and what is still missing."""
    items = []
    for e in new_since_last_look():
        src = e["sources"][0]["source"] if e.get("sources") else "unknown"
        miss = ", ".join(e.get("missing") or []) or "nothing — it is complete"
        items.append({
            "kind": "new_close_detected",
            "title": f"New close detected — {e['person'] or 'unnamed'}",
            "detail": (f"{e['close_date']} · seen first by {src} · "
                       f"{e['state'].lower()} · still missing: {miss}"),
            "person": e["person"], "close_date": e["close_date"],
            "state": e["state"], "evidence": e.get("evidence"),
        })
    return items


# ── THE PIOLO PACKAGE — the exact cells somebody has to fill ───────────────

K_FEED = "feed:extra:close_detect"      # one publisher, replaced wholesale


def piolo_package() -> dict:
    """Every gap the detection found, as an exact-row instruction.

    The tracker stays view-only — this is what to type, not a write. Each
    item retires by construction: the next scan rebuilds the channel, so a
    row that has since been filled simply stops being published."""
    rows, items = [], []
    for e in latest().get("entries") or []:
        ev = e.get("evidence") or {}
        edits = []
        sources = {s["source"] for s in e.get("sources") or []}
        if "tracker" not in sources:
            edits.append(f"lead row + Close Date = {e['close_date']}")
        if not str(ev.get("contract") or "").strip():
            edits.append("Contract Value = (from the closed-deal form — "
                         "never inferred from the payment)")
        if not ev.get("charge_ids") and "payment" not in sources:
            edits.append("Cash Collected = (once a payment is matched)")
        if not edits:
            continue
        rows.append({"person": e.get("person"), "close_date": e["close_date"],
                     "state": e.get("state"), "edits": edits,
                     "evidence": ev})
        items.append({
            "severity": "S2", "category": "data_quality",
            "title": f"close detected, tracker not updated — {e.get('person') or 'unnamed'}",
            "detail": "; ".join(edits)[:180],
            "action": ("fill the tracker row at source (READ-ONLY law: the "
                       "agent never writes the sheet) — this item retires "
                       "when the next scan sees the cells"),
        })
    kv_store.put(K_FEED, items[:20])
    kv_store.put("closes:package", {"built": str(today_sydney()), "rows": rows})
    return {"rows": len(rows), "queue_items": len(items[:20])}


# ── the owner's confirmation ────────────────────────────────────────────────

def confirm(key: str, actor: str = "rydel") -> dict:
    """Owner confirms a DETECTED close. The date goes in through the same
    sanctioned derivation lane the gap engine uses, carrying its evidence,
    and the blocks rebuild at once.

    It can only confirm something already IN the ledger — there is no path
    here that creates a close from a name and a date somebody typed."""
    entry = next((e for e in latest().get("entries") or []
                  if e.get("key") == key), None)
    if not entry:
        return {"ok": False, "error": "no detected close with that key — "
                                      "nothing is confirmed from thin air"}
    evidence = entry.get("evidence") or {}
    if not evidence:
        return {"ok": False, "error": ("this entry carries no evidence links — "
                                       "the derivation lane refuses it, and so "
                                       "does this")}
    try:
        import resolution
        ok = resolution.record_derived_date(
            key, "close_date", entry["close_date"],
            provenance=(f"confirmed by {actor} · detected via "
                        f"{entry['sources'][0]['source'] if entry.get('sources') else 'unknown'}"
                        f" (#161)"),
            evidence=evidence)
        if not ok:
            return {"ok": False, "error": "the derivation lane refused it "
                                          "(evidence or schema incomplete)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"the derivation lane refused it: {str(e)[:120]}"}
    journal = kv_store.get("closes:confirm_journal") or []
    journal.append({"at": now_sydney().isoformat(), "key": key, "by": actor,
                    "close_date": entry["close_date"],
                    "evidence": entry.get("evidence")})
    kv_store.put("closes:confirm_journal", journal[-500:])
    return {"ok": True, "entry": entry,
            "invalidated": invalidate_now(f"close confirmed: {entry['person']}")}


# ── event-driven recompute ─────────────────────────────────────────────────

def invalidate_now(reason: str) -> dict:
    """THE POINT OF THE WHOLE EXERCISE: evidence lands → the numbers move.

    A timer is not a pipeline. When a close or a payment changes what is
    true, this bumps the derivation epoch (which drops every cached
    attribution result) and rebuilds the engine blocks the tiles read, so the
    next page load is already right rather than right in two hours."""
    out = {"reason": reason, "at": now_sydney().isoformat(), "rebuilt": []}
    try:
        import resolution
        out["epoch"] = resolution.bump_derived_epoch(reason)
    except Exception as e:  # noqa: BLE001
        out["epoch_error"] = str(e)[:120]
    try:
        import freshness
        for name, fn in freshness._block_builders():
            try:
                fn()
                out["rebuilt"].append(name)
            except Exception as e:  # noqa: BLE001
                out.setdefault("failed", []).append({"block": name,
                                                     "why": str(e)[:120]})
    except Exception as e:  # noqa: BLE001
        out["rebuild_error"] = str(e)[:120]
    kv_store.put("closes:last_invalidation", out)
    return out


def tick() -> dict:
    """Scan, and if anything is new, invalidate immediately. Cheap enough for
    the short loop: four reads of stores the syncs already maintain."""
    before = {f"{e['key']}|{e['close_date']}"
              for e in (latest().get("entries") or [])}
    res = scan()
    after = {f"{e['key']}|{e['close_date']}" for e in res["entries"]}
    fresh = after - before
    res["new"] = sorted(fresh)
    try:
        res["package"] = piolo_package()
    except Exception as e:  # noqa: BLE001
        logger.warning("close package failed: %s", e)
    if fresh:
        res["invalidation"] = invalidate_now(
            f"{len(fresh)} new close(s) detected: {sorted(fresh)[:3]}")
    return res


# ── EDITH: "what closed today" ──────────────────────────────────────────────

_TODAY_RE = re.compile(
    r"\bwhat (?:has )?closed (?:today|this week|yesterday)\b|"
    r"\b(?:any|new) closes?\b|\bwho closed (?:today|this week)\b", re.I)


def handle_closed_today(text: str) -> tuple[str | None, bool]:
    """The tracker's close columns can be empty and a deal can still have
    closed. She answers from the detection ledger, naming the source and
    saying plainly what is still missing — never implying a silent tracker
    means a quiet week."""
    if not text or not _TODAY_RE.search(text):
        return None, False
    det = latest()
    entries = det.get("entries") or []
    t = str(today_sydney())
    if "week" in text.lower():
        start = str(today_sydney() - dt.timedelta(days=today_sydney().weekday()))
        window, hits = "since Monday", [e for e in entries if e["close_date"] >= start]
    elif "yesterday" in text.lower():
        y = str(today_sydney() - dt.timedelta(days=1))
        window, hits = "yesterday", [e for e in entries if e["close_date"] == y]
    else:
        window, hits = "today", [e for e in entries if e["close_date"] == t]
    if not det.get("at"):
        return ("I haven't scanned for closes yet — ask me again in a few "
                "minutes, or open the System page to see when the last scan "
                "ran."), True
    if not hits:
        return (f"Nothing shows as closed {window}. That is across the "
                f"tracker, the CRM stage, the stage recorder and matched "
                f"payments — if one of them moves, it appears within minutes."), True
    lines = []
    for e in hits:
        src = e["sources"][0]["source"] if e.get("sources") else "unknown"
        miss = (" · still missing: " + ", ".join(e["missing"])) if e.get("missing") else ""
        lines.append(f"{e['person'] or 'unnamed'} ({e['state'].lower()}, "
                     f"seen by {src}){miss}")
    return (f"{len(hits)} close{'s' if len(hits) != 1 else ''} {window}: "
            + "; ".join(lines) + "."), True
