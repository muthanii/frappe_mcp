"""Frappe MCP server — exposes Frappe REST API as MCP tools."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

from frappe_mcp.client import FrappeClient

# ------------------------------------------------------------------ #
#  Configuration
# ------------------------------------------------------------------ #

def _get_client() -> FrappeClient:
    """Build a FrappeClient from environment variables."""
    verify = os.environ.get("FRAPPE_VERIFY_SSL", "true").lower() != "false"
    timeout = float(os.environ.get("FRAPPE_TIMEOUT", "30"))
    return FrappeClient(verify_ssl=verify, timeout=timeout)


# ------------------------------------------------------------------ #
#  Tool definitions
# ------------------------------------------------------------------ #

TOOLS = [
    Tool(
        name="frappe_ping",
        description="Check connectivity to the configured Frappe/ERPNext site.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="frappe_get_doc",
        description="Retrieve a single document (doctype record) by its doctype and document name.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType (e.g. 'Sales Invoice', 'Customer', 'Item').",
                },
                "name": {
                    "type": "string",
                    "description": "The document name/ID (e.g. 'SINV-00001', 'CUST-001').",
                },
            },
            "required": ["doctype", "name"],
        },
    ),
    Tool(
        name="frappe_search_docs",
        description="Search or list documents of a given DocType with optional filters, field selection, pagination, and ordering.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType to search.",
                },
                "filters": {
                    "type": "array",
                    "description": "Optional list of filters, each as [field, operator, value], e.g. [['status','=','Open']].",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of field names to return (e.g. ['name', 'status', 'grand_total']).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20).",
                },
                "order_by": {
                    "type": "string",
                    "description": "Field to sort by (e.g. 'creation desc').",
                },
            },
            "required": ["doctype"],
        },
    ),
    Tool(
        name="frappe_create_doc",
        description="Create a new document of the given DocType with the provided field values.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType to create.",
                },
                "data": {
                    "type": "object",
                    "description": "Key-value pairs of fields and their values.",
                },
            },
            "required": ["doctype", "data"],
        },
    ),
    Tool(
        name="frappe_update_doc",
        description="Update an existing document identified by doctype and name with the provided field values.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType of the document.",
                },
                "name": {
                    "type": "string",
                    "description": "The document name/ID.",
                },
                "data": {
                    "type": "object",
                    "description": "Key-value pairs of fields to update.",
                },
            },
            "required": ["doctype", "name", "data"],
        },
    ),
    Tool(
        name="frappe_delete_doc",
        description="Delete a document by its doctype and name.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType of the document to delete.",
                },
                "name": {
                    "type": "string",
                    "description": "The document name/ID to delete.",
                },
            },
            "required": ["doctype", "name"],
        },
    ),
    Tool(
        name="frappe_run_method",
        description="Call a whitelisted server-side Python method on the Frappe site (e.g. 'frappe.auth.get_logged_user').",
        inputSchema={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "description": "Dotted path to the method (e.g. 'frappe.auth.get_logged_user' or 'erpnext.stock.utils.get_stock_balance').",
                },
                "kwargs": {
                    "type": "object",
                    "description": "Keyword arguments to pass to the method.",
                },
            },
            "required": ["method"],
        },
    ),
]


# ------------------------------------------------------------------ #
#  Server
# ------------------------------------------------------------------ #

app = Server("frappe-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    client = _get_client()
    try:
        if name == "frappe_ping":
            result = client.ping()
        elif name == "frappe_get_doc":
            result = client.get_doc(arguments["doctype"], arguments["name"])
        elif name == "frappe_search_docs":
            result = client.search_docs(
                doctype=arguments["doctype"],
                filters=arguments.get("filters"),
                fields=arguments.get("fields"),
                limit=arguments.get("limit", 20),
                order_by=arguments.get("order_by"),
            )
        elif name == "frappe_create_doc":
            result = client.create_doc(arguments["doctype"], arguments["data"])
        elif name == "frappe_update_doc":
            result = client.update_doc(
                arguments["doctype"], arguments["name"], arguments["data"]
            )
        elif name == "frappe_delete_doc":
            result = client.delete_doc(arguments["doctype"], arguments["name"])
        elif name == "frappe_run_method":
            result = client.run_method(
                arguments["method"], arguments.get("kwargs")
            )
        else:
            raise ValueError(f"Unknown tool: {name}")

        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
    finally:
        client.close()


# ------------------------------------------------------------------ #
#  Entrypoint
# ------------------------------------------------------------------ #

def main() -> None:
    """Run the MCP server over stdio."""
    import asyncio

    # Validate config early.
    for var in ("FRAPPE_URL", "FRAPPE_API_KEY", "FRAPPE_API_SECRET"):
        if not os.environ.get(var):
            print(f"Error: environment variable {var} is required.", file=sys.stderr)
            sys.exit(1)

    asyncio.run(_run())


async def _run() -> None:
    async with stdio_server() as (reader, writer):
        await app.run(reader, writer, app.create_initialization_options())


if __name__ == "__main__":
    main()
