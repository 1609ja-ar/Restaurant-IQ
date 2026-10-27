"""Authentication: accounts, bcrypt passwords, JWT sessions in an HttpOnly cookie, login rate limiting.

Design (see docs/assumptions_log.md A23-A27):
* Passwords are hashed with bcrypt (cost 12). Plain passwords and tokens are never stored or logged.
* A successful sign-in sets a short-lived (JWT_EXPIRE_MINUTES) HS256 JWT in the ``riq_session`` cookie:
  HttpOnly (not readable by JavaScript), SameSite=Lax (not sent on cross-site POSTs), Secure when
  COOKIE_SECURE=true. API clients may also send ``Authorization: Bearer <token>``.
* Tokens carry the user's ``token_version``; changing the password bumps it, ending every other session.
  Logout revokes the token's id (jti) for the rest of its lifetime (in memory) and clears the cookie.
* Every route is protected by the app-wide ``require_auth`` dependency except the PUBLIC_PATHS below.
* Failed sign-ins are limited to 5 per 15 minutes per email and per client IP (in memory).
"""
from __future__ import annotations

import contextvars
import logging
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .config import get_settings

log = logging.getLogger("restaurantiq.auth")

COOKIE_NAME = "riq_session"
ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12
MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
GENERIC_LOGIN_ERROR = "Incorrect email or password."
SIGN_IN_REQUIRED = "Please sign in to continue."
SESSION_EXPIRED = "Your session expired. Please sign in again."

# Routes reachable without signing in. Everything else under the app requires a valid session.
PUBLIC_PATHS = {"/", "/favicon.ico", "/api/health", "/api/auth/config", "/api/auth/login", "/api/auth/register",
                "/api/auth/demo-login", "/api/auth/logout"}

_current_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar("riq_current_user", default=None)
_ephemeral_secret: str | None = None


class AuthConfigError(RuntimeError):
    """Raised at startup when authentication cannot be configured safely."""


def _store():
    """The active storage backend (looked up at call time so tests can swap it)."""
    from . import main
    return main.store


# ---------------------------------------------------------------------------
# Secrets and configuration
# ---------------------------------------------------------------------------
def jwt_secret() -> str:
    """JWT_SECRET from .env. In development a missing secret gets a random per-process one (sessions end on
    restart); in production (RIQ_ENV=production) a missing or short secret is a startup error."""
    global _ephemeral_secret
    s = get_settings()
    if s.jwt_secret:
        if s.app_env == "production" and len(s.jwt_secret) < 32:
            raise AuthConfigError("JWT_SECRET must be at least 32 characters in production.")
        return s.jwt_secret
    if s.app_env == "production":
        raise AuthConfigError("JWT_SECRET is not set. Generate one with: python -c \"import secrets; "
                              "print(secrets.token_urlsafe(48))\" and add JWT_SECRET=... to backend/.env.")
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        log.warning("JWT_SECRET is not set: using a temporary secret for this development run. Everyone is signed "
                    "out when the backend restarts. Set JWT_SECRET in backend/.env to keep sessions.")
    return _ephemeral_secret


def startup_check() -> None:
    jwt_secret()   # raises AuthConfigError in production without a proper secret
    seed_demo_user()


# ---------------------------------------------------------------------------
# Passwords and validation
# ---------------------------------------------------------------------------
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(422, "Enter a valid email address, for example name@example.com.")


