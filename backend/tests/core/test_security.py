"""JWT verification against a locally generated RSA key (the JWKS client is stubbed)."""

import time
from dataclasses import dataclass
from typing import Protocol

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import cognito_settings
from app.core.exceptions import AppError
from tests.seeds import seed_user

KID = "test-key"
SUB = "cognito-sub-1"

type Claims = dict[str, object]


class Mint(Protocol):
    def __call__(self, overrides: Claims | None = None) -> str: ...


@dataclass(frozen=True)
class _StubJwksClient:
    jwk: PyJWK

    def get_signing_key_from_jwt(self, _token: str) -> PyJWK:
        return self.jwk


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _stub_jwks(monkeypatch: pytest.MonkeyPatch, private_key: rsa.RSAPrivateKey) -> None:
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk = PyJWK.from_dict({**public_jwk, "kid": KID, "alg": "RS256", "use": "sig"})
    monkeypatch.setattr(security, "_jwks_client", lambda: _StubJwksClient(jwk))


@pytest.fixture
def mint(private_key: rsa.RSAPrivateKey) -> Mint:
    def _mint(overrides: Claims | None = None) -> str:
        now = int(time.time())
        claims: Claims = {
            "sub": SUB,
            "token_use": "access",
            "client_id": cognito_settings.cognito_client_id,
            "iss": cognito_settings.issuer,
            "iat": now,
            "exp": now + 300,
            **(overrides or {}),
        }
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KID})

    return _mint


async def test_valid_access_token_yields_claims(mint: Mint) -> None:
    claims = await security.verify_access_token(mint())

    assert claims.sub == SUB
    assert claims.token_use == "access"


@pytest.mark.parametrize(
    "overrides",
    [
        {"token_use": "id"},
        {"client_id": "another-app-client"},
        {"exp": int(time.time()) - 10},
        {"iss": "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_OTHERPOOL"},
    ],
    ids=["id_token", "wrong_client_id", "expired", "wrong_issuer"],
)
async def test_invalid_tokens_are_rejected(mint: Mint, overrides: Claims) -> None:
    with pytest.raises(AppError) as excinfo:
        await security.verify_access_token(mint(overrides))

    assert excinfo.value.status_code == 401


async def test_garbage_token_is_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        await security.verify_access_token("not.a.jwt")

    assert excinfo.value.status_code == 401


async def test_bearer_resolves_to_the_local_user(client: AsyncClient, db_session: AsyncSession, mint: Mint) -> None:
    user = await seed_user(db_session, email="jwt@example.com", cognito_sub=SUB)

    response = await client.get("/api/users/me", headers={"Authorization": f"Bearer {mint()}"})

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


async def test_valid_token_without_local_user_is_401(client: AsyncClient, mint: Mint) -> None:
    response = await client.get("/api/users/me", headers={"Authorization": f"Bearer {mint({'sub': 'nobody'})}"})

    assert response.status_code == 401
    assert response.json()["error"] == "Unknown user"
