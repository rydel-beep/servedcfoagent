"""
dashboard/routes.py
-------------------
Flask blueprint for the Jarvis CFO dashboard.
"""
from __future__ import annotations

import json
import logging
import os

from flask import (
    Blueprint, render_template, request, jsonify, make_response, redirect,
    url_for, Response, stream_with_context, session,
)

from dashboard.auth import (require_auth, require_owner, is_owner,
                            DASHBOARD_TOKEN, COOKIE_NAME, COOKIE_MAX_AGE)
from dashboard.chat import chat as chat_fn, chat_stream as chat_stream_fn
from config import CFO_REFRESH_KEY

logger = logging.getLogger(__name__)

# Cache-bust static assets per deploy: Railway exposes the git sha; fall back
# to process start time so every restart still busts.
import time as _time
_ASSET_VERSION = (os.environ.get("RAILWAY_GIT_COMMIT_SHA", "") or str(int(_time.time())))[:12]

bp = Blueprint(
    "dashboard",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="static",
)


def _repetition_failure(reply: str, history: list, user_msg: str) -> bool:
    """A drafted deterministic reply that is VERBATIM-identical to a recent assistant reply, in
    response to a DIFFERENT user message, is a routing failure (the incident's canned-line re-fire).
    Return True → suppress it and fall to the thread-aware/model path. Re-asking the SAME question is
    fine (answered consistently), so we compare the user messages too."""
    if not reply:
        return False
    def _n(s):
        return " ".join((s or "").lower().split())
    r = _n(reply)
    users = [m.get("content") for m in (history or []) if m.get("role") == "user"]
    prev_user = _n(users[-2]) if len(users) >= 2 else ""   # the message before the current one
    if _n(user_msg) == prev_user:
        return False   # genuinely the same question re-asked → a consistent repeat is acceptable
    for m in reversed(history or []):
        if m.get("role") == "assistant":
            return _n(m.get("content")) == r   # identical to the immediately prior answer → failure
    return False


def _edith_cfg_json() -> str:
    import json as _json
    from config import PICOVOICE_ACCESS_KEY
    wake_ppn = os.path.exists(os.path.join(
        os.path.dirname(__file__), "static", "wake", "hey_edith_wasm.ppn"))
    return _json.dumps({
        "picovoiceKey": PICOVOICE_ACCESS_KEY,   # authed page only, by design
        "wakePpnPresent": wake_ppn,
        "wakePpnPath": "/dashboard/static/wake/hey_edith_wasm.ppn",
    })


@bp.route("/")
@require_auth
def index():
    """RETIRED as the landing — TODAY is the landing now (the finish line).

    The old landing's job was to be an index of surfaces; the persistent nav
    does that on every page, and TODAY answers the question the index never
    could. The route stays as a REDIRECT so no link anywhere breaks, and the
    page itself remains reachable at /dashboard/landing while the new one
    beds in."""
    return redirect(url_for("dashboard.today_page"))


@bp.route("/landing")
@require_auth
def landing_page():
    """The previous landing — SERVER-RENDERED TRUTH (dashboard hardening).

    The executive top (≤ 8 tiles + one verdict line) and the summary cards
    are computed server-side from the one engine's kv-cached blocks and
    written INTO the HTML. JS enhances (drawers, refresh); it never fills a
    headline. With JS disabled the page still reads correctly."""
    from snapshot import load_persisted
    from dashboard import exec_top
    from dashboard.auth import is_owner
    snap = load_persisted()
    try:
        owner = is_owner()
    except Exception:
        owner = False
    # CSM card honors DISCREET MODE (#146): owner AND discreet-off
    try:
        csm_visible = owner and not bool(session.get(_CSM_DISCREET_KEY))
    except Exception:
        csm_visible = False
    try:
        exec_data = exec_top.build(snap, owner, csm_visible=csm_visible)
    except Exception as e:  # the landing page NEVER 500s into a blank
        logger.exception("exec_top build failed")
        exec_data = {"tiles": [], "cards": [],
                     "verdict": {"line": f"executive top failed honestly: {str(e)[:120]}",
                                 "state": "degraded"},
                     "snapshot_age": "unknown", "today": ""}
    degraded_count = len((snap or {}).get("degraded") or [])
    age = exec_data.get("snapshot_age") or "unknown"
    status_text = (f"{degraded_count} degraded · {age}" if degraded_count
                   else f"healthy · {age}")
    resp = make_response(render_template(
        "dashboard.html", exec=exec_data, degraded_count=degraded_count,
        status_text=status_text, edith_cfg=_edith_cfg_json(),
        defs_json=_defs_json(), asset_v=_ASSET_VERSION))
    # the HTML carries live values — it must never be served from cache
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ── THE SHELL: nav + breadcrumbs + ⌘K, on every page ────────────────────────

@bp.app_context_processor
def _inject_shell():
    """Make the shell available to EVERY template, so the nav is on every
    page without each route having to remember it. Memoized per request and
    skipped for API endpoints, so it costs one cheap kv read per page."""
    from flask import g as _g
    path = request.path or ""
    if "/api/" in path:
        return {}
    cached = getattr(_g, "_shell_ctx", None)
    if cached is not None:
        return cached
    active = ""
    if path.startswith("/ads"):
        active = "ads"
    elif "/scale" in path:
        active = "plan"
    elif path.rstrip("/").endswith("/sales"):
        active = "sales"
    elif path.rstrip("/").endswith("/today"):
        active = "today"
    elif path.rstrip("/").endswith("/csm"):
        active = "csm"
    elif "/view/" in path:
        from dashboard.shell import AREA_PARENT
        active = AREA_PARENT.get(path.rsplit("/", 1)[-1], "")
    ctx = _shell(active)
    _g._shell_ctx = ctx
    return ctx


def _shell(active: str = "", crumbs=None) -> dict:
    """Template context for the persistent shell. Cheap (kv reads only) and
    guarded — a page must never fail to render because its nav could not
    count something."""
    from dashboard import shell as _shell_mod
    import json as _json
    try:
        nav = _shell_mod.nav_context(active, crumbs)
    except Exception as e:  # noqa: BLE001
        logger.warning("nav context failed: %s", e)
        nav = {"links": [], "crumbs": [], "health_dot": "amber",
               "health_why": f"nav degraded: {str(e)[:70]}", "actor": "",
               "owner": False, "ad_only": False, "active": active}
    try:
        targets = _shell_mod.palette_targets(nav.get("owner", False),
                                             nav.get("ad_only", False))
    except Exception as e:  # noqa: BLE001
        logger.warning("palette targets failed: %s", e)
        targets = []
    # THE EDITH DOCK (#160): owner-only, kill-switchable without a deploy,
    # and discreet-mode aware. The template renders an inert pill; the script
    # loads after first paint inside its own boundary.
    dock = {"enabled": False, "discreet": False}
    try:
        import os
        if nav.get("owner") and os.environ.get("EDITH_DOCK", "on").lower() not in (
                "off", "0", "false", "no"):
            dock["enabled"] = True
            dock["discreet"] = bool(session.get(_CSM_DISCREET_KEY))
    except Exception as e:  # noqa: BLE001
        logger.warning("edith dock context failed: %s", e)
    return {"nav": nav,
            "palette_json": _json.dumps(targets).replace("</", "<\\/"),
            "edith_dock": dock,
            "edith_dock_json": _json.dumps(dock).replace("</", "<\\/"),
            # the ONE definitions registry, so every shell page can explain
            # itself — encoded once per process, not per request
            "defs_json": _defs_json()}


# ── TODAY — the landing: "are we winning?" in ten seconds ───────────────────

