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
     commissions     = rulebook $ per close × clients (ONE mix, both cards)
     bounties        = $50 × qualified sets (calls × qualified rate)
     headcount cost  = whole extra setters/closers needed × role cost
     tooling         = fixed base + per-seat × sales seats
     cac      = (spend + commissions + bounties + fixed + headcount
                 + tooling) ÷ clients
     ltv:cac  = avg contract ÷ cac
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
     {m0_share, contract_avg, mrr_avg, margin_avg, comm_rate, tooling (fixed
      base), tooling_per_seat, qualified_rate, capacity: {setters, closers,
      leads_per_setter_month, calls_per_closer_month, setter_cost_monthly,
      closer_cost_monthly, hire_from}, cash_curve, epsilon, spend_baseline}
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
    /* COMMISSIONS FROM THE RULEBOOK (#159), matching compass_engine exactly:
       dollars per close (mix-weighted from THE ONE deal mix), plus the $50
       bounty on every QUALIFIED set (rulebook R-SET), plus the monthly
       fixed costs. The old `comm_rate * cashTerm` is kept ONLY as the
       fallback for a payload that predates the rulebook. */
    var qRate = (agg.qualified_rate === undefined || agg.qualified_rate === null)
      ? 1 : agg.qualified_rate;
    var qualified = calls * qRate;
    var comm, bounties, monthlyFixed;
    if (agg.comm_per_close !== undefined && agg.comm_per_close !== null) {
      comm = agg.comm_per_close * clients;
      bounties = (agg.bounty_per_set_agg || 0) * qualified;
      monthlyFixed = agg.monthly_fixed_agg || 0;
    } else {
      comm = agg.comm_rate * cashTerm;
      bounties = 0; monthlyFixed = 0;
    }
    /* CAPACITY: the sales headcount this volume needs against today's team
       — whole people, config role costs, the SAME formula as the engine's
       _capacity_need (parity-tested). Without it CAC stays flat forever. */
    var cap = agg.capacity || null;
    var gapS = 0, gapC = 0, capCost = 0;
    if (cap) {
      var lps = cap.leads_per_setter_month || 175;
      var cpc = cap.calls_per_closer_month || 60;
      gapS = Math.max(Math.ceil(leads / lps - 1e-9) - (cap.setters || 0), 0);
      gapC = Math.max(Math.ceil(calls / cpc - 1e-9) - (cap.closers || 0), 0);
      capCost = gapS * (cap.setter_cost_monthly || 0) +
                gapC * (cap.closer_cost_monthly || 0);
    }
    var seats = (cap ? (cap.setters || 0) + (cap.closers || 0) : 0) + gapS + gapC;
    var tooling = (agg.tooling || 0) + (agg.tooling_per_seat || 0) * seats;
    var acq = spend + comm + bounties + monthlyFixed + capCost + tooling;
    var cac = clients >= 0.01 ? acq / clients : null;
    var cacSpendOnly = clients >= 0.01 ? spend / clients : null;
    var ltgpPerClient = agg.contract_avg * agg.margin_avg;
    var capExtra = gapS + gapC;
    var capLabel = capExtra
      ? ('sales headcount needed at this volume: +' + capExtra +
         (cap && cap.hire_from ? ' (from ' + cap.hire_from + ')' : ''))
      : "sales headcount: today's team covers this volume";
    /* payback: the month the mix-weighted cash schedule covers the all-in
       cost of winning the client */
    var payback = null;
    if (cac && agg.cash_curve && agg.cash_curve.length) {
      for (var i = 0; i < agg.cash_curve.length; i++) {
        if (agg.cash_curve[i] * agg.contract_avg >= cac) { payback = i + 1; break; }
      }
    }
    return {
      spend: spend, cpl_effective: eff, leads: leads, calls: calls,
      qualified_sets: qualified,
      shows: shows, clients: clients, cash_this_month: cashNow,
      cash_over_term: cashTerm, mrr_added: mrr,
      commissions_over_term: comm, bounties: bounties,
      monthly_fixed: monthlyFixed,
      headcount_extra: capExtra, headcount_cost: capCost,
      tooling_total: tooling,
      cost_card: [
        {label: 'ad spend', amount: spend, kind: 'variable'},
        {label: 'commissions on closes', amount: comm, kind: 'variable'},
        {label: 'set bounties (qualified sets)', amount: bounties, kind: 'variable'},
        {label: 'manager retainer + bonuses', amount: monthlyFixed, kind: 'fixed'},
        {label: capLabel, amount: capCost, kind: 'steps with volume'},
        {label: 'sales tooling', amount: tooling,
         kind: (agg.tooling_per_seat ? 'fixed base + per-seat' : 'fixed')}
      ],
      cac: cac, cac_spend_only: cacSpendOnly,
      ltv_cac: cac ? agg.contract_avg / cac : null,
      ltgp_per_client: ltgpPerClient,
      ltgp_cac: cac ? ltgpPerClient / cac : null,
      payback_months: payback
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

  /* REQUIRED-RATE MODE (brief 36's missing half).
     Counts already go both ways: requiredSpend() turns a wanted count into
     the spend it takes. What you could not ask was the other question —
     "what close rate do I need to get 8 clients out of the consults I have
     already booked?"

     Editing a stage COUNT solves the rate of THAT stage, holding everything
     upstream where it is:  required = wanted ÷ the stage above.

     stage: calls|shows|clients   (the three stages that have a rate)
     Returns the required rate, the measured one, the gap in POINTS, and a
     plausibility flag:
       impossible — above 100%: you cannot close more deals than consults
       stretch    — outside the measured band: possible, never yet done
       ok         — inside the band we have actually achieved                */
  var RATE_OF = { calls: 'set', shows: 'show', clients: 'close' };

  function upstreamCount(stage, chained) {
    if (stage === 'calls') return chained.leads;
    if (stage === 'shows') return chained.calls;
    if (stage === 'clients') return chained.shows;
    return null;
  }

  function requiredRate(stage, wantedCount, spend, cpl, rates, agg, curve, band) {
    var key = RATE_OF[stage];
    if (!key) return null;
    var base = chain(spend, cpl, rates, agg, curve);
    var above = upstreamCount(stage, base);
    if (!above || above <= 0) {
      return { stage: stage, rate_key: key, required: null, measured: rates[key],
               above: above || 0, flag: 'impossible',
               note: 'there is nothing upstream to convert' };
    }
    var required = wantedCount / above;
    var measured = rates[key];
    var lo = band && band[key] ? band[key][0] : null;
    var hi = band && band[key] ? band[key][1] : null;
    var flag = 'ok';
    if (required > 1) flag = 'impossible';
    else if (hi !== null && required > hi) flag = 'stretch';
    else if (lo !== null && required < lo) flag = 'stretch';
    return {
      stage: stage, rate_key: key,
      required: required, measured: measured,
      above: above, wanted: wantedCount,
      points: (required - measured) * 100,
      flag: flag,
      note: (flag === 'impossible' && required > 1)
        ? ('not achievable from ' + Math.round(above) + ' ' +
           (stage === 'clients' ? 'booked consults' : 'upstream') +
           ' — that would need ' + Math.round(required * 100) + '%')
        : (flag === 'stretch'
           ? 'beyond the band we have measured — possible, never yet done'
           : 'inside the band we have actually achieved')
    };
  }

  /* Applying a solved rate returns a FULL chain with that one rate replaced
     and everything upstream untouched — so the page can show the knock-on
     downstream without a second formula. */
  function chainWithRate(stage, wantedCount, spend, cpl, rates, agg, curve) {
    var sol = requiredRate(stage, wantedCount, spend, cpl, rates, agg, curve, null);
    if (!sol || sol.required === null) return null;
    var next = {set: rates.set, show: rates.show, close: rates.close};
    next[sol.rate_key] = sol.required;
    return { solution: sol, chained: chain(spend, cpl, next, agg, curve),
             rates: next };
  }

  return { effectiveCpl: effectiveCpl, chain: chain, requiredSpend: requiredSpend,
           requiredRate: requiredRate, chainWithRate: chainWithRate,
           RATE_OF: RATE_OF };
}));
