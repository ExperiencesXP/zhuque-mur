import time
import webbrowser

import requests

from constants.info import USER_AGENT
from utils.secrets import env_val


class OAuthError(RuntimeError):
    pass


def _headers() -> dict:
    return {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def discover(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    response = requests.get(url, headers=_headers(), timeout=20)
    response.raise_for_status()
    return response.json()


def resolve_client_id(oauth: dict) -> str:
    env_name = oauth.get("client_id_env")
    if env_name:
        override = env_val(env_name)
        if override:
            return override
    client_id = oauth.get("client_id")
    if not client_id:
        raise OAuthError("No OAuth client_id configured for this provider.")
    return client_id


def device_login(oauth: dict, announce) -> dict:
    """RFC 8628 device authorization grant.

    `announce(verification_uri, user_code, verification_uri_complete)` is
    called once so the CLI can print the code before we start polling.
    """
    issuer = oauth["issuer"]
    client_id = resolve_client_id(oauth)
    scope = oauth.get("scope") or "openid"
    try:
        config = discover(issuer)
    except requests.RequestException as exc:
        raise OAuthError(f"Could not load OAuth discovery from {issuer}: {exc}") from exc

    device_url = config.get("device_authorization_endpoint")
    token_url = config.get("token_endpoint")
    if not device_url or not token_url:
        raise OAuthError(f"{issuer} does not advertise a device-code flow.")

    try:
        started = requests.post(
            device_url,
            data={"client_id": client_id, "scope": scope},
            headers=_headers(),
            timeout=20,
        )
        started.raise_for_status()
        device = started.json()
    except requests.RequestException as exc:
        raise OAuthError(f"Device-code request failed: {exc}") from exc

    user_code = device.get("user_code")
    verify = device.get("verification_uri") or device.get("verification_uri_complete")
    complete = device.get("verification_uri_complete")
    if not user_code or not verify:
        raise OAuthError(f"Unexpected device-code response from {issuer}.")

    announce(verify, user_code, complete)
    open_url = complete or verify
    try:
        webbrowser.open(open_url)
    except Exception:
        pass

    interval = int(device.get("interval") or 5)
    deadline = time.time() + int(device.get("expires_in") or 600)
    payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device["device_code"],
        "client_id": client_id,
    }

    while time.time() < deadline:
        time.sleep(interval)
        try:
            polled = requests.post(token_url, data=payload, headers=_headers(), timeout=20)
            body = polled.json()
        except requests.RequestException:
            continue
        if "access_token" in body:
            body["_issuer"] = issuer
            body["_client_id"] = client_id
            body["_token_endpoint"] = token_url
            return body
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error in {"expired_token", "access_denied"}:
            raise OAuthError(f"OAuth {error}. Run auth login again.")
        raise OAuthError(body.get("error_description") or error or "OAuth failed")

    raise OAuthError("OAuth timed out before you approved it.")


def refresh_tokens(entry: dict) -> dict:
    refresh = entry.get("refresh_token")
    token_url = entry.get("token_endpoint")
    client_id = entry.get("client_id")
    if not refresh or not token_url or not client_id:
        raise OAuthError("Stored OAuth session cannot be refreshed. Run auth login again.")
    response = requests.post(
        token_url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        },
        headers=_headers(),
        timeout=20,
    )
    body = response.json() if response.content else {}
    if response.status_code >= 400 or "access_token" not in body:
        raise OAuthError(body.get("error_description") or "OAuth refresh failed. Run auth login again.")
    merged = dict(entry)
    merged["access_token"] = body["access_token"]
    if body.get("refresh_token"):
        merged["refresh_token"] = body["refresh_token"]
    expires_in = int(body.get("expires_in") or 3600)
    merged["expires_at"] = int(time.time()) + expires_in
    return merged