@bp.route("/today")
@require_auth
def today_page():
    """TODAY. Eight server-rendered tiles, one verdict line, three short
    lists — and nothing else, by rule.

    Every tile is MOVED from the engines that already own it (six straight
    out of exec_top), never recomputed. The request path reads kv caches
    only; no external call happens on page load."""
    from snapshot import load_persisted
    from dashboard import today as today_mod
    from dashboard.auth import is_owner
    try:
        owner = is_owner()
    except Exception:
        owner = False
    snap = load_persisted()
    try:
        data = today_mod.build(snap, owner)
    except Exception as e:  # noqa: BLE001 — TODAY never 500s into a blank
        logger.exception("today build failed")
        data = {"tiles": [], "pulse": [], "rulings": {"hidden": True, "items": []},
                "since": {"show": False},
                "verdict": {"line": f"today failed honestly: {str(e)[:120]}",
                            "state": "degraded", "href": "/dashboard/scale/travelling",
                            "gap": "", "age": "unknown"},
                "today": "", "snapshot_age": "unknown",
                "unmatched": {"count": 0, "total": 0, "rows": [],
                              "available": False,
                              "note": "today failed before the payment scan"},
                "new_closes": [], "new_closes_total": 0}
    resp = make_response(render_template(
        "today.html", today=data, asset_v=_ASSET_VERSION, owner=owner,
        **_shell("today")))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ── THE SYSTEM PAGE (#160) — stored results only, no work on load ──────────

@bp.route("/system")
@require_auth
def system_page_view():
    """SERVER-RENDERED FROM STORED RESULTS. Loading this page runs no scan,
    no sync and no heavy query — Phase 0 found two sections filled by inline
    fetch() after load and the whole page inheriting a ten-minute
    re-render."""
    import system_page
    try:
        sys_data = system_page.build()
    except Exception as e:  # noqa: BLE001
        logger.exception("system page build failed")
        sys_data = {"at": "", "poll_seconds": 60,
                    "headline": {"state": "degraded",
                                 "line": f"the system page failed honestly: {str(e)[:120]}"},
                    "sections": {k: {"rows": [], "error": str(e)[:120]}
                                 for k in ("sources", "checks", "jobs", "errors", "gates")},
                    "run_state": {"running": False}}
    resp = make_response(render_template("system.html", sys=sys_data,
                                         asset_v=_ASSET_VERSION, **_shell("system")))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/system", methods=["GET"])
@require_auth
def api_system():
    """The poll payload — the same stored results, nothing recomputed."""
    import system_page
    return jsonify(system_page.build())


@bp.route("/api/system/run-checks", methods=["GET", "POST"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_system_run_checks():
    """GET = where the run is up to. POST = start one, if none is running and
    the rate limit allows. Owner-only: these call outside services."""
    import system_page
    if request.method == "GET":
        return jsonify(system_page.run_state())
    from dashboard.auth import current_actor
    return jsonify(system_page.start_check_run(
        (current_actor() or {}).get("user") or "owner"))


@bp.route("/api/freshness", methods=["GET"])
@require_auth
def api_freshness():
    """Per-source freshness against the stated contract."""
    import freshness
    return jsonify(freshness.sources())


@bp.route("/api/refresh-now", methods=["POST"])
@require_owner
def api_refresh_now():
    """REFRESH NOW (#160). Pulls what can safely be pulled, then rebuilds the
    engine blocks the tiles actually read — the half neither old button did.
    Xero is never force-pulled; the reply says when its next pull is."""
    import freshness
    from dashboard.auth import current_actor
    body = request.get_json(silent=True) or {}
    res = freshness.refresh_now(
        (current_actor() or {}).get("user") or "owner",
        str(body.get("what") or "all"))
    return jsonify(res), (429 if res.get("rate_limited") else 200)


# ── MONEY THAT LANDED WITHOUT A NAME, AND CLOSES NOBODY LOGGED (#161) ──────

@bp.route("/api/unmatched", methods=["GET"])
@require_auth
def api_unmatched_payments():
    """The unmatched-payments panel. Stored results only — a page load never
    calls Stripe. ?full=1 returns every row instead of the panel's eight."""
    import unmatched_payments as UP
    if request.args.get("full"):
        return jsonify(UP.latest())
    return jsonify(UP.panel())


@bp.route("/api/clients/names", methods=["GET"])
@require_auth
def api_client_names():
    """Names only — the picker's list. Roster venues + tracker businesses."""
    import unmatched_payments as UP
    return jsonify({"names": UP.client_names()})


@bp.route("/api/unmatched/confirm", methods=["POST"])
@require_owner
def api_unmatched_confirm():
    """Rydel's word: this payer pays for this client. Writes the alias,
    journals who said so and which charge proved it, re-runs the match and
    rebuilds what the tiles read — so the number moves now, not in two hours.

    OWNER-ONLY: attaching money to a client is a money-truth action."""
    import unmatched_payments as UP
    from dashboard.auth import current_actor
    body = request.get_json(silent=True) or {}
    res = UP.confirm(str(body.get("payer") or ""), str(body.get("client") or ""),
                     (current_actor() or {}).get("user") or "owner",
                     body.get("charge_id"))
    return jsonify(res), (200 if res.get("ok") else 400)


@bp.route("/api/closes/pending", methods=["GET"])
@require_auth
def api_closes_pending():
    """Closes any source can see, with provenance and what is still missing."""
    import close_detect
    return jsonify(close_detect.latest())


@bp.route("/api/closes/confirm", methods=["POST"])
@require_owner
def api_closes_confirm():
    """Owner confirms a DETECTED close — the date is recorded through the
    sanctioned derivation lane with its evidence, and the engine blocks
    rebuild immediately. Never creates a close without evidence: the entry
    must already exist in the detection ledger."""
    import close_detect
    from dashboard.auth import current_actor
    body = request.get_json(silent=True) or {}
    res = close_detect.confirm(str(body.get("key") or ""),
                               (current_actor() or {}).get("user") or "owner")
    return jsonify(res), (200 if res.get("ok") else 400)


# ── SALES COMP RULES (#159) — OWNER ONLY, every edit journaled ──────────────

@bp.route("/api/comp/rules", methods=["GET"])
@require_owner
def api_comp_rules():
    """The rulebook: the current version up front, the reconstructed history
    behind it, the open items, and the fit against what was recorded.

    OWNER-ONLY. Per-person commission is finance — ad_domain and any future
    sales role are refused structurally by the decorator, not by hiding a
    link."""
    import comp_rulebook as RB
    import commission_engine as CE
    import sales_cost as SC
    out = {
        "current": RB.current_version(),
        "versions": [RB._with_overrides(v) for v in RB.VERSIONS],
        "open_items": RB.open_items(),
        "coby_policy_flag": RB.coby_policy_flag(),
        "journal": RB.journal(),
        "decision_cards": CE.decision_cards(),
        "set_fee_basis": RB.set_fee_basis(),
    }
    try:
        out["per_close_cost"] = SC.per_close_cost_table()
    except Exception as e:  # noqa: BLE001
        out["per_close_cost"] = {"error": str(e)[:120]}
    try:
        out["fit"] = CE.fit_check(SC._tracker_deals())
    except Exception as e:  # noqa: BLE001
        out["fit"] = {"error": str(e)[:120]}
    return jsonify(out)


@bp.route("/api/comp/rules", methods=["POST"])
@require_owner
def api_comp_rules_edit():
    """Journaled edit — e.g. switching the set-fee wording between
    'qualified' and 'showed'. Nothing is overwritten; a new effective value
    is recorded with who changed it and when."""
    import comp_rulebook as RB
    from dashboard.auth import current_actor
    body = request.get_json(silent=True) or {}
    version = int(body.get("version") or RB.current_version()["version"])
    changes = body.get("changes") or {}
    if not isinstance(changes, dict) or not changes:
        return jsonify({"error": "no changes given"}), 400
    res = RB.set_override(version, changes,
                          (current_actor() or {}).get("user") or "owner",
                          body.get("note") or "")
    return jsonify(res)


@bp.route("/api/comp/cost", methods=["GET"])
@require_owner
def api_comp_cost():
    """The averages and true CAC — owner-only, same reason."""
    import sales_cost as SC
    days = int(request.args.get("days") or 90)
    return jsonify(SC.averages(days))


# ── SALES — the team's scoreboard (owner/finance only) ──────────────────────

@bp.route("/sales")
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def sales_board_page():
    """The scoreboard: per setter and per closer, the pipeline, the next
    seven days, and the consults nobody marked.

    ad_domain and sales sessions are refused structurally by their own
    allowlists, not by hiding a link. Piolo reads the page (R-PIOLO, #161);
    the per-person COMMISSION column is owner-only and is not rendered for
    him — including the total, when one person is the only contributor."""
    from dashboard import shell as _shell_mod  # noqa: F401 (shell context below)
    from dashboard.auth import is_owner
    import sales_scoreboard
    window = request.args.get("window") or "mtd"
    try:
        board = sales_scoreboard.build(
            window, request.args.get("start"), request.args.get("end"),
            comp_visible=is_owner())   # R-PIOLO: per-person pay is owner-only
    except Exception as e:  # noqa: BLE001 — the page degrades, never blanks
        logger.exception("sales scoreboard failed")
        board = {"window": {"label": "unavailable", "key": window, "start": "",
                            "end": "", "progress": ""},
                 "degraded": [{"block": "everything", "why": str(e)[:160]}],
                 "setters": [], "closers": [], "totals": {},
                 "pipeline": {"stages": [], "note": ""},
                 "upcoming": {"rows": [], "count": 0, "note": ""},
                 "unmarked": {"rows": [], "count": 0, "note": "", "by_closer": []},
                 "comp_visible": is_owner(),
                 "speed_to_lead": {"available": False, "note": "unavailable"},
                 "targets": {"available": False, "note": "unavailable", "found": []},
                 "cash": {"total": 0, "source": "—"}, "notes": []}
    resp = make_response(render_template(
        "sales_board.html", board=board, asset_v=_ASSET_VERSION,
        **_shell("sales")))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ── AREA PAGES (IA split): every heavy panel lives on its own page ──────────
# Card count == page count == the panel inventory (CRASH_DIAGNOSIS.md).
_AREAS = {
    "brief":       ("Morning brief (full)", True),
    "cash":        ("Cash & capital", False),
    "sales":       ("Ads & sales", True),
    "unit-econ":   ("Unit economics", True),
    "projection":  ("Forward projection", False),
    "renewals":    ("Renewals & churn", False),
    "outflows":    ("Outflows & BAS", False),
    "team":        ("Team & strategy", False),
    "receivables": ("Receivables", False),
    "decisions":   ("Needs your ruling", False),   # owner-only (checked below)
    "system":      ("System health", False),
}


@bp.route("/view/<area>")
@require_auth
def area_page(area):
    """A sub-page hosting one area's panels — same renderers, but every panel
    is an error boundary and absent sections are skipped (body[data-area])."""
    if area == "system":
        # the System page was rebuilt (#160) — stored results only, no
        # dashboard bundle, so the 60-second memory-status poll and the
        # ten-minute re-render cannot ride along. The old path redirects.
        return redirect(url_for("dashboard.system_page_view"))
    if area not in _AREAS:
        return jsonify({"error": "unknown area", "known": sorted(_AREAS)}), 404
    from dashboard.auth import is_owner
    if area == "decisions" and not is_owner():
        return jsonify({"error": "owner only"}), 403
    import json as _json
    from snapshot import load_persisted
    snap = load_persisted()
    boot = _json.dumps(snap).replace("</", "<\\/") if snap else "null"
    title, window_bar = _AREAS[area]
    burn_box = _burn_box() if area == "projection" else None
    resp = make_response(render_template(
        "panel_page.html", area=area, area_title=title,
        show_window_bar=window_bar, boot_snapshot=boot, burn_box=burn_box,
        edith_cfg=_edith_cfg_json(), defs_json=_defs_json(),
        asset_v=_ASSET_VERSION))
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _burn_box() -> dict | None:
    """COMPASS 1.2 — the projection page's server-rendered burn line
    (OpEx ex-tax; tax accrual BESIDE; net burn; runway). Guarded: a failed
    read renders an honest degraded box, never a crash."""
    try:
        import kv_store
        from snapshot import load_persisted
        from dashboard.exec_top import _age_h, _fmt_age
        d = (kv_store.get("compass:defaults") or {})
        opex = (d.get("items") or {}).get("opex_monthly_ex_tax") or {}
        snap = load_persisted() or {}
        cp = snap.get("cash_position") or {}
        mrr = (snap.get("client_health") or {}).get("current_mrr")
        ov = opex.get("value")
        net_burn = round((ov or 0) - (mrr or 0), 2) if ov is not None else None
        cash_ex = round((cp.get("cash_in_bank") or 0)
                        - (cp.get("tax_reserved") or 0), 2)
        if net_burn is not None and net_burn > 0:
            runway = f"{cash_ex / net_burn:.1f} mo"
        elif net_burn is not None:
            runway = "∞ (the book covers OpEx)"
        else:
            runway = "—"
        tax = cp.get("tax_reserved")
        return {
            "opex": f"${ov:,.0f}/mo" if ov is not None else "— (not yet measured)",
            "tax_line": f"${tax:,.0f} set aside" if tax else "set-aside logic",
            "net_burn": (f"${net_burn:,.0f}/mo" if net_burn is not None else "—"),
            "runway": runway,
            "stamp": f"measured band · computed {_fmt_age(_age_h(d.get('computed_at')))}",
            "note": ("OpEx here excludes ad spend + commissions (modelled "
                     "explicitly in the compass) and ALL tax — the accrual "
                     "settles quarterly via BAS and never hides inside burn."),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("burn box failed: %s", e)
        return {"opex": "—", "tax_line": "—", "net_burn": "—", "runway": "—",
                "stamp": "degraded", "note": f"burn box failed honestly: {str(e)[:80]}"}


# ── THE SCALING COMPASS (/scale — owner-only) ───────────────────────────────

@bp.route("/scale")
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def scale_page():
    """The compass tab. First paint is SERVER-RENDERED from the kv-cached
    Base run (hardening doctrine); interactivity is the bounded JS layer."""
    import json as _json
    import kv_store
    import compass_engine
    base = kv_store.get("compass:base_run") or {}
    defaults = kv_store.get(compass_engine.K_DEFAULTS) or {}
    backtest = kv_store.get(compass_engine.K_BACKTEST) or {}
    run = base.get("run")
    hero = None
    if run and run.get("months"):
        last = run["months"][-1]
        binds = {}
        for m in run["months"]:
            nm = (m.get("binding_constraint") or {}).get("name", "—")
            binds[nm] = binds.get(nm, 0) + 1
        hero = {
            "end_month": last["month"],
            "end_mrr": f"${last['net_mrr']:,.0f}",
            "capital_dip": (f"${run['capital_dip']:,.0f}"
                            if run.get("capital_dip") is not None else "—"),
            "next_binding": (run["months"][0].get("binding_constraint")
                             or {}).get("name", "—"),
            "next_binding_why": (run["months"][0].get("binding_constraint")
                                 or {}).get("why", ""),
            "bind_summary": " · ".join(f"{k}×{v}" for k, v in binds.items()),
        }
    # SIMPLE VIEW first paint — the simulator chain server-rendered from the
    # measured defaults (kv reads only; JS recomputes on edit)
    sim = None
    conf = {}
    acc = None
    try:
        sim = compass_engine.simulate_month()
        items = (defaults.get("items") or {})
        conf = {k: compass_engine.confidence_word((items.get(k) or {}).get("n"))
                for k in ("set_rate", "show_rate", "close_rate", "cpl")}
        acc = compass_engine.accuracy_sentence()
    except Exception as e:  # noqa: BLE001
        logger.warning("scale simple first-paint failed: %s", e)
    # NORTH STAR — server-rendered from the kv cache (the loop computes it)
    ns = None
    try:
        ns = (kv_store.get("compass:north_star") or {}).get("data")
        # normalise whatever shape the cache holds — a missing lever key
        # 500'd this page once (jinja Undefined arithmetic); the route now
        # guarantees the template's contract regardless of cache age
        if ns:
            for lv in ns.get("levers") or []:
                for k in ("required", "plan", "actual", "note"):
                    lv.setdefault(k, None)
            for k in ("actual", "plan", "pace", "verdict", "plan_src",
                      "metric_label", "constraint"):
                ns.setdefault(k, None)
            ns.setdefault("pinned", {})
            if not ns.get("verdict"):
                ns["verdict"] = "pacing is being recomputed — the next refresh fills this in"
    except Exception:
        ns = None
    # LOGIC VERIFIED badge — reads the last behaviour-gate pass (kv)
    badge = None
    try:
        bv = kv_store.get("behaviour:last_pass") or {}
        if bv.get("at"):
            from dashboard.exec_top import _age_h
            age = _age_h(bv["at"])
            ok = bool(bv.get("ok")) and (age is not None and age < 48)
            txt = ("LOGIC VERIFIED " + str(bv["at"])[:16].replace("T", " ")
                   if bv.get("ok") else
                   "LOGIC CHECK FAILED — " + str(bv.get("reason") or "")[:60])
            if bv.get("ok") and not ok:
                txt += " (stale — over 48h old)"
            badge = {"ok": ok, "text": txt}
    except Exception:
        badge = None
    plan_rec = kv_store.get(compass_engine.K_PLAN) or {}
    plan_inputs_json = _json.dumps(plan_rec.get("inputs") or None).replace("</", "<\\/")         if plan_rec else "null"
    resp = make_response(render_template(
        "scale.html", asset_v=_ASSET_VERSION, defs_json=_defs_json(),
        badge=badge, ns=ns, has_plan=bool(plan_rec),
        plan_inputs_json=plan_inputs_json,
        sim=sim, conf=conf, acc_sentence=acc,
        sim_json=_json.dumps(sim).replace("</", "<\\/"),
        hero=hero, base_computed=base.get("computed_at"),
        backtest_verdict=(backtest.get("verdict") or "backtest pending"),
        defaults_json=_json.dumps(defaults).replace("</", "<\\/"),
        base_run_json=_json.dumps(run or None).replace("</", "<\\/"),
        backtest_json=_json.dumps(backtest or None).replace("</", "<\\/")))
    resp.headers["Cache-Control"] = "no-store"
    return resp


_DEFS_CACHE = None


def _defs_json() -> str:
    """The registry, JSON-encoded once per process for template injection."""
    global _DEFS_CACHE
    if _DEFS_CACHE is None:
        import json as _json
        from dashboard import definitions
        _DEFS_CACHE = _json.dumps(definitions.load()).replace("</", "<\\/")
    return _DEFS_CACHE


@bp.route("/definitions")
@require_auth
def definitions_page():
    """The legend — auto-generated from the ONE registry, grouped by screen."""
    from dashboard import definitions
    reg = definitions.load()
    resp = make_response(render_template(
        "definitions.html", groups=reg.get("groups") or {},
        entries=reg.get("entries") or {}, asset_v=_ASSET_VERSION))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/definitions", methods=["GET"])
@require_auth
def api_definitions():
    from dashboard import definitions
    return jsonify(definitions.load())


@bp.route("/api/scale/calibration-log", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_scale_calibration_log():
    import kv_store
    import compass_engine
    return jsonify({"log": kv_store.get(compass_engine.K_CAL_LOG) or [],
                    "defaults_journal": kv_store.get(compass_engine.K_DEFAULTS_JOURNAL) or []})


@bp.route("/api/scale/north-star", methods=["GET", "POST"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_scale_north_star():
    import kv_store
    import compass_engine
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        metric = body.get("metric")
        if metric not in ("net_new_mrr", "cash_collected"):
            return jsonify({"error": "metric must be net_new_mrr or cash_collected"}), 400
        kv_store.put(compass_engine.K_NORTH_METRIC, metric)
    fresh = compass_engine.north_star()
    kv_store.put("compass:north_star",
                 {"computed_at": __import__('helpers').now_sydney().isoformat(),
                  "data": fresh})
    return jsonify(fresh)


@bp.route("/api/scale/behaviour-verified", methods=["POST"])
@require_owner
def api_scale_behaviour_verified():
    """The behaviour gate posts its result here (owner session) — the
    'LOGIC VERIFIED' badge and the sentinel read it. Evidence stays in the
    repo's owner-only evidence folder."""
    import kv_store
    from helpers import now_sydney
    body = request.get_json(silent=True) or {}
    rec = {"at": now_sydney().isoformat(), "ok": bool(body.get("ok")),
           "commit": str(body.get("commit") or "")[:16],
           "passes": int(body.get("passes") or 0),
           "reason": str(body.get("reason") or "")[:200]}
    kv_store.put("behaviour:last_pass", rec)
    return jsonify({"ok": True, "stored": rec})


@bp.route("/scale/travelling")
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def travelling_page():
    """HOW WE'RE TRAVELLING — the live month beside the model. Server-rendered
    from the URL inputs (refresh-safe); the only client work is opening the
    rosters and the two actions."""
    import json as _json
    import travelling as TV
    scenario_param = request.args.get("s") or ""
    scenario = None
    if scenario_param:
        try:
            import base64
            pad = scenario_param + "=" * (-len(scenario_param) % 4)
            scenario = _json.loads(base64.urlsafe_b64decode(
                pad.encode()).decode())
        except Exception:
            scenario = None
    compare = request.args.get("compare") or ("scenario" if scenario else "usual")
    try:
        data = TV.build(window=request.args.get("window") or "mtd",
                        compare=compare, scenario=scenario,
                        start=request.args.get("start"),
                        end=request.args.get("end"))
    except Exception as e:  # noqa: BLE001 — the page never 500s into a blank
        logger.exception("travelling build failed")
        return render_template("travelling.html", asset_v=_ASSET_VERSION,
                               defs_json=_defs_json(), rosters_json="{}",
                               history=None, scenario_param=scenario_param,
                               data={"window": {"key": "mtd", "label": "Month to date",
                                                "progress": "", "start": "", "end": ""},
                                     "compare": {"key": compare, "label": "—",
                                                 "from_usual": []},
                                     "stages": [], "gaps": [], "checks": [],
                                     "verdict": f"This view could not be built just now: {str(e)[:120]}",
                                     "read": {"sentences": []},
                                     "setter": {"call_records": 0, "conversations": 0, "note": ""},
                                     "computed_at": "", "label": ""}), 200
    ns = None
    try:
        import kv_store as _kv
        raw = (_kv.get("compass:north_star") or {}).get("data") or {}
        # only show the headline when it can actually be measured — an empty
        # state gives direction instead of a row of dashes
        if raw.get("actual") is not None:
            fmt = lambda v: (f"${v:,.0f}" if v is not None else "not set")
            ns = {"metric_label": raw.get("metric_label") or "",
                  "actual_text": fmt(raw.get("actual")),
                  "plan_text": fmt(raw.get("plan")),
                  "pace_text": fmt(raw.get("pace")),
                  "constraint": raw.get("constraint")}
        elif raw.get("constraint"):
            ns = {"metric_label": "", "actual_text": "", "plan_text": "",
                  "pace_text": "", "constraint": raw.get("constraint"),
                  "empty": ("This month's revenue movement needs a reading "
                            "from the 1st — it fills in from the next daily "
                            "record.")}
    except Exception:
        ns = None
    rosters = {s["id"]: {"name": s["name"], "roster": s.get("roster") or [],
                         "extra": s.get("extra_rosters") or {},
                         "note": s.get("math")}
               for s in data["stages"]}
    resp = make_response(render_template(
        "travelling.html", asset_v=_ASSET_VERSION, defs_json=_defs_json(),
        data=data, history=TV.history(6), scenario_param=scenario_param, ns=ns,
        rosters_json=_json.dumps(rosters).replace("</", "<\\/")))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/ground-truth", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_ground_truth():
    """SCAN 3 — the engine against the outside world (read-only)."""
    import ground_truth
    return jsonify(ground_truth.run(full=request.args.get("full") == "1"))


@bp.route("/api/health-row", methods=["POST"])
@require_owner
def api_health_row():
    """The triple scan posts its HEALTH row here."""
    import ground_truth
    body = request.get_json(silent=True) or {}
    return jsonify({"ok": True,
                    "row": ground_truth.record_health_row({
                        k: body.get(k) for k in
                        ("commit", "runtime_s", "scan1_ok", "scan2_ok",
                         "scan3_ok", "findings", "top", "pages")})})


@bp.route("/api/health", methods=["GET"])
@require_auth
def api_health_rows():
    import ground_truth
    return jsonify(ground_truth.health())


@bp.route("/api/travelling", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_travelling():
    import travelling as TV
    return jsonify(TV.build(window=request.args.get("window") or "mtd",
                            compare=request.args.get("compare") or "usual",
                            start=request.args.get("start"),
                            end=request.args.get("end")))


@bp.route("/api/travelling/remodel", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_travelling_remodel():
    import travelling as TV
    return jsonify(TV.remodel_inputs(window=request.args.get("window") or "mtd",
                                     start=request.args.get("start"),
                                     end=request.args.get("end")))


@bp.route("/api/travelling/save", methods=["POST"])
@require_owner
def api_travelling_save():
    import travelling as TV
    from dashboard.auth import current_actor
    body = request.get_json(silent=True) or {}
    actor = (current_actor() or {}).get("user", "owner")
    return jsonify(TV.save_check(actor, window=body.get("window") or "mtd",
                                 compare=body.get("compare") or "usual"))


@bp.route("/api/travelling/history", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_travelling_history():
    import travelling as TV
    return jsonify(TV.history(int(request.args.get("n", 8))))


@bp.route("/api/scale/simulate", methods=["POST"])
@require_auth   # R-PIOLO: the simulator computes, it never commits
def api_scale_simulate():
    """The simulator's server truth — the gate compares the page's arithmetic
    against this (math shown must equal math computed)."""
    import compass_engine
    body = request.get_json(silent=True) or {}
    return jsonify(compass_engine.simulate_month(
        body.get("inputs") or {},
        spend=body.get("spend"),
        cpl_override=body.get("cpl"),
        cpl_curve=bool(body.get("cpl_curve"))))


@bp.route("/api/scale/defaults", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_scale_defaults():
    import compass_engine
    return jsonify({"defaults": compass_engine.measured_defaults(),
                    "inputs": compass_engine.default_inputs()})


@bp.route("/api/scale/run", methods=["POST"])
@require_auth   # R-PIOLO: the simulator computes, it never commits
def api_scale_run():
    import compass_engine
    body = request.get_json(silent=True) or {}
    return jsonify(compass_engine.forward(body.get("inputs") or {}))


@bp.route("/api/scale/solve", methods=["POST"])
@require_auth   # R-PIOLO: the simulator computes, it never commits
def api_scale_solve():
    import compass_engine
    body = request.get_json(silent=True) or {}
    return jsonify(compass_engine.solve(body.get("target") or {},
                                        body.get("inputs") or {}))


@bp.route("/api/scale/bands", methods=["POST"])
@require_owner
def api_scale_bands():
    import compass_engine
    body = request.get_json(silent=True) or {}
    return jsonify(compass_engine.bands(body.get("inputs") or {}))


@bp.route("/api/scale/backtest", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_scale_backtest():
    import compass_engine
    import kv_store
    if request.args.get("fresh") == "1":
        return jsonify(compass_engine.backtest())
    return jsonify(kv_store.get(compass_engine.K_BACKTEST)
                   or {"note": "backtest pending — the monthly watch runs it"})


@bp.route("/api/scale/scenarios", methods=["GET", "POST"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_scale_scenarios():
    import compass_engine
    if request.method == "GET":
        return jsonify(compass_engine.list_scenarios(
            full=request.args.get("full") == "1"))
    body = request.get_json(silent=True) or {}
    return jsonify(compass_engine.save_scenario(
        body.get("name") or "", body.get("inputs") or {},
        body.get("note") or ""))


@bp.route("/api/scale/commit-plan", methods=["POST"])
@require_owner
def api_scale_commit_plan():
    import compass_engine
    from dashboard.auth import current_actor
    body = request.get_json(silent=True) or {}
    if not body.get("confirm"):
        return jsonify({"error": "pass confirm:true — committing a plan of "
                                 "record is explicit (it stays a labelled "
                                 "scenario; never actuals)"}), 400
    actor = (current_actor() or {}).get("user", "owner")
    return jsonify(compass_engine.commit_plan(body.get("name") or "", actor))


@bp.route("/api/scale/scenario-pdf", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_scale_scenario_pdf():
    """Owner-only briefing PDF of a saved scenario (or the Base run)."""
    import compass_engine
    import kv_store
    name = request.args.get("name") or ""
    if name:
        sc = (kv_store.get(compass_engine.K_SCENARIOS) or {}).get(name)
        if not sc:
            return jsonify({"error": f"unknown scenario '{name}'"}), 404
        run = compass_engine.forward(sc["inputs"])
        title = f"Scenario: {name}"
    else:
        run = (kv_store.get("compass:base_run") or {}).get("run")
        title = "Base scenario (measured defaults)"
        if not run:
            return jsonify({"error": "base run not yet computed"}), 503
    try:
        from fpdf import FPDF

        def _latin(s):
            return str(s).replace("—", "-").replace("·", "-").replace("×", "x") \
                .encode("latin-1", "replace").decode("latin-1")
        pdf = FPDF()
        pdf.add_page(orientation="L")
        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(0, 8, _latin(f"THE SCALING COMPASS - {title}"),
                       new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(0, 5, _latin(
            f"LABELLED SCENARIO - never actuals. Capital dip "
            f"{run.get('capital_dip')}. {run.get('label')}"),
            new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 7)
        hdr = ["month", "spend", "leads", "calls", "closes", "new MRR",
               "net MRR", "cash in", "net cash", "position", "binding"]
        w = [18, 22, 18, 18, 18, 24, 24, 24, 24, 26, 60]
        for h, wd in zip(hdr, w):
            pdf.cell(wd, 6, _latin(h), border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 7)
        for m in run["months"]:
            vals = [m["month"], f"{m['spend']:,.0f}", f"{m['leads']:,.0f}",
                    f"{m['calls_booked']:,.0f}", f"{m['closes']:.1f}",
                    f"{m['mrr_new']:,.0f}", f"{m['net_mrr']:,.0f}",
                    f"{m['cash_in']:,.0f}", f"{m['net_cash']:,.0f}",
                    f"{m['position']:,.0f}",
                    (m.get("binding_constraint") or {}).get("name", "")]
            for v, wd in zip(vals, w):
                pdf.cell(wd, 5, _latin(v), border=1)
            pdf.ln()
        data = bytes(pdf.output())
        resp = make_response(data)
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Disposition"] = "attachment; filename=scaling-compass.pdf"
        return resp
    except Exception as e:  # noqa: BLE001
        logger.warning("scenario pdf failed: %s", e)
        return jsonify({"error": f"pdf failed: {str(e)[:120]}"}), 500


@bp.route("/api/scale/plan-vs-actual", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_scale_plan_vs_actual():
    import compass_engine
    return jsonify(compass_engine.plan_vs_actual())


@bp.route("/api/scale/expiring", methods=["GET"])
@require_auth
def api_scale_expiring():
    import compass_engine
    days = min(max(int(request.args.get("days", 30)), 7), 120)
    return jsonify(compass_engine.expiring(days))


@bp.route("/api/scale/expiring-preview", methods=["POST"])
@require_auth
def api_scale_expiring_preview():
    """SCENARIO pins preview — journal NOTHING; stateless compute."""
    import compass_engine
    body = request.get_json(silent=True) or {}
    slider = body.get("slider_pct")
    return jsonify(compass_engine.expiring_preview(
        body.get("pins") or {},
        float(slider) if slider is not None else None))


@bp.route("/login", methods=["GET"])
def login_page():
    """Login form — username/password once per-user auth is enabled, else the legacy token field."""
    import dashboard.auth as auth
    return render_template("login.html", per_user=auth.per_user_enabled())


@bp.route("/login", methods=["POST"])
def login_submit():
    """Per-user login (username + password) → server-side session with role. Legacy token still
    accepted ONLY while no per-user accounts are configured (safe migration)."""
    from flask import session
    import dashboard.auth as auth
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    actor = auth.verify_login(username, password)
    if actor:
        session.permanent = True
        session["actor"] = actor
        auth.audit_login(actor, ok=True)
        return redirect(url_for("dashboard.index"))
    if username:
        auth.audit_login({"user": username}, ok=False)

    # Legacy token path — only while per-user auth is not yet enabled.
    token = request.form.get("token", "").strip()
    if not auth.per_user_enabled() and token and token == DASHBOARD_TOKEN:
        resp = make_response(redirect(url_for("dashboard.index")))
        resp.set_cookie(COOKIE_NAME, DASHBOARD_TOKEN, max_age=COOKIE_MAX_AGE,
                        httponly=True, samesite="Lax", secure=True)
        return resp
    return render_template("login.html", error="Invalid credentials",
                           per_user=auth.per_user_enabled()), 401


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    from flask import session
    session.pop("actor", None)
    resp = make_response(redirect(url_for("dashboard.login_page")))
    resp.delete_cookie(COOKIE_NAME)
    return resp


@bp.route("/api/snapshot", methods=["GET"])
@require_auth
def api_snapshot():
    """Return current snapshot as JSON.

    R-PIOLO (#161): the snapshot carries per-person pay, so a non-owner gets
    it with those figures removed and a note saying they were — the leak hunt
    found them here, reaching a role the comp routes correctly refuse."""
    from snapshot import load_persisted
    from dashboard.auth import current_actor
    import role_access as RA
    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404
    resp = jsonify(RA.scrubbed_for((current_actor() or {}).get("role"), snap))
    # Never let a client/proxy serve a stale snapshot after a refresh.
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/refresh", methods=["POST"])
@require_auth
def api_refresh():
    """Trigger a snapshot refresh server-side."""
    if not CFO_REFRESH_KEY:
        return jsonify({"error": "CFO_REFRESH_KEY not configured"}), 500

    from snapshot import build_snapshot
    snap = build_snapshot()

    # Update the in-memory cache in app.py too
    import app as app_module
    app_module._current_snapshot = snap

    resp = jsonify({
        "status": "refreshed",
        "ok": snap.get("ok"),
        "degraded_count": len(snap.get("degraded", [])),
        "generated_at": snap.get("generated_at"),
    })
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/history", methods=["GET"])
@require_auth
def api_history():
    """Return last N daily snapshots for sparkline/trend data."""
    import history_store
    n = request.args.get("n", 14, type=int)
    n = min(n, 30)  # cap at 30 entries
    entries = history_store.last_n_snapshots(n)

    # Extract only the fields needed for sparklines (keep payload small)
    result = []
    for entry in entries:
        snap = entry.get("snapshot", {})
        sales = snap.get("sales") or {}
        funnel = sales.get("funnel") or {}
        per_closer = sales.get("per_closer") or []
        deep = sales.get("deep") or {}
        setter_perf = deep.get("setter_performance") or []
        ch = snap.get("client_health") or {}

        result.append({
            "date": entry.get("date"),
            "funnel": {
                "leads_in": funnel.get("leads_in"),
                "sets": funnel.get("sets"),
                "shows": funnel.get("shows"),
                "closes": funnel.get("closes"),
            },
            "setters": [
                {"name": s.get("name"), "sets": s.get("sets"), "dials": s.get("dials"),
                 "show_pct": s.get("show_pct")}
                for s in setter_perf
            ],
            "closers": [
                {"name": c.get("name"), "closes": c.get("closes"),
                 "close_rate_pct": c.get("close_rate_pct"), "commission_total": c.get("commission_total")}
                for c in per_closer
            ],
            "mrr": ch.get("current_mrr"),
            "clients": ch.get("total_clients"),
            # Brief "movers": engine values only, no recomputation
            "cash_in_bank": (snap.get("cash_position") or {}).get("cash_in_bank"),
            "runway_months": (snap.get("cash_position") or {}).get("runway_months"),
            "total_monthly_burn": (snap.get("cash_position") or {}).get("total_monthly_burn"),
            "active_clients": (snap.get("active_clients") or {}).get("active_count"),
            "next_mrr": ch.get("next_mrr"),
            "stripe_collected_30d": (((snap.get("stripe") or {}).get("revenue") or {}).get("current") or {}).get("total_aud"),
            "failed_charges": (snap.get("stripe") or {}).get("failed_charges_count"),
        })

    return jsonify(result)


@bp.route("/api/voice-status", methods=["GET"])
@require_auth
def api_voice_status():
    """Voice layer health: ElevenLabs configured? usage vs caps + degradation state
    (voice_health) so the client can ANNOUNCE a fallback. No key material."""
    from dashboard.voice import tts_usage
    out = tts_usage()
    try:
        import voice_health
        out["health"] = voice_health.status()
    except Exception:
        out["health"] = None
    return jsonify(out)


@bp.route("/api/memory-status", methods=["GET"])
@require_auth
def api_memory_status():
    """Persistent-memory health for the UI badge — so a DB failure is LOUD, never a
    silent fall-back to forgetting. Returns online + reason + table row counts. No
    secrets (the connection string never leaves the server)."""
    import memory
    import db
    status = memory.memory_status()          # {online, reason}
    status["schema"] = db.schema_overview()  # {} when offline; counts when up
    return jsonify(status)


@bp.route("/api/tts", methods=["GET", "POST"])
@require_auth
def api_tts():
    """Stream ElevenLabs audio for the given text (server-proxied; key never
    leaves the server). GET supports progressive playback via an <audio> src.
    On any TTS failure returns JSON {fallback: true} so the client drops to
    browser speechSynthesis — a TTS failure never blocks the answer."""
    from dashboard.voice import stream_tts
    from flask import Response

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        voice_id = data.get("voice_id")
    else:
        text = request.args.get("text", "")
        voice_id = request.args.get("voice_id")
    return tts_response(text, voice_id)


def tts_response(text: str, voice_id=None):
    """Shared TTS proxy core (dashboard route above + the Timeline bridge).
    Caller is responsible for auth. The text is rewritten FOR THE EAR here —
    currency, ratios, acronyms, dates, eye-formatting — so BOTH surfaces speak
    cleanly; the client keeps the eye-formatted text for its captions."""
    from dashboard.voice import stream_tts
    from flask import Response
    from speech_normalize import normalize_for_speech
    text = normalize_for_speech(text)

    try:
        gen = stream_tts(text, voice_id_override=voice_id)
        # Pull the first chunk eagerly so failures surface as JSON, not mid-stream
        first = next(gen)
    except (RuntimeError, StopIteration) as e:
        reason = str(e) or "no audio"
        cls = getattr(e, "cls", "unknown")
        rydel_action = getattr(e, "rydel_action", None)
        # LOUD degradation (2026-08-10: now CLASSIFIED): every failure is
        # recorded with its class + owner action — the widget announces it, the
        # persistent banner shows it, the action feed carries the exact fix.
        try:
            import voice_health
            voice_health.record_failure(reason, cls=cls, rydel_action=rydel_action)
        except Exception:
            pass
        return jsonify({"fallback": True, "reason": reason, "cls": cls,
                        "rydel_action": rydel_action}), 503
    try:
        import voice_health
        voice_health.record_ok()
    except Exception:
        pass

    def stream():
        yield first
        yield from gen

    return Response(stream(), mimetype="audio/mpeg",
                    headers={"Cache-Control": "no-store"})


@bp.route("/api/brief", methods=["POST"])
@require_auth
def api_brief():
    """Compose the spoken daily brief from the engines (text; client TTS's it)."""
    from snapshot import load_persisted
    from dashboard.voice import build_brief
    import history_store

    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404

    entries = history_store.last_n_snapshots(2)
    history = []
    for entry in entries:
        s = entry.get("snapshot", {})
        ch = s.get("client_health") or {}
        history.append({
            "mrr": ch.get("current_mrr"),
            "stripe_collected_30d": (((s.get("stripe") or {}).get("revenue") or {}).get("current") or {}).get("total_aud"),
            "active_clients": (s.get("active_clients") or {}).get("active_count"),
            "failed_charges": (s.get("stripe") or {}).get("failed_charges_count"),
        })

    token = request.cookies.get(COOKIE_NAME, "anon")
    result = build_brief(snap, history, token)
    return jsonify(result)


@bp.route("/api/greeting", methods=["GET"])
@require_auth
def api_greeting():
    """EDITH's boot greeting: resolved location + salient NEW events, composed fresh each time.
    Session-gated — a quick refresh/resume within the idle gap returns the SAME greeting (no
    re-greet, no re-watermarking). A genuinely new session composes fresh and advances the feed."""
    return greeting_response(force=(request.args.get("fresh") == "1"))


def greeting_response(force: bool = False):
    """Shared greeting core (dashboard route above + the Timeline bridge). The
    25-min re-greet gate and the salience watermark are deliberately SHARED across
    surfaces — news is announced once, whichever window he opens first."""
    import time as _t
    import kv_store
    from snapshot import load_persisted
    from dashboard.voice import build_greeting
    snap = load_persisted() or {}
    _IDLE = 25 * 60
    last = kv_store.get("greeting:last_delivered") or {}
    if not force and last.get("ts") and (_t.time() - last["ts"]) < _IDLE and last.get("payload"):
        return jsonify({**last["payload"], "regreet": False})
    payload = build_greeting(snap, mark=True)   # composes, watermarks, remembers shape
    kv_store.put("greeting:last_delivered", {"ts": _t.time(), "payload": payload})
    return jsonify({**payload, "regreet": True})


# ── Collaboration layer (work log, queue, verification, digest, journal) ─────
@bp.route("/api/collab/log", methods=["GET", "POST"])
@require_auth
def api_collab_log():
    import collab
    from dashboard.auth import current_actor
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        actor = current_actor()
        body = (d.get("body") or "").strip()
        if not body:
            return jsonify({"ok": False, "error": "empty — type something to post"}), 400
        e = collab.add_entry(actor.get("user"), d.get("kind", "suggestion"),
                             body, d.get("link_type"), d.get("link_ref"), d.get("parent_id"))
        if not e:
            # loud server-side surfacing — role + endpoint so the next such bug is diagnosable fast
            logger.error("collab LOG WRITE FAILED — user=%s role=%s endpoint=/api/collab/log kind=%s",
                         actor.get("user"), actor.get("role"), d.get("kind"))
            return jsonify({"ok": False, "error": "couldn’t save to the log — please retry"}), 500
        return jsonify({"ok": True, "entry": e})
    return jsonify({"entries": collab.list_entries(
        start=request.args.get("start"), end=request.args.get("end"),
        author=request.args.get("author"), kind=request.args.get("kind"),
        include_archived=request.args.get("archived") == "1")})


@bp.route("/api/collab/queue", methods=["GET"])
@require_auth
def api_collab_queue():
    import collab
    from snapshot import load_persisted
    return jsonify({"queue": collab.queue(load_persisted() or {})})


@bp.route("/api/collab/resolve", methods=["POST"])
@require_auth
def api_collab_resolve():
    import collab
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    actor = current_actor()
    if not d.get("flag_id"):
        return jsonify({"ok": False, "error": "flag_id required"}), 400
    res = collab.resolve_item(d["flag_id"], d.get("note", ""), actor)
    if isinstance(res, dict) and res.get("ok") is False:
        logger.error("collab RESOLVE FAILED — user=%s role=%s endpoint=/api/collab/resolve flag=%s",
                     actor.get("user"), actor.get("role"), d.get("flag_id"))
        return jsonify(res), 500
    return jsonify(res)


@bp.route("/api/collab/digest", methods=["GET"])
@require_auth
def api_collab_digest():
    import collab
    return jsonify(collab.digest("rydel", advance=request.args.get("peek") != "1"))


@bp.route("/api/collab/journal", methods=["GET"])
@require_auth
def api_collab_journal():
    import collab
    from dashboard.auth import current_actor
    return jsonify({"journal": collab.journal(start=request.args.get("start"),
                                              end=request.args.get("end"),
                                              role=current_actor().get("role"))})


@bp.route("/api/collab/export", methods=["POST"])
@require_auth
def api_collab_export():
    import collab
    return jsonify(collab.export_archive())


@bp.route("/api/whoami", methods=["GET"])
@require_auth
def api_whoami():
    from dashboard.auth import current_actor
    return jsonify(current_actor())


@bp.route("/api/geolocation", methods=["POST"])
@require_auth
def api_geolocation():
    """Dashboard-provided browser coordinates (consented) → reverse-geocode + cache as last-known,
    so the greeting follows Rydel when he travels. Silent, best-effort."""
    import location
    data = request.get_json(silent=True) or {}
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"ok": False, "error": "lat/lon required"}), 400
    loc = location.set_geo(float(lat), float(lon))
    return jsonify({"ok": True, "place": (loc or {}).get("place")})


@bp.route("/api/action-feed", methods=["GET"])
@require_auth
def api_action_feed():
    """ZONE 3 — the consolidated action feed (owner-only): salience + data-quality + reconciliation,
    ranked by severity with plain-language actions. One feed, not scattered warnings."""
    import action_feed
    from snapshot import load_persisted
    return jsonify(action_feed.build_action_feed(load_persisted() or {}))


@bp.route("/api/triage", methods=["POST"])
@require_auth   # R-PIOLO: the simulator computes, it never commits
def api_triage():
    """Dismiss / snooze / delegate / restore an action item (owner-only). The ONLY
    ways an ACTION item leaves besides deciding it — explicit, logged, reversible."""
    import triage
    from dashboard.auth import current_actor
    body = request.get_json(silent=True) or {}
    op = (body.get("op") or "").strip().lower()
    key = (body.get("key") or "").strip()
    if op not in ("dismissed", "snoozed", "delegated", "restore") or not key:
        return jsonify({"error": "op must be dismissed|snoozed|delegated|restore with a key"}), 400
    actor = current_actor()
    st = triage.set_state(key, op, who=(body.get("who") or actor.get("display") or "owner"),
                          reason=(body.get("reason") or "")[:140],
                          days=body.get("days"))
    return jsonify({"ok": True, "key": key, "state": st})


@bp.route("/api/bas", methods=["GET"])
@require_auth
def api_bas():
    """The BAS/PAYG card (the one bas_engine, kv-read — no Xero on this path):
    estimate + schedule + the set-aside split vs current cash. ESTIMATES FOR
    PLANNING — the disclaimer rides the payload and every render."""
    import bas_engine
    from snapshot import load_persisted
    est = bas_engine.estimate()
    snap = load_persisted() or {}
    cash = (snap.get("cash_position") or {}).get("cash_in_bank")
    return jsonify({"available": est is not None, "estimate": est,
                    "obligations": bas_engine.scheduled_obligations(),
                    "free_cash": bas_engine.free_cash_view(cash),
                    "disclaimer": bas_engine.DISCLAIMER})


@bp.route("/api/forecast", methods=["GET"])
@require_auth
def api_forecast():
    """The forecasting block (owner-only): 13-week cash flow, dynamic runway, MRR scenarios,
    accuracy. Every figure is a PROJECTION with visible, adjustable assumptions. Deterministic base."""
    import forecasting_engine
    from snapshot import load_persisted
    return jsonify(forecasting_engine.build_forecast(load_persisted() or {}))


@bp.route("/api/capacity", methods=["GET"])
@require_auth
def api_capacity():
    """Team & Capacity block (owner-only, behind dashboard auth): department load, hire trigger,
    hiring budget, constraint check. Raise signals are a separate owner-only call. Deterministic."""
    import capacity_engine
    from snapshot import load_persisted
    snap = load_persisted() or {}
    payload = capacity_engine.build_capacity(snap)
    if request.args.get("raises") == "1":
        payload["raise_signals"] = capacity_engine.raise_signals(snap)
    return jsonify(payload)


@bp.route("/api/voice-config", methods=["POST"])
@require_auth
def api_voice_config():
    """Set the runtime voice (audition tool): {voice_id, stability, similarity}.
    Empty body resets to the locked default. No redeploy needed."""
    from dashboard.voice import save_voice_config, tts_usage
    cfg = save_voice_config(request.get_json(silent=True) or {})
    out = tts_usage()
    out["saved"] = cfg
    return jsonify(out)


# Entrance music slot: env-configurable, Railway-volume-aware.
# /data (volume) survives redeploys; the app-dir fallback does NOT — the
# status payload flags that so the UI can say "re-upload after each deploy".
_HAS_VOLUME = os.path.isdir("/data")
_ENTRANCE_FILE = os.environ.get(
    "ENTRANCE_AUDIO_PATH",
    "/data/entrance.mp3" if _HAS_VOLUME
    else os.path.join(os.path.dirname(__file__), "..", "state", "entrance.mp3"))
_ENTRANCE_MAX_BYTES = 15 * 1024 * 1024
_ENTRANCE_TYPES = {"audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/aac"}


def _entrance_status() -> dict:
    present = os.path.exists(_ENTRANCE_FILE)
    return {
        "present": present,
        "bytes": os.path.getsize(_ENTRANCE_FILE) if present else 0,
        "volatile": not _HAS_VOLUME and not os.environ.get("ENTRANCE_AUDIO_PATH"),
    }


@bp.route("/audio/entrance", methods=["GET"])
@require_auth
def audio_entrance():
    """EDITH's wake track — the user-uploaded file only. The build ships NO
    audio files; absent slot → 404 and the client plays the synth power-up."""
    from flask import send_file
    if os.path.exists(_ENTRANCE_FILE):
        return send_file(_ENTRANCE_FILE, mimetype="audio/mpeg", max_age=300)
    return jsonify({"error": "no entrance audio uploaded"}), 404


@bp.route("/api/entrance-audio", methods=["GET", "POST", "DELETE"])
@require_auth
def api_entrance_audio():
    """Status / upload / remove for the user-supplied entrance track.
    Stored at ENTRANCE_AUDIO_PATH (volume), never in the repo."""
    if request.method == "GET":
        return jsonify(_entrance_status())

    if request.method == "DELETE":
        if os.path.exists(_ENTRANCE_FILE):
            os.remove(_ENTRANCE_FILE)
        return jsonify({"ok": True, "present": False})

    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    if f.mimetype and f.mimetype not in _ENTRANCE_TYPES:
        return jsonify({"error": f"unsupported type {f.mimetype} (mp3/m4a only)"}), 415
    blob = f.read(_ENTRANCE_MAX_BYTES + 1)
    if len(blob) > _ENTRANCE_MAX_BYTES:
        return jsonify({"error": "file too large (15MB max)"}), 413
    os.makedirs(os.path.dirname(_ENTRANCE_FILE), exist_ok=True)
    with open(_ENTRANCE_FILE, "wb") as out:
        out.write(blob)
    logger.info("Entrance audio uploaded (%d bytes) -> %s", len(blob), _ENTRANCE_FILE)
    out_status = _entrance_status()
    out_status["ok"] = True
    return jsonify(out_status)


@bp.route("/api/hiring-scenario", methods=["POST"])
@require_auth
def api_hiring_scenario():
    """Model one or more hires' affordability and financial impact."""
    from hiring_model import compute_hiring_analysis
    from snapshot import load_persisted

    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404

    data = request.get_json(silent=True) or {}

    # Accept either a list of roles or a single role (backwards compat)
    roles = data.get("roles")
    if not roles:
        roles = [{
            "role": data.get("role", "New hire"),
            "monthly_cost": data.get("monthly_cost", 0),
            "is_revenue_generating": data.get("is_revenue_generating", False),
        }]

    ctx = snap.get("hiring_context") or {}
    profit = snap.get("profit") or {}
    fp = snap.get("financial_position") or {}

    # Get growth rate from projection for 3-month forecast
    projection = (snap.get("client_health") or {}).get("mrr_projection") or {}
    growth_rate = projection.get("growth_rate_latest")

    # Get binding constraint from deficiency analysis
    da = snap.get("deficiency_analysis") or {}
    deficiencies = da.get("deficiencies") or []
    binding = deficiencies[0].get("label") if deficiencies else None

    burn = snap.get("monthly_burn") or {}
    total_burn = burn.get("total_recurring_burn")

    result = compute_hiring_analysis(
        roles=roles,
        monthly_net_income=ctx.get("monthly_net_income", 0),
        current_mrr=ctx.get("current_mrr", 0),
        monthly_revenue=ctx.get("monthly_revenue") or profit.get("total_revenue"),
        monthly_cogs=profit.get("total_cogs"),
        monthly_opex=profit.get("total_operating_expenses"),
        avg_contract_value=ctx.get("avg_contract_value"),
        close_rate_pct=ctx.get("close_rate_pct"),
        avg_cash_per_close=ctx.get("avg_cash_per_close"),
        gross_margin_pct=ctx.get("gross_margin_pct"),
        true_team_cost=ctx.get("true_team_cost", 0),
        financial_position=fp,
        growth_rate_pct=growth_rate,
        binding_constraint=binding,
        forward_mrr=snap.get("forward_mrr"),
        cash_position=snap.get("cash_position"),
        raises=data.get("raises"),
        total_monthly_burn=total_burn,
    )
    return jsonify(result)


@bp.route("/api/sales-summary", methods=["GET"])
@require_auth
def api_sales_summary():
    """Generate a sales-team-safe markdown summary for a given window.

    Privacy boundary: ONLY sales/funnel/rep data. No financials, no payroll,
    no commissions, no MRR, no revenue, no CAC, no LTGP.
    """
    from dashboard.sales_summary import build_sales_summary
    from snapshot import load_persisted

    window_days = request.args.get("window_days", 30, type=int)
    if window_days not in (7, 14, 30, 60, 90):
        window_days = 30

    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404

    markdown = build_sales_summary(snap, window_days)
    return jsonify({"markdown": markdown, "window_days": window_days})


@bp.route("/api/briefing-pdf", methods=["GET"])
@require_auth
def api_briefing_pdf():
    """Generate and return the full CFO briefing PDF."""
    from dashboard.briefing_pdf import generate_briefing_pdf
    from snapshot import load_persisted

    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available — trigger a refresh first"}), 404

    try:
        pdf_data = generate_briefing_pdf(snap)
        pdf_bytes = bytes(pdf_data)  # fpdf2 returns bytearray; Flask needs bytes
    except Exception as e:
        logger.exception("PDF generation failed")
        import traceback
        tb = traceback.format_exc()
        return jsonify({"error": str(e), "traceback": tb}), 500

    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = "attachment; filename=served-cfo-briefing.pdf"
    resp.headers["Content-Length"] = str(len(pdf_bytes))
    return resp


@bp.route("/api/chat", methods=["POST"])
@require_auth
def api_chat():
    """Handle chat message with conversation history and snapshot context."""
    data = request.get_json(silent=True) or {}
    history = data.get("history", [])
    if not history:
        return jsonify({"error": "Empty message"}), 400

    from snapshot import load_persisted
    snap = load_persisted()
    snapshot_json = json.dumps(snap, indent=2) if snap else "{}"

    from dashboard.auth import current_actor
    token = current_actor().get("user") or request.cookies.get(COOKIE_NAME, "anon")
    voice = bool(data.get("voice"))

    # Persistent memory: resume/start a conversation, persist the user turn (async),
    # and build the recall block. All graceful no-ops if the DB is offline.
    import memory
    channel = "voice" if voice else "text"
    conv_id = memory.start_conversation(channel)
    user_msg = (history[-1].get("content") if history else "") or ""
    # Rebuild the thread from the DB if the client lost it (refresh/new tab) BEFORE
    # writing the new turn — this is what makes a refresh RESUME instead of restart.
    history = memory.resume_thread(conv_id, history)
    # CSM confidentiality (#146): turns touching the owner-only CSM domain are
    # NEVER persisted to shared memory (user or assistant side) — the trigram
    # recall would replay them to any authenticated identity otherwise.
    import csm_plan as _csm_mod
    _csm_turn = bool(user_msg and _csm_mod._CSM_RE.search(user_msg.lower()))
    if not _csm_turn:
        memory.record_turn(conv_id, "user", user_msg, channel=channel)
    # Self-improvement loop: silent incident capture + loop-resolution detection on
    # every user turn (corrections, answers that close open loops). Never blocks.
    try:
        import convo_quality
        convo_quality.scan_user_turn(user_msg)
    except Exception:
        pass

    # Data-layer commands: "resync"/"sync now" (immediate mirror sync + rebuild) and
    # "what's plugged into your system / is your data current" — handled locally (no model).
    import sheet_mirror
    for _h in (sheet_mirror.handle_resync_command, sheet_mirror.handle_sources_query):
        _reply, _handled = _h(user_msg)
        if _handled:
            memory.record_turn(conv_id, "assistant", _reply, channel=channel, intent="command")
            return jsonify({"reply": _reply, "error": None, "intent": "command"})

    # Manual target/benchmark/note command? Handle locally (no model), with a
    # confirmation loop. Only manual (no-live-source) values; auth already enforced.
    import manual_targets
    tgt_reply, handled = manual_targets.handle_turn(user_msg, token)
    if handled:
        memory.record_turn(conv_id, "assistant", tgt_reply, channel=channel, intent="command")
        return jsonify({"reply": tgt_reply, "error": None, "intent": "command"})

    # Email-engine review commands ("approve the weekly" → echo → "yes"): confirmation loop.
    import email_pipeline as _ep
    _er, _eh = _ep.handle_review_command(user_msg, token)
    if _eh:
        memory.record_turn(conv_id, "assistant", _er, channel=channel, intent="command")
        return jsonify({"reply": _er, "error": None, "intent": "command"})

    # Client churn/downgrade WRITE-BACK (dashboard override, confirmation loop) + undo + Piolo queue.
    # Checked early so a "yes/no" confirmation lands here. Auth already enforced (only Rydel writes).
    import client_overrides
    for _cb in (lambda m: client_overrides.handle_client_writeback_command(m, token),
                lambda m: client_overrides.handle_undo_command(m, token),
                client_overrides.handle_pending_updates_query,
                client_overrides.handle_client_changes_query):
        _r, _h = _cb(user_msg)
        if _h:
            memory.record_turn(conv_id, "assistant", _r, channel=channel, intent="command")
            return jsonify({"reply": _r, "error": None, "intent": "command"})

    # Location override + "where am I" + "what's new" — short explicit commands/queries (TIER 1),
    # run before the ramble gate so they always resolve deterministically.
    import location, salience
    for _lh in (location.handle_location_command, salience.handle_whats_new):
        _r, _h = _lh(user_msg)
        if _h:
            memory.record_turn(conv_id, "assistant", _r, channel=channel, intent="command")
            return jsonify({"reply": _r, "error": None, "intent": "command"})

    # SELF-CHECK LOOP (TIER 1): a challenge to a data claim ("that's wrong / it's not blank / I just
    # checked") triggers in-chat resync → re-read → correct-or-confirm with root cause. Runs before
    # the ramble gate + needs the thread (where the claim was made). Also the incident handoff.
    import tracker_read, incident_log
    _thread6 = " ".join((m.get("content") or "") for m in (history or [])[-6:])
    import stripe_reconcile
    for _sh in (lambda m: tracker_read.handle_self_check(m, _thread6),
                incident_log.handle_incident_query,
                stripe_reconcile.handle_alias_confirm):
        _r, _h = _sh(user_msg)
        if _h:
            memory.record_turn(conv_id, "assistant", _r, channel=channel, intent="command")
            return jsonify({"reply": _r, "error": None, "intent": "command"})

    # ── TIER 2: deterministic DATA handlers — GATED. A conversational ramble (long, declarative,
    # no data-request structure) SKIPS these entirely and falls through to the model (TIER 3).
    # Default-to-conversation: when unsure, a generic reply beats a jarring data non-sequitur.
    import intent_router, range_unit_economics, payback_reconciliation
    import leads_view, closes_view, liabilities_view, salary_view
    if not intent_router.is_conversational_ramble(user_msg):
        _thread = " ".join((m.get("content") or "") for m in (history or [])[-6:])
        # (handler, entity_scoped?) — entity_scoped lookups are entity-filtered (the Romano rule);
        # superlative/recency lookups (latest lead, biggest deal) surface entities by design → exempt.
        import capacity_engine, forecasting_engine
        # CSM drill (#146): owner-only, silent fall-through for every other
        # identity; replies never persist to memory. ABOVE conversation so
        # 'path to 4x' follow-ups aren't grabbed by advisory/anaphora.
        _csm_handler = (lambda m: __import__('csm_plan').handle_csm_command(
            m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()))
        _tier2 = [
            (_csm_handler, False),
            # FINANCE CURRENCY (#148/#149): ROAS/verdict + gap/currency drills
            # — high so 'roas'/'what did I miss' aren't grabbed downstream.
            (__import__('finance_analysis').handle_finance_command, False),
            (__import__('gap_reconcile').handle_gap_command, False),
            # DATA SCRUTINY (#150): three nets / committed-is-revenue /
            # who-hasn't-paid / did-X-resign — the label-law drills.
            (__import__('tile_drawers').handle_net_command, False),
            (__import__('receivables').handle_ar_command, False),
            (__import__('finance_tabs').handle_resign_command, False),
            (lambda m: __import__('conversation').handle(m, history), False),  # ADVISORY + ANAPHORA/scenario — FIRST so follow-ups ('5 more closes') aren't grabbed by forecast/recital
            (lambda m: __import__('capital_allocation').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # capital allocation: deploy / opportunity-cost / review / set buffer|return
            (lambda m: __import__('open_loops').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # Pillar 1: 'remind me to X' / 'drop it' (internal reminders only)
            (__import__('sales_cost').handle_commission_query, False),   # #159: 'what do commissions cost per client' → the rulebook average (OWNER-ONLY)
            (__import__('outflow_bands').handle_expense_query, False),    # outflow truth: 'real monthly expenses' → OpEx + tax stated separately
            (__import__('ads_lifecycle').handle_decision_recall, False),   # Board v2: 'why did we kill X' → move reason + mover (journal truth)
            (__import__('ads_lifecycle').handle_stance_recall, False),     # Board v2: 'what does the team think of X' → stances + quotes (one store)
            (__import__('ads_discussion').handle_discussion_recall, False),  # 'what has Romano noticed' → real quotes + context stamps (read-only)
            (__import__('timeline_adapter').handle_timeline_client, False),   # Universal advisor P2: per-client delivery state (+finance join on 'overall')
            (__import__('timeline_adapter').handle_timeline_risk, False),     # 'what's overdue/stalled' → Timeline drill, verbatim
            (__import__('timeline_adapter').handle_timeline_signals, False),  # complaints/praise from the Timeline signals log
            (__import__('timeline_adapter').handle_timeline_events, False),   # upcoming client events + countdowns
            (__import__('automations').handle_automation_health, False),      # P3: automation-health registry truth
            (__import__('dashboard.definitions', fromlist=['x']).handle_explain_command, False),  # 'what is/explain X' → the ONE definitions registry
            (__import__('travelling').handle_travelling_command, False),  # 'how are we travelling this month' → the live month beside the model
            (__import__('notion_content').handle_content_list, False),        # P4: what emails/lead magnets went out this week
            (__import__('email_pipeline').handle_pipeline_query, False),     # Email engine: what's pending my review / pipeline state
            (capacity_engine.handle_capacity_command, False),  # hiring/capacity/raise/afford questions
            (forecasting_engine.handle_forecast_command, False),  # cash-flow / MRR / runway forecasts
            (__import__('voice_health').handle_voice_health_command, False),  # 'is your voice okay?'
            (__import__('memory_maintenance').handle_memory_maintenance_command, False),  # cards/journal/restore
            (__import__('convo_quality').handle_quality_command, False),  # quality metrics/proposals/apply
            (__import__('bas_engine').handle_set_instalment, False),     # 'set PAYG instalment to $X'
            (__import__('bas_engine').handle_mark_paid, False),          # 'mark the Apr–Jun BAS as paid'
            (__import__('bas_engine').handle_refresh_command, False),    # 'refresh the BAS estimate'
            (__import__('bas_engine').handle_bas_command, False),        # BAS/GST/set-aside/due-date answers
            (__import__('triage').handle_triage_action_command, False),   # dismiss/snooze/delegate/restore <item>
            (__import__('triage').handle_suppressed_command, False),      # 'show me what you suppressed'
            (__import__('triage').handle_why_here_command, False),        # 'why is this here'
            (__import__('ads_truth').handle_confirm_attendance, False),  # 'confirm attendance for X'
            (__import__('resolution').handle_apply_date_card, False),    # 'apply the date card for X'
            (__import__('resolution').handle_proposed_fixes_command, False),  # P1/P2 fix cards
            (__import__('resolution').handle_autofix_log_command, False),     # 'what did you auto-fix'
            (__import__('action_feed').handle_action_feed_command, False),  # 'what needs my attention'
            (lambda m: __import__('collab').handle_collab_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # work log / queue / digest
            (__import__('close_detect').handle_closed_today, False),  # 'what closed today' → the detection ledger, with provenance
            (__import__('stripe_reconcile').handle_reconciliation_query, False),  # unmatched payments
            (__import__('cash_truth').handle_latest_cash_command, False),   # "last cash collected" → Stripe-actual
            (__import__('cash_truth').handle_needs_logging_command, False), # "what needs logging?"
            (tracker_read.handle_tracker_check, False),    # "check the tracker for X" → verbatim row
            (tracker_read.handle_cash_for, False),         # "cash collected for X" / "why not include"
            (tracker_read.handle_verify_data, False),      # "verify your data" → sync-state summary
            (lambda m: __import__('quarterly_review').handle_quarterly_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # quarterly review / QoQ+YoY / 3x
            (lambda m: __import__('reactivation').handle_reactivation_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # GHL lead reactivation / where-left-off
            (lambda m: __import__('test_leads').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # test-lead exclusion / what's excluded / mark test|real
            (range_unit_economics.handle_unit_econ_command, False),
            (payback_reconciliation.handle_payback_command, False),
            (lambda m: __import__('attribution_queries').handle_basis_command(m), False),  # what basis / which clock
            (lambda m: __import__('attribution_queries').handle_invariants_command(m), False),  # are the invariants green
            (lambda m: __import__('ads_truth').handle_accuracy_command(m), False),  # how accurate is the ad data (sweep table)
            (lambda m: __import__('attribution_queries').handle_tracking_accuracy_command(m), False),  # how accurate is our tracking
            (lambda m: __import__('attribution_queries').handle_shared_name_command(m), False),  # which ads share the name X
            (lambda m: __import__('close_integrity').handle_integrity_command(m), False),  # do the systems agree on closes
            (lambda m: __import__('attribution_queries').handle_flags_command(m), False),  # ad-board flags, verbatim
            (lambda m: __import__('attribution_queries').handle_scoreboard_command(m), False),  # ad scoreboard (reads the engine)
            (lambda m: __import__('attribution_queries').handle_which_creative_command(m), False),  # which creative brought X
            (lambda m: __import__('attribution_queries').handle_qualified_for_creative_command(m), False),  # qualified per creative
            (leads_view.handle_lead_count_command, False),
            (closes_view.handle_close_count_command, False),
            (leads_view.handle_substage_count_command, False),
            (leads_view.handle_client_count_command, False),
            (liabilities_view.handle_amex_command, False),
            (salary_view.handle_salary_command, True),     # entity-scoped → filter
            (leads_view.handle_leads_command, False),
            (closes_view.handle_closes_command, False),
        ]
        for _h, _entity_scoped in _tier2:
            _r, _handled = _h(user_msg)
            if not _handled:
                continue
            if _entity_scoped and not intent_router.entity_relevant(_r, user_msg, _thread):
                break   # a lookup naming a person he never mentioned → suppress, fall to conversation
            # REPETITION GUARD: a verbatim repeat to a DIFFERENT question is a routing failure, not an
            # answer — suppress it and let the thread-aware/model path answer properly (logged).
            if _repetition_failure(_r, history, user_msg):
                logger.warning("repetition guard: handler %s re-emitted a prior reply for a new msg %r",
                               getattr(_h, "__name__", "lambda"), user_msg[:60])
                break
            # Capacity/raise replies carry salary-derived figures → owner-only, NEVER to memory.
            # CSM replies (#146) likewise never persist.
            if _h is not capacity_engine.handle_capacity_command and _h is not _csm_handler:
                memory.record_turn(conv_id, "assistant", _r, channel=channel, intent="command")
            return jsonify({"reply": _r, "error": None, "intent": "command"})

    recall = memory.build_recall_context(user_msg, conversation_id=conv_id,
                                        owner=is_owner())

    # Ground affordability/salary questions on VERIFIED SALARY-tab figures (deterministic), so the
    # model does its cost/FX math on real numbers instead of memory.
    import salary_view
    _mem_block = recall["block"]
    _sal_ctx = salary_view.salary_context(user_msg)
    if _sal_ctx:
        _mem_block = _sal_ctx + "\n\n" + (_mem_block or "")

    # READ-BEFORE-ASSERT: if the turn asks about a client's tracker field state, read the exact
    # row(s) NOW and hand the model the VERBATIM cells — so it can never infer 'blank' (the incident).
    _trk_ctx = tracker_read.client_context(user_msg)
    if _trk_ctx:
        _mem_block = _trk_ctx + "\n\n" + (_mem_block or "")
    # Universal advisor P4: content-review turns get the piece's VERBATIM Notion copy
    # (read-only integration) so the advisory register critiques the real text.
    import notion_content
    _cc = notion_content.content_context(user_msg)
    if _cc:
        _mem_block = _cc + "\n\n" + (_mem_block or "")
    # Timeline surface: ground Tier-3 conversation in the delivery world (overview
    # digest + entity vocabulary + freshness) so delivery talk is never free-styled.
    if channel == "timeline":
        import timeline_adapter
        _tl_ctx = timeline_adapter.conversation_context()
        if _tl_ctx:
            _mem_block = _tl_ctx + "\n\n" + (_mem_block or "")
    # Ad-domain discussion digest (#136): team observations ground EDITH's
    # answers (read-only — EDITH never posts). Empty string when no notes.
    try:
        _disc_ctx = __import__('ads_discussion').edith_context()
        if _disc_ctx:
            _mem_block = _disc_ctx + "\n\n" + (_mem_block or "")
    except Exception:
        pass
    # CSM (#146): OWNER tier-3 turns touching the domain get the engine's
    # grounded context; the whole turn then stays out of memory + distillation.
    _csm_ctx = _csm_mod.csm_context(user_msg, current_actor())
    if _csm_ctx:
        _mem_block = _csm_ctx + "\n\n" + (_mem_block or "")

    result = chat_fn(history, snapshot_json, token, voice=voice, memory_block=_mem_block, channel=channel)

    reply = result.get("reply")
    if reply and not _csm_turn and not _csm_ctx:
        memory.record_turn(conv_id, "assistant", reply, channel=channel, intent=result.get("intent"))
        memory.maybe_distill_async(conv_id)
    if recall.get("recalled"):
        result["recalled"] = recall["recalled"]  # transparency: "recalled from <date>"
    return jsonify(result)


@bp.route("/api/chat-stream", methods=["POST"])
@require_auth
def api_chat_stream():
    """Server-Sent Events stream of the reply as it's generated, so the client can
    start TTS on the first sentence (Phase 1). Same brain + intent routing as
    /api/chat; that endpoint stays as the non-streaming fallback.

    Events: `meta` {intent, context_tokens} → many `delta` {text} → `done` {reply}
    or `error` {error}.
    """
    data = request.get_json(silent=True) or {}
    history = data.get("history", [])
    voice = bool(data.get("voice"))
    if not history:
        return jsonify({"error": "Empty message"}), 400
    # Rate/state bucket: the authenticated user, so per-user sessions stop sharing
    # one "anon" bucket (the legacy dash_token cookie no longer exists per-user).
    from dashboard.auth import current_actor, is_owner
    token = current_actor().get("user") or request.cookies.get(COOKIE_NAME, "anon")
    # CHANNEL (#160): the dashboard dock is a NEW CHANNEL on the SAME brain —
    # channel-scoped thread, shared memory, exactly as the Timeline bridge
    # already is. Allowlisted, and `dashboard` is OWNER-ONLY: a non-owner
    # asking for it gets the ordinary text thread, never a 500 and never
    # somebody else's thread.
    requested = str(data.get("channel") or "").strip().lower()
    if requested == "dashboard" and is_owner():
        channel = "dashboard"
    else:
        channel = "voice" if voice else "text"
    return chat_stream_response(history, voice,
                                channel=channel, token=token,
                                ui=data.get("ui") or {})


def chat_stream_response(history: list, voice: bool, channel: str, token: str, ui: dict | None = None):
    """The ONE streaming chat core — shared by the dashboard route above and the
    owner-gated Timeline bridge (dashboard/bridge.py). channel scopes the thread
    (db.get_or_create_active_conversation); token scopes rate-limit + pending-state
    buckets. Caller is responsible for auth. Same brain everywhere — never fork."""
    from snapshot import load_persisted
    snap = load_persisted()
    snapshot_json = json.dumps(snap, indent=2) if snap else "{}"

    # Persistent memory: resume/start conversation, persist user turn (async), build recall.
    import memory
    conv_id = memory.start_conversation(channel)
    user_msg = (history[-1].get("content") if history else "") or ""
    # Rebuild the thread from the DB on refresh BEFORE writing the new turn (resume, not restart).
    history = memory.resume_thread(conv_id, history)
    # CSM confidentiality (#146): CSM-domain turns never persist to shared
    # memory on ANY channel (dashboard voice/text + timeline bridge).
    import csm_plan as _csm_mod
    _csm_turn = bool(user_msg and _csm_mod._CSM_RE.search(user_msg.lower()))
    if not _csm_turn:
        memory.record_turn(conv_id, "user", user_msg, channel=channel)
    # Self-improvement loop: silent incident capture + loop-resolution detection on
    # every user turn (corrections, answers that close open loops). Never blocks.
    try:
        import convo_quality
        convo_quality.scan_user_turn(user_msg)
    except Exception:
        pass

    def sse(event: str, payload) -> str:
        return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

    # Local commands (short-circuit the model, emit one done event): data-layer
    # resync / sources query first, then manual targets.
    import sheet_mirror, manual_targets
    _cmd_reply = None
    for _h in (sheet_mirror.handle_resync_command, sheet_mirror.handle_sources_query):
        _r, _handled = _h(user_msg)
        if _handled:
            _cmd_reply = _r
            break
    if _cmd_reply is None:
        _r, _handled = manual_targets.handle_turn(user_msg, token)
        if _handled:
            _cmd_reply = _r
    if _cmd_reply is None:
        import email_pipeline as _ep
        _r, _handled = _ep.handle_review_command(user_msg, token)
        if _handled:
            _cmd_reply = _r
    if _cmd_reply is None:
        import client_overrides
        for _cb in (lambda m: client_overrides.handle_client_writeback_command(m, token),
                    lambda m: client_overrides.handle_undo_command(m, token),
                    client_overrides.handle_pending_updates_query,
                    client_overrides.handle_client_changes_query):
            _r, _handled = _cb(user_msg)
            if _handled:
                _cmd_reply = _r
                break
    if _cmd_reply is None:
        import location, salience
        for _lh in (location.handle_location_command, salience.handle_whats_new):
            _r, _handled = _lh(user_msg)
            if _handled:
                _cmd_reply = _r
                break
    if _cmd_reply is None:
        # Self-check challenge loop + incident handoff (voice path), before the ramble gate.
        import tracker_read, incident_log
        _thread6 = " ".join((m.get("content") or "") for m in (history or [])[-6:])
        import stripe_reconcile
        for _sh in (lambda m: tracker_read.handle_self_check(m, _thread6),
                    incident_log.handle_incident_query,
                    stripe_reconcile.handle_alias_confirm):
            _r, _handled = _sh(user_msg)
            if _handled:
                _cmd_reply = _r
                break
    # ── TIER 2 (voice path): GATED — a conversational ramble skips the data handlers → model.
    # This is the surface the Romano misfire happened on. Default-to-conversation when unsure.
    import intent_router
    # ── VOICE-DRIVEN NAVIGATION (deterministic, FIRST): "show me X" is a navigation
    # command — it must NEVER fall through to the model, whose emergent "text and
    # voice only" line caused the 2026-08-05 incident. Timeline channel gets the
    # honest cross-surface answer (no actions) until Part 2 adopts the handler.
    _cmd_actions: list = []
    if _cmd_reply is None:
        try:
            import nav_router
            _nr, _na, _nh = nav_router.handle(user_msg, ui=ui, channel=channel)
            if _nh:
                _cmd_reply, _cmd_actions = _nr, (_na or [])
        except Exception as _e:
            logger.warning("nav router failed (falling through): %s", _e)
    if _cmd_reply is None and not intent_router.is_conversational_ramble(user_msg):
        import range_unit_economics, payback_reconciliation, leads_view, closes_view, liabilities_view, salary_view
        import tracker_read, capacity_engine, forecasting_engine
        _thread = " ".join((m.get("content") or "") for m in (history or [])[-6:])
        # CSM drill (#146) — registered on the STREAMING list too (voice +
        # timeline widget run through here); owner-only, silent fall-through.
        _csm_handler = (lambda m: __import__('csm_plan').handle_csm_command(
            m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()))
        _tier2 = [
            (_csm_handler, False),
            # FINANCE CURRENCY (#148/#149): ROAS/verdict + gap/currency drills
            # — high so 'roas'/'what did I miss' aren't grabbed downstream.
            (__import__('finance_analysis').handle_finance_command, False),
            (__import__('gap_reconcile').handle_gap_command, False),
            # DATA SCRUTINY (#150): three nets / committed-is-revenue /
            # who-hasn't-paid / did-X-resign — the label-law drills.
            (__import__('tile_drawers').handle_net_command, False),
            (__import__('receivables').handle_ar_command, False),
            (__import__('finance_tabs').handle_resign_command, False),
            (lambda m: __import__('conversation').handle(m, history), False),  # ADVISORY + ANAPHORA/scenario — FIRST so follow-ups ('5 more closes') aren't grabbed by forecast/recital
            (lambda m: __import__('capital_allocation').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # capital allocation: deploy / opportunity-cost / review / set buffer|return
            (lambda m: __import__('open_loops').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # Pillar 1: 'remind me to X' / 'drop it' (internal reminders only)
            (__import__('sales_cost').handle_commission_query, False),   # #159: 'what do commissions cost per client' → the rulebook average (OWNER-ONLY)
            (__import__('outflow_bands').handle_expense_query, False),    # outflow truth: 'real monthly expenses' → OpEx + tax stated separately
            (__import__('ads_lifecycle').handle_decision_recall, False),   # Board v2: 'why did we kill X' → move reason + mover (journal truth)
            (__import__('ads_lifecycle').handle_stance_recall, False),     # Board v2: 'what does the team think of X' → stances + quotes (one store)
            (__import__('ads_discussion').handle_discussion_recall, False),  # 'what has Romano noticed' → real quotes + context stamps (read-only)
            (__import__('timeline_adapter').handle_timeline_client, False),   # Universal advisor P2: per-client delivery state (+finance join on 'overall')
            (__import__('timeline_adapter').handle_timeline_risk, False),     # 'what's overdue/stalled' → Timeline drill, verbatim
            (__import__('timeline_adapter').handle_timeline_signals, False),  # complaints/praise from the Timeline signals log
            (__import__('timeline_adapter').handle_timeline_events, False),   # upcoming client events + countdowns
            (__import__('automations').handle_automation_health, False),      # P3: automation-health registry truth
            (__import__('dashboard.definitions', fromlist=['x']).handle_explain_command, False),  # 'what is/explain X' → the ONE definitions registry
            (__import__('travelling').handle_travelling_command, False),  # 'how are we travelling this month' → the live month beside the model
            (__import__('notion_content').handle_content_list, False),        # P4: what emails/lead magnets went out this week
            (__import__('email_pipeline').handle_pipeline_query, False),     # Email engine: what's pending my review / pipeline state
            (capacity_engine.handle_capacity_command, False),
            (forecasting_engine.handle_forecast_command, False),
            (__import__('voice_health').handle_voice_health_command, False),  # 'is your voice okay?'
            (__import__('memory_maintenance').handle_memory_maintenance_command, False),  # cards/journal/restore
            (__import__('convo_quality').handle_quality_command, False),  # quality metrics/proposals/apply
            (__import__('bas_engine').handle_set_instalment, False),     # 'set PAYG instalment to $X'
            (__import__('bas_engine').handle_mark_paid, False),          # 'mark the Apr–Jun BAS as paid'
            (__import__('bas_engine').handle_refresh_command, False),    # 'refresh the BAS estimate'
            (__import__('bas_engine').handle_bas_command, False),        # BAS/GST/set-aside/due-date answers
            (__import__('triage').handle_triage_action_command, False),   # dismiss/snooze/delegate/restore <item>
            (__import__('triage').handle_suppressed_command, False),      # 'show me what you suppressed'
            (__import__('triage').handle_why_here_command, False),        # 'why is this here'
            (__import__('ads_truth').handle_confirm_attendance, False),  # 'confirm attendance for X'
            (__import__('resolution').handle_apply_date_card, False),    # 'apply the date card for X'
            (__import__('resolution').handle_proposed_fixes_command, False),  # P1/P2 fix cards
            (__import__('resolution').handle_autofix_log_command, False),     # 'what did you auto-fix'
            (__import__('action_feed').handle_action_feed_command, False),
            (lambda m: __import__('collab').handle_collab_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),
            (__import__('close_detect').handle_closed_today, False),  # 'what closed today' → the detection ledger, with provenance
            (__import__('stripe_reconcile').handle_reconciliation_query, False),
            (__import__('cash_truth').handle_latest_cash_command, False),   # "last cash collected" → Stripe-actual
            (__import__('cash_truth').handle_needs_logging_command, False), # "what needs logging?"
            (tracker_read.handle_tracker_check, False),
            (tracker_read.handle_cash_for, False),
            (tracker_read.handle_verify_data, False),
            (lambda m: __import__('quarterly_review').handle_quarterly_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # quarterly review / QoQ+YoY / 3x
            (lambda m: __import__('reactivation').handle_reactivation_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # GHL lead reactivation / where-left-off
            (lambda m: __import__('test_leads').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # test-lead exclusion / what's excluded / mark test|real
            (range_unit_economics.handle_unit_econ_command, False),
            (payback_reconciliation.handle_payback_command, False),
            (lambda m: __import__('attribution_queries').handle_basis_command(m), False),  # what basis / which clock
            (lambda m: __import__('attribution_queries').handle_invariants_command(m), False),  # are the invariants green
            (lambda m: __import__('ads_truth').handle_accuracy_command(m), False),  # how accurate is the ad data (sweep table)
            (lambda m: __import__('attribution_queries').handle_tracking_accuracy_command(m), False),  # how accurate is our tracking
            (lambda m: __import__('attribution_queries').handle_shared_name_command(m), False),  # which ads share the name X
            (lambda m: __import__('close_integrity').handle_integrity_command(m), False),  # do the systems agree on closes
            (lambda m: __import__('attribution_queries').handle_flags_command(m), False),  # ad-board flags, verbatim
            (lambda m: __import__('attribution_queries').handle_scoreboard_command(m), False),  # ad scoreboard (reads the engine)
            (lambda m: __import__('attribution_queries').handle_which_creative_command(m), False),  # which creative brought X
            (lambda m: __import__('attribution_queries').handle_qualified_for_creative_command(m), False),  # qualified per creative
            (leads_view.handle_lead_count_command, False),
            (closes_view.handle_close_count_command, False),
            (leads_view.handle_substage_count_command, False),
            (leads_view.handle_client_count_command, False),
            (liabilities_view.handle_amex_command, False),
            (salary_view.handle_salary_command, True),      # entity-scoped → filter (Romano rule)
            (leads_view.handle_leads_command, False),
            (closes_view.handle_closes_command, False),
        ]
        for _h, _entity_scoped in _tier2:
            _r, _handled = _h(user_msg)
            if not _handled:
                continue
            if _entity_scoped and not intent_router.entity_relevant(_r, user_msg, _thread):
                break   # suppress a salary lookup about someone he never mentioned → conversation
            if _repetition_failure(_r, history, user_msg):
                logger.warning("repetition guard (stream): re-emit suppressed for %r", user_msg[:60])
                break
            _cmd_reply = _r
            _cmd_sensitive = (_h is capacity_engine.handle_capacity_command
                              or _h is _csm_handler)   # #146: never to memory
            break
    if _cmd_reply is not None:
        if not locals().get("_cmd_sensitive"):   # capacity/raise salary figures never enter memory
            memory.record_turn(conv_id, "assistant", _cmd_reply, channel=channel, intent="command")
        def gen_cmd():
            yield sse("meta", {"intent": "command", "context_tokens": 0})
            for _a in (_cmd_actions or []):
                yield sse("nav", _a)          # schema v1 — unknown events are ignored
            yield sse("done", {"reply": _cmd_reply})
        return Response(gen_cmd(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    recall = memory.build_recall_context(user_msg, conversation_id=conv_id,
                                        owner=is_owner())
    # Ground affordability/salary questions on VERIFIED SALARY-tab figures (deterministic).
    import salary_view, tracker_read
    _mem_block = recall["block"]
    _sal_ctx = salary_view.salary_context(user_msg)
    if _sal_ctx:
        _mem_block = _sal_ctx + "\n\n" + (_mem_block or "")
    # READ-BEFORE-ASSERT (voice path): inject verbatim tracker row(s) for client field-state questions.
    _trk_ctx = tracker_read.client_context(user_msg)
    if _trk_ctx:
        _mem_block = _trk_ctx + "\n\n" + (_mem_block or "")
    # Universal advisor P4: content-review turns get the piece's VERBATIM Notion copy
    # (read-only integration) so the advisory register critiques the real text.
    import notion_content
    _cc = notion_content.content_context(user_msg)
    if _cc:
        _mem_block = _cc + "\n\n" + (_mem_block or "")
    # Timeline surface: ground Tier-3 conversation in the delivery world (overview
    # digest + entity vocabulary + freshness) so delivery talk is never free-styled.
    if channel == "timeline":
        import timeline_adapter
        _tl_ctx = timeline_adapter.conversation_context()
        if _tl_ctx:
            _mem_block = _tl_ctx + "\n\n" + (_mem_block or "")
    # Ad-domain discussion digest (#136): team observations ground EDITH's
    # answers (read-only — EDITH never posts). Empty string when no notes.
    try:
        _disc_ctx = __import__('ads_discussion').edith_context()
        if _disc_ctx:
            _mem_block = _disc_ctx + "\n\n" + (_mem_block or "")
    except Exception:
        pass
    # CSM (#146): owner tier-3 turns get the engine's grounded context; the
    # whole turn then stays out of memory + distillation (see finally below).
    from dashboard.auth import current_actor as _ca146
    _csm_ctx = _csm_mod.csm_context(user_msg, _ca146())
    if _csm_ctx:
        _mem_block = _csm_ctx + "\n\n" + (_mem_block or "")

    @stream_with_context
    def generate():
        final_reply = ""
        try:
            for event_type, payload in chat_stream_fn(history, snapshot_json, token,
                                                      voice=voice, memory_block=_mem_block,
                                                      channel=channel):
                if event_type == "delta":
                    yield sse("delta", {"text": payload})
                elif event_type == "meta":
                    yield sse("meta", payload)
                elif event_type == "done":
                    final_reply = payload
                    yield sse("done", {"reply": payload})
                elif event_type == "error":
                    yield sse("error", {"error": payload})
        except Exception as e:  # never let a stream crash leak a 500 mid-SSE
            logger.error("chat-stream generator error: %s", e)
            yield sse("error", {"error": "stream interrupted"})
        finally:
            # Persist the assistant turn once the stream completes (async) + distil.
            # CSM turns (#146) never persist or distil.
            if final_reply and not _csm_turn and not _csm_ctx:
                memory.record_turn(conv_id, "assistant", final_reply, channel=channel)
                memory.maybe_distill_async(conv_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",   # disable proxy buffering so chunks flush live
            "Connection": "keep-alive",
        },
    )


# ── Manual targets / benchmarks / goalposts (Rydel-set, auth-gated) ──────────

@bp.route("/targets", methods=["GET"])
@require_auth
def targets_page():
    """Settings panel to view/edit/reset the manual targets + see change history."""
    return render_template("targets.html")


@bp.route("/api/targets", methods=["GET"])
@require_auth
def api_targets():
    """Current manual targets/benchmarks + recent change history (settings panel)."""
    import manual_targets
    return jsonify({"targets": manual_targets.get_all(), "history": manual_targets.history()})


@bp.route("/api/targets/set", methods=["POST"])
@require_auth
def api_targets_set():
    """Direct set from the settings panel (no confirmation — explicit UI action)."""
    import manual_targets
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    value = data.get("value")
    if key not in manual_targets.DEFAULTS:
        return jsonify({"error": f"Unknown target '{key}'"}), 400
    try:
        rec = manual_targets.set_value(key, float(value))
    except (TypeError, ValueError):
        return jsonify({"error": "value must be numeric"}), 400
    return jsonify({"ok": True, "target": rec})


@bp.route("/api/targets/reset", methods=["POST"])
@require_auth
def api_targets_reset():
    """Reset a target to its documented default."""
    import manual_targets
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    if key not in manual_targets.DEFAULTS:
        return jsonify({"error": f"Unknown target '{key}'"}), 400
    return jsonify({"ok": True, "target": manual_targets.reset_value(key)})


# ── Sheet mirror: data-sources panel + immediate resync (auth-gated) ──────────

@bp.route("/data-sources", methods=["GET"])
@require_auth
def data_sources_page():
    """Transparency panel — what's plugged into EDITH + per-tab freshness."""
    return render_template("data_sources.html")


@bp.route("/api/data-sources", methods=["GET"])
@require_auth
def api_data_sources():
    import sheet_mirror
    payload = {"sources": sheet_mirror.get_sources(),
               "interval_seconds": __import__("config").SHEET_SYNC_INTERVAL_SECONDS}
    try:
        import ghl_mirror
        payload["ghl_sources"] = ghl_mirror.get_sources()
        payload["ghl_counts"] = ghl_mirror.counts()
    except Exception as e:
        logger.info("ghl sources unavailable: %s", e)
    return jsonify(payload)


@bp.route("/api/ghl-backfill", methods=["POST"])
@require_auth
def api_ghl_backfill():
    """One resumable backfill chunk (opps + up to ?cap contacts/notes). Call until remaining==0."""
    import ghl_mirror
    if not ghl_mirror.enabled():
        return jsonify({"ok": False, "error": "GHL mirror not configured"}), 503
    cap = request.args.get("cap", 150, type=int)
    res = ghl_mirror.backfill_chunk(cap=cap)
    return jsonify({"ok": True, **res})


@bp.route("/api/reactivation", methods=["GET"])
@require_auth
def api_reactivation():
    """Deterministic reactivation intelligence: ranked leads + totals + notes-hygiene + reconciliation.
    ?bucket=stale|pitched_stalled  ?min_value=  ?limit=  (PII-bearing → auth-gated only)."""
    import reactivation
    leads = reactivation.classify()
    bucket = request.args.get("bucket")
    min_value = request.args.get("min_value", 0.0, type=float)
    limit = request.args.get("limit", type=int)
    resp = jsonify({
        "list": reactivation.reactivation_list(bucket=bucket, min_value=min_value, limit=limit, leads=leads),
        "totals": reactivation.summary_totals(leads),
        "notes_hygiene": reactivation.notes_hygiene(leads),
        "reconciliation": reactivation.reconciliation(leads),
    })
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _audit_pii_export(kind: str, n: int):
    """Log a deliberate PII-bearing export (contact names/emails/phones) to the forever archive."""
    try:
        import collab
        from dashboard.auth import current_actor
        a = current_actor()
        collab.record_action(a, f"exported the reactivation {kind} ({n} leads, contains contact PII)",
                             link_type="reactivation_export", link_ref=kind)
    except Exception as e:
        logger.info("reactivation export audit failed: %s", e)


@bp.route("/api/capital", methods=["GET"])
@require_auth
def api_capital():
    """The full capital-allocation state — cash, wall, surplus, the idle-cash bleed, buckets, the
    open review + unassigned, and review history. Owner-visible (Piolo has full visibility too)."""
    import capital_allocation
    state = capital_allocation.compute_state()
    state["history"] = capital_allocation.review_history()
    resp = jsonify(state)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/capital/settings", methods=["POST"])
@require_auth
def api_capital_settings():
    """Set the wall / assumed return / cadence. (UI already confirms; voice uses the confirm loop.)"""
    import capital_allocation
    d = request.get_json(silent=True) or {}
    results = {}
    # A field PRESENT in the payload is applied — including an explicit null to CLEAR it (so an
    # assumption can be un-set, never leaving a value I chose). Absent fields are left untouched.
    for field in ("survival_buffer_aud", "assumed_annual_return_pct", "review_cadence"):
        if field in d:
            results[field] = capital_allocation.set_setting(field, d[field])
    return jsonify({"ok": True, "results": results, "state": capital_allocation.compute_state()})


@bp.route("/api/capital/review", methods=["POST"])
@require_auth
def api_capital_review():
    """Review actions: {action: 'run'|'assign'|'commit', ...}."""
    import capital_allocation
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    if action == "run":
        return jsonify(capital_allocation.run_review())
    if action == "assign":
        return jsonify(capital_allocation.set_line(d.get("review_id"), d.get("bucket_id"),
                                                   d.get("assigned_aud"), d.get("note")))
    if action == "commit":
        return jsonify(capital_allocation.commit_review(d.get("review_id")))
    if action == "discard":
        return jsonify(capital_allocation.discard_review(d.get("review_id")))
    return jsonify({"ok": False, "error": "unknown action"}), 400


@bp.route("/api/capital/reset", methods=["POST"])
@require_owner
def api_capital_reset():
    """Start over — clear reviews/deployments (+ optionally the buffer/return). Buckets preserved."""
    import capital_allocation
    d = request.get_json(silent=True) or {}
    return jsonify(capital_allocation.reset_all(clear_settings=d.get("clear_settings", True)))


@bp.route("/api/capital/deploy", methods=["POST"])
@require_auth
def api_capital_deploy():
    """Log a deployment — idle_surplus shrinks, the bleed tile drops (the reward loop)."""
    import capital_allocation
    d = request.get_json(silent=True) or {}
    if not d.get("bucket_id") or d.get("amount_aud") is None:
        return jsonify({"ok": False, "error": "bucket_id and amount_aud required"}), 400
    return jsonify(capital_allocation.mark_deployed(d["bucket_id"], d["amount_aud"],
                                                    d.get("note"), d.get("review_id")))


@bp.route("/api/test-lead-scan", methods=["GET"])
@require_auth
def api_test_lead_scan():
    """The excluded-entries AUDIT VIEW: classify both mirrors → the voided list + borderline (owner +
    Piolo). Raw lead access lives ONLY here + the classifier; metrics read the clean view."""
    import test_leads
    return jsonify(test_leads.scan())


@bp.route("/api/test-leads/override", methods=["POST"])
@require_auth
def api_test_lead_override():
    """Manual mark test/real (owner + Piolo). Persisted, audited, REMEMBERED — outranks rules and
    survives re-syncs."""
    import test_leads
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    key = d.get("key")
    if not key:
        return jsonify({"ok": False, "error": "key required"}), 400
    actor = current_actor()
    test_leads.set_override(key, bool(d.get("is_test")), actor.get("user"))
    try:
        import collab
        collab.record_action(actor, f"marked a lead {'TEST' if d.get('is_test') else 'REAL'} ({key})",
                             link_type="test_lead_override", link_ref=key)
    except Exception:
        pass
    return jsonify({"ok": True, "key": key, "is_test": bool(d.get("is_test"))})


@bp.route("/api/test-leads/confirm", methods=["POST"])
@require_owner
def api_test_lead_confirm():
    """Owner confirms the first classification pass (enables the repoints) + persists the token rules."""
    import test_leads
    d = request.get_json(silent=True) or {}
    if d.get("rules"):
        test_leads.set_rules(d["rules"])
    test_leads.confirm_first_pass(by="rydel")
    # One-time data-cleaning note in the forever archive (future-you will ask why counts changed).
    try:
        import collab
        collab.add_entry("rydel", "done",
                         f"Data cleaning {today_sydney()}: test leads voided from all sales metrics "
                         "(staff/test-shaped matches; excluded not deleted). Rules: rydel/jaspher/test. "
                         "See the test-lead audit view (/api/test-lead-scan).",
                         link_type="data_cleaning", link_ref=str(today_sydney()))
    except Exception as e:
        logger.info("data-cleaning journal note skipped: %s", e)
    return jsonify({"ok": True, "confirmed": True, "rules": test_leads.rules()})


@bp.route("/leads", methods=["GET"])
@require_auth
def sales_page():
    """The scoped Lead Reactivation view — the sales team's home. Owner/COO can view it too, but a
    sales session is confined to it (fail-closed scoping in require_auth). No financial data here."""
    return render_template("sales.html", asset_v=_ASSET_VERSION)


@bp.route("/api/lead-lookup", methods=["GET"])
@require_auth
def api_lead_lookup():
    """'Where did we leave off with X' for the sales view: grounded summary + contact for one lead.
    ?name= or ?contact_id=. Sales-scope-allowed. PII-bearing (auth-gated)."""
    import reactivation
    res = reactivation.lookup_lead(name=request.args.get("name"),
                                   contact_id=request.args.get("contact_id"))
    resp = jsonify(res)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/reactivation/export.csv", methods=["GET"])
@require_auth
def api_reactivation_csv():
    """CSV of the ranked reactivation list (full fields for GHL smart-lists). Contains contact PII —
    deliberate, auth-gated, audit-logged."""
    import reactivation, reactivation_export
    leads = reactivation.reactivation_list(min_value=request.args.get("min_value", 0.0, type=float),
                                           limit=request.args.get("limit", type=int))
    cap = request.args.get("cap", 200, type=int)
    csv_text = reactivation_export.build_csv(leads, cap=cap)
    _audit_pii_export("CSV", min(len(leads), cap))
    resp = make_response(csv_text)
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = f"attachment; filename=reactivation-{today_sydney()}.csv"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/reactivation/brief.pdf", methods=["GET"])
@require_auth
def api_reactivation_brief():
    """Formatted reactivation brief PDF (top-N ranked with grounded summaries + angles). Contact PII —
    deliberate, auth-gated, audit-logged."""
    import reactivation, reactivation_export
    from helpers import today_sydney
    top_n = request.args.get("top_n", 40, type=int)
    leads = reactivation.reactivation_list()
    try:
        pdf = reactivation_export.build_brief_pdf(leads, top_n=top_n)
    except Exception as e:
        logger.exception("reactivation brief failed")
        return jsonify({"error": str(e)}), 500
    _audit_pii_export("brief PDF", min(len(leads), top_n))
    resp = make_response(bytes(pdf))
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f"attachment; filename=reactivation-brief-{today_sydney()}.pdf"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/resync", methods=["POST"])
@require_auth
def api_resync():
    """Force an immediate sync of all mirrored tabs, then rebuild the snapshot."""
    import sheet_mirror
    res = sheet_mirror.sync_all()
    try:
        from snapshot import build_snapshot
        snap = build_snapshot()
        import app as app_module
        app_module._current_snapshot = snap
        res["snapshot_generated_at"] = snap.get("generated_at")
    except Exception as e:
        logger.error("resync snapshot rebuild failed: %s", e)
        res["snapshot_error"] = str(e)[:160]
    resp = jsonify({"ok": True, "sync": res})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/unit-economics", methods=["GET"])
@require_auth
def api_unit_economics():
    """Range-aware LTGP:CAC / ROAS / LTV:CAC, window-consistent. ?start=&end= (ISO) or ?days=N.

    The dashboard window buttons and EDITH's spoken answers route through this same engine,
    so they never drift for the same window.
    """
    import range_unit_economics
    from helpers import today_sydney
    start = request.args.get("start")
    end = request.args.get("end")
    if not (start and end):
        from datetime import timedelta
        days = request.args.get("days", 30, type=int)
        today = today_sydney()
        start, end = str(today - timedelta(days=days - 1)), str(today)
    res = range_unit_economics.unit_economics(start, end)
    resp = jsonify(res)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/payback", methods=["GET"])
@require_auth
def api_payback():
    """True payback per deal / per offer via Stripe payment reconciliation. ?start=&end= or ?days=N
    (default last 90d). Read-only Stripe; PII-safe (no emails in output)."""
    import payback_reconciliation
    from helpers import today_sydney
    start = request.args.get("start")
    end = request.args.get("end")
    if not (start and end):
        from datetime import timedelta
        days = request.args.get("days", 90, type=int)
        today = today_sydney()
        start, end = str(today - timedelta(days=days - 1)), str(today)
    res = payback_reconciliation.compute_payback(start, end)
    resp = jsonify(res)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/leads", methods=["GET"])
@require_auth
def api_leads():
    """Most recently entered leads from the mirrored tracker. ?limit=N (default 10). PII-safe
    (no email/phone in output)."""
    import leads_view
    limit = request.args.get("limit", 10, type=int)
    resp = jsonify(leads_view.recent_leads(limit=limit))
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _resolve_quarter_args():
    """?year=&q= (calendar) or default to the last completed calendar quarter."""
    import quarterly_pack as qp
    year = request.args.get("year", type=int)
    q = request.args.get("q", type=int)
    if not (year and q in (1, 2, 3, 4)):
        year, q = qp.last_completed_quarter()
    assumptions = {}
    for k, caster in (("multiple", float), ("close_rate_target", float),
                      ("ltgp_cac_floor", float), ("clients_per_delivery_hire", int)):
        v = request.args.get(k, type=caster)
        if v is not None:
            assumptions[k] = v
    return year, q, (assumptions or None)


@bp.route("/api/quarterly-pack", methods=["GET"])
@require_auth
def api_quarterly_pack():
    """The full quarterly review as JSON (packs + QoQ/YoY comparisons + the 3x model). Both roles
    may read. ?year=&q= or default last completed quarter; 3x knobs via ?multiple=&close_rate_target=.
    This is the same object the PDF renders from, so chat answers never drift from the document."""
    import quarterly_review
    year, q, assumptions = _resolve_quarter_args()
    try:
        review = quarterly_review.build_review(year, q, assumptions)
    except Exception as e:
        logger.exception("quarterly pack failed")
        return jsonify({"error": str(e)}), 500
    resp = jsonify(review)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/quarterly-review", methods=["GET"])
@require_auth
def api_quarterly_review():
    """Generate the branded Quarterly Review PDF (both roles may generate — Rydel's full-visibility
    call). Every $-figure is verbatim from the pack (validated; generation fails loudly otherwise).
    The PDF is dated into the forever archive, and the generation is flagged to Rydel (if Piolo runs
    it, it surfaces in the owner digest via collab.record_action). ?year=&q= or default last Q."""
    import quarterly_review
    from dashboard.quarterly_pdf import generate_quarterly_pdf
    from dashboard.auth import current_actor
    from helpers import today_sydney
    year, q, assumptions = _resolve_quarter_args()
    try:
        review = quarterly_review.build_review(year, q, assumptions)
        pdf_bytes = generate_quarterly_pdf(review)
    except ValueError as e:
        # verbatim-number guard tripped — refuse to emit a document with an untraceable figure
        logger.error("Quarterly PDF verbatim check failed: %s", e)
        return jsonify({"error": "verbatim-number check failed — refusing to emit", "detail": str(e)}), 500
    except Exception as e:
        logger.exception("Quarterly PDF generation failed")
        return jsonify({"error": str(e)}), 500

    label = review.get("quarter", {}).get("label", f"Q{q} {year}")
    actor = current_actor()
    # Forever archive: dated record + the PDF file on disk (survives DB loss; joins the export).
    filename = f"served-cfo-quarterly-{label.replace(' ', '-')}-{today_sydney()}.pdf"
    try:
        import collab, os as _os
        arch_dir = _os.path.join(_os.path.dirname(__file__), "archive_exports")
        _os.makedirs(arch_dir, exist_ok=True)
        with open(_os.path.join(arch_dir, filename), "wb") as fh:
            fh.write(pdf_bytes)
        collab.add_entry(actor.get("user", "rydel"), "done",
                         f"Quarterly Review generated: {label} ({filename})",
                         link_type="quarterly_pdf", link_ref=label)
        collab.record_action(actor, f"generated the Quarterly Review PDF for {label}",
                             link_type="quarterly_pdf", link_ref=label)
    except Exception as e:
        logger.info("Quarterly PDF archive step non-fatal error: %s", e)

    resp = make_response(bytes(pdf_bytes))
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    resp.headers["Content-Length"] = str(len(pdf_bytes))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ── RENEWAL & CHURN TRUTH LOOP (#135) — scan · declare · converge ────────────
# THE BOUNDARY: these routes NEVER write the MRR contract sheet. Declarations
# are owner-only money events; the scan is owner-triggered; convergence happens
# by Piolo editing the sheet and the next scan noticing.

@bp.route("/api/renewal/scan", methods=["POST"])
@require_owner
def api_renewal_scan():
    """On-demand sheet scan (both card buttons hit this). Sync server-side
    (~1–3s: one CSV pull + diff); the client renders progress + result panel."""
    import renewal_loop
    from dashboard.auth import current_actor
    result = renewal_loop.scan(trigger="button", actor=current_actor().get("user", "rydel"))
    resp = jsonify(result)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/renewal/state", methods=["GET"])
@require_auth
def api_renewal_state():
    """Panel state without a fresh pull: last scan meta, pending declarations,
    recent journal. Read-only; visible to owner+coo (Piolo sees his queue)."""
    import client_overrides
    import renewal_loop
    pend = [renewal_loop._pend_view(o) for o in client_overrides.active_overrides()]
    return jsonify({"last_scan": renewal_loop.last_scan_meta(),
                    "pending": pend,
                    "journal": renewal_loop.journal_entries()[-15:]})


@bp.route("/api/renewal/clients", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_renewal_clients():
    """Type-ahead over the CURRENT client set — selection binds to a roster
    entry (IDs are truth); free text matching nothing is honestly empty."""
    import client_overrides
    q = (request.args.get("q") or "").strip().lower()
    roster = client_overrides._roster()
    out = []
    for c in roster:
        nm = c.get("name") or ""
        if not q or q in nm.lower():
            out.append({"name": nm, "current_mrr": c.get("current_mrr"),
                        "contract_end": c.get("contract_end"),
                        "status": c.get("status")})
    return jsonify({"clients": out[:12], "total": len(roster)})


@bp.route("/api/renewal/declare", methods=["POST"])
@require_owner
def api_renewal_declare():
    """Two-phase, extending the existing confirmation-gated write-back contract:
    stage=preview → impact preview + token; stage=confirm + token → applied
    (journaled, one engine, snapshot refreshed, Piolo item spawned)."""
    import secrets
    import client_overrides
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    stage = d.get("stage") or "preview"
    if stage == "preview":
        prev, err = client_overrides.preview_declaration(
            d.get("client") or "", d.get("kind") or "",
            effective_date=d.get("effective_date") or None,
            new_mrr=d.get("new_mrr"),
            reason=(d.get("reason") or "").strip() or None,
            # RICHER RESIGN (forward-MRR wave): amount · term · cadence · start
            amount=d.get("amount"),
            term_months=d.get("term_months"),
            cadence=(d.get("cadence") or "").strip().lower() or None,
            start_date=d.get("start_date") or None,
            # CSM wave: downsell/continuity + expansion join the one flow
            subtype=(d.get("subtype") or "").strip().lower() or None,
            first6_value=d.get("first6_value"))
        if err:
            return jsonify({"error": err}), 400
        token = secrets.token_urlsafe(16)
        client_overrides._set_pending(token, prev["payload"])
        return jsonify({"preview": prev["preview"], "mrr_delta": prev["mrr_delta"],
                        "current_mrr": prev["current_mrr"], "old_end": prev["old_end"],
                        "token": token})
    if stage == "confirm":
        token = d.get("token") or ""
        payload = client_overrides._get_pending(token)
        if not payload:
            return jsonify({"error": "confirmation expired or unknown — preview again"}), 400
        client_overrides._clear_pending(token)
        oid, err = client_overrides.apply_declaration(payload, current_actor())
        if err:
            return jsonify({"error": err}), 500
        import renewal_loop
        return jsonify({"ok": True, "id": oid,
                        "chip": "declared · pending sheet",
                        "piolo_item": renewal_loop.piolo_edit_text(payload)})
    return jsonify({"error": "stage must be preview|confirm"}), 400


@bp.route("/api/outflow-bands", methods=["GET"])
@require_auth
def api_outflow_bands():
    """OUTFLOW TRUTH: the trailing months restated by band (OPEX ·
    TAX/STATUTORY · PERSONAL · FLAGGED) + the accrual/cash view data +
    partition invariant. One classifier; finance surface (ad_domain walled
    by the allowlist)."""
    import outflow_bands
    months = min(max(int(request.args.get("months", 6) or 6), 1), 12)
    payload = outflow_bands.monthly_bands(months)
    payload["journal"] = outflow_bands.journal_entries(20)
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/outflow-bands/assign", methods=["POST"])
@require_owner
def api_outflow_bands_assign():
    """One-click FLAGGED-lane assignment → a deterministic rule (owner-only,
    journaled, reversible — assign band='flagged' to clear)."""
    import outflow_bands
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    out, err = outflow_bands.assign(current_actor(), d.get("account"), d.get("band"))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, **out})


@bp.route("/api/projection", methods=["GET"])
@require_auth
def api_projection():
    """THE TWO-LAYER FORWARD PROJECTION (forward-MRR wave): committed +
    assumed-pool curves from the one engine. The renewal slider is CLIENT-side
    what-if over the engine's stated formula — committed takes no assumption
    parameter (slider-immune by construction). Finance surface: ad_domain is
    walled by the fail-closed allowlist."""
    import forward_projection
    resp = jsonify(forward_projection.project())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/projection/config", methods=["POST"])
@require_owner
def api_projection_config():
    """The DEFAULT assumption + horizon — config, owner-only, journaled
    {who, when, old→new}. Slider positions are what-ifs and never journal."""
    import forward_projection
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    cfg, err = forward_projection.set_config(current_actor(), d)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, "config": cfg})


@bp.route("/api/renewal/reverse", methods=["POST"])
@require_owner
def api_renewal_reverse():
    """Journaled reversal of a declaration by id (two-phase: confirm=true
    required — the UI asks first). EXCLUDED ≠ DELETED: history stays."""
    import client_overrides
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    if not d.get("confirm"):
        return jsonify({"error": "reversal needs confirm=true (the UI confirms first)"}), 400
    try:
        oid = int(d.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    row, err = client_overrides.reverse_declaration(oid, current_actor())
    if err:
        return jsonify({"error": err}), 404
    return jsonify({"ok": True, "reversed": {"client": row["client_name"],
                                             "kind": row["change_type"]}})


# ── PIOLO QUEUE FIX (2026-08-10) — un-dismiss + restore (owner-side admin) ───

@bp.route("/api/collab/undismiss", methods=["POST"])
@require_owner
def api_collab_undismiss():
    import collab
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    if not d.get("flag_id"):
        return jsonify({"error": "flag_id required"}), 400
    return jsonify(collab.un_dismiss(d["flag_id"], current_actor()))


@bp.route("/api/collab/restore", methods=["POST"])
@require_owner
def api_collab_restore():
    import collab
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    if not d.get("signature"):
        return jsonify({"error": "signature required"}), 400
    return jsonify(collab.restore_to_active(d["signature"], current_actor()))


# ── FINANCE DASHBOARD IA (2026-08-10) — summarize, don't dump ────────────────
# The worklog + bookkeeping queue leave the main scroll and become compact
# summary cards; each gets a dedicated, URL-addressable page. Auth INHERITED
# exactly: same require_auth wall as the dashboard surfaces they replace; the
# scoped roles (sales / ad_domain) stay excluded by their fail-closed
# allowlists — a new endpoint cannot leak to them by omission.

@bp.route("/worklog", methods=["GET"])
@require_auth
def page_worklog():
    return render_template("worklog.html")


@bp.route("/bookkeeping", methods=["GET"])
@require_auth
def page_bookkeeping():
    return render_template("bookkeeping.html")


@bp.route("/api/ops-summary", methods=["GET"])
@require_auth
def api_ops_summary():
    """The two summary cards' numbers — read from the SAME generators the full
    pages use (collab.worklog_page_data / collab.queue_lanes). One engine:
    card == page count by construction, and tested."""
    import collab
    from snapshot import load_persisted
    lanes = collab.queue_lanes(load_persisted() or {})
    resp = jsonify({"worklog": collab.worklog_summary(),
                    "bookkeeping": {"active": len(lanes["active"]),
                                    "aged": len(lanes["aged"]),
                                    "done": len(lanes["done"])}})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/worklog", methods=["GET"])
@require_auth
def api_worklog():
    import collab
    resp = jsonify(collab.worklog_page_data())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# CSM INVESTMENT (#146) — OWNER-ONLY surface. The confidentiality law:
# every API here is @require_owner (the FIRST owner-only page domain — the
# ruled exception to Piolo's full-visibility standing); the page route
# redirects non-owners (require_owner would return raw JSON on a page);
# sales/ad_domain are already walled by the fail-closed allowlist; nothing
# in this domain writes to collab/feed/salience/snapshot/memory. Discreet
# mode is an owner SESSION flag — it hides the dashboard card + any CSM
# mention while Rydel records Looms.
# ═══════════════════════════════════════════════════════════════════════════

_CSM_DISCREET_KEY = "csm_discreet"


@bp.route("/csm", methods=["GET"])
@require_auth
def page_csm():
    from dashboard.auth import is_owner
    if not is_owner():
        return redirect(url_for("dashboard.index"))
    return render_template("csm.html", asset_v=_ASSET_VERSION)


@bp.route("/api/csm/summary", methods=["GET"])
@require_owner
def api_csm_summary():
    import csm_plan
    payload = csm_plan.summary()
    payload["discreet"] = bool(session.get(_CSM_DISCREET_KEY))
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/card", methods=["GET"])
@require_owner
def api_csm_card():
    """The dashboard card feed. Owner + discreet-off only; the card element
    ships hidden and ONLY this 200 reveals it (fail-closed by construction)."""
    import csm_plan
    if session.get(_CSM_DISCREET_KEY):
        resp = jsonify({"show": False, "discreet": True})
    else:
        s = csm_plan.summary()
        resp = jsonify({"show": True, "discreet": False,
                        "line": s["card_line"],
                        "next_action": s["next_action"]})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/discreet", methods=["POST"])
@require_owner
def api_csm_discreet():
    """One-click discreet toggle — session-persisted, default OFF."""
    d = request.get_json(silent=True) or {}
    session[_CSM_DISCREET_KEY] = bool(d.get("on"))
    session.permanent = True
    return jsonify({"ok": True, "discreet": session[_CSM_DISCREET_KEY]})


@bp.route("/api/csm/model", methods=["GET"])
@require_owner
def api_csm_model():
    import csm_plan
    custom = None
    if request.args.get("renewal_pct"):
        custom = {"renewal_pct": request.args.get("renewal_pct")}
    resp = jsonify(csm_plan.model_view(custom))
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/scoreboard", methods=["GET"])
@require_owner
def api_csm_scoreboard():
    import csm_plan
    resp = jsonify(csm_plan.scoreboard())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/baselines", methods=["GET"])
@require_owner
def api_csm_baselines():
    import csm_baselines
    fresh = request.args.get("fresh") == "1"
    resp = jsonify(csm_baselines.all_baselines(fresh=fresh))
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/calendar", methods=["GET"])
@require_owner
def api_csm_calendar():
    import csm_plan
    resp = jsonify(csm_plan.ladder_calendar())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/gates", methods=["GET", "POST"])
@require_owner
def api_csm_gates():
    import csm_plan
    from dashboard.auth import current_actor
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        out, err = csm_plan.tick_gate(current_actor(), d.get("id") or "",
                                      bool(d.get("done")))
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"ok": True, **out})
    resp = jsonify({**csm_plan.gates(),
                    "phase_strip": csm_plan.phase_strip(),
                    "journal": csm_plan.journal_entries(30)})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/risks", methods=["GET", "POST"])
@require_owner
def api_csm_risks():
    import csm_plan
    from dashboard.auth import current_actor
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        out, err = csm_plan.set_risk(current_actor(), d.get("id") or "",
                                     d.get("status") or "", d.get("note"))
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"ok": True, **out})
    resp = jsonify(csm_plan.risks())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/config", methods=["GET", "POST"])
@require_owner
def api_csm_config():
    """Owner config incl. the director comp offset figures — journaled with
    MASKED values for director keys; kv-only; never in any doc/export."""
    import csm_plan
    from dashboard.auth import current_actor
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        cfg, err = csm_plan.set_config(current_actor(), d)
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"ok": True, "config": cfg})
    resp = jsonify({"config": csm_plan.config()})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/tier", methods=["POST"])
@require_owner
def api_csm_tier():
    import csm_baselines
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    out, err = csm_baselines.set_tier(current_actor(), d.get("client") or "",
                                      d.get("tier"))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, **out})


@bp.route("/api/csm/scenario-overlay", methods=["GET"])
@require_owner
def api_csm_scenario_overlay():
    """M8: the labelled 'include CSM hire plan' what-if overlay for the main
    forward-projection panel. Owner-only + discreet-aware (the overlay is a
    CSM mention on the finance dashboard)."""
    import csm_plan
    if session.get(_CSM_DISCREET_KEY):
        resp = jsonify({"enabled": False, "discreet": True})
    else:
        resp = jsonify(csm_plan.scenario_overlay())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/analysis", methods=["GET", "POST"])
@require_owner
def api_csm_analysis():
    """D4: POST regenerates (dated version); GET returns the latest (md) +
    the version list."""
    import csm_docs
    if request.method == "POST":
        return jsonify({"ok": True, **csm_docs.generate_analysis()})
    latest = csm_docs.latest_analysis()
    resp = jsonify({"latest": latest, "versions": csm_docs.analysis_versions()})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/analysis.pdf", methods=["GET"])
@require_owner
def api_csm_analysis_pdf():
    import csm_docs
    from helpers import today_sydney
    pdf = csm_docs.analysis_pdf()
    resp = make_response(pdf)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = \
        f"attachment; filename=csm-analysis-{today_sydney()}.pdf"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/csm/comp-preflight", methods=["GET"])
@require_owner
def api_csm_comp_preflight():
    """D5 preflight: shows EXACTLY what the candidate page includes and what
    is stripped, with the forbidden-token proof — before anything renders."""
    import csm_docs
    resp = jsonify(csm_docs.comp_page_preflight())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/csm/comp-page.pdf", methods=["GET"])
@require_owner
def api_csm_comp_page_pdf():
    """D5: the candidate offer-pack comp page — stripped + proven (the
    generator REFUSES to emit if the preflight finds a forbidden token)."""
    import csm_docs
    from helpers import today_sydney
    try:
        pdf = csm_docs.comp_page_pdf()
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    resp = make_response(pdf)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = \
        f"attachment; filename=csm-compensation-{today_sydney()}.pdf"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/csm/explain", methods=["POST"])
@require_owner
def api_csm_explain():
    """'Explain this' on every /csm tile — EDITH narrates the number FROM the
    engine (the same drill the chat surfaces use; owner voice/text)."""
    import csm_plan
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    q = (d.get("q") or "").strip()
    reply, handled = csm_plan.handle_csm_command(q or "csm roi status",
                                                current_actor())
    if not handled or not reply:
        reply = "The engine has no drill for that tile yet — the page's own numbers are the truth."
    return jsonify({"reply": reply})


# ═══════════════════════════════════════════════════════════════════════════
# FINANCE CURRENCY + GAP + ANALYSIS (#148/#149, 2026-09-17). Finance
# surfaces (require_auth — piolo full visibility; ad_domain/sales walled by
# the allowlist); the owner briefing is @require_owner. READ-ONLY LAW: these
# routes only read engines + kv; the backfill is a Piolo package.
# ═══════════════════════════════════════════════════════════════════════════

@bp.route("/api/roas", methods=["GET"])
@require_auth
def api_roas():
    """Three ROAS side by side, labelled, never blended — plus the verdict."""
    import finance_analysis
    win = request.args.get("window", "sep_mtd")
    if win not in ("sep_mtd", "aug_full", "t30", "t60", "t90"):
        return jsonify({"error": "unknown window"}), 400
    payload = {"activity": finance_analysis.window_report(win, "activity"),
               "cohort": finance_analysis.window_report(win, "cohort"),
               "verdict": finance_analysis.verdict()}
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/gap", methods=["GET"])
@require_auth
def api_gap():
    """The tracker-gap state: window + evidence + close ledger + the Piolo
    backfill package (Piolo executes it — full visibility)."""
    import gap_reconcile
    import kv_store
    resp = jsonify({"state": kv_store.get("gap:state"),
                    "ledger": gap_reconcile.close_ledger(),
                    "package": kv_store.get("gap:backfill_package"),
                    "lead_diff": gap_reconcile.lead_diff(),
                    "journal": kv_store.get("gap:journal")})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/gap/rebuild", methods=["POST"])
@require_owner
def api_gap_rebuild():
    """Owner: re-detect + rebuild the ledger + refresh the package now."""
    import gap_reconcile
    st = gap_reconcile.detect_gap(force=True)
    led = gap_reconcile.rebuild_closes(apply=True)
    pkg = gap_reconcile.build_backfill_package()
    return jsonify({"ok": True, "state": st.get("gap"),
                    "auto": led.get("auto"), "proposed": led.get("proposed"),
                    "package_rows": pkg.get("rows")})


@bp.route("/api/finance-analysis", methods=["GET", "POST"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_finance_analysis():
    import finance_analysis
    if request.method == "POST":
        return jsonify({"ok": True, **finance_analysis.generate_briefing()})
    resp = jsonify({"latest": finance_analysis.latest_briefing()})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/finance-analysis.pdf", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_finance_analysis_pdf():
    import finance_analysis
    from helpers import today_sydney
    pdf = finance_analysis.briefing_pdf()
    resp = make_response(pdf)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = \
        f"attachment; filename=financial-analysis-{today_sydney()}.pdf"
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# DATA SCRUTINY (#150): show-your-work drawers, three nets, receivables,
# unit economics, decision cards. Finance surfaces = require_auth (allowlist
# walls ad/sales); decision cards = owner-only.
# ═══════════════════════════════════════════════════════════════════════════

@bp.route("/api/drawer/<tile>", methods=["GET"])
@require_auth
def api_drawer(tile):
    """The show-your-work drawer for a headline tile: definition · formula ·
    components (source + ids) · clock · reconciliation delta."""
    import tile_drawers
    import finance_analysis
    if tile == "ltv_cac":
        payload = finance_analysis.drawer_ltv_cac()
    elif tile == "ltgp_cac":
        payload = finance_analysis.drawer_ltgp_cac()
    else:
        payload = tile_drawers.drawer(tile)
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# ── CLIENT TELEMETRY (dashboard hardening): browser crashes reach the same
# feed as server failures. Auth-gated, rate-limited, no PII beyond route+error.
@bp.route("/api/client-error", methods=["POST"])
@require_auth
def api_client_error():
    import kv_store
    from helpers import now_sydney
    body = request.get_json(silent=True) or {}
    # rate limit: 60 stored events per rolling hour bucket, server-side
    hour_key = "telemetry:err_count:" + now_sydney().strftime("%Y-%m-%d-%H")
    try:
        count = int(kv_store.get(hour_key) or 0)
    except Exception:
        count = 0
    kv_store.put(hour_key, count + 1)
    if count >= 60:
        return jsonify({"ok": True, "stored": False, "reason": "rate-limited"}), 202
    entry = {
        "at": now_sydney().isoformat(),
        "kind": str(body.get("kind") or "unknown")[:40],
        "detail": str(body.get("detail") or "")[:400],
        "src": str(body.get("src") or "")[:200],
        "route": str(body.get("route") or "")[:120],
        "commit": str(body.get("commit") or "")[:16],
    }
    ring = kv_store.get("telemetry:client_errors") or []
    ring.append(entry)
    kv_store.put("telemetry:client_errors", ring[-200:])
    return jsonify({"ok": True, "stored": True})


@bp.route("/api/telemetry", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_telemetry():
    """Owner view: recent client errors + hourly rate + the render-health
    self-check state (the sentinel's watch reads the same keys)."""
    import kv_store
    import render_health
    ring = kv_store.get("telemetry:client_errors") or []
    return jsonify({
        "recent": ring[-50:][::-1],
        "total_stored": len(ring),
        "rate": render_health.error_rate_last_hours(6),
        "render_health": kv_store.get("render_health:last") or
                         {"note": "no self-check has run yet"},
    })


@bp.route("/api/nets", methods=["GET"])
@require_auth
def api_nets():
    """The three honest nets (Part A2), components summing, tax banded."""
    import tile_drawers
    resp = jsonify(tile_drawers.three_nets())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/ar", methods=["GET"])
@require_auth
def api_ar():
    """Receivables: per-client expected/received/outstanding + aging +
    the Xero AR anchor + unmatched-payment alias proposals."""
    import receivables
    fresh = request.args.get("fresh") == "1"
    resp = jsonify(receivables.build_ar(fresh=fresh))
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/unit-econ-honest", methods=["GET"])
@require_auth
def api_unit_econ_honest():
    """LTV:CAC + LTGP:CAC with loaded vs spend-only CAC and input provenance
    (#150 D3) — per cohort month + trailing 90d + by package."""
    import finance_analysis
    resp = jsonify(finance_analysis.unit_econ_view())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/tab-map", methods=["GET"])
@require_auth
def api_tab_map():
    import finance_tabs
    resp = jsonify({"tab_map": finance_tabs.enumerate_tabs(),
                    "renewal_ledger": finance_tabs.renewal_ledger(),
                    "cross_tab": finance_tabs.cross_tab_recon()})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/decision-cards", methods=["GET"])
@require_auth   # R-PIOLO: read granted to the coo role; the allowlist in role_access.py decides
def api_decision_cards():
    """Owner-only: everything only Rydel can rule, evidence attached."""
    import decision_cards
    resp = jsonify(decision_cards.build_cards())
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
