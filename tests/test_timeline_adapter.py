"""Universal advisor P2: timeline handlers — entity gates, verbatim grounding, fail-honest."""
import timeline_adapter as TA

OV = {"clients": [
        {"client_key": "pizzicotto", "client_name": "Pizzicotto", "health_score": 82},
        {"client_key": "panini-co", "client_name": "Panini Co", "health_score": 61},
        {"client_key": "panini-bar", "client_name": "Panini Bar", "health_score": 70}],
      "freshness": {"hours_since_sync": 2.0, "stale": False}}
DETAIL = {"onboarding_status": "week 3 of 6", "health": {"score": 82, "light": "green"},
          "summary": {"open_tasks": 14, "overdue": 2},
          "complaints": [{"created_at": "2026-08-01T10:00:00", "kind": "complaint"}],
          "events": [{"name": "Trivia Night", "event_date": "2026-08-15"}]}
RISK = {"overdue": {"count": 7, "tasks": [{"client_name": "Panini Co"}] * 4 + [{"client_name": "Pizzicotto"}] * 3},
        "stale": {"count": 2, "tasks": []}, "at_risk": {"count": 1, "tasks": []}}
SIGNALS = {"signals": [
    {"client_key": "pizzicotto", "kind": "complaint", "severity": "High",
     "description": "Food arrived cold at the launch", "created_at": "2026-08-02T09:00:00"},
    {"client_key": "panini-co", "kind": "positive",
     "description": "Loved the reel", "created_at": "2026-07-01T09:00:00"}]}


def _wire(monkeypatch, mapping):
    monkeypatch.setenv("TIMELINE_BRIDGE_URL", "https://tl.example")
    monkeypatch.setenv("EDITH_BRIDGE_SECRET", "s")
    monkeypatch.setattr(TA, "_get", lambda path, params=None: mapping.get(path.split("?")[0]))
    TA._cache.clear()


def test_client_exact_match_verbatim(monkeypatch):
    _wire(monkeypatch, {"/bridge/data/overview": OV,
                        "/bridge/data/client/pizzicotto": DETAIL})
    r, h = TA.handle_timeline_client("where's Pizzicotto's onboarding at?")
    assert h and "week 3 of 6" in r and "82" in r and "14 open tasks" in r and "2 overdue" in r
    assert "Timeline synced 2.0 h ago" in r


def test_client_ambiguous_asks(monkeypatch):
    _wire(monkeypatch, {"/bridge/data/overview": OV})
    r, h = TA.handle_timeline_client("how's Panini doing?")
    assert h and "which one" in r.lower() and "Panini Co" in r and "Panini Bar" in r


def test_client_unknown_not_invented(monkeypatch):
    _wire(monkeypatch, {"/bridge/data/overview": OV})
    r, h = TA.handle_timeline_client("how's Nonexistent Cafe tracking?")
    assert h and "don't see a client" in r and "guess" in r


def test_unreachable_fail_honest(monkeypatch):
    _wire(monkeypatch, {})
    r, h = TA.handle_timeline_risk("what's overdue right now?")
    assert h and "can't reach the Timeline bridge" in r and "won't guess" in r


def test_not_configured_passes_to_model(monkeypatch):
    monkeypatch.delenv("TIMELINE_BRIDGE_URL", raising=False)
    r, h = TA.handle_timeline_client("how's Pizzicotto doing?")
    assert not h and r is None


def test_risk_counts_verbatim(monkeypatch):
    _wire(monkeypatch, {"/bridge/data/overview": OV, "/bridge/data/risk": RISK})
    r, h = TA.handle_timeline_risk("what is overdue or stalled right now?")
    assert h and "7 overdue" in r and "Panini Co 4" in r and "2 stale" in r


def test_signals_week_filter_and_praise_split(monkeypatch):
    import helpers
    import datetime as _dt
    # freeze the clock inside the fixture's week — the complaint is dated
    # 2026-08-02, so an unfrozen "today − 7d" cutoff made this test start
    # failing every day after 2026-08-09 (triple-sweep calendar-flake fix)
    monkeypatch.setattr(helpers, "today_sydney", lambda: _dt.date(2026, 8, 8))
    _wire(monkeypatch, {"/bridge/data/overview": OV, "/bridge/data/signals": SIGNALS})
    r, h = TA.handle_timeline_signals("any complaints this week?")
    assert h and "Food arrived cold" in r and "severity High" in r and "Loved the reel" not in r
    TA._cache.clear()
    r2, h2 = TA.handle_timeline_signals("any praise on record?")
    assert h2 and "Loved the reel" in r2 and "Food arrived cold" not in r2


def test_ramble_does_not_trip_handlers(monkeypatch):
    _wire(monkeypatch, {"/bridge/data/overview": OV})
    for msg in ("I was thinking about the offer structure for hospitality clients",
                "revenue looked decent yesterday honestly"):
        assert TA.handle_timeline_client(msg)[1] is False
        assert TA.handle_timeline_risk(msg)[1] is False
        assert TA.handle_timeline_events(msg)[1] is False


def test_no_write_paths_in_adapter():
    import inspect
    src = inspect.getsource(TA)
    for verb in ("requests.post", "requests.put", "requests.patch", "requests.delete"):
        assert verb not in src


def test_alias_confirm_no_longer_swallows_questions():
    """3 Aug 2026: 'What is overdue?' was captured as payer='What' by the alias handler
    (pre-tier-2), starving every data handler. Question openers must fall through."""
    import stripe_reconcile as SR
    for q in ("What is overdue or stalled right now?",
              "Where is Butler's Cucina's onboarding at?",
              "How is Nonexistent Bistro tracking?",
              "What is our runway looking like"):
        r, h = SR.handle_alias_confirm(q)
        assert not h, q


def test_alias_confirm_still_learns_real_aliases(monkeypatch):
    import stripe_reconcile as SR
    monkeypatch.setattr(SR, "_known_businesses", lambda: {SR._norm("Masala Factory")})
    learned = []
    monkeypatch.setattr(SR, "learn_alias", lambda p, b: learned.append((p, b)))
    r, h = SR.handle_alias_confirm("Jagjeet Singh is Masala Factory")
    assert h and learned and "auto-match" in r


def test_pronouns_never_entity_match(monkeypatch):
    _wire(monkeypatch, {"/bridge/data/overview": OV})
    for msg in ("how is it doing overall?", "how's that going?", "how is the business tracking?"):
        assert TA.handle_timeline_client(msg)[1] is False, msg


def test_full_picture_phrasing_and_finance_join(monkeypatch):
    import sys, types
    _wire(monkeypatch, {"/bridge/data/overview": OV, "/bridge/data/client/pizzicotto": DETAIL})
    snap_mod = types.ModuleType('snapshot')
    snap_mod.load_persisted = lambda: {"active_clients": {"active": [
        {"name": "Pizzicotto", "current_mrr": 2500.0, "cash_collected": 5000.0,
         "package": "Firestarter", "status": "Active", "awaiting_stripe": False}]}}
    monkeypatch.setitem(sys.modules, 'snapshot', snap_mod)
    r, h = TA.handle_timeline_client("Full picture on Pizzicotto please — delivery and money.")
    assert h and "week 3 of 6" in r
    assert "Finance side (CFO snapshot): MRR $2500.0" in r and "Firestarter" in r
