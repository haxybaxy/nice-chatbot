"""The one error shape every client sees: {error, code, statusCode, correlationId, details?}."""

from uuid import UUID

from httpx import AsyncClient

ENVELOPE_KEYS = {"error", "code", "statusCode", "correlationId"}


async def test_unmatched_path_is_enveloped(client: AsyncClient) -> None:
    response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["code"] == "HTTP_ERROR"
    assert body["statusCode"] == 404


async def test_validation_error_is_enveloped_with_details(client: AsyncClient) -> None:
    response = await client.post("/api/auth/signup", json={"email": "not-an-email", "password": "short"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    # The test tier exposes debug details; each entry names the offending field.
    locations = {tuple(error["loc"]) for error in body["details"]}
    assert ("body", "email") in locations
    assert ("body", "password") in locations


async def test_unknown_request_field_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/signin", json={"email": "a@example.com", "password": "x", "rememberMe": True}
    )

    assert response.status_code == 422


async def test_missing_bearer_is_401_with_challenge(client: AsyncClient) -> None:
    response = await client.get("/api/users/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "AUTH_FAILED"


async def test_client_request_id_is_echoed_as_correlation_id(client: AsyncClient) -> None:
    request_id = "3f0b2b2c-3a3d-4b7e-9d4e-2f9c9c8f1a11"

    response = await client.get("/api/does-not-exist", headers={"X-Request-ID": request_id})

    assert response.headers["x-correlation-id"] == request_id
    assert response.json()["correlationId"] == request_id


async def test_correlation_id_is_minted_when_absent_or_invalid(client: AsyncClient) -> None:
    response = await client.get("/api/does-not-exist", headers={"X-Request-ID": "not-a-uuid"})

    correlation_id = response.headers["x-correlation-id"]
    assert correlation_id != "not-a-uuid"
    assert UUID(correlation_id)
    assert response.json()["correlationId"] == correlation_id
