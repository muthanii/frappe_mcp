"""Frappe REST API client with token-based authentication."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("frappe_mcp")


def _seg(value: str) -> str:
    """Percent-encode a single URL path segment.

    Tool arguments arrive from an LLM and may contain ``/``, ``?`` or ``..``.
    Interpolating those raw would let a call escape its intended endpoint —
    e.g. ``get_doc("Customer", "../../api/method/some.method")`` would resolve
    to ``/api/method/some.method`` instead of a resource read. Encoding with
    ``safe=""`` keeps every segment literal.
    """
    return quote(str(value), safe="")

# ------------------------------------------------------------------ #
#  Custom exception so callers can identify specific failures
# ------------------------------------------------------------------ #


class FrappeError(Exception):
    """Base exception for Frappe API errors."""


class FrappeAuthError(FrappeError):
    """Authentication failed (401)."""


class FrappeNotFoundError(FrappeError):
    """Resource not found (404)."""


class FrappeConflictError(FrappeError):
    """Resource already exists (409)."""


class FrappeConnectionError(FrappeError):
    """Could not connect to the Frappe site."""


# ------------------------------------------------------------------ #
#  Client
# ------------------------------------------------------------------ #


class FrappeClient:
    """Thin wrapper around the Frappe REST API.

    Authenticates via token-based auth (Authorization header).
    Supports context-manager usage:

        with FrappeClient() as client:
            client.ping()

    Or manually:

        client = FrappeClient()
        try:
            client.ping()
        finally:
            client.close()
    """

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.url = (url or os.environ["FRAPPE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["FRAPPE_API_KEY"]
        self.api_secret = api_secret or os.environ["FRAPPE_API_SECRET"]
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.max_retries = max_retries

        self._client = httpx.Client(
            base_url=self.url,
            headers={
                "Authorization": f"token {self.api_key}:{self.api_secret}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    # -- context manager -------------------------------------------------- #

    def __enter__(self) -> FrappeClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- low-level request helpers ---------------------------------------- #

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict[str, Any]:
        """Unified request with retry and error translation."""
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                r = self._client.request(
                    method, path, params=params, json=json_body
                )
            except httpx.ConnectError as exc:
                raise FrappeConnectionError(
                    f"Cannot connect to {self.url}. "
                    f"Check FRAPPE_URL and network connectivity."
                ) from exc
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise FrappeConnectionError(
                    f"Request to {self.url}{path} timed out after "
                    f"{self.timeout}s."
                ) from exc

            # Translate HTTP statuses to meaningful errors
            if r.status_code == 401:
                raise FrappeAuthError(
                    "Authentication failed (401). Check FRAPPE_API_KEY "
                    "and FRAPPE_API_SECRET."
                )
            if r.status_code == 403:
                raise FrappeError(
                    "Permission denied (403). Your API key lacks "
                    "permission for this action."
                )
            if r.status_code == 404:
                raise FrappeNotFoundError(
                    f"Not found (404): {method} {path}"
                )
            if r.status_code == 409:
                raise FrappeConflictError(
                    f"Conflict (409): {method} {path} — document may "
                    "already exist."
                )

            # 202 Accepted (deletes) may have no body
            if r.status_code == 202:
                return {"data": "accepted"}

            r.raise_for_status()

            # Frappe may return errors inside the JSON body even on 200
            data = r.json()
            if isinstance(data, dict):
                exc_msg = data.get("exc") or data.get("exception")
                server_msgs = data.get("_server_messages")
                if exc_msg:
                    raise FrappeError(
                        f"Frappe error: {exc_msg}"
                    )
                if server_msgs:
                    try:
                        msgs = json.loads(server_msgs)
                        logger.warning("Frappe server messages: %s", msgs)
                    except json.JSONDecodeError:
                        pass
            return data

        # Shouldn't be reached, but satisfy type checker
        raise last_exc  # type: ignore[misc]

    def _get(
        self, path: str, params: dict | None = None
    ) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _post(
        self, path: str, json_body: dict | None = None
    ) -> dict[str, Any]:
        return self._request("POST", path, json_body=json_body)

    def _put(
        self, path: str, json_body: dict | None = None
    ) -> dict[str, Any]:
        return self._request("PUT", path, json_body=json_body)

    def _delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path)

    # -- public API ------------------------------------------------------- #

    def ping(self) -> dict[str, Any]:
        """Check connectivity. Returns the server's pong response."""
        return self._get("/api/method/ping")

    def get_doc(self, doctype: str, name: str) -> dict[str, Any]:
        """Retrieve a single document by doctype and name."""
        return self._get(f"/api/resource/{_seg(doctype)}/{_seg(name)}")

    def search_docs(
        self,
        doctype: str,
        filters: list | None = None,
        fields: list[str] | None = None,
        limit: int = 20,
        order_by: str | None = None,
    ) -> dict[str, Any]:
        """Search / list documents with optional filters.

        Args:
            doctype: The DocType to query.
            filters: List of [field, operator, value] triples.
            fields: List of field names to return.
            limit: Max results (Frappe caps at 200).
            order_by: Sort expression, e.g. ``\"creation desc\"``.
        """
        params: dict[str, Any] = {}
        if filters:
            params["filters"] = json.dumps(filters)
        if fields:
            params["fields"] = json.dumps(fields)
        params["limit_page_length"] = min(limit, 200)
        if order_by:
            params["order_by"] = order_by
        return self._get(f"/api/resource/{_seg(doctype)}", params=params)

    def create_doc(self, doctype: str, data: dict) -> dict[str, Any]:
        """Create a new document."""
        return self._post(f"/api/resource/{_seg(doctype)}", json_body=data)

    def update_doc(
        self, doctype: str, name: str, data: dict
    ) -> dict[str, Any]:
        """Update an existing document by doctype and name."""
        return self._put(
            f"/api/resource/{_seg(doctype)}/{_seg(name)}", json_body=data
        )

    def delete_doc(self, doctype: str, name: str) -> dict[str, Any]:
        """Delete a document by doctype and name."""
        return self._delete(f"/api/resource/{_seg(doctype)}/{_seg(name)}")

    def run_method(
        self, method: str, kwargs: dict | None = None
    ) -> dict[str, Any]:
        """Call a whitelisted server-side Python method.

        Args:
            method: Dotted path, e.g. ``\"frappe.auth.get_logged_user\"``.
            kwargs: Keyword arguments forwarded to the method.
        """
        return self._post(
            f"/api/method/{_seg(method)}", json_body=kwargs or {}
        )
