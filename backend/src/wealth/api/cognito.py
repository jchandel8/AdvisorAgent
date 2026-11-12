"""Verify Amazon Cognito access tokens and map them to a person in the database.

The browser signs in through Cognito's hosted login page (OAuth code flow with PKCE) and sends the
ACCESS token as `Authorization: Bearer ...`. Every request checks, in this order:

1. signature: RS256 with a key from the user pool's published JWKS (keys cached, refreshed on rotation);
2. issuer: exactly this user pool;
3. expiry (with 30 s leeway) and `token_use == "access"`;
4. `client_id`: exactly our app client (access tokens carry client_id, not aud);
5. exactly one of the groups advisors / clients / admins.

Identity mapping: the Cognito username IS the database username (advisors.username / clients.username,
both unique), and the group says which table. No custom attributes or Lambda triggers are needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt

GROUPS = {"advisors": "advisor", "clients": "client", "admins": "admin"}
LEEWAY_SECONDS = 30


class TokenError(Exception):
    """The token is missing, malformed, expired, or not for this app. Always answered with 401."""


@dataclass(frozen=True)
class TokenIdentity:
    kind: str  # advisor | client | admin
    username: str
    sub: str


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    # Caches the key set; an unknown key id triggers one refetch (key rotation).
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def signing_key(token: str, issuer: str) -> object:
    return _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token).key


def verify_access_token(
    token: str, *, issuer: str, client_id: str, key_resolver=signing_key
) -> TokenIdentity:
    try:
        key = key_resolver(token, issuer)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],  # never "none", never HS*
            issuer=issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "sub", "token_use", "client_id"], "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(f"invalid token: {type(exc).__name__}") from exc
    except Exception as exc:  # key fetch problems and the like: still a 401, never a 500 with details
        raise TokenError("token could not be verified") from exc

    if claims.get("token_use") != "access":
        raise TokenError("not an access token")
    if claims.get("client_id") != client_id:
        raise TokenError("token is for another app")
    groups = [g for g in claims.get("cognito:groups", []) if g in GROUPS]
    if len(groups) != 1:
        raise TokenError("user must be in exactly one of advisors, clients, admins")
    username = claims.get("username") or claims.get("cognito:username")
    if not isinstance(username, str) or not username:
        raise TokenError("token has no username")
    return TokenIdentity(kind=GROUPS[groups[0]], username=username, sub=str(claims["sub"]))
