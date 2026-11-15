# The sign-up app: Google sign-in, face pictures, connecting Brightspace, settings.
# run: gunicorn 'app.main:create_app()' --bind 0.0.0.0:3500
#
# The browser only talks to this app (and d3l's sign-in tab). The app keeps people and settings
# in the database, sends face pictures to faces and asks d3l to start Brightspace sign-ins.

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import httpx
from authlib.integrations.flask_client import OAuth, OAuthError
from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user

from .config import Settings, load_settings
from .layout import LayoutError, validate_layout
from .services import D3l, Faces, ServiceError
from .store import UNITS, Person, PostgresStore, Store
from .vault import Vault

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 10 * 1024 * 1024  # five face pictures with room to spare
MAX_PICTURES = 20                  # the faces service's limit
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# read-only access to events, for the mirror's calendar widget
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"


class SignInFailed(Exception):
    pass


@dataclass(frozen=True)
class GoogleAccount:
    sub: str                        # Google's ID for the account
    name: str
    calendar: bool                  # they let us read their calendar
    refresh_token: Optional[str]    # only sent when they've just been asked


class Google(Protocol):
    def start(self, redirect_uri: str, ask_again: bool = False) -> Response: ...
    def finish(self) -> GoogleAccount: ...
    def revoke(self, refresh_token: str) -> None: ...


class AuthlibGoogle:
    """Google sign-in (OpenID Connect) through Authlib, which checks the state, nonce and ID token."""

    def __init__(self, app: Flask, settings: Settings):
        self._client = OAuth(app).register(
            "google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            # who they are, their name, and their calendar events. no email
            client_kwargs={"scope": f"openid profile {CALENDAR_SCOPE}"},
        )

    def start(self, redirect_uri: str, ask_again: bool = False) -> Response:
        # "offline" gets us a refresh token, so the mirror can read the calendar when they're not
        # signed in here. Google only sends it when it asks the person, which it does the first
        # time, and again whenever prompt=consent.
        extra = {"access_type": "offline", "include_granted_scopes": "true"}
        if ask_again:
            extra["prompt"] = "consent"
        return self._client.authorize_redirect(redirect_uri, **extra)

    def finish(self) -> GoogleAccount:
        try:
            token = self._client.authorize_access_token()
        except OAuthError as error:
            raise SignInFailed(error.description or error.error) from None
        claims = token.get("userinfo")
        if not claims or not claims.get("sub"):
            raise SignInFailed("Google didn't say who you are")
        return GoogleAccount(
            sub=claims["sub"],
            name=_display_name(claims),
            calendar=CALENDAR_SCOPE in (token.get("scope") or "").split(),
            refresh_token=token.get("refresh_token"),
        )

    def revoke(self, refresh_token: str) -> None:
        """Tells Google to forget the access it gave us. Best effort."""
        try:
            httpx.post("https://oauth2.googleapis.com/revoke", data={"token": refresh_token}, timeout=10)
        except httpx.HTTPError as error:
            logger.warning("Couldn't revoke a Google token: %r", error)


class User(UserMixin):
    def __init__(self, person: Person):
        self.person = person

    def get_id(self) -> str:
        return str(self.person.id)


def _display_name(claims: dict[str, Any]) -> str:
    name = (claims.get("given_name") or claims.get("name") or "").strip()
    return name[:60] or "Friend"


