"""Prod verification for the CSM cockpit (#146) — read-only except the
engine's own kv stores (baseline cache, book ledger seed, analysis version).
No director figures exist in config yet, so output is figure-safe."""
import json

import csm_plan, csm_baselines, csm_docs, csm_model

out = {}
b = csm_baselines.all_baselines(fresh=True)
b1 = b["b1_renewal"]
out["b1"] = {k: b1.get(k) for k in ("value", "lower_bound", "confidence_pm",
                                    "n_decided", "n_renewed", "n_ambiguous",
                                    "label")}
out["b1_undated_churned"] = len(b1.get("churned_undated") or [])
itc = b["b1_in_term_completion"]
out["in_term_completion"] = {"value": itc.get("value"), "label": itc.get("label"),
                             "skipped": itc.get("skipped_missing_fields")}
b2 = b["b2_refund_split"]
out["b2"] = {"xero_line_total": b2.get("xero_line_total"),
             "stripe": b2.get("stripe_client_refunds"),
             "label": b2.get("label"), "degraded": b2.get("degraded")}
out["b3_stepup_proxy"] = b["b3_expansion"]["stepup_repeat_deal_rate_pct"]
t = b["b4_book"]["tiers"]
out["b4"] = {"book": t.get("book_count"), "tier1": t.get("tier1_count"),
             "ledger_members": len(b["b4_book"]["ledger"].get("members") or []),
             "workload": b["b4_book"]["workload"]["cycle_hours_month"],
             "second_csm_fires": t["second_csm_trigger"]["fires"]}
d5 = b["b5_dqs_proxy"]
out["b5"] = {"available": d5.get("available"),
             "book_avg_health": d5.get("book_avg_health"),
             "pct_with_score": d5.get("pct_with_score"),
             "stale": d5.get("stale_accounts"), "reason": d5.get("reason")}
s = csm_plan.summary()
out["card_line"] = s["card_line"]
out["next_action"] = s["next_action"]
out["one_number"] = s["one_number"] if isinstance(s["one_number"], dict) else s["one_number"]
reg = csm_model.regression_check()
out["regression_ok"] = reg["ok"]
out["solve_4x"] = csm_model.solve_renewal_for_cohort_roi(4.0)["renewal_pct"]
cal = csm_plan.ladder_calendar()
out["calendar"] = {"dated_clients": len(cal["clients"]),
                   "undated": len(cal["undated"]),
                   "sample": cal["clients"][0] if cal["clients"] else None}
sb = csm_plan.scoreboard()
out["scoreboard_state"] = sb["state"]
out["nrr"] = sb["k1_retention"]["nrr"]
ana = csm_docs.generate_analysis()
out["d4"] = {"version": ana["version"], "generated": ana["generated"],
             "headline": ana["headline"]}
pre = csm_docs.comp_page_preflight()
out["d5_preflight"] = {"clean": pre["clean"], "hits": pre["forbidden_token_hits"]}
out["d5_pdf_bytes"] = len(csm_docs.comp_page_pdf())
out["d4_pdf_bytes"] = len(csm_docs.analysis_pdf())
sw = csm_plan.sentinel_watch()
out["sentinel"] = {"ok": sw["ok"], "problems": sw["problems"],
                   "leak_probe": sw["checks"].get("leak_probe")}
g = csm_plan.gates(b)
out["gate0"] = f"{g['done']}/{g['total']}"
print(json.dumps(out, indent=1, default=str))
