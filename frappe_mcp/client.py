"""Frappe REST API client with token-based authentication."""

from __future__ import annotations

import os
from typing import Any

import httpx


class FrappeClient:
    """Thin wrapper around the Frappe REST API.

    Authenticates via token-based auth (Authorization header).
    """

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.url = (url or os.environ["FRAPPE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["FRAPPE_API_KEY"]
        self.api_secret = api_secret or os.environ["FRAPPE_API_SECRET"]
        self.verify_ssl = verify_ssl
        self.timeout = timeout

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

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ #
    #  Low-level request helpers
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        r = self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, json: dict | None = None) -> dict[str, Any]:
        r = self._client.post(path, json=json)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, json: dict | None = None) -> dict[str, Any]:
        r = self._client.put(path, json=json)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> dict[str, Any]:
        r = self._client.delete(path)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def ping(self) -> dict[str, Any]:
        """Check connectivity. Returns the server's response to a ping."""
        return self._get("/api/method/ping")

    def get_doc(self, doctype: str, name: str) -> dict[str, Any]:
        """Retrieve a single document."""
        return self._get(f"/api/resource/{doctype}/{name}")

    def search_docs(
        self,
        doctype: str,
        filters: list | None = None,
        fields: list[str] | None = None,
        limit: int = 20,
        order_by: str | None = None,
    ) -> dict[str, Any]:
        """Search / list documents with optional filters."""
        params: dict[str, Any] = {}
        if filters:
            params["filters"] = filters
        if fields:
            params["fields"] = fields
        if limit:
            params["limit_page_length"] = limit
        if order_by:
            params["order_by"] = order_by
        return self._get(f"/api/resource/{doctype}", params=params)

    def create_doc(self, doctype: str, data: dict) -> dict[str, Any]:
        """Create a new document."""
        return self._post(f"/api/resource/{doctype}", json=data)

    def update_doc(self, doctype: str, name: str, data: dict) -> dict[str, Any]:
        """Update an existing document."""
        return self._put(f"/api/resource/{doctype}/{name}", json=data)

    def delete_doc(self, doctype: str, name: str) -> dict[str, Any]:
        """Delete a document."""
        return self._delete(f"/api/resource/{doctype}/{name}")

    def run_method(
        self, method: str, kwargs: dict | None = None
    ) -> dict[str, Any]:
        """Call a whitelisted server-side Python method."""
        return self._post(f"/api/method/{method}", json=kwargs or {})