def create_app(
    settings: Optional[Settings] = None,
    store: Optional[Store] = None,
    google: Optional[Google] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> Flask:
    """`store`, `google` and `transport` are for tests."""
    settings = settings or load_settings()
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_NAME="sumirrorize",
        SESSION_COOKIE_SECURE=settings.secure_cookies,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=MAX_BODY_BYTES,
    )

    db = store or PostgresStore(settings.database_url)
    vault = Vault(settings.google_token_key)
    google = google or AuthlibGoogle(app, settings)
    client = httpx.Client(transport=transport, timeout=60)
    d3l = D3l(client, settings.d3l_url, settings.d3l_service_key)
    faces = Faces(client, settings.faces_url, settings.faces_api_key)

    login_manager = LoginManager(app)

    @login_manager.user_loader
    def load_user(person_id: str) -> Optional[User]:
        person = db.person(int(person_id))
        return User(person) if person else None

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/me"):
            return jsonify(error="Sign in first", code="signed_out"), 401
        return redirect(url_for("home"))

    def me() -> Person:
        return current_user.person

    # --- checks on every request ---

    @app.before_request
    def same_site_only():
        # every change comes from our own pages, which always send our Origin. this stops other
        # sites making changes with someone's login cookie
        if request.method not in SAFE_METHODS and request.headers.get("Origin") != settings.origin:
            return jsonify(error="Requests must come from the app's own pages", code="bad_origin"), 403

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ServiceError)
    def service_error(error: ServiceError):
        if error.status >= 500:
            logger.warning("%s: %s", error.code, error.message)
        return jsonify(error=error.message, code=error.code, **error.extra), error.status

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", message="There's no page here."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="That's too much to send at once", code="too_large"), 413

    @app.errorhandler(500)
    def server_error(_error):
        return render_template("error.html", message="Something went wrong on our end. Try again."), 500

    # --- pages ---

    @app.get("/")
    def home():
        if not current_user.is_authenticated:
            return render_template("index.html")
        person = me()
        # the page still loads if a service is down, it just says it couldn't check
        try:
            pictures: Optional[int] = len(faces.saved(person.id))
        except ServiceError as error:
            logger.warning("Settings page: %s: %s", error.code, error.message)
            pictures = None
        try:
            brightspace: Optional[dict[str, Any]] = d3l.status(person.id)
        except ServiceError as error:
            logger.warning("Settings page: %s: %s", error.code, error.message)
            brightspace = None
        return render_template("settings.html", person=person, pictures=pictures, brightspace=brightspace,
                               calendar=db.calendar_token(person.id) is not None,
                               units=db.units(person.id), api_url=settings.d3l_public_url)

    @app.get("/faces")
    @login_required
    def face_pictures():
        return render_template("faceregistration.html")

    @app.get("/layout")
    @login_required
    def layout():
        return render_template("layout.html", widgets=db.widgets(me().id))

    # --- Google sign-in ---

    @app.get("/login")
    def login():
        # ?calendar=1 is the "Connect Google Calendar" button: make Google ask again
        return google.start(f"{settings.public_url}/login/callback", ask_again=request.args.get("calendar") == "1")

    @app.get("/login/callback")
    def login_callback():
        try:
            account = google.finish()
        except SignInFailed as error:
            logger.info("Google sign-in failed: %s", error)
            return render_template("error.html", message="Signing in with Google didn't finish. Try again."), 400
        person, is_new = db.sign_in(account.sub, account.name)
        if account.calendar and account.refresh_token:
            db.save_calendar(person.id, vault.seal(person.id, account.refresh_token))
        login_user(User(person))
        if is_new:
            logger.info("New person %d signed up", person.id)
        # new people start with their face pictures
        return redirect(url_for("face_pictures") if is_new else url_for("home"))

    @app.post("/logout")
    def logout():
        logout_user()
        return redirect(url_for("home"))

    # --- JSON routes the pages call ---

    @app.put("/me/faces")
    @login_required
    def save_faces():
        body = request.get_json(silent=True)
        pictures = body.get("pictures") if isinstance(body, dict) else None
        if not isinstance(pictures, list) or not 1 <= len(pictures) <= MAX_PICTURES:
            return jsonify(error=f"Send between 1 and {MAX_PICTURES} pictures", code="bad_request"), 400
        return jsonify(faces.save(me().id, pictures))

    @app.post("/me/brightspace")
    @login_required
    def connect_brightspace():
        started = d3l.start_sign_in(me().id)
        path = started.get("path", "")
        if not path.startswith("/login/"):
            raise ServiceError(502, "d3l gave back an odd sign-in link", "d3l_error")
        return jsonify(url=settings.d3l_public_url + path, expiresAt=started.get("expiresAt"))

    @app.get("/me/brightspace")
    @login_required
    def brightspace_status():
        return jsonify(d3l.status(me().id))

    @app.delete("/me/brightspace")
    @login_required
    def disconnect_brightspace():
        d3l.sign_out(me().id)
        return "", 204

    @app.put("/me/units")
    @login_required
    def save_units():
        body = request.get_json(silent=True)
        units = body.get("units") if isinstance(body, dict) else None
        if units not in UNITS:
            return jsonify(error=f"units must be one of {', '.join(UNITS)}", code="bad_request"), 400
        db.set_units(me().id, units)
        return jsonify(units=units)

    @app.put("/me/widgets")
    @login_required
    def save_widgets():
        try:
            widgets = validate_layout(request.get_json(silent=True))
            db.set_widgets(me().id, widgets)
        except (LayoutError, ValueError) as error:
            return jsonify(error=str(error), code="bad_layout"), 400
        return jsonify(ok=True)

    @app.post("/me/api-key")
    @login_required
    def new_api_key():
        return jsonify(apiKey=db.new_api_key(me().id))

    def forget_calendar(person_id: int) -> None:
        sealed = db.calendar_token(person_id)
        token = vault.unseal(person_id, sealed) if sealed else None
        if token:
            google.revoke(token)
        db.forget_calendar(person_id)

    @app.delete("/me/calendar")
    @login_required
    def disconnect_calendar():
        forget_calendar(me().id)
        return "", 204

    @app.delete("/me")
    @login_required
    def delete_account():
        person = me()
        # d3l first, so it stops any sign-in and drops the login it holds in memory
        d3l.sign_out(person.id)
        forget_calendar(person.id)
        db.delete_person(person.id)
        logout_user()
        logger.info("Person %d deleted their account", person.id)
        return "", 204

    @app.get("/health")
    def health():
        return jsonify(ok=True)

    return app
