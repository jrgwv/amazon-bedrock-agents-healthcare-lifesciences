"""Veeva Vault REST API client with session-based auth and DynamoDB caching."""

import json
import os
import time

import boto3
import httpx
from aws_lambda_powertools import Logger

logger = Logger()

_VAULT_BASE_URL = os.environ.get("VAULT_BASE_URL", "")
_VAULT_API_VERSION = os.environ.get("VAULT_API_VERSION", "v26.1")
_SECRET_ARN = os.environ.get("VAULT_AUTH_SECRET_ARN", "")
_TABLE_NAME = os.environ.get("SESSION_CACHE_TABLE", "")
_SESSION_TTL_SECONDS = 900  # 15 min (under Vault's 20-min inactivity timeout)

_ddb = boto3.resource("dynamodb")
_secrets = boto3.client("secretsmanager")
_http = httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))


def _get_cache_key() -> str:
    return f"SESSION#{_VAULT_BASE_URL}"


def _get_cached_session() -> str | None:
    """Retrieve cached session from DynamoDB if not expired."""
    table = _ddb.Table(_TABLE_NAME)
    try:
        resp = table.get_item(Key={"pk": _get_cache_key()})
        item = resp.get("Item")
        if item and item.get("ttl", 0) > int(time.time()):
            return item["sessionId"]
    except Exception:
        logger.debug("Cache miss or error")
    return None


def _cache_session(session_id: str) -> None:
    """Store session in DynamoDB with TTL."""
    table = _ddb.Table(_TABLE_NAME)
    table.put_item(
        Item={
            "pk": _get_cache_key(),
            "sessionId": session_id,
            "ttl": int(time.time()) + _SESSION_TTL_SECONDS,
        }
    )


def _authenticate() -> str:
    """Authenticate against Vault and return sessionId."""
    secret_value = _secrets.get_secret_value(SecretId=_SECRET_ARN)
    creds = json.loads(secret_value["SecretString"])

    resp = _http.post(
        f"{_VAULT_BASE_URL}/api/{_VAULT_API_VERSION}/auth",
        data={"username": creds["username"], "password": creds["password"]},
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("responseStatus") != "SUCCESS":
        raise RuntimeError(f"Vault auth failed: {data.get('errors', [])}")

    session_id = data["sessionId"]
    _cache_session(session_id)
    logger.info("Vault authentication successful")
    return session_id


def get_session() -> str:
    """Get a valid Vault session, using cache or re-authenticating."""
    cached = _get_cached_session()
    if cached:
        return cached
    return _authenticate()


def vault_request(method: str, path: str, params: dict | None = None) -> dict:
    """Make an authenticated request to Vault with 401 retry.

    Args:
        method: HTTP method (GET, POST)
        path: API path (e.g., "/query")
        params: Query parameters

    Returns:
        Parsed JSON response from Vault
    """
    url = f"{_VAULT_BASE_URL}/api/{_VAULT_API_VERSION}{path}"

    for attempt in range(2):
        session_id = get_session()
        headers = {"Authorization": session_id, "Accept": "application/json"}

        resp = _http.request(method, url, headers=headers, params=params)

        if resp.status_code == 401 and attempt == 0:
            logger.warning("Vault session expired, re-authenticating")
            _authenticate()
            continue

        resp.raise_for_status()
        data = resp.json()

        if data.get("responseStatus") == "FAILURE":
            errors = data.get("errors", [])
            raise RuntimeError(f"Vault API error: {errors}")

        return data

    raise RuntimeError("Vault request failed after retry")


def vault_query(vql: str) -> list[dict]:
    """Execute a VQL query and return the data rows."""
    resp = vault_request("GET", "/query", params={"q": vql})
    return resp.get("data", [])
