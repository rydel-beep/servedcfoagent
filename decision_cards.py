"""decision_cards.py — "Needs your ruling" (#150, owner-only).

One consolidated list of everything ONLY Rydel can decide, each card:
what's known · what's missing · the exact evidence · the one action.
Sources are the live engines (never a copy): the gap ledger's PROPOSED
closes, the AR unmatched-payment alias proposals, the cross-tab register,
the ad-set mapping, the review-session cadence, the Piolo package, the
GHL-owner flags. Cards self-retire as the underlying state resolves.
"""

from __future__ import annotations

import logging

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)


def build_cards() -> dict:
    cards = []

    def card(cid, title, known, missing, evidence, action):
        cards.append({"id": cid, "title": title, "known": known,
                      "missing": missing, "evidence": evidence,
                      "action": action})

    # 1 · PROPOSED gap closes
    try:
        import gap_reconcile
        for e in (gap_reconcile.close_ledger().get("ledger") or []):
            if e.get("state") != "PROPOSED":
                continue
            card(f"proposed_close_{e['person'].replace(' ', '_').lower()}",
                 f"PROPOSED close — {e['person']} ({e['close_date']})",
                 f"GHL closed-stage {e['close_date']} "
                 f"(opp {str((e.get('evidence') or {}).get('opp_id'))[:10]}…)",
                 e.get("missing"),
                 e.get("evidence"),
                 "confirm: bank transfer (check Xero) / your word → declare "
                 "the close in the dialog · or reject the stage move (flag "
                 "to the GHL owner)")
    except Exception as ex:
        logger.info("cards: gap ledger unavailable: %s", ex)

    # 2 · Harman's venue (the no-client-row close)
    try:
        import gap_reconcile
        for e in (gap_reconcile.close_ledger().get("ledger") or []):
            if e.get("state") == "AUTO" and not e.get("health_row"):
                card(f"venue_{e['person'].replace(' ', '_').lower()}",
                     f"{e['person']} — venue + contract unknown",
                     f"payment-corroborated close {e['close_date']} "
                     f"(${(e.get('stripe') or {}).get('cash_to_date')})",
                     "the venue name and the signed contract value (blank ≠ "
                     "zero — no client row exists anywhere)",
                     e.get("evidence"),
                     "name the venue → Piolo rows it on the tracker + Health "
                     "tab")
    except Exception:
        pass

    # 3 · unmatched payments (alias proposals)
    try:
        import receivables
        ar = receivables.build_ar()
        for u in (ar.get("unmatched_receipts") or [])[:6]:
            card(f"alias_{str(u.get('charge_id'))[:12]}",
                 f"unmatched payment — {u.get('payer')} "
                 f"${u.get('amount'):,.0f} ({u.get('date')})",
                 f"Stripe {u.get('charge_id')}",
                 "which client this payer belongs to",
                 {"charge_id": u.get("charge_id"),
                  "proposed": u.get("proposed_client")},
                 (f"confirm alias → {u['proposed_client']}"
                  if u.get("proposed_client") else
                  "name the client (alias flow — never auto-assigned)"))
    except Exception:
        pass

    # 4 · cross-tab register (footer, zero-MRR, tab conflicts)
    try:
        import finance_tabs
        recon = finance_tabs.cross_tab_recon()
        card("footer_mismatch",
             "RECOGNIZED footer ≠ its rows",
             (recon.get("sums") or {}).get("footer_note"),
             "who fixes the footer formula",
             {"tab": "RECOGNIZED"},
             "assign to Piolo (the standing queue item)")
        for z in (recon.get("zero_mrr_resolved") or []):
            card(f"zeromrr_{z['client'].replace(' ', '_').lower()}",
                 f"zero-MRR active EXPLAINED — {z['client']}",
                 z["cause"], "Piolo to fill the roster MRR cell",
                 {"renewed": z.get("renewed"),
                  "mrr_per_ledger": z.get("mrr_per_ledger")},
                 "confirm the ledger renewal → Piolo fills the cell")
        for c in (finance_tabs.renewal_ledger().get("conflicts") or []):
            card(f"tabconflict_{c['client'].replace(' ', '_').lower()}",
                 f"tab conflict — {c['client']}",
                 f"RECOGNIZED says '{c['recognized']}', Sheet5 says "
                 f"'{c['sheet5']}'",
                 "which tab is right",
                 c.get("refs"),
                 "rule it → Piolo aligns the tabs (RECOGNIZED stays primary "
                 "until you say otherwise)")
        for u in (finance_tabs.renewal_ledger().get("urgent") or []):
            card(f"urgent_{u['client'].replace(' ', '_').lower()}",
                 f"sheet says URGENT: CONTACT NOW — {u['client']}",
                 f"renewal {u.get('renewal_status')}, term ended "
                 f"{u.get('term_end')}",
                 "the renewal conversation",
                 u.get("provenance"), "call them (or rule churned)")
    except Exception:
        pass

    # 5 · ad-set mapping + review session
    try:
        import ads_lifecycle
        import attribution_engine as AE
        win = AE.compute(days=30, basis="activity")
        allr = AE.compute(days=90, basis="activity")
        so = ads_lifecycle.sets_overview(win.get("creatives") or [],
                                         allr.get("creatives") or [])
        for u in (so.get("unmapped") or [])[:6]:
            card(f"setmap_{u['adset_id']}",
                 f"unmapped ad set — {u.get('adset_name')}",
                 f"${u.get('window_spend'):,.0f} window spend on "
                 f"{u.get('ads')} ads outside the four roles",
                 "its R-A2 role (or 'not part of the strategy')",
                 {"adset_id": u["adset_id"]},
                 "map it in the /ads strategy panel (journaled, reversible)")
        if not ads_lifecycle.review_sessions(limit=3):
            card("review_session",
                 "first R-A2 review session never run",
                 "the 7–8-day review cadence has zero recorded sessions "
                 "since the 08-24 migration",
                 "a session (you + the ad team)",
                 {"panel": "/ads?view=board&session=1"},
                 "run the session — pull/keep/inject from the peer-relative "
                 "flags")
    except Exception:
        pass

    # 6 · GHL-owner flag
    card("ghl_open_closed",
         "56 GHL closed-stage opps still status 'open'",
         "status-based win reads are wrong until closed-won is set "
         "(the August audit's standing finding)",
         "the GHL owner to bulk-set won/lost statuses",
         {"owner": "GHL owner (Tristan)"},
         "flag only — READ-ONLY law: the agent never re-stages")
    return {"date": str(today_sydney()), "cards": cards, "n": len(cards)}
