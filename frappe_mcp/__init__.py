"""Frappe MCP package."""

from frappe_mcp.client import FrappeClient
from frappe_mcp.server import main

__all__ = ["FrappeClient", "main"]
