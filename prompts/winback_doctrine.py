"""
prompts/winback_doctrine.py — the winback sequencing doctrine, VERSIONED.

Source of authority: the "Winback SOP" page in the Email Command Centre is the CONTENT
rulebook (read live via email_pipeline.winback_rules() once visible to the integration).
The SEQUENCING parameters below were dictated by Rydel on 2026-08-04 and encoded here
per the Phase-0 agreement (verbal confirmation → versioned doctrine file):

  • P&D stage is team-maintained; a contact entering the stage starts the sequence
  • first touch: 3–4 days after stage entry
  • cadence: 2 emails per week
  • the OFFER email lands in the final week (bonus-stacked per the discount lock —
    never discount-broken)
"""
WINBACK_DOCTRINE_VERSION = "v1-2026-08-04"
TIMING = {"first_touch_days": (3, 4), "emails_per_week": 2, "offer_week": "final"}
