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
    CallToolResult,
    TextContent,
    Tool,
    ToolAnnotations,
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
#  Output schemas
#
#  Frappe wraps REST responses in {"data": ...} and /api/method
#  responses in {"message": ...}. `required` is deliberately omitted
#  where a site or Frappe version may vary the envelope, so a valid
#  response is never rejected by output validation.
# ------------------------------------------------------------------ #

_DOCUMENT_SCHEMA = {
    "type": "object",
    "description": (
        "A Frappe document. Keys are DocType fieldnames; child tables "
        "appear as arrays of row objects. Always includes `name` (the "
        "primary key), `owner`, `creation`, `modified` and `docstatus` "
        "(0 = draft, 1 = submitted, 2 = cancelled)."
    ),
    "additionalProperties": True,
}

_SINGLE_DOC_OUTPUT = {
    "type": "object",
    "properties": {"data": _DOCUMENT_SCHEMA},
    "required": ["data"],
    "additionalProperties": True,
}

_LIST_OUTPUT = {
    "type": "object",
    "properties": {
        "data": {
            "type": "array",
            "description": (
                "Matching documents, in the requested order. Empty when "
                "nothing matched. Each row carries only the requested "
                "`fields`, or every field when `fields` was omitted."
            ),
            "items": _DOCUMENT_SCHEMA,
        }
    },
    "required": ["data"],
    "additionalProperties": True,
}

_PING_OUTPUT = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "The literal string 'pong' when the site is reachable and the credentials authenticate.",
        }
    },
    "required": ["message"],
    "additionalProperties": True,
}

_DELETE_OUTPUT = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "Confirmation string returned by Frappe, typically 'ok'.",
        },
        "data": {
            "type": "string",
            "description": "Present instead of `message` when the site answers 202 Accepted; the value is 'accepted'.",
        },
    },
    "additionalProperties": True,
}

_METHOD_OUTPUT = {
    "type": "object",
    "properties": {
        "message": {
            "description": (
                "The value returned by the whitelisted method. The type "
                "is whatever that method returns — object, array, "
                "string, number, boolean or null. Absent when the method "
                "returns nothing."
            )
        }
    },
    "additionalProperties": True,
}


# ------------------------------------------------------------------ #
#  Tool definitions
# ------------------------------------------------------------------ #

