"""Google desktop OAuth with PKCE and Secret Service storage."""

import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from wsgiref.simple_server import WSGIRequestHandler, make_server

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from keyring.backends.SecretService import Keyring

PREFIX = "https://www.googleapis.com/auth/googlehealth."
SCOPES = [
    PREFIX + x + ".readonly"
    for x in ("activity_and_fitness", "sleep", "health_metrics_and_measurements", "settings")
]


class AuthError(Exception):
    """Only safe, fixed messages may be passed to this exception."""


class Vault:
    def __init__(self, namespace):
        self.keyring = Keyring()
        self.service = "fitdash-widget:" + namespace

    def load(self):
        try:
            raw = self.keyring.get_password(self.service, "google-health")
            if not raw:
                return None
            info = json.loads(raw)
            return Credentials.from_authorized_user_info(info)
        except Exception:
            raise AuthError("keyring_unavailable") from None

    def save(self, credentials):
        try:
            # Persist actual grants, not the originally requested scope set.
            info = json.loads(credentials.to_json())
            if credentials.granted_scopes is not None:
                info["scopes"] = list(credentials.granted_scopes)
            self.keyring.set_password(self.service, "google-health", json.dumps(info))
        except Exception:
            raise AuthError("keyring_unavailable") from None

    def clear(self):
        try:
            if self.keyring.get_password(self.service, "google-health"):
                self.keyring.delete_password(self.service, "google-health")
        except Exception:
            raise AuthError("keyring_unavailable") from None


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass  # Callback URLs contain authorization codes.


def authenticate(client_path, vault, cache, scopes=SCOPES):
    vault.load()  # Fail before opening the browser if keyring access is unavailable.
    with open(client_path) as source:
        config = json.load(source)
    if "installed" not in config:
        raise AuthError("desktop_client_required")
    client = config["installed"]
    if (
        client.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth"
        and client.get("auth_uri") != "https://accounts.google.com/o/oauth2/v2/auth"
    ):
        raise AuthError("invalid_client_configuration")
    if client.get("token_uri") != "https://oauth2.googleapis.com/token":
        raise AuthError("invalid_client_configuration")
    flow = InstalledAppFlow.from_client_config(config, scopes=scopes, autogenerate_code_verifier=True)
    state = secrets.token_urlsafe(32)
    result = {}

    def callback(environ, start_response):
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        valid = environ.get("PATH_INFO") == "/" and secrets.compare_digest(query.get("state", [""])[0], state)
        if not valid:
            start_response("400 Bad Request", [("Content-Type", "text/plain")])
            return [b"Invalid authorization callback. Return to FitDash and try again."]
        result.update(query)
        start_response(
            "200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store")]
        )
        return [
            b"<html><title>FitDash</title><body><h1>FitDash</h1><p>Authorization received. You can close this tab and return to the widget.</p></body></html>"
        ]

    with make_server("127.0.0.1", 0, callback, handler_class=QuietHandler) as server:
        server.timeout = 1
        flow.redirect_uri = f"http://127.0.0.1:{server.server_port}/"
        url, _ = flow.authorization_url(state=state, access_type="offline", prompt="consent")
        cache.write("auth.json", {"status": "authorizing", "started_at": time.time()})
        if not webbrowser.open(url):
            raise AuthError("browser_unavailable")
        deadline = time.monotonic() + 300
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result:
        raise AuthError("authorization_timeout")
    if "error" in result or not result.get("code"):
        raise AuthError("authorization_denied")
    try:
        # A user may grant only some requested scopes. Keep the actual grants.
        previous = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        try:
            flow.fetch_token(code=result["code"][0], timeout=20)
        finally:
            if previous is None:
                os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
            else:
                os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = previous
    except Exception:
        raise AuthError("token_exchange_failed") from None
    creds = flow.credentials
    if not creds.refresh_token:
        raise AuthError("refresh_token_missing")
    vault.save(creds)
    cache.clear_health()
    cache.write("auth.json", {"status": "connected", "completed_at": time.time()})


def refreshed(vault, force=False):
    creds = vault.load()
    if creds is None:
        raise AuthError("disconnected")
    if force or not creds.valid:
        from google.auth.exceptions import RefreshError, TransportError

        try:

            class TimedRequest(Request):
                def __call__(self, *args, **kwargs):
                    kwargs["timeout"] = 15
                    return super().__call__(*args, **kwargs)

            creds.refresh(TimedRequest())
        except RefreshError as error:
            raise AuthError("offline" if error.retryable else "reconnect_required") from None
        except TransportError:
            raise AuthError("offline") from None
        vault.save(creds)
    return creds
