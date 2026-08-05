"""
Voice-driven navigation + the self-model fix (AD_SECTION_VOICE_NAV_REPORT).

Rails: "show me X" is deterministic navigation — it never reaches the model; every
navigation pairs an action with a spoken confirmation; entity gating (ambiguous asks,
nonexistent refuses, NO action either way); the timeline channel gets the honest
cross-surface answer with zero actions; window/verdict/sort commands are thread-aware
via the ui context; the SSE stream carries `nav` events on the deterministic path; the
persona knows she's embedded in the dashboard and the false "text and voice only"
self-model is dead.
"""
from __future__ import annotations

import nav_registry as R
import nav_router as N


def _no_engine(monkeypatch):
    monkeypatch.setattr(N, "_engine", lambda days=30: None)
    monkeypatch.setattr(N, "_cached_result", lambda days=30: None)


# ── the ad board ─────────────────────────────────────────────────────────────

def test_show_me_the_ad_dashboard_navigates(monkeypatch):
    _no_engine(monkeypatch)
    reply, actions, handled = N.handle("show me the ad dashboard right now"[:28])
    assert handled and actions == [R.navigate("ad_tracking")]
    assert reply and "text and voice" not in reply.lower()


def test_variants_all_navigate(monkeypatch):
    _no_engine(monkeypatch)
    for phrase in ("show me the ad dashboard", "open the ads board", "pull up the ad tracking section",
                   "show me the scoreboard", "back to the ad board", "go to the attribution dashboard"):
        _r, actions, handled = N.handle(phrase)
        assert handled and actions and actions[0]["target"] == "ad_tracking", phrase


def test_confirmation_carries_value_when_engine_warm(monkeypatch):
    monkeypatch.setattr(N, "_cached_result", lambda days=30: {
        "totals": {"attribution_rate_pct": 86.2},
        "creatives": [{"tier": "ad", "label": "Creative A", "spend": 900.0,
                       "leads": 17, "closes": 1}]})
    reply, actions, handled = N.handle("show me the ad board")
    assert handled and "86.2%" in reply and "Creative A" in reply


def test_timeline_channel_gets_honest_cross_surface_answer(monkeypatch):
    _no_engine(monkeypatch)
    reply, actions, handled = N.handle("show me the ad dashboard", channel="timeline")
    assert handled and actions == []
    assert "finance dashboard" in reply
    assert "text and voice" not in reply.lower() and "can't display" not in reply.lower()


# ── windows / filters / sort (thread-aware) ──────────────────────────────────

def test_window_on_ad_board_uses_section_selector(monkeypatch):
    _no_engine(monkeypatch)
    reply, actions, handled = N.handle("filter to 60 days", ui={"section": "ad_tracking"})
    assert handled and actions == [R.filter_action("ad_tracking", window=60)]


def test_window_off_board_sets_global_bar(monkeypatch):
    _no_engine(monkeypatch)
    reply, actions, handled = N.handle("set the window to 14 days", ui={"section": "cash"})
    assert handled and actions == [R.set_window(14)]


def test_invalid_window_asks_no_action(monkeypatch):
    _no_engine(monkeypatch)
    reply, actions, handled = N.handle("filter to 45 days", ui={"section": "ad_tracking"})
    assert handled and actions == [] and "30, 60 or 90" in reply


def test_just_the_kills_thread_aware(monkeypatch):
    _no_engine(monkeypatch)
    r1, a1, h1 = N.handle("just the ones to kill", ui={"section": "ad_tracking"})
    assert h1 and a1 == [R.filter_action("ad_tracking", verdict="KILL")]
    r2, a2, h2 = N.handle("show me just the kills", ui={"section": "cash"})
    assert h2 and a2[0] == R.navigate("ad_tracking") \
        and a2[1] == R.filter_action("ad_tracking", verdict="KILL")


def test_sort_by_cash_on_board(monkeypatch):
    _no_engine(monkeypatch)
    reply, actions, handled = N.handle("now sort by cash", ui={"section": "ad_tracking"})
    assert handled and actions == [R.filter_action("ad_tracking", sort="cash")]