TOOLS = [
    Tool(
        name="frappe_ping",
        title="Check Frappe connection",
        description=(
            "Check connectivity and credentials against the configured Frappe/ERPNext site.\n"
            "Use first when another tool fails, to tell a network or credential problem apart from a bad doctype or document name. This is a diagnostic, not a data tool — it never reads or writes documents.\n"
            "Behavior: read-only and idempotent, with no side effects. A pong proves the site is reachable and that FRAPPE_API_KEY/FRAPPE_API_SECRET authenticate; it does not prove the API user has permission for any particular DocType. Failure surfaces as a connection error (site unreachable, wrong URL, TLS problem) or an auth error (bad key or secret).\n"
            "Parameters: none by design — the target site and credentials come from the server's own environment, never from the caller, so this tool cannot be aimed at a different host.\n"
            'Returns: {"message": "pong"}.'
        ),
        annotations=ToolAnnotations(
            title="Check Frappe connection",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        outputSchema=_PING_OUTPUT,
    ),
    Tool(
        name="frappe_get_doc",
        title="Get one document",
        description=(
            "Retrieve one complete document (a single DocType record) by its exact doctype and document name.\n"
            "Use when the document's name is already known, such as 'SINV-00001'. Use frappe_search_docs instead to find documents by field value, to fetch many records, or to return only a few fields; use frappe_run_method for values that are computed rather than stored on the document.\n"
            "Behavior: read-only and idempotent, with no side effects. Returns the document in whatever state it is stored — draft, submitted or cancelled — without filtering. Results respect the API user's role permissions: a document that exists but is not permitted raises a permission error, while an unknown doctype or name raises a not-found error.\n"
            "Parameters: doctype and name are both case-sensitive and must match Frappe exactly. `name` is the primary key from the list view, not a title — for DocTypes using a naming series it looks like 'SINV-00001', and only for DocTypes named by field does it equal a human-readable value such as a customer name.\n"
            'Returns: {"data": {...}} containing every stored field, with child tables nested as arrays of row objects.'
        ),
        annotations=ToolAnnotations(
            title="Get one document",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The target DocType name (e.g. 'Sales Invoice', 'Customer', 'Item', 'Sales Order', 'Purchase Order', 'User'). Case-sensitive and must match the DocType exactly as defined in Frappe.",
                    "examples": ["Sales Invoice", "Customer", "Item", "User"],
                    "minLength": 1,
                },
                "name": {
                    "type": "string",
                    "description": "The unique document name or ID to retrieve (e.g. 'SINV-00001', 'CUST-00001', 'ITEM-00001', 'Administrator'). This is the `name` primary key shown in the Frappe list view or document form, not a title or description field.",
                    "examples": ["SINV-00001", "CUST-00001", "Administrator"],
                    "minLength": 1,
                },
            },
            "required": ["doctype", "name"],
            "additionalProperties": False,
        },
        outputSchema=_SINGLE_DOC_OUTPUT,
    ),
    Tool(
        name="frappe_search_docs",
        title="Search or list documents",
        description=(
            "Search or list documents of one DocType, with optional filters, field selection, ordering and pagination.\n"
            "Use to find documents by field value or to browse a DocType. Use frappe_get_doc instead when the exact document name is known and every field is wanted; use frappe_run_method for aggregates, totals or report output, which this tool cannot compute.\n"
            "Behavior: read-only and idempotent, with no side effects. Only documents the API user's role permissions allow are returned, so a short result may mean restricted access rather than no matches. An unknown doctype raises a not-found error, and an unknown fieldname in `filters`, `fields` or `order_by` raises a Frappe error rather than being silently ignored.\n"
            "Parameters: `filters` entries are ANDed together — there is no OR — and each is a [field, operator, value] triple; `in`/`not in` take a list as the value and `between` takes a two-element list. `fields` should name only what is needed, since omitting it returns every field of every row and can be very large. `limit` defaults to 20 and Frappe caps it at 200; there is no offset parameter, so page by ordering on `creation` and filtering past the last value already seen.\n"
            'Returns: {"data": [...]} — an array of documents, empty when nothing matches.'
        ),
        annotations=ToolAnnotations(
            title="Search or list documents",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType to search within (e.g. 'Sales Invoice', 'Customer', 'Item', 'ToDo', 'Contact'). Case-sensitive; exactly one DocType per call, as this tool cannot search across DocTypes.",
                    "examples": ["Sales Invoice", "Customer", "Item"],
                    "minLength": 1,
                },
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "prefixItems": [
                            {"type": "string", "description": "Fieldname to filter on — the DocType's fieldname (e.g. 'grand_total'), not its form label."},
                            {"type": "string", "description": "Operator: =, !=, >, <, >=, <=, like, not like, in, not in, between"},
                            {"type": "string", "description": "Value to compare against. Use % as the wildcard with 'like'; pass a list for 'in'/'not in' and a two-element list for 'between'."},
                        ],
                    },
                    "description": "Optional list of filter conditions, all ANDed together. Each filter is a triple [field, operator, value]. Supported operators: =, !=, >, <, >=, <=, like, not like, in, not in, between. Example: [['status','=','Open'], ['grand_total','>','1000']]. Dates are compared as 'YYYY-MM-DD' strings.",
                    "examples": [[["status", "=", "Open"]], [["grand_total", ">", "1000"], ["status", "!=", "Cancelled"]]],
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of fieldnames to return. Limits the response to only the specified fields, which keeps large result sets manageable. Example: ['name', 'status', 'grand_total', 'posting_date']. When omitted, all fields are returned. Child-table fields are not expanded here — fetch the full document with frappe_get_doc for those.",
                    "examples": [["name", "status", "grand_total"]],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 20, maximum: 200). Frappe caps results at 200 per request; there is no offset parameter, so paginate by narrowing `filters` rather than by increasing this.",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                },
                "order_by": {
                    "type": "string",
                    "description": "Field to sort by with direction, formatted as 'fieldname direction'. Examples: 'creation desc' (newest first), 'modified asc' (oldest updated first), 'name asc' (alphabetical). The direction is required. Defaults to 'creation desc' when omitted.",
                    "examples": ["creation desc", "modified asc", "name asc"],
                },
            },
            "required": ["doctype"],
            "additionalProperties": False,
        },
        outputSchema=_LIST_OUTPUT,
    ),
    Tool(
        name="frappe_create_doc",
        title="Create a document",
        description=(
            "Create a new document of the given DocType from the supplied field values.\n"
            "Use to insert a record that does not yet exist. Use frappe_update_doc instead to change a record that already exists — this tool never updates in place, so re-running it creates a second, separately named document.\n"
            "Behavior: writes to the site and is NOT idempotent. The document is inserted as a draft (docstatus 0) and is not submitted, so submittable DocTypes such as Sales Invoice still need a submit step via frappe_run_method. Frappe assigns the name from the DocType's naming series, so the name is unknown until this call returns. Server-side validation, mandatory-field checks and DocType hooks all run on insert; a missing mandatory field or an invalid Link value raises a Frappe error and nothing is created. Requires create permission on the DocType.\n"
            "Parameters: `data` keys are fieldnames (`customer_name`), not form labels ('Customer Name'); Link fields take the target document's `name`, not its title. Child tables are passed as a list of row objects under the child field's own fieldname. Omit `name` — it is assigned by the naming series and any value supplied is ignored unless the DocType prompts for naming.\n"
            'Returns: {"data": {...}} — the created document, including the assigned `name`.'
        ),
        annotations=ToolAnnotations(
            title="Create a document",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The target DocType name for the new document (e.g. 'Customer', 'Sales Invoice', 'Item', 'ToDo', 'Contact', 'Address'). Case-sensitive and must be a DocType that exists on the target Frappe site.",
                    "examples": ["Customer", "Sales Invoice", "ToDo", "Contact"],
                    "minLength": 1,
                },
                "data": {
                    "type": "object",
                    "description": "Key-value pairs of document field values to set. Keys are fieldnames (e.g. 'customer_name', 'email_id', 'status', 'items'), not form labels; Link fields take the target document's `name`. Child-table fields take a list of row objects. Must include every field the target DocType marks mandatory, or the insert is rejected.",
                    "examples": [
                        {"customer_name": "Acme Corp", "customer_type": "Company", "email_id": "billing@acme.com"},
                        {"subject": "Review contract", "status": "Open", "priority": "Medium"},
                    ],
                    "minProperties": 1,
                },
            },
            "required": ["doctype", "data"],
            "additionalProperties": False,
        },
        outputSchema=_SINGLE_DOC_OUTPUT,
    ),
    Tool(
        name="frappe_update_doc",
        title="Update a document",
        description=(
            "Update selected fields of an existing document, identified by its doctype and name.\n"
            "Use for partial edits: only the keys present in `data` change and every other field is left alone. Use frappe_create_doc for records that do not exist yet, and prefer this tool over frappe_delete_doc when a document should be voided rather than removed — setting a status such as 'Cancelled' preserves the audit trail.\n"
            "Behavior: writes to the site, overwriting the previous values of the fields supplied; those old values are not recoverable through this API. Idempotent — repeating an identical call leaves the document in the same state. Validation and DocType hooks run on save, so an update is accepted or rejected as a whole, never partially applied. Documents already submitted (docstatus 1) accept changes only to fields marked 'Allow on Submit'; other edits fail. Requires write permission on the DocType.\n"
            "Parameters: `data` keys are fieldnames, not form labels. Supplying a child-table field replaces the entire table rather than merging rows, so to amend one row read the document with frappe_get_doc first and send back the complete row list. Fields omitted from `data` are untouched — there is no way to clear a field except by setting it explicitly to null or an empty string.\n"
            'Returns: {"data": {...}} — the whole document as it stands after the update.'
        ),
        annotations=ToolAnnotations(
            title="Update a document",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType of the document to update (e.g. 'Sales Invoice', 'Customer', 'Item', 'Sales Order'). Case-sensitive and must match the doctype of the existing document.",
                    "examples": ["Sales Invoice", "Customer", "Item"],
                    "minLength": 1,
                },
                "name": {
                    "type": "string",
                    "description": "The `name` primary key of the existing document to modify (e.g. 'SINV-00001', 'CUST-00001', 'ITEM-00001'). The document must already exist; this tool does not create one.",
                    "examples": ["SINV-00001", "CUST-00001"],
                    "minLength": 1,
                },
                "data": {
                    "type": "object",
                    "description": "Fieldnames and their new values. Only the fields included here are modified; others retain their current values. Passing a child-table field replaces every row in that table. Example: {'status': 'Cancelled', 'remarks': 'Cancelled per customer request'}.",
                    "examples": [
                        {"status": "Cancelled", "remarks": "Cancelled per customer request"},
                        {"email_id": "newemail@example.com", "mobile_no": "+1234567890"},
                    ],
                    "minProperties": 1,
                },
            },
            "required": ["doctype", "name", "data"],
            "additionalProperties": False,
        },
        outputSchema=_SINGLE_DOC_OUTPUT,
    ),
    Tool(
        name="frappe_delete_doc",
        title="Delete a document (irreversible)",
        description=(
            "Permanently delete a document by its doctype and name.\n"
            "Use only for genuinely disposable records such as ToDo or Note, or for a test document created moments earlier — the deletion is irreversible, with no undo and no recycle bin. Prefer frappe_update_doc to set a status such as 'Cancelled' whenever an audit trail matters, which covers most transactional records (Sales Invoice, Sales Order, Payment Entry, Journal Entry).\n"
            "Behavior: writes to the site. Not idempotent from the caller's point of view — a second call for the same name raises a not-found error. Frappe refuses the delete while other documents link to this one, so a link-exists error means the dependants must be handled first. Deleting a parent removes its child-table rows with it. Submitted documents must be cancelled before they can be deleted. Requires delete permission on the DocType.\n"
            "Parameters: `name` is the exact `name` primary key, not a title, and a wrong value deletes the wrong record with no warning — confirm with frappe_get_doc first when there is any doubt. One document per call: there is no bulk mode and no dry-run, and the deletion is committed as soon as the call is accepted.\n"
            'Returns: {"message": "ok"} on success.'
        ),
        annotations=ToolAnnotations(
            title="Delete a document (irreversible)",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The DocType of the document to delete (e.g. 'ToDo', 'Note', 'Contact', 'Address'). WARNING: deleting a transactional or parent document removes its child rows and may be blocked by, or orphan, linked records.",
                    "examples": ["ToDo", "Note", "Contact"],
                    "minLength": 1,
                },
                "name": {
                    "type": "string",
                    "description": "The exact `name` primary key of the document to permanently remove (e.g. 'TODO-00001', 'NOTE-00001'). This operation cannot be undone, so verify the value identifies the intended record before calling.",
                    "examples": ["TODO-00001", "NOTE-00001"],
                    "minLength": 1,
                },
            },
            "required": ["doctype", "name"],
            "additionalProperties": False,
        },
        outputSchema=_DELETE_OUTPUT,
    ),
    Tool(
        name="frappe_run_method",
        title="Call a whitelisted server method",
        description=(
            "Call a whitelisted server-side Python method on the Frappe site.\n"
            "Use as the escape hatch for anything the CRUD tools cannot express — submitting or cancelling documents, running reports, computing stock balances, or invoking a custom app's API. Use frappe_get_doc, frappe_search_docs, frappe_create_doc or frappe_update_doc for ordinary record work: they validate their arguments and describe their effects, whereas this tool cannot.\n"
            "Behavior: the effect is determined entirely by the method named and may read, write, delete or enqueue background jobs, so treat every call as potentially destructive and non-idempotent unless the method is known to be safe. The target must be decorated with @frappe.whitelist(); anything else raises a permission error, as does a method whose own permission checks reject the API user. Calls run synchronously and are subject to the server's request timeout (FRAPPE_TIMEOUT, 30s by default).\n"
            "Parameters: `method` is the full dotted import path — module path plus function name — not a DocType method name or a REST path. `kwargs` maps onto that method's named arguments exactly; names come from its signature, and an unexpected or missing key raises a Frappe error rather than being ignored. Values must be JSON-serialisable, with dates passed as 'YYYY-MM-DD' strings. Omitting `kwargs` calls the method with no arguments.\n"
            'Returns: {"message": ...} — the method\'s return value, whose type depends entirely on the method called.'
        ),
        annotations=ToolAnnotations(
            title="Call a whitelisted server method",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "description": "Full dotted Python path to the whitelisted method — module path plus function name. Examples: 'frappe.auth.get_logged_user', 'frappe.client.submit', 'erpnext.stock.utils.get_stock_balance', or any custom whitelisted method from an installed Frappe app. Not a REST path and not a DocType method name.",
                    "examples": [
                        "frappe.auth.get_logged_user",
                        "frappe.client.submit",
                        "erpnext.stock.utils.get_stock_balance",
                    ],
                    "minLength": 1,
                },
                "kwargs": {
                    "type": "object",
                    "description": "Optional keyword arguments passed to the remote method. Keys must match that method's parameter names exactly — they depend entirely on the method being called, and an unknown key raises an error rather than being ignored. Values must be JSON-serialisable; pass dates as 'YYYY-MM-DD' strings. Example for stock balance: {'item_code': 'ITEM-001', 'warehouse': 'Stores - W'}. Defaults to no arguments when omitted.",
                    "examples": [
                        {"item_code": "ITEM-001", "warehouse": "Stores - W"},
                        {"from_date": "2025-01-01", "to_date": "2025-12-31"},
                    ],
                },
            },
            "required": ["method"],
            "additionalProperties": False,
        },
        outputSchema=_METHOD_OUTPUT,
    ),
]


# ------------------------------------------------------------------ #
#  Server
# ------------------------------------------------------------------ #

app = Server("frappe-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


def _error_result(message: str) -> CallToolResult:
    """Build an error result.

    Returned as a CallToolResult so the SDK skips outputSchema
    validation — an error payload does not match a success schema.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": message}))],
        isError=True,
    )


@app.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> tuple[list[TextContent], dict[str, Any]] | CallToolResult:
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
                return _error_result(f"Unknown tool: {name}")

            text = json.dumps(result, indent=2, default=str)
            # Round-trip through the serialiser so structured content
            # only ever carries JSON-safe values (Frappe returns dates
            # and Decimals), matching the text block exactly.
            structured = json.loads(text)
            if not isinstance(structured, dict):
                # MCP structured content must be an object; Frappe
                # normally returns one, but wrap defensively.
                structured = {"data": structured}
            return [TextContent(type="text", text=text)], structured

        except (FrappeError, httpx.HTTPError) as exc:
            msg = _format_error(client, exc)
            logger.error("Tool %s failed: %s", name, msg)
            return _error_result(msg)
        except Exception:
            logger.exception("Unexpected error in tool %s", name)
            return _error_result(
                "An unexpected error occurred. Check the MCP server "
                "logs for details."
            )


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
