"""ghl_tracker_sweep.py — ENTITY BY ENTITY, ID-EXACT, BOTH DIRECTIONS (#162).

One pass over every entity the estate holds in more than one system —
contacts, leads, appointments, shows, closes, cash, contracts, status/MRR —
with the count on each side, the matched, the mismatched WITH NAMES, and a
cause class for every mismatch. Read-only throughout; the output is a
markdown register printed to stdout (the caller saves it).

Cause classes: r-gap-window · unfilled-column · payer-alias · id-unlinked ·
picklist-drift · timezone · status-vocabulary · roster-stale.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from helpers import today_sydney  # noqa: E402

L = []


def say(line=""):
    L.append(line)


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def main():
    t = today_sydney()
    w0 = t - dt.timedelta(days=90)
    say(f"# GHL ↔ TRACKER ↔ DASHBOARD SWEEP — {t}")
    say()
    say(f"Trailing 90 days ({w0} → {t}) unless a section says otherwise. "
        f"Read-only; every mismatch carries a cause class.")
    say()

    import sheet_mirror
    import attribution_engine as AE
    import stripe_reconcile as SR

    rows = sheet_mirror.read_tab("ltc_tracker") or []
    cols = AE.tracker_cols(rows[0]) if rows else {}

    def cell(r, key):
        i = cols.get(key)
        return (r[i] if i is not None and i < len(r) else "") or ""

    # ── 1 · CONTACTS / CLIENTS ────────────────────────────────────────────
    say("## 1 · Contacts and clients")
    import ghl_mirror
    contacts = ghl_mirror.read_all_contacts() or {}
    roster = SR._roster_index()
    tr_emails = {cell(r, "email").strip().lower() for r in rows[1:]
                 if cell(r, "email").strip()}
    ghl_emails = set()
    for c in contacts.values():
        raw = c.get("raw") if isinstance(c.get("raw"), dict) else c
        e = (raw.get("email") or "").strip().lower()
        if e:
            ghl_emails.add(e)
    tr_biz = {_norm(cell(r, "business")) for r in rows[1:]
              if cell(r, "business").strip()}
    roster_only = sorted(v for k, v in (roster.get("venues") or {}).items()
                         if k not in tr_biz)
    say(f"- GHL contacts: **{len(contacts)}** · tracker rows: **{len(rows)-1}** "
        f"· roster clients: **{len(roster.get('venues') or {})}** "
        f"({len(roster.get('active') or [])} active)")
    inter = len(tr_emails & ghl_emails)
    say(f"- email-linked tracker↔GHL: **{inter}** of {len(tr_emails)} tracker "
        f"emails ({len(tr_emails - ghl_emails)} tracker-only, "
        f"{len(ghl_emails - tr_emails)} GHL-only) — cause: **id-unlinked** "
        f"(historic rows predate the CRM; new rows link by email)")
    say(f"- roster clients with NO tracker lead row ({len(roster_only)}) — "
        f"cause: **unfilled-column / pre-tracker client**: "
        + (", ".join(roster_only[:12]) + ("…" if len(roster_only) > 12 else "")))
    say()

    # ── 2 · LEADS ─────────────────────────────────────────────────────────
    say("## 2 · Leads (90d)")
    tr_leads = [r for r in rows[1:]
                if (d := _date(cell(r, "input_date"))) and str(w0) <= d <= str(t)]
    import db
    ghl_new = 0
    try:
        with db.get_conn() as c:
            ghl_new = c.execute(
                "SELECT count(*) n FROM ghl_opportunities WHERE deleted=FALSE "
                "AND created_at >= %s", (str(w0),)).fetchone()["n"]
    except Exception as e:  # noqa: BLE001
        say(f"- GHL count unavailable: {e}")
    import gap_reconcile as GR
    diff = GR.lead_diff() or {}
    missing = diff.get("missing_from_tracker") or []
    say(f"- tracker lead rows: **{len(tr_leads)}** · GHL opportunities created: "
        f"**{ghl_new}**")
    say(f"- GHL leads missing a tracker row: **{len(missing)}** — cause: "
        f"**r-gap-window / unfilled-column** (each already a Piolo package "
        f"line): " + ", ".join(sorted({m.get('name') or '?' for m in missing})[:10])
        + ("…" if len(missing) > 10 else ""))
    say()

    # ── 3 · QUALIFIED — are the rule's inputs present? ────────────────────
    say("## 3 · Qualified (rule inputs present?)")
    n_rev = sum(1 for r in tr_leads if cell(r, "revenue").strip())
    n_mkt = sum(1 for r in tr_leads if cell(r, "market").strip())
    say(f"- of {len(tr_leads)} leads: revenue band filled **{n_rev}** "
        f"({_pct(n_rev, tr_leads)}) · market filled **{n_mkt}** "
        f"({_pct(n_mkt, tr_leads)}) — blanks are cause: **unfilled-column** "
        f"(the qualified rule cannot fire on a blank)")
    say()

    # ── 4 · APPOINTMENTS ──────────────────────────────────────────────────
    say("## 4 · Appointments (calendar window −7d → +35d)")
    import appointments as AP
    st = AP.store() or {}
    evs = st.get("events") or []
    if evs:
        booked = [e for e in evs if not e.get("cancelled")
                  and e.get("calendar_kind") not in ("test", "onboarding")]
        cancelled = [e for e in evs if e.get("cancelled")]
        tests = [e for e in evs if e.get("calendar_kind") == "test"]
        tr_sets = sum(1 for r in rows[1:] if "set" in cell(r, "setter_outcome").lower())
        say(f"- calendar events held: **{len(evs)}** — booked **{len(booked)}**, "
            f"cancelled **{len(cancelled)}**, test-calendar **{len(tests)}**")
        say(f"- tracker rows marked SET (all time): **{tr_sets}** · the tracker's "
            f"Set Date column has been empty since April — cause: "
            f"**unfilled-column**; the CRM calendars are the booked source (#162)")
    else:
        say("- calendar store empty — sync has not run on this box yet")
    say()

    # ── 5 · SHOWS ─────────────────────────────────────────────────────────
    say("## 5 · Shows (t30, the one show-basis rule)")
    try:
        import travelling
        sb = travelling.show_basis_trailing(30)
        say(f"- confirmed **{sb.get('confirmed')}** · unmarked "
            f"**{sb.get('unconfirmed')}** of {sb.get('due')} due — rate "
            f"{_pctv(sb.get('rate'))} (upper {_pctv(sb.get('rate_upper'))}) — "
            f"unmarked consults are cause: **status-vocabulary** (nobody "
            f"recorded an outcome; the attendance surface lists them)")
    except Exception as e:  # noqa: BLE001
        say(f"- show basis unavailable: {e}")
    say()

    # ── 6 · CLOSES ────────────────────────────────────────────────────────
    say("## 6 · Closes (90d, tracker vs GHL stage vs payments)")
    import close_detect
    det = close_detect.latest() or {}
    ent = det.get("entries") or []
    say(f"- detection ledger: **{len(ent)}** ({det.get('confirmed')} confirmed, "
        f"{det.get('detected')} detected)")
    for e in ent:
        srcs = {s["source"] for s in e.get("sources") or []}
        cause = ("aligned" if len(srcs) >= 3 else
                 "payer-alias" if "payment" not in srcs else
                 "r-gap-window / unfilled-column")
        miss = ", ".join(e.get("missing") or []) or "nothing"
        say(f"  - {e['close_date']} · **{e['person']}** · {e['state']} · seen by "
            f"{', '.join(sorted(srcs))} · missing: {miss} · cause: **{cause}**")
    say()

    # ── 7 · CASH ──────────────────────────────────────────────────────────
    say("## 7 · Cash (Stripe vs attachment vs the tracker column)")
    import unmatched_payments as UP
    u = UP.latest() or {}
    say(f"- matched payments: **{len(u.get('matched') or [])}** · unattached: "
        f"**{u.get('count')}** (${u.get('total_unmatched'):,.2f}) — every "
        f"unattached row is cause: **payer-alias** (one click each)")
    tr_cash_rows = sum(1 for r in rows[1:] if cell(r, "cash").strip())
    say(f"- tracker Cash Collected cells filled: **{tr_cash_rows}** — blanks on "
        f"won rows are cause: **unfilled-column** (Piolo package)")
    say()

    # ── 8 · CONTRACTS ─────────────────────────────────────────────────────
    say("## 8 · Contract values (90d closes)")
    import finance_analysis as FA
    closes = FA._closes_union(str(w0), str(t), "activity")
    nc = [c["person"] for c in closes if not c.get("contract")]
    say(f"- closes: **{len(closes)}** · missing a contract value: **{len(nc)}**"
        + (f" ({', '.join(nc[:6])}) — cause: **unfilled-column**" if nc else ""))
    say()

    # ── 9 · STATUS / MRR ──────────────────────────────────────────────────
    say("## 9 · Client status and MRR (the standing rule)")
    import client_status_watch as CSW
    stale = CSW.latest() or {}
    say(f"- status-stale findings: **{stale.get('count', 0)}** — cause: "
        f"**roster-stale**")
    for f in stale.get("findings") or []:
        pays = " + ".join(f"${p['amount']:,.0f} ({p['date']})"
                          for p in f["payments"][:3])
        say(f"  - **{f['client']}** paid {pays} while the roster says "
            f"{'; '.join(f['problems'])} — charge ids "
            f"{', '.join(p['charge_id'] for p in f['payments'][:2])}")
    say()
    print("\n".join(L))


def _date(v):
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(v or ""))
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def _pct(n, of):
    return f"{n / len(of) * 100:.0f}%" if of else "—"


def _pctv(v):
    return f"{v * 100:.0f}%" if isinstance(v, (int, float)) else "—"


if __name__ == "__main__":
    main()
