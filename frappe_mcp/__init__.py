"""Frappe MCP package."""

from frappe_mcp.client import (
    FrappeAuthError,
    FrappeClient,
    FrappeConflictError,
    FrappeConnectionError,
    FrappeError,
    FrappeNotFoundError,
)
from frappe_mcp.server import main

__all__ = [
    "FrappeClient",
    "FrappeError",
    "FrappeAuthError",
    "FrappeConnectionError",
    "FrappeNotFoundError",
    "FrappeConflictError",
    "main",
]
