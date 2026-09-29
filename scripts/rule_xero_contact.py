"""rule_xero_contact.py — a Xero contact → client ruling (#170), journaled.
A PRODUCTION WRITE — run only on Rydel's word, his words verbatim.

  python scripts/rule_xero_contact.py --contact "Kin Fun Keng Wong" \
      --client "Noodle Asia" --words "Kin Fun Keng Wong → Noodle Asia"
  python scripts/rule_xero_contact.py --contact "Warners At The Bay" \
      --client "Warners At The Bay" --kind photography --exclude \
      --words "photography work, not a marketing retainer"
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
ap = argparse.ArgumentParser()
ap.add_argument("--contact", required=True); ap.add_argument("--client", required=True)
ap.add_argument("--words", required=True); ap.add_argument("--kind")
ap.add_argument("--exclude", action="store_true")
a = ap.parse_args()
import client_receipts as CRx
print(json.dumps(CRx.confirm_contact(a.contact, a.client, a.words, "rydel",
                                     exclude_from_measurement=a.exclude, kind=a.kind), indent=1))
