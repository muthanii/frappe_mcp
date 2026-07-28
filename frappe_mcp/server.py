"""Frappe MCP server — exposes Frappe REST API as MCP tools."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

from frappe_mcp.client import (
    FrappeAuthError,
    FrappeClient,
    FrappeConflictError,
    FrappeConnectionError,
    FrappeError,
    FrappeNotFoundError,
)

# ------------------------------------------------------------------ #
#  Logging — writes to stderr so MCP stdio is not polluted
# ------------------------------------------------------------------ #

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("frappe_mcp")

# ------------------------------------------------------------------ #
#  Configuration
# ------------------------------------------------------------------ #

def _get_client() -> FrappeClient:
    """Build a FrappeClient from environment variables."""
    verify = os.environ.get("FRAPPE_VERIFY_SSL", "true").lower() != "false"
    timeout = float(os.environ.get("FRAPPE_TIMEOUT", "30"))
    return FrappeClient(verify_ssl=verify, timeout=timeout)


# ------------------------------------------------------------------ #
#  Friendly error messages for common failure modes
# ------------------------------------------------------------------ #

ERROR_HINTS = {
    FrappeConnectionError: (
        "Cannot reach Frappe at {url}. Is the URL correct and is the "
        "site running?"
    ),
    FrappeAuthError: (
        "Authentication rejected by {url}. Check FRAPPE_API_KEY and "
        "FRAPPE_API_SECRET."
    ),
    FrappeNotFoundError: (
        "The requested resource was not found on {url}. Check the "
        "doctype and document name."
    ),
    FrappeConflictError: (
        "A conflict occurred — the document may already exist."
    ),
    FrappeError: "Frappe error: {error}",
}


def _format_error(client: FrappeClient, exc: Exception) -> str:
    """Return a user-friendly error string for common failure modes."""
    for exc_type, template in ERROR_HINTS.items():
        if isinstance(exc, exc_type):
            return template.format(url=client.url, error=exc)
    return str(exc)


# ------------------------------------------------------------------ #
#  Tool definitions
# ------------------------------------------------------------------ #

TOOLS = [
    Tool(
        name="frappe_ping",
        description="Check connectivity to the configured Frappe/ERPNext site. Returns a pong response confirming the server is reachable, authenticated, and responsive. Use this as a health-check before making other calls to verify the connection is working.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="frappe_get_doc",
        description="Retrieve a single document (doctype record) by its doctype and document name. Returns all fields and values of the document. Common use cases: fetch a Sales Invoice by its number, get Customer details, load an Item record, or retrieve any saved document by its unique name.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The target DocType name (e.g. 'Sales Invoice', 'Customer', 'Item', 'Sales Order', 'Purchase Order', 'User'). Case-sensitive and must match the DocType exactly as defined in Frappe.",
                    "examples": ["Sales Invoice", "Customer", "Item", "User"],
                },
                "name": {
                    "type": "string",
                    "description": "The unique document name or ID to retrieve (e.g. 'SINV-00001', 'CUST-00001', 'ITEM-00001', 'Administrator'). This is typically the `name` field shown in the Frappe list view or document form.",
                    "examples": ["SINV-00001", "CUST-00001", "Administrator"],
                },
            },
            "required": ["doctype", "name"],
        },
    ),
    Tool(
        name="frappe_search_docs",
        description="Search or list documents of a given DocType with optional filters, field selection, pagination (default 20, max 200), and ordering. Returns a paginated list of matching documents. Use filters to narrow results by status, date range, amount, or any document field.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType to search within (e.g. 'Sales Invoice', 'Customer', 'Item', 'ToDo', 'Contact'). This parameter is required.",
                    "examples": ["Sales Invoice", "Customer", "Item"],
                },
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "prefixItems": [
                            {"type": "string", "description": "Field name to filter on"},
                            {"type": "string", "description": "Operator: =, !=, >, <, >=, <=, like, not like, in, not in, between"},
                            {"type": "string", "description": "Value to compare against"},
                        ],
                    },
                    "description": "Optional list of filter conditions. Each filter is a triple [field, operator, value]. Supported operators: =, !=, >, <, >=, <=, like, not like, in, not in, between. Example: [['status','=','Open'], ['grand_total','>','1000']].",
                    "examples": [[["status", "=", "Open"]], [["grand_total", ">", "1000"], ["status", "!=", "Cancelled"]]],
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of field names to return. Limits the response to only the specified fields for efficiency. Example: ['name', 'status', 'grand_total', 'posting_date']. When omitted, all fields are returned.",
                    "examples": [["name", "status", "grand_total"]],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 20, maximum: 200). Use for pagination. Frappe caps results at 200 per request.",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                },
                "order_by": {
                    "type": "string",
                    "description": "Field to sort by with direction. Format: 'fieldname direction'. Examples: 'creation desc' (newest first), 'modified asc' (oldest updated first), 'name asc' (alphabetical). Default ordering is by creation date descending.",
                    "examples": ["creation desc", "modified asc", "name asc"],
                },
            },
            "required": ["doctype"],
        },
    ),
    Tool(
        name="frappe_create_doc",
        description="Create a new document of the specified DocType with the provided field values. The data object should contain field names as keys and their respective values. Frappe auto-generates document names (via naming series) for new records. Returns the created document including its system-assigned name and all field values.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The target DocType name for the new document (e.g. 'Customer', 'Sales Invoice', 'Item', 'ToDo', 'Contact', 'Address'). Must be a valid DocType that exists on the target Frappe site.",
                    "examples": ["Customer", "Sales Invoice", "ToDo", "Contact"],
                },
                "data": {
                    "type": "object",
                    "description": "Key-value pairs of document field values to set. Keys are field names (e.g. 'customer_name', 'email_id', 'status', 'items'), values are the field values. For child table fields, provide a list of dicts. Must include at least all mandatory fields required by the target DocType.",
                    "examples": [
                        {"customer_name": "Acme Corp", "customer_type": "Company", "email_id": "billing@acme.com"},
                        {"subject": "Review contract", "status": "Open", "priority": "Medium"},
                    ],
                },
            },
            "required": ["doctype", "data"],
        },
    ),
    Tool(
        name="frappe_update_doc",
        description="Update specific fields of an existing document identified by its doctype and name. Only the fields provided in the data object are modified; all other fields remain unchanged. Returns the updated document with all current values. Use for changing status, updating contact information, modifying amounts, or adjusting any document field.",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType of the document to update (e.g. 'Sales Invoice', 'Customer', 'Item', 'Sales Order'). Must match the doctype of the existing document.",
                    "examples": ["Sales Invoice", "Customer", "Item"],
                },
                "name": {
                    "type": "string",
                    "description": "The unique document name or ID of the existing document to modify (e.g. 'SINV-00001', 'CUST-00001', 'ITEM-00001').",
                    "examples": ["SINV-00001", "CUST-00001"],
                },
                "data": {
                    "type": "object",
                    "description": "Dictionary of field names and their new values. Only the fields included here are modified; other fields retain their current values. Example: {'status': 'Cancelled', 'remarks': 'Cancelled per customer request'}.",
                    "examples": [
                        {"status": "Cancelled", "remarks": "Cancelled per customer request"},
                        {"email_id": "newemail@example.com", "mobile_no": "+1234567890"},
                    ],
                },
            },
            "required": ["doctype", "name", "data"],
        },
    ),
    Tool(
        name="frappe_delete_doc",
        description="Permanently delete a document by its doctype and name. This action is irreversible — the document and all its associated data are removed from the system. Use with caution. For audit purposes, consider updating the document status to 'Cancelled' instead where applicable (e.g., for Sales Invoices, Sales Orders).",
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType of the document to delete (e.g. 'ToDo', 'Note', 'Contact', 'Address'). WARNING: Deleting transactional or parent documents may affect or orphan linked child records.",
                    "examples": ["ToDo", "Note", "Contact"],
                },
                "name": {
                    "type": "string",
                    "description": "The unique document name or ID to permanently remove from the system (e.g. 'TODO-00001', 'NOTE-00001'). This operation cannot be undone.",
                    "examples": ["TODO-00001", "NOTE-00001"],
                },
            },
            "required": ["doctype", "name"],
        },
    ),
    Tool(
        name="frappe_run_method",
        description="Call a whitelisted server-side Python method on the Frappe site remotely. Use this for operations not covered by the standard CRUD tools — such as getting the logged user, computing stock balances, running reports, triggering workflows, or invoking custom API methods. The target method must be decorated with @frappe.whitelist() on the server.",
        inputSchema={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "description": "Dotted Python path to the whitelisted method to call. Examples: 'frappe.auth.get_logged_user', 'frappe.utils.get_stock_balance', 'erpnext.stock.utils.get_stock_balance', or any custom whitelisted method from your Frappe app.",
                    "examples": [
                        "frappe.auth.get_logged_user",
                        "frappe.utils.get_stock_balance",
                        "erpnext.stock.utils.get_stock_balance",
                    ],
                },
                "kwargs": {
                    "type": "object",
                    "description": "Optional dictionary of keyword arguments to pass to the remote method. The keys and expected values depend entirely on the specific method being called. Example for stock balance: {'item_code': 'ITEM-001', 'warehouse': 'Stores - W'}. Defaults to an empty dict when omitted.",
                    "examples": [
                        {"item_code": "ITEM-001", "warehouse": "Stores - W"},
                        {"from_date": "2025-01-01", "to_date": "2025-12-31"},
                    ],
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
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[TextContent]:
    with _get_client() as client:
        try:
            if name == "frappe_ping":
                result = client.ping()
            elif name == "frappe_get_doc":
                result = client.get_doc(
                    arguments["doctype"], arguments["name"]
                )
            elif name == "frappe_search_docs":
                result = client.search_docs(
                    doctype=arguments["doctype"],
                    filters=arguments.get("filters"),
                    fields=arguments.get("fields"),
                    limit=arguments.get("limit", 20),
                    order_by=arguments.get("order_by"),
                )
            elif name == "frappe_create_doc":
                result = client.create_doc(
                    arguments["doctype"], arguments["data"]
                )
            elif name == "frappe_update_doc":
                result = client.update_doc(
                    arguments["doctype"],
                    arguments["name"],
                    arguments["data"],
                )
            elif name == "frappe_delete_doc":
                result = client.delete_doc(
                    arguments["doctype"], arguments["name"]
                )
            elif name == "frappe_run_method":
                result = client.run_method(
                    arguments["method"],
                    arguments.get("kwargs"),
                )
            else:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"error": f"Unknown tool: {name}"}
                        ),
                    )
                ]

            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, default=str),
                )
            ]

        except (FrappeError, httpx.HTTPError) as exc:
            msg = _format_error(client, exc)
            logger.error("Tool %s failed: %s", name, msg)
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": msg}),
                )
            ]
        except Exception:
            logger.exception("Unexpected error in tool %s", name)
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": (
                                "An unexpected error occurred. "
                                "Check the MCP server logs for "
                                "details."
                            )
                        }
                    ),
                )
            ]


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
