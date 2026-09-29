"""#170 — renewal + completion measured from payment history."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import csm_baselines as B

D = dt.date
TODAY, START = D(2026, 9, 29), D(2025, 3, 1)


def _monthly(first, n, amt):
    out, d = [], first
    for _ in range(n):
        out.append((d, amt))
        d = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=first.day)
    return out


def test_renewal_counts_churners_and_downgrades():
    charges = {
        "Renewer": _monthly(D(2025, 10, 1), 9, 3355.0),       # kept paying
        "Churner": _monthly(D(2025, 11, 1), 4, 3355.0),       # stopped mid-term
        "Downgrade": _monthly(D(2025, 10, 5), 6, 3355.0) + [(D(2026, 4, 10), 800.0)],
        "Websub": _monthly(D(2025, 10, 1), 12, 219.0),
        "Old": _monthly(D(2025, 3, 5), 18, 3355.0),            # left-censored
    }
    deals = {"Renewer": {"offer": "Growth Pro", "close_date": D(2025, 10, 1), "contract": 18300},
             "Churner": {"offer": "Growth Pro", "close_date": D(2025, 11, 1), "contract": 18300},
             "Downgrade": {"offer": "Growth Pro", "close_date": D(2025, 10, 5), "contract": 18300},
             "Websub": {"offer": "Web Sub"},
             "Old": {"offer": "Growth Pro"}}
    r = B.measure_from_payments(charges, deals, TODAY, START)
    got = {x["client"]: x["renewed"] for x in r["renewal"]["rows"]}
    assert got == {"Renewer": True, "Churner": False, "Downgrade": False}
    assert r["renewal"]["value"] == 33.3 and r["renewal"]["n"] == 3
    lo, hi = r["renewal"]["ci95"]
    assert lo < 33.3 < hi                                   # honest about n=3
    assert {e["client"] for e in r["renewal"]["excluded"]} == {"Websub", "Old"}
    # completion: Churner paid 4 of 6 months → dollar-weighted below 100
    assert r["completion"]["n"] == 3 and r["completion"]["value"] < 100


def test_wilson_is_bounded():
    assert B.wilson(0, 0) is None
    lo, hi = B.wilson(5, 5)
    assert hi == 100.0 and lo > 40


def test_a_ruled_non_retainer_client_is_excluded_but_counted():
    """Rydel, 29 Sep: Warners At The Bay is photography work — cash attached,
    excluded from renewal and completion."""
    import kv_store
    import client_receipts as CRx
    kv_store.delete(CRx.K_MAP)
    assert CRx.confirm_contact("Warners At The Bay", "Warners At The Bay",
                               words="photography work, not a marketing retainer",
                               exclude_from_measurement=True, kind="photography")["ok"]
    charges = {"Warners At The Bay": _monthly(D(2025, 10, 1), 9, 3355.0)}
    deals = {"Warners At The Bay": {"offer": "Growth Pro", "close_date": D(2025, 10, 1),
                                    "contract": 18300}}
    r = B.measure_from_payments(charges, deals, TODAY, START)
    assert r["renewal"]["n"] == 0
    assert "not a marketing retainer" in r["renewal"]["excluded"][0]["why"]
    kv_store.delete(CRx.K_MAP)