# ── pages + anchors ──────────────────────────────────────────────────────────

def test_open_leads_page_and_anchor_sections(monkeypatch):
    _no_engine(monkeypatch)
    r, a, h = N.handle("open the leads page")
    assert h and a == [R.navigate("leads_page")]
    r, a, h = N.handle("show me the funnel")
    assert h and a == [R.navigate("funnel")]
    r, a, h = N.handle("take me to cash")
    assert h and a == [R.navigate("cash")]


# ── creative drill: entity-gated ─────────────────────────────────────────────

def _engine_with(monkeypatch, creatives):
    monkeypatch.setattr(N, "_engine", lambda days=30: {"creatives": creatives})
    monkeypatch.setattr(N, "_cached_result", lambda days=30: None)


def test_drill_unique_match_navigates_with_value(monkeypatch):
    _engine_with(monkeypatch, [{
        "tier": "ad", "label": "Served 2026 Q1 ADS 36 - Rydel AD B",
        "creative_key": "served 2026 q1 ads 36 - rydel ad b", "verdict": "DOUBLE DOWN",
        "leads": 8, "closes": 3, "cash": 18105.0, "spend": 299.01,
        "gates": {"gate": "ok"}}])
    reply, actions, handled = N.handle("show me Ad B")
    assert handled and actions[0]["type"] == "navigate" \
        and actions[0]["params"]["drill"] is True
    assert "double down" in reply.lower() and "$18,105" in reply


def test_drill_ambiguous_asks_no_action(monkeypatch):
    _engine_with(monkeypatch, [
        {"tier": "ad", "label": "Ad B v1", "creative_key": "ad b v1", "leads": 1,
         "closes": 0, "cash": 0, "spend": 1, "gates": {}},
        {"tier": "ad", "label": "Ad B v2", "creative_key": "ad b v2", "leads": 1,
         "closes": 0, "cash": 0, "spend": 1, "gates": {}}])
    reply, actions, handled = N.handle("open Ad B")
    assert handled and actions == [] and "which one" in reply.lower()


def test_drill_nonexistent_refuses_no_action(monkeypatch):
    _engine_with(monkeypatch, [])
    reply, actions, handled = N.handle("show me the Zebulon VSL ad")
    assert handled and actions == []
    assert "won't guess" in reply


# ── capability + self-model ──────────────────────────────────────────────────

def test_what_can_you_show_me_lists_real_targets(monkeypatch):
    _no_engine(monkeypatch)
    reply, actions, handled = N.handle("what can you show me?")
    assert handled and "ad tracking board" in reply and "funnel" in reply
    reply_t, a_t, h_t = N.handle("what can you show me?", channel="timeline")
    assert h_t and "finance dashboard" in reply_t


def test_persona_self_model_updated():
    import dashboard.chat as chat
    assert "EMBEDDED IN the finance dashboard" in chat.BASE_PERSONA
    assert "never say that" in chat.BASE_PERSONA        # the false line is named + banned
    assert "text and voice only\" — never" in chat.BASE_PERSONA or \
           'text and voice only' in chat.BASE_PERSONA


# ── the SSE nav event on the deterministic path ──────────────────────────────

def test_stream_carries_nav_event(monkeypatch):
    import importlib
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    from app import app
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/dashboard/login", data={"token": "test-dash-token"})
    import nav_router
    monkeypatch.setattr(nav_router, "_engine", lambda days=30: None)
    monkeypatch.setattr(nav_router, "_cached_result", lambda days=30: None)
    resp = client.post("/dashboard/api/chat-stream",
                       json={"history": [{"role": "user", "content": "show me the ad dashboard"}],
                             "voice": False, "ui": {"section": "cash"}})
    body = resp.get_data(as_text=True)
    assert "event: nav" in body
    assert '"target": "ad_tracking"' in body
    assert "event: done" in body
