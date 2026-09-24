"""pompoko_alias_correction.py — THE ALIAS POINTS AT THE VENUE, NOT THE CONTACT.

Rydel's correction (24 Sep): the earlier ruling recorded the payer
"Sanatani Rombola" as paying for "Koji". Koji is the CONTACT; the
client/venue is POMPOKO BAR. This re-points the alias through the ONE
sanctioned lane (unmatched_payments.confirm — the same journal, rematch and
invalidation as any owner click) and journals it as a CORRECTION of the
earlier target, never a silent edit.

Evidence first: it prints what the alias store holds now and what every
system calls the venue, uses the string the systems actually match on
(so the roster/tracker join keeps working), and records Rydel's exact
wording ("POMPOKO BAR") in the journal either way.

Run on the box:
  railway ssh "cd /app && PYTHONPATH=/app /opt/venv/bin/python /tmp/d/pompoko_alias_correction.py"
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PAYER = "Sanatani Rombola"
RYDEL_WORDING = "POMPOKO BAR"


def _n(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def main():
    import kv_store
    import stripe_reconcile as SR

    print("=" * 70)
    print("BEFORE — what the alias store holds")
    aliases = SR._aliases()
    current = aliases.get(_n(PAYER))
    print(f"  alias[{_n(PAYER)!r}] = {current!r}")

    print("\nWHAT THE SYSTEMS CALL THE VENUE")
    candidates = []
    try:
        import sheet_mirror
        import attribution_engine as AE
        rows = sheet_mirror.read_tab("ltc_tracker") or []
        cols = AE.tracker_cols(rows[0]) if rows else {}
        bi, ni = cols.get("business"), cols.get("name")
        for r in rows[1:]:
            b = (r[bi] if bi is not None and bi < len(r) else "") or ""
            n = (r[ni] if ni is not None and ni < len(r) else "") or ""
            if "pompoko" in b.lower() or "koji" in n.lower():
                print(f"  tracker: person={n!r} business={b!r}")
                if b:
                    candidates.append(("tracker business cell", b))
    except Exception as e:  # noqa: BLE001
        print("  tracker unreadable:", e)
    try:
        roster = SR._roster_index()
        for k in (roster.get("active") or {}):
            if "pompoko" in k:
                print(f"  Health tab (roster): {k!r}")
                candidates.append(("Health tab", k))
    except Exception as e:  # noqa: BLE001
        print("  roster unreadable:", e)

    # the venue string the matcher can actually JOIN on: prefer the tracker's
    # business cell, then the Health tab row; Rydel's wording is the fallback
    # and is journaled verbatim in every case.
    target = next((v for _src, v in candidates if v), RYDEL_WORDING)
    src = next((s for s, v in candidates if v), "Rydel's wording (no system row found)")
    print(f"\nTARGET: {target!r} (from {src}) · Rydel's wording: {RYDEL_WORDING!r}")
    if current and _n(current) == _n(target):
        print("alias already points at the venue — nothing to re-point; "
              "journaling the confirmation only")

    print("\nAPPLYING through the sanctioned lane (journal + rematch + invalidate)")
    import unmatched_payments as UP
    # the charge that proved the alias yesterday, if it is in the scanned window
    charge_id = None
    st = UP.latest()
    for m in (st.get("matched") or []) + (st.get("rows") or []):
        if _n(m.get("payer")) == _n(PAYER):
            charge_id = m.get("charge_id")
            break
    res = UP.confirm(PAYER, target, actor="rydel — 24 Sep correction (#164)",
                     charge_id=charge_id)
    print(json.dumps({k: v for k, v in res.items() if k != "rematch"},
                     default=str)[:600])

    try:
        import close_register as CR
        CR.journal(
            "correction",
            f"alias target corrected: payer {PAYER!r} was recorded as paying "
            f"for 'Koji' (the CONTACT); the client/venue is {RYDEL_WORDING} — "
            f"alias now points at {target!r} (the string the systems match "
            f"on, from {src}). Koji remains the contact on the close record.",
            actor="rydel (brief, 24 Sep)",
            evidence={"payer": PAYER, "old_target": current,
                      "new_target": target, "charge_id": charge_id})
        CR.build()
        print("register journal written + register rebuilt")
    except Exception as e:  # noqa: BLE001
        print("register journal failed:", e)

    print("\nAFTER")
    print(f"  alias[{_n(PAYER)!r}] = {SR._aliases().get(_n(PAYER))!r}")


if __name__ == "__main__":
    main()
