"""Test-lead classification: strong/borderline/override behavior (review-first, one engine)."""
import test_leads as tl

CTX = ({"staff_tokens": ["rydel", "jaspher"], "test_tokens": ["test"], "enabled": True}, {})


def c(email="", name="", business="", tags="", ctx=CTX):
    return tl.classify(email=email, name=name, business=business, tags=tags, source="t", ctx=ctx)


def test_strong_staff_and_test_matches():
    assert c(name="Jaspher Test")["is_test"]                      # whole-word test + staff
    assert c(email="jaspher@servedmarketing.com.au")["is_test"]   # staff token in email
    assert c(email="ryd@x.com", name="Curry Delights")["is_test"] is False  # 'rydel' NOT in 'ryd'
    assert c(email="curryrydel@gmail.com", name="Curry Delights")["is_test"]  # rydel in email
    assert c(email="test@gmail.com", name="Try")["is_test"]       # test-shaped email
    assert c(name="Test Jas")["is_test"]


def test_borderline_defaults_to_keep():
    r = c(name="Testaccio Trattoria")           # real venue, substring 'test'
    assert r["is_test"] is False and r["strength"] == "borderline"
    r2 = c(email="attestation@venue.com", name="Mario Rossi")
    assert r2["is_test"] is False and r2["strength"] == "borderline"


def test_clean_real_lead():
    assert c(email="mario@trattoria.com", name="Mario Rossi", business="Bella Napoli")["is_test"] is False


def test_override_outranks_rules():
    key = tl.lead_key("t", "curryrydel@gmail.com", "Curry Delights")
    ctx = (CTX[0], {key: {"is_test": False, "by": "rydel", "at": "2026-07-29"}})
    # rule says test (rydel in email) but the override says real → real wins
    r = tl.classify(email="curryrydel@gmail.com", name="Curry Delights", source="t", ctx=ctx)
    assert r["is_test"] is False and r["source_of_truth"] == "override"


def test_clean_tracker_rows_removes_test(monkeypatch):
    monkeypatch.setattr(tl, "load_ctx", lambda: CTX)
    rows = [["Input Date", "Lead Name", "Email", "Business Name"],
            ["2026-06-01", "Mario Rossi", "mario@x.com", "Bella Napoli"],
            ["2026-06-02", "Jaspher Test", "jaspher@servedmarketing.com.au", ""],
            ["2026-06-03", "Anna Lee", "anna@y.com", "Testaccio Trattoria"]]  # borderline biz → KEEP
    clean = tl.clean_tracker_rows(rows)
    names = [r[1] for r in clean[1:]]
    assert "Mario Rossi" in names and "Anna Lee" in names and "Jaspher Test" not in names
    assert len(clean) == 3  # header + 2 kept
