"""
scripts/ingest_bas_export.py — record a LODGED activity statement as ground truth.

THE FILE-DROP FLOW (BAS_CALIBRATION_REPORT): Rydel drops/pastes a new BAS export →
a session (or this script) extracts the official lines → run this → the engine
recalibrates and reports its accuracy. The official figures become the stored record
for that quarter; the estimator's ledger figures stay only as the comparison.

Run INSIDE the Railway container (kv is Postgres-internal):
  railway ssh "cd /app && /opt/venv/bin/python3 scripts/ingest_bas_export.py --seed"
  railway ssh "cd /app && /opt/venv/bin/python3 scripts/ingest_bas_export.py \
      --quarter 2026-07-01 --json '{\"total\": 30000, \"net_gst\": ...}' --source '...'"

--seed ingests the Apr–Jun 2026 statement (parsed 2026-08-06 from
'THE 97 GROUP PTY LTD - Activity Statement.pdf', the official Xero export) and sets
the PAYG instalment config from its T7 line, provenance journaled.
"""
import argparse
import json
import sys

sys.path.insert(0, "/app")

APR_JUN_2026 = {
    # per the lodged Activity Statement, period ending 30 June 2026 (cash basis)
    "g1": 263391.0, "one_a": 23937.0, "one_b": 4149.0, "net_gst": 19788.0,
    "w1": 84133.0, "paygw": 20281.0, "instalment": 1450.0, "total": 41519.0,
    "due": "2026-08-25",   # agent-program due date
}
APR_JUN_SOURCE = ("Activity Statement export, THE 97 GROUP PTY LTD, period ending "
                  "30 Jun 2026 (Xero official; parsed 2026-08-06)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="ingest the Apr–Jun 2026 statement")
    ap.add_argument("--quarter", help="quarter START date iso, e.g. 2026-07-01")
    ap.add_argument("--json", help="official lines as JSON")
    ap.add_argument("--source", default="lodged BAS export")
    args = ap.parse_args()

    import bas_engine

    if args.seed:
        rec = bas_engine.ingest_lodged("2026-04-01", APR_JUN_2026, APR_JUN_SOURCE)
        cfg = bas_engine.set_config("instalment_amount", APR_JUN_2026["instalment"],
                                    set_by="lodged BAS Apr–Jun 2026 (T7)")
        print("lodged record:", json.dumps(rec, default=str))
        print("instalment config:", json.dumps(
            {k: cfg[k] for k in ("instalment_amount", "instalment_amount_provenance")},
            default=str))
    elif args.quarter and args.json:
        rec = bas_engine.ingest_lodged(args.quarter, json.loads(args.json), args.source)
        print("lodged record:", json.dumps(rec, default=str))
    else:
        ap.error("--seed or (--quarter + --json) required")

    est = bas_engine.refresh()
    if est:
        print("refreshed; position:", json.dumps(est.get("position"), default=str))
        print("honesty:", json.dumps(bas_engine.honesty_score(), default=str))
    else:
        print("refresh failed — run 'refresh the BAS estimate' later; record stored.")


if __name__ == "__main__":
    main()
