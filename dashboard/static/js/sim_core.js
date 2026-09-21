/* sim_core.js — THE ONE FORMULA CORE for the simulator.
   Runs in the BROWSER (instant recompute) and in NODE (the 200-set parity
   test compares this exact file against compass_engine.simulate_month —
   client and engine can never diverge silently). Pure functions, no DOM,
   no side effects, nothing here can write anything.

   Formulas (identical to compass_engine.simulate_month):
     effective CPL = cpl                       (constant mode — DEFAULT)
                   = cpl × (spend/S0)^ε        (elasticity mode, opt-in)
     leads   = spend ÷ effective CPL
     calls   = leads × set rate
     shows   = calls × show rate
     clients = shows × close rate
     cash this month = clients × m0_share × avg contract
     cash over term  = clients × avg contract
     mrr added       = clients × avg mrr
     commissions     = commission rate × cash over term
     cac     = (spend + commissions + tooling) ÷ clients
     ltgp:cac = (avg contract × margin) ÷ cac                            */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SimCore = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function effectiveCpl(spend, cpl, curve, epsilon, spendBaseline) {
    if (!curve) return cpl;
    var S0 = spendBaseline || 1;
    return cpl * Math.pow(Math.max(spend, 1) / S0, epsilon || 0);
  }

  /* agg = the engine-provided aggregates:
     {m0_share, contract_avg, mrr_avg, margin_avg, comm_rate, tooling,
      epsilon, spend_baseline}
     rates = {set, show, close} */
  function chain(spend, cpl, rates, agg, curve) {
    var eff = effectiveCpl(spend, cpl, curve, agg.epsilon, agg.spend_baseline);
    var leads = eff > 0 ? spend / eff : 0;
    var calls = leads * rates.set;
    var shows = calls * rates.show;
    var clients = shows * rates.close;
    var cashNow = clients * agg.m0_share * agg.contract_avg;
    var cashTerm = clients * agg.contract_avg;
    var mrr = clients * agg.mrr_avg;
    var comm = agg.comm_rate * cashTerm;
    var cac = clients >= 0.01 ? (spend + comm + agg.tooling) / clients : null;
    var cacSpendOnly = clients >= 0.01 ? spend / clients : null;
    var ltgpPerClient = agg.contract_avg * agg.margin_avg;
    return {
      spend: spend, cpl_effective: eff, leads: leads, calls: calls,
      shows: shows, clients: clients, cash_this_month: cashNow,
      cash_over_term: cashTerm, mrr_added: mrr,
      commissions_over_term: comm, cac: cac, cac_spend_only: cacSpendOnly,
      ltgp_per_client: ltgpPerClient,
      ltgp_cac: cac ? ltgpPerClient / cac : null
    };
  }

  /* TARGET MODE: what SPEND delivers the wanted outcome at this CPL and
     these rates. kind: leads|calls|clients|cash|mrr. Elasticity solved by
     fixed-point iteration (effective CPL depends on the answer). */
  function requiredSpend(kind, value, cpl, rates, agg, curve) {
    var perClientCash = agg.m0_share * agg.contract_avg;
    var clients = null;
    if (kind === 'clients') clients = value;
    else if (kind === 'cash') clients = value / (perClientCash || 1);
    else if (kind === 'mrr') clients = value / (agg.mrr_avg || 1);
    var leads;
    if (kind === 'leads') leads = value;
    else if (kind === 'calls') leads = value / (rates.set || 1);
    else leads = clients / ((rates.set * rates.show * rates.close) || 1);
    var spend = leads * cpl;
    if (curve) {
      for (var i = 0; i < 40; i++) {
        spend = leads * effectiveCpl(spend, cpl, true, agg.epsilon, agg.spend_baseline);
      }
    }
    return { spend: spend, leads: leads };
  }

  return { effectiveCpl: effectiveCpl, chain: chain, requiredSpend: requiredSpend };
}));