def check_password_strength(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters long.")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise HTTPException(422, "Password must contain at least one letter and one number.")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(422, "Password must be at most 72 bytes (bcrypt limit). Use a shorter password.")


def check_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise HTTPException(422, "Enter your name.")
    if len(name) > 80:
        raise HTTPException(422, "Name must be at most 80 characters.")
    return name


def public_user(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"], "is_demo": bool(user.get("is_demo"))}


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
_revoked: dict[str, float] = {}      # jti -> expiry (unix time)
_revoked_lock = threading.Lock()


def create_token(user: dict) -> tuple[str, int]:
    minutes = get_settings().jwt_expire_minutes
    now = datetime.now(timezone.utc)
    claims = {"sub": user["id"], "ver": int(user.get("token_version", 0)), "jti": uuid.uuid4().hex,
              "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(claims, jwt_secret(), algorithm=ALGORITHM), minutes * 60


def decode_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, jwt_secret(), algorithms=[ALGORITHM], options={"require": ["sub", "exp", "jti"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, SESSION_EXPIRED)
    except jwt.InvalidTokenError:
        raise HTTPException(401, SIGN_IN_REQUIRED)
    with _revoked_lock:
        if claims["jti"] in _revoked:
            raise HTTPException(401, SIGN_IN_REQUIRED)
    return claims


def revoke(claims: dict) -> None:
    with _revoked_lock:
        now = time.time()
        for jti, exp in list(_revoked.items()):
            if exp < now:
                del _revoked[jti]
        _revoked[claims["jti"]] = float(claims["exp"])


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(COOKIE_NAME)


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=max_age, httponly=True, samesite="lax",
                        secure=get_settings().cookie_secure, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=get_settings().cookie_secure)


# ---------------------------------------------------------------------------
# App-wide dependency
# ---------------------------------------------------------------------------
def user_from_request(request: Request) -> dict:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(401, SIGN_IN_REQUIRED)
    claims = decode_token(token)
    user = _store().get_user(claims["sub"])
    if user is None or int(user.get("token_version", 0)) != int(claims.get("ver", -1)):
        raise HTTPException(401, SESSION_EXPIRED)
    request.state.token_claims = claims
    return user


async def require_auth(request: Request) -> None:
    """Applied to every route. Public paths and the API docs pass through; everything else needs a session.
    Async on purpose: the user is stored in a context variable that the (threadpool) endpoint inherits."""
    path = request.url.path
    if path in PUBLIC_PATHS or not path.startswith("/api/"):
        return
    user = user_from_request(request)
    request.state.user = user
    _current_user.set(user)


def current_user() -> dict:
    user = _current_user.get()
    if user is None:
        raise HTTPException(401, SIGN_IN_REQUIRED)
    return user


def current_user_id() -> str:
    return current_user()["id"]


# ---------------------------------------------------------------------------
# Login rate limiting (in memory; per email and per client IP)
# ---------------------------------------------------------------------------
class LoginLimiter:
    def __init__(self, max_failures: int = MAX_FAILURES, window: int = WINDOW_SECONDS):
        self.max_failures, self.window = max_failures, window
        self._failures: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def check(self, *keys: str) -> None:
        now = time.time()
        with self._lock:
            for key in keys:
                q = self._prune(key, now)
                if len(q) >= self.max_failures:
                    wait = max(1, int((self.window - (now - q[0])) // 60) + 1)
                    raise HTTPException(429, f"Too many failed sign-in attempts. Try again in about {wait} minute"
                                             f"{'s' if wait != 1 else ''}.")

    def fail(self, *keys: str) -> None:
        now = time.time()
        with self._lock:
            for key in keys:
                self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


limiter = LoginLimiter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
def _new_user(name: str, email: str, password: str, is_demo: bool = False) -> dict:
    return {"id": uuid.uuid4().hex, "name": name, "email": email, "password_hash": hash_password(password),
            "token_version": 0, "is_demo": is_demo,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def seed_demo_user() -> None:
    """Creates the demo account from DEMO_USER_EMAIL / DEMO_USER_PASSWORD on first startup (never overwrites)."""
    from .store import DuplicateUser
    s = get_settings()
    if not s.demo_user_email:
        return
    try:
        email = normalize_email(s.demo_user_email)
    except HTTPException:
        log.warning("DEMO_USER_EMAIL is not a valid email address (reserved domains such as .local or .test are "
                    "not accepted; use e.g. demo@example.com); no demo account was created.")
        return
    try:
        if _store().get_user_by_email(email):
            return
        if not s.demo_user_password:
            log.warning("DEMO_USER_EMAIL is set but DEMO_USER_PASSWORD is empty; no demo account was created.")
            return
        try:
            check_password_strength(s.demo_user_password)
        except HTTPException as exc:
            log.warning("DEMO_USER_PASSWORD is too weak (%s); no demo account was created.", exc.detail)
            return
        user = _store().create_user(_new_user("Demo User", email, s.demo_user_password, is_demo=True))
        claimed = _store().claim_unowned(user["id"])
        log.info("Created demo account %s%s.", email,
                 f" and gave it {len(claimed)} dataset version(s) created before accounts existed" if claimed else "")
    except DuplicateUser:
        return
    except Exception as exc:  # database not reachable etc. - reported by the health check
        log.error("Could not create the demo account: %s", exc)


def demo_user() -> dict | None:
    s = get_settings()
    if not s.demo_user_email:
        return None
    try:
        user = _store().get_user_by_email(normalize_email(s.demo_user_email))
    except HTTPException:
        return None
    return user if user and user.get("is_demo") else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str = Field(max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


def _signed_in(response: Response, user: dict) -> dict:
    token, max_age = create_token(user)
    set_session_cookie(response, token, max_age)
    return {"user": public_user(user), "expires_in": max_age}


@router.get("/config")
def auth_config():
    return {"allow_registration": get_settings().allow_registration, "demo_available": demo_user() is not None}


@router.post("/register", status_code=201)
def register(req: RegisterRequest, response: Response):
    from .store import DuplicateUser
    if not get_settings().allow_registration:
        raise HTTPException(403, "New accounts are disabled on this server. Ask the administrator for an account.")
    name = check_name(req.name)
    email = normalize_email(req.email)
    check_password_strength(req.password)
    first_user = _store().count_users() == 0
    try:
        user = _store().create_user(_new_user(name, email, req.password))
    except DuplicateUser:
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    if first_user and not get_settings().demo_user_email:
        claimed = _store().claim_unowned(user["id"])
        if claimed:
            log.info("First account created; it now owns %d dataset version(s) from before accounts existed.", len(claimed))
    return _signed_in(response, user)


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response):
    email = req.email.strip().lower()
    keys = (f"email:{email}", f"ip:{_client_ip(request)}")
    limiter.check(*keys)
    user = _store().get_user_by_email(email) if email else None
    ok = verify_password(req.password, user["password_hash"] if user else _DUMMY_HASH) and user is not None
    if not ok:
        limiter.fail(*keys)
        log.info("Failed sign-in attempt for %s from %s", email or "<empty>", _client_ip(request))
        raise HTTPException(401, GENERIC_LOGIN_ERROR)
    limiter.reset(keys[0])
    return _signed_in(response, user)


@router.post("/demo-login")
def demo_login(response: Response):
    user = demo_user()
    if user is None:
        raise HTTPException(404, "No demo account is configured on this server.")
    return _signed_in(response, user)


@router.post("/logout")
def logout(request: Request, response: Response):
    token = _token_from_request(request)
    if token:
        try:
            revoke(decode_token(token))
        except HTTPException:
            pass   # already invalid or expired: nothing to revoke
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me():
    return {"user": public_user(current_user())}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request, response: Response):
    user = current_user()
    if not verify_password(req.current_password, user["password_hash"]):
        raise HTTPException(400, "Your current password is incorrect.")
    check_password_strength(req.new_password)
    if req.new_password == req.current_password:
        raise HTTPException(422, "Choose a new password that is different from the current one.")
    version = int(user.get("token_version", 0)) + 1
    _store().update_user(user["id"], password_hash=hash_password(req.new_password), token_version=version)
    claims = getattr(request.state, "token_claims", None)
    if claims:
        revoke(claims)
    return _signed_in(response, {**user, "token_version": version})
