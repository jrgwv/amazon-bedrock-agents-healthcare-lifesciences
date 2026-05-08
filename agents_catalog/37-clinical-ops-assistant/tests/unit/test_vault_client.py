"""Unit tests for vault_client — auth, session caching, 401 retry."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("VAULT_BASE_URL", "https://test.veevavault.com")
    monkeypatch.setenv("VAULT_API_VERSION", "v26.1")
    monkeypatch.setenv("VAULT_AUTH_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:test")
    monkeypatch.setenv("SESSION_CACHE_TABLE", "test-sessions")


@patch("vault_client._secrets")
@patch("vault_client._ddb")
@patch("vault_client._http")
def test_authenticate_success(mock_http, mock_ddb, mock_secrets):
    """Successful auth stores session in DynamoDB."""
    import vault_client

    mock_secrets.get_secret_value.return_value = {
        "SecretString": json.dumps({"username": "user", "password": "pass"})
    }
    mock_response = MagicMock()
    mock_response.json.return_value = {"responseStatus": "SUCCESS", "sessionId": "abc123"}
    mock_response.raise_for_status = MagicMock()
    mock_http.post.return_value = mock_response

    mock_table = MagicMock()
    mock_ddb.Table.return_value = mock_table

    session = vault_client._authenticate()

    assert session == "abc123"
    mock_table.put_item.assert_called_once()
    item = mock_table.put_item.call_args[1]["Item"]
    assert item["sessionId"] == "abc123"
    assert item["ttl"] > int(time.time())


@patch("vault_client._ddb")
def test_get_cached_session_valid(mock_ddb):
    """Returns cached session if TTL not expired."""
    import vault_client

    mock_table = MagicMock()
    mock_ddb.Table.return_value = mock_table
    mock_table.get_item.return_value = {
        "Item": {"pk": "SESSION#test", "sessionId": "cached123", "ttl": int(time.time()) + 600}
    }

    result = vault_client._get_cached_session()
    assert result == "cached123"


@patch("vault_client._ddb")
def test_get_cached_session_expired(mock_ddb):
    """Returns None if TTL expired."""
    import vault_client

    mock_table = MagicMock()
    mock_ddb.Table.return_value = mock_table
    mock_table.get_item.return_value = {
        "Item": {"pk": "SESSION#test", "sessionId": "old", "ttl": int(time.time()) - 100}
    }

    result = vault_client._get_cached_session()
    assert result is None


@patch("vault_client.get_session")
@patch("vault_client._authenticate")
@patch("vault_client._http")
def test_vault_request_retries_on_401(mock_http, mock_auth, mock_get_session):
    """401 triggers re-auth and retry."""
    import vault_client

    mock_get_session.return_value = "expired_session"
    mock_auth.return_value = "new_session"

    resp_401 = MagicMock()
    resp_401.status_code = 401

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"responseStatus": "SUCCESS", "data": []}
    resp_200.raise_for_status = MagicMock()

    mock_http.request.side_effect = [resp_401, resp_200]

    result = vault_client.vault_request("GET", "/query", params={"q": "SELECT id FROM study__v"})
    assert result == {"responseStatus": "SUCCESS", "data": []}
    assert mock_http.request.call_count == 2
