"""
dashboard/auth.py
-----------------
Per-user authentication with roles + actor identity, replacing the single shared DASHBOARD_TOKEN.

Two accounts (env-configured): rydel (owner) and piolo (coo). Piolo has FULL visibility + authority
(Rydel's call 2026-07-21) — the roles differ only by IDENTITY: every action is attributed, and
Piolo's write-actions are flagged to Rydel. Server-side Flask session carries {user, role}; each
request exposes the actor via g.actor / current_actor().

SAFE MIGRATION: setting RYDEL_PASSWORD + PIOLO_PASSWORD both ENABLES per-user login AND RETIRES the
legacy shared token — atomically. Until the passwords are set, the old token path still works (no
lockout, no behaviour change), so this deploys safely before the credentials exist.
"""
from __future__ import annotations

import functools
import hmac
import logging
import os
import secrets

from flask import redirect, request, make_response, url_for, session, g, jsonify

from role_access import finance_blocked  # R-PIOLO-PARITY, #167

logger = logging.getLogger(__name__)

# ── Legacy shared token (fallback only while no per-user accounts are configured) ──
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")
if not DASHBOARD_TOKEN:
    _token_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".dashboard_token")
    if os.path.exists(_token_file):
        with open(_token_file) as f:
            DASHBOARD_TOKEN = f.read().strip()
    if not DASHBOARD_TOKEN:
        DASHBOARD_TOKEN = secrets.token_urlsafe(32)
        try:
            with open(_token_file, "w") as f:
                f.write(DASHBOARD_TOKEN)
        except OSError as e:
            logger.warning("Could not write token file: %s", e)

COOKIE_NAME = "dash_token"
COOKIE_MAX_AGE = 30 * 24 * 3600


# ── Per-user accounts (from env; passwords are server-side secrets) ──────────
def _accounts() -> dict:
    accts: dict = {}
    rp = os.environ.get("RYDEL_PASSWORD", "")
    pp = os.environ.get("PIOLO_PASSWORD", "")
    sp = os.environ.get("SALES_PASSWORD", "")
    if rp:
        accts["rydel"] = {"role": "owner", "pw": rp, "display": "Rydel"}
    if pp:
        accts["piolo"] = {"role": "coo", "pw": pp, "display": "Piolo"}
    # Scoped sales-team login (Kalin + setters): leads/reactivation ONLY, never financials.
    if sp:
        accts["sales"] = {"role": "sales", "pw": sp, "display": "Sales Team"}
    # ── ad_domain role (Rydel's word GIVEN 2026-08-10 — the #113/#117 standing
    # "until his word" condition is satisfied; grant + scope in DECISIONS).
    # ONE role, config-driven assignees: AD_DOMAIN_USERS (default the three
    # named users), each enabled by their own {USER}_PASSWORD env — adding a
    # user later is one env line, never a code change. Fail-closed allowlisted
    # to the AD DASHBOARD only (below); zero finance surfaces, zero applies.
    # MEDIA_BUYER_PASSWORD stays honoured as Romano's legacy credential env.
    for u in _ad_domain_users():
        pw = os.environ.get(f"{u.upper()}_PASSWORD", "")
        if not pw and u == "romano":
            pw = os.environ.get("MEDIA_BUYER_PASSWORD", "")
        if pw and u not in accts:                 # core accounts always win the name
            accts[u] = {"role": "ad_domain", "pw": pw, "display": u.capitalize()}
    return accts


def _ad_domain_users() -> list[str]:
    raw = os.environ.get("AD_DOMAIN_USERS", "romano,isaiah,inna")
    return [u.strip().lower() for u in raw.split(",") if u.strip()]


# The sales role is SCOPED (fail-closed): a sales session may reach ONLY these path fragments;
# every other authenticated route returns 403 (API) or redirects to the leads view (pages). New
# endpoints are therefore denied to sales BY DEFAULT — no financial surface can leak by omission.
_SALES_ALLOWED_FRAGMENTS = (
    "/api/reactivation",   # list + export.csv + brief.pdf
    "/api/lead-lookup",    # "where did we leave off with X" (grounded, scoped)
    "/api/whoami",
)


# ad_domain is SCOPED the same fail-closed way: the ad dashboard and nothing else.
# Every finance surface (snapshot, cash, payroll, quarterly, email, leads) is denied
# BY DEFAULT — a new endpoint cannot leak to the role by omission. Discussion
# endpoints live under /ads/api/ so the role reaches them; card APPLIES and
# every money-truth action live outside /ads and stay owner-side structurally.
_AD_DOMAIN_ALLOWED_FRAGMENTS = (
    "/ads",                # the dedicated ad dashboard (pages + its /ads/api/*)
    "/api/whoami",
    "/logout",
)

_AD_DOMAIN_ROLES = ("ad_domain", "media_buyer")   # media_buyer = stale-session synonym


def ad_domain_permitted(path: str) -> bool:
    p = path or ""
    return any(frag in p for frag in _AD_DOMAIN_ALLOWED_FRAGMENTS)


def is_ad_domain(role: str | None = None) -> bool:
    r = role if role is not None else current_actor().get("role")
    return r in _AD_DOMAIN_ROLES


# legacy name kept — external references and tests predate the rename
def media_buyer_permitted(path: str) -> bool:
    return ad_domain_permitted(path)


def is_sales() -> bool:
    return current_actor().get("role") == "sales"


def sales_permitted(path: str) -> bool:
    """True if a sales session may access `path`. Fail-closed: unknown paths are NOT permitted."""
    p = path or ""
    if any(frag in p for frag in _SALES_ALLOWED_FRAGMENTS):
        return True
    tail = p.rstrip("/")
    return tail.endswith("/leads") or tail.endswith("/logout")


