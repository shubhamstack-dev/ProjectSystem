"""Microsoft Entra ID (what used to be called Azure AD).

Two separate conversations with Microsoft, and they use different credentials
for good reason.

*Signing in* is the authorisation code flow with PKCE, run in the browser. The
user authenticates against Microsoft directly; this API only ever receives a
code, which it exchanges for an id token. No password reaches us, which is
rather the point of using a directory at all.

*Importing users* is the client credentials flow against Microsoft Graph, run
by an administrator from a screen. It uses the application's own identity and
needs User.Read.All granted with admin consent on the app registration.

Everything here degrades honestly: with no tenant configured the endpoints say
so plainly rather than failing somewhere deeper with a stack trace.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .. import config

GRAPH = "https://graph.microsoft.com/v1.0"
# The fields worth having. userType is the one that decides which side of the
# wall an imported person lands on.
GRAPH_FIELDS = ("id,displayName,givenName,surname,mail,userPrincipalName,"
                "jobTitle,department,accountEnabled,userType")


class EntraNotConfigured(RuntimeError):
    pass


class EntraError(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.ENTRA_TENANT_ID and config.ENTRA_CLIENT_ID)


def can_import() -> bool:
    """Importing needs a client secret as well as the tenant and client id."""
    return configured() and bool(config.ENTRA_CLIENT_SECRET)


def _require() -> None:
    if not configured():
        raise EntraNotConfigured(
            "Microsoft sign-in is not set up. Add ENTRA_TENANT_ID and "
            "ENTRA_CLIENT_ID to the backend .env, then restart the API.")


def _authority() -> str:
    return f"https://login.microsoftonline.com/{config.ENTRA_TENANT_ID}"


# ------------------------------------------------------------------- PKCE

def new_pkce() -> tuple[str, str]:
    """Verifier and its S256 challenge.

    PKCE matters here even though this is a confidential client: the code comes
    back through the browser, and the verifier is what stops an intercepted code
    being redeemed by anybody else.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def authorize_url(state: str, challenge: str, redirect_uri: str) -> str:
    _require()
    q = {
        "client_id": config.ENTRA_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": "openid profile email User.Read",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{_authority()}/oauth2/v2.0/authorize?" + urllib.parse.urlencode(q)


# ------------------------------------------------------------------- tokens

def _post_form(url: str, form: dict) -> dict:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            j = json.loads(body)
            msg = j.get("error_description") or j.get("error") or body
        except Exception:
            msg = body
        raise EntraError(f"Microsoft refused the request: {msg.splitlines()[0][:300]}")
    except Exception as e:
        raise EntraError(f"Could not reach Microsoft: {e}")


def exchange_code(code: str, verifier: str, redirect_uri: str) -> dict:
    """Swap the authorisation code for tokens, and return the id token claims."""
    _require()
    form = {
        "client_id": config.ENTRA_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "scope": "openid profile email User.Read",
    }
    if config.ENTRA_CLIENT_SECRET:
        form["client_secret"] = config.ENTRA_CLIENT_SECRET
    tok = _post_form(f"{_authority()}/oauth2/v2.0/token", form)
    if "id_token" not in tok:
        raise EntraError("Microsoft returned no id token")
    return decode_id_token(tok["id_token"])


def decode_id_token(id_token: str) -> dict:
    """Read the claims out of the id token.

    The token arrived over TLS directly from Microsoft's token endpoint, in
    response to a code that only we could redeem, so the claims are trusted on
    the strength of that channel. An id token picked up anywhere else must have
    its signature checked against the tenant's JWKS before it is believed.
    """
    try:
        _, body, _ = id_token.split(".")
        pad = "=" * (-len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception:
        raise EntraError("The id token from Microsoft could not be read")


def _app_token() -> str:
    """The application's own token, for Graph."""
    if not can_import():
        raise EntraNotConfigured(
            "Fetching users needs ENTRA_CLIENT_SECRET as well as the tenant and "
            "client id, and User.Read.All granted with admin consent.")
    tok = _post_form(f"{_authority()}/oauth2/v2.0/token", {
        "client_id": config.ENTRA_CLIENT_ID,
        "client_secret": config.ENTRA_CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    })
    if "access_token" not in tok:
        raise EntraError("Microsoft returned no access token for the application")
    return tok["access_token"]


# -------------------------------------------------------------------- Graph

def fetch_users(limit: int = 500, search: str | None = None) -> list[dict]:
    """Every user in the tenant, normalised.

    Graph pages at 100 by default and hands back an @odata.nextLink; a tenant
    with 300 staff would silently import as 100 if that were ignored.
    """
    token = _app_token()
    q = {"$select": GRAPH_FIELDS, "$top": "100"}
    if search:
        # startswith rather than $search, which needs a ConsistencyLevel header
        safe = search.replace("'", "''")
        q["$filter"] = (f"startswith(displayName,'{safe}') or "
                        f"startswith(mail,'{safe}') or "
                        f"startswith(userPrincipalName,'{safe}')")
    url = f"{GRAPH}/users?" + urllib.parse.urlencode(q)
    out: list[dict] = []
    while url and len(out) < limit:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                page = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:400]
            if e.code == 403:
                raise EntraError(
                    "Microsoft refused the directory read. The app registration "
                    "needs User.Read.All as an application permission, granted "
                    "with admin consent.")
            raise EntraError(f"Graph returned {e.code}: {body}")
        except Exception as e:
            raise EntraError(f"Could not reach Microsoft Graph: {e}")
        for u in page.get("value", []):
            out.append(normalise(u))
        url = page.get("@odata.nextLink")
    return out[:limit]


def normalise(u: dict) -> dict:
    """Graph's shape, reduced to what this product stores.

    mail is empty for plenty of real accounts, so userPrincipalName is the
    fallback; a guest's upn carries the #EXT# mangling, which is fine as an
    identifier and wrong as an address, so it is only used when mail is absent.
    """
    email = (u.get("mail") or u.get("userPrincipalName") or "").strip().lower()
    return {
        "oid": u.get("id"),
        "display_name": (u.get("displayName") or email or "").strip(),
        "email": email,
        "job_title": u.get("jobTitle"),
        "department": u.get("department"),
        "user_type": u.get("userType") or "Member",
        "enabled": bool(u.get("accountEnabled", True)),
    }
