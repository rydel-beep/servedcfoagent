"""THE SCOREBOARD — a clean rebuild on the sources of truth (#173).

An ISOLATED module. It copies each source's records into its own raw tables
(store.py), links them by exact ids/emails/phones only (linking.py), and
counts every number directly from those rows (build.py). It never calls the
old engines (close register, gap rules, evidence ladders, unit-economics
engine, registries, derived closes).

Reused on purpose, and nothing else:
  · dashboard.auth           — logins and sessions (owner + Piolo)
  · db.get_conn              — the existing Postgres connection
  · config                   — the existing read-only API credentials
  · xero_pull._load_tokens / _refresh_access_token — the existing Xero connection
  · sheet_mirror._live_fetch — the existing read-only tracker connection
  · the #172 Part A rescheduled-chain rule — re-written in build.calls (not imported),
    tightened so a booking already marked showed/no-show is never folded away
  · comp_rulebook            — THE comp rulebook (the ruled source of commissions)

READ-ONLY LAW: every outbound call goes through fetch._get (HTTP GET). Nothing
here writes to GHL, Stripe, Xero, Meta or the tracker, and nothing reads
the GHL email token. A test enforces both.
"""