def per_user_enabled() -> bool:
    """True once at least one per-user password is set — this also retires the legacy token."""
    return bool(_accounts())


def verify_login(username: str, password: str) -> dict | None:
    """Constant-time credential check. Returns {user, role, display} or None."""
    a = _accounts().get((username or "").strip().lower())
    if a and password and hmac.compare_digest(a["pw"], password):
        return {"user": (username or "").strip().lower(), "role": a["role"], "display": a["display"]}
    return None


def current_actor() -> dict:
    """The acting user for this request — {user, role, display}. Set by require_auth; falls back to
    owner (rydel) on the legacy-token path so attribution is never blank."""
    act = getattr(g, "actor", None) or session.get("actor")
    return act or {"user": "rydel", "role": "owner", "display": "Rydel"}


def is_owner() -> bool:
    return current_actor().get("role") == "owner"


# ── R-PIOLO-PARITY (#167) — Rydel's ruling, 24 Sep, supersedes the #161
# carve-outs. The finance role (Piolo, CFO/bookkeeper) sees and does
# EVERYTHING the owner does: every tab, drawer, export and action, EDITH
# chat AND voice with the same facts. The safeguards that replace the
# carve-outs: every action is attributed and journaled, the owner can
# reverse any action, and discreet mode stays the owner's own toggle.
# Exactly three things remain truly owner-only: the discreet-mode toggle,
# credential/env management, and the parity exception list itself.
_FINANCE_ROLES = ("owner", "coo")


def is_finance(role: str | None = None) -> bool:
    """Owner-grade access: the owner, or the finance role at parity."""
    r = role if role is not None else current_actor().get("role")
    return r in _FINANCE_ROLES


def audit_login(actor: dict, ok: bool = True) -> None:
    """Append a login event to the durable audit (kv_store); never stores the password."""
    try:
        import kv_store
        from helpers import now_sydney
        log = kv_store.get("auth:login_log") or []
        log.append({"user": actor.get("user") if actor else "(unknown)",
                    "ok": ok, "at": now_sydney().isoformat(),
                    "ip": (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:45]})
        kv_store.put("auth:login_log", log[-500:])
    except Exception as e:
        logger.info("audit_login failed: %s", e)


def _set_legacy_cookie(resp):
    resp.set_cookie(COOKIE_NAME, DASHBOARD_TOKEN, max_age=COOKIE_MAX_AGE,
                    httponly=True, samesite="Lax", secure=True)
    return resp


def require_auth(f):
    """Authenticate + set g.actor. Per-user session first; legacy token ONLY while no per-user
    accounts are configured (so setting the passwords retires the token)."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        act = session.get("actor")
        if act:
            g.actor = act
            # Scoped sales role: fail-closed allowlist. Anything outside it is denied here, once,
            # centrally — so no financial endpoint can leak to the sales team by being forgotten.
            if act.get("role") == "sales" and not sales_permitted(request.path):
                if "/api/" in (request.path or ""):
                    return jsonify({"error": "This view is limited to lead reactivation.",
                                    "scope": "sales"}), 403
                return redirect(url_for("dashboard.sales_page"))
            # R-PIOLO-PARITY (#167): the finance role inherits the owner's
            # reach — no allowlist to maintain, so a route granted to the
            # owner is granted to finance at the same moment. The ONLY
            # denials come from the explicit exception list (default empty;
            # the CSM toggle writes to it) and the three strict items.
            if act.get("role") == "coo":
                blocked, why = finance_blocked(request.path)
                if blocked:
                    if "/api/" in (request.path or ""):
                        return jsonify({"error": why, "scope": "finance"}), 403
                    return redirect(url_for("dashboard.landing_page"))
            if act.get("role") in _AD_DOMAIN_ROLES and not ad_domain_permitted(request.path):
                if "/api/" in (request.path or ""):
                    return jsonify({"error": "This view is limited to the ad dashboard.",
                                    "scope": "ad_domain"}), 403
                return redirect("/ads")
            return f(*args, **kwargs)

        # Legacy shared-token path — disabled once per-user auth is enabled.
        if not per_user_enabled():
            token_param = request.args.get("t")
            if token_param == DASHBOARD_TOKEN:
                return _set_legacy_cookie(make_response(redirect(request.path)))
            if request.cookies.get(COOKIE_NAME) == DASHBOARD_TOKEN:
                g.actor = {"user": "rydel", "role": "owner", "display": "Rydel"}
                return _set_legacy_cookie(make_response(f(*args, **kwargs)))

        # Not authenticated.
        if "/api/" in (request.path or ""):
            return jsonify({"error": "session expired — log in again",
                            "login": url_for("dashboard.login_page")}), 401
        return redirect(url_for("dashboard.login_page"))

    return wrapper


def require_owner(f):
    """FINANCE-GRADE gate (R-PIOLO-PARITY, #167): the owner or the finance
    role at full parity. The name stays for the sixty-plus call sites; the
    meaning is the ruling's. For the three truly-owner-only items use
    require_owner_strict."""
    @functools.wraps(f)
    @require_auth
    def wrapper(*args, **kwargs):
        if not is_finance():
            return jsonify({"error": "finance-only",
                            "role": current_actor().get("role")}), 403
        return f(*args, **kwargs)
    return wrapper


def require_owner_strict(f):
    """The THREE (#167): the discreet-mode toggle, credential/env
    management, and the parity exception list. Nobody but the owner."""
    @functools.wraps(f)
    @require_auth
    def wrapper(*args, **kwargs):
        if not is_owner():
            return jsonify({"error": "owner-only (strict)",
                            "role": current_actor().get("role")}), 403
        return f(*args, **kwargs)
    return wrapper
