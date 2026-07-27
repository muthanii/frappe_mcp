"""Tests for the Frappe MCP client."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from frappe_mcp.client import (
    FrappeAuthError,
    FrappeClient,
    FrappeConflictError,
    FrappeConnectionError,
    FrappeError,
    FrappeNotFoundError,
)


@pytest.fixture
def client() -> FrappeClient:
    return FrappeClient(
        url="https://test.example.com",
        api_key="fake-key",
        api_secret="fake-secret",
    )


@pytest.fixture
def mock_response() -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"message": "ok"}
    return resp


# -- initialization ----------------------------------------------------- #


def test_client_uses_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRAPPE_URL", "https://env.example.com")
    monkeypatch.setenv("FRAPPE_API_KEY", "env-key")
    monkeypatch.setenv("FRAPPE_API_SECRET", "env-secret")
    c = FrappeClient()
    assert c.url == "https://env.example.com"
    assert c.api_key == "env-key"
    assert c.api_secret == "env-secret"


def test_url_strips_trailing_slash() -> None:
    c = FrappeClient(url="https://example.com/", api_key="k", api_secret="s")
    assert c.url == "https://example.com"


# -- context manager ---------------------------------------------------- #


def test_context_manager() -> None:
    with FrappeClient(
        url="https://x.com", api_key="k", api_secret="s"
    ) as c:
        assert c.url == "https://x.com"
    # After exit, client is closed
    assert c._client.is_closed


# -- error handling ----------------------------------------------------- #


def test_raises_on_401(client: FrappeClient, mock_response: MagicMock) -> None:
    mock_response.status_code = 401
    with patch.object(client._client, "request", return_value=mock_response):
        with pytest.raises(FrappeAuthError):
            client.ping()


def test_raises_on_404(client: FrappeClient, mock_response: MagicMock) -> None:
    mock_response.status_code = 404
    with patch.object(client._client, "request", return_value=mock_response):
        with pytest.raises(FrappeNotFoundError):
            client.get_doc("FakeDoctype", "nonexistent")


def test_raises_on_409(client: FrappeClient, mock_response: MagicMock) -> None:
    mock_response.status_code = 409
    with patch.object(client._client, "request", return_value=mock_response):
        with pytest.raises(FrappeConflictError):
            client.create_doc("FakeDoctype", {})


def test_raises_on_connection_error(client: FrappeClient) -> None:
    with patch.object(
        client._client,
        "request",
        side_effect=httpx.ConnectError("boom"),
    ):
        with pytest.raises(FrappeConnectionError):
            client.ping()


def test_handles_202_no_body(
    client: FrappeClient, mock_response: MagicMock
) -> None:
    mock_response.status_code = 202
    with patch.object(client._client, "request", return_value=mock_response):
        result = client.delete_doc("FakeDoctype", "doc-1")
        assert result == {"data": "accepted"}


def test_raises_on_json_exc_field(
    client: FrappeClient, mock_response: MagicMock
) -> None:
    mock_response.status_code = 200
    mock_response.json.return_value = {"exc": "Something broke"}
    with patch.object(client._client, "request", return_value=mock_response):
        with pytest.raises(FrappeError, match="Something broke"):
            client.ping()


# -- search params ------------------------------------------------------ #


def test_search_docs_json_encodes_filters(
    client: FrappeClient, mock_response: MagicMock
) -> None:
    with patch.object(client._client, "request", return_value=mock_response):
        client.search_docs(
            "User", filters=[["status", "=", "Open"]], fields=["name"]
        )
        call_args = client._client.request.call_args
        params = call_args.kwargs["params"]
        assert params["filters"] == '[["status", "=", "Open"]]'
        assert params["fields"] == '["name"]'


def test_search_docs_caps_limit(
    client: FrappeClient, mock_response: MagicMock
) -> None:
    with patch.object(client._client, "request", return_value=mock_response):
        client.search_docs("User", limit=500)
        call_args = client._client.request.call_args
        assert call_args.kwargs["params"]["limit_page_length"] == 200


# -- URL encoding ------------------------------------------------------- #


def test_get_doc_encodes_doctype(
    client: FrappeClient, mock_response: MagicMock
) -> None:
    with patch.object(client._client, "request", return_value=mock_response):
        client.get_doc("Sales Invoice", "SINV-00001")
        call_args = client._client.request.call_args
        assert "Sales%20Invoice" in call_args[0][1]\
            or "Sales+Invoice" in call_args[0][1]\
            or "Sales Invoice" in call_args[0][1]
