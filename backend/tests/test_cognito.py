"""Cognito access-token verification and the API's cognito auth mode. A local RSA key stands in for the
user pool's JWKS, so these tests never call AWS."""

from __future__ import annotations

import time
from contextlib import contextmanager

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from tests.fixtures import A1, C1
from wealth.api import deps, routes_advisor
from wealth.api.cognito import TokenError, verify_access_token
from wealth.api.main import create_app
from wealth.config import get_settings

ISSUER = "https://cognito-idp.us-west-1.amazonaws.com/us-west-1_TESTPOOL"
CLIENT_ID = "test-client-id"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def resolver(token, issuer):
    return KEY.public_key()


def token(**overrides):
    now = int(time.time())
    claims = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "username": "adv101",
        "cognito:groups": ["advisors"],
        "iat": now,
        "exp": now + 3600,
    }
    sign_with = overrides.pop("_key", KEY)
    alg = overrides.pop("_alg", "RS256")
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, sign_with, algorithm=alg)


def verify(t):
    return verify_access_token(t, issuer=ISSUER, client_id=CLIENT_ID, key_resolver=resolver)


# --- verify_access_token --------------------------------------------------------------------------------


def test_valid_advisor_and_client_tokens():
    ident = verify(token())
    assert (ident.kind, ident.username) == ("advisor", "adv101")
    assert verify(token(**{"cognito:groups": ["clients"], "username": "cli201"})).kind == "client"


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"exp": int(time.time()) - 120}, id="expired"),
        pytest.param({"iss": "https://cognito-idp.us-west-1.amazonaws.com/us-west-1_OTHER"}, id="other-pool"),
        pytest.param({"client_id": "someone-elses-app"}, id="other-client"),
        pytest.param({"token_use": "id"}, id="id-token"),
        pytest.param({"cognito:groups": []}, id="no-group"),
        pytest.param({"cognito:groups": ["advisors", "clients"]}, id="two-groups"),
        pytest.param({"cognito:groups": ["superusers"]}, id="unknown-group"),
        pytest.param({"username": None}, id="no-username"),
        pytest.param({"_key": OTHER_KEY}, id="wrong-signing-key"),
    ],
)
def test_bad_tokens_are_rejected(bad):
    with pytest.raises(TokenError):
        verify(token(**bad))


def test_unsigned_and_hmac_tokens_are_rejected():
    claims = jwt.decode(token(), options={"verify_signature": False})
    with pytest.raises(TokenError):
        verify(jwt.encode(claims, None, algorithm="none"))
    with pytest.raises(TokenError):
        verify(jwt.encode(claims, "guessable-secret-padded-to-32-bytes!!", algorithm="HS256"))


def test_tampered_payload_is_rejected():
    header, payload, sig = token().split(".")
    other = token(username="adv102").split(".")[1]
    with pytest.raises(TokenError):
        verify(f"{header}.{other}.{sig}")


def test_garbage_is_rejected():
    with pytest.raises(TokenError):
        verify("not-a-jwt")


# --- API in cognito mode ------------------------------------------------------------------------------


@pytest.fixture
def cognito_api(conn, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setenv("COGNITO_REGION", "us-west-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-west-1_TESTPOOL")
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("COGNITO_DOMAIN", "advisoragent-test.auth.us-west-1.amazoncognito.com")
    get_settings.cache_clear()

    @contextmanager
    def store():
        yield conn

    app = create_app()
    app.dependency_overrides[deps.get_conn] = lambda: conn
    app.dependency_overrides[deps.get_key_resolver] = lambda: resolver
    app.dependency_overrides[routes_advisor.get_store] = lambda: store
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def test_identity_comes_from_the_token(cognito_api):
    me = cognito_api.get("/api/me", headers=bearer(token())).json()
    assert (me["kind"], me["id"]) == ("advisor", A1)  # username adv101 -> advisors.id 101
    me = cognito_api.get(
        "/api/me", headers=bearer(token(**{"cognito:groups": ["clients"], "username": "cli201"}))
    ).json()
    assert (me["kind"], me["id"]) == ("client", C1)


def test_demo_header_is_ignored_in_cognito_mode(cognito_api):
    assert cognito_api.get("/api/me", headers={"X-Demo-User": f"advisor:{A1}"}).status_code == 401
    assert cognito_api.get("/api/demo/users").status_code == 404


def test_group_decides_the_portal(cognito_api):
    client_token = token(**{"cognito:groups": ["clients"], "username": "cli201"})
    assert cognito_api.get("/api/advisor/clients", headers=bearer(client_token)).status_code == 403
    assert cognito_api.get("/api/client/accounts", headers=bearer(client_token)).status_code == 200


def test_advisor_group_with_a_client_username_finds_no_account(cognito_api):
    # Group says advisor, but the username belongs to a client: no advisor row matches, so no access.
    t = token(**{"cognito:groups": ["advisors"], "username": "cli201"})
    assert cognito_api.get("/api/me", headers=bearer(t)).status_code == 401


def test_bad_or_missing_tokens_are_401(cognito_api):
    assert cognito_api.get("/api/me").status_code == 401
    assert cognito_api.get("/api/me", headers={"Authorization": "Basic abc"}).status_code == 401
    assert cognito_api.get("/api/me", headers=bearer(token(exp=int(time.time()) - 600))).status_code == 401
    assert cognito_api.get("/api/me", headers=bearer(token(username="nobody"))).status_code == 401


def test_admins_wait_for_step_4(cognito_api):
    t = token(**{"cognito:groups": ["admins"], "username": "admin1"})
    assert cognito_api.get("/api/me", headers=bearer(t)).status_code == 403


def test_auth_config_is_public_and_secret_free(cognito_api):
    cfg = cognito_api.get("/api/auth/config").json()
    assert cfg == {
        "mode": "cognito",
        "authority": ISSUER,
        "client_id": CLIENT_ID,
        "domain": "advisoragent-test.auth.us-west-1.amazoncognito.com",
    }


def test_cognito_mode_refuses_to_start_without_pool_settings(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    for name in ("COGNITO_REGION", "COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="COGNITO_REGION"):
            with TestClient(create_app()):
                pass
    finally:
        get_settings.cache_clear()
