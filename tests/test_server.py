"""Tests for the MCP tool surface: metadata, schemas and structured output."""

from __future__ import annotations

import json

import jsonschema
import pytest

from frappe_mcp import server
from frappe_mcp.server import TOOLS

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
ALL_NAMES = sorted(TOOLS_BY_NAME)

WRITE_TOOLS = {
    "frappe_create_doc",
    "frappe_update_doc",
    "frappe_delete_doc",
    "frappe_run_method",
}


@pytest.mark.parametrize("name", ALL_NAMES)
def test_tool_has_annotations(name: str) -> None:
    """Every tool declares behavioural hints, not just prose."""
    ann = TOOLS_BY_NAME[name].annotations
    assert ann is not None
    assert ann.title
    assert ann.readOnlyHint is not None
    assert ann.destructiveHint is not None
    assert ann.idempotentHint is not None
    assert ann.openWorldHint is True


@pytest.mark.parametrize("name", ALL_NAMES)
def test_read_only_hint_matches_intent(name: str) -> None:
    """Read tools claim read-only; write tools do not."""
    assert TOOLS_BY_NAME[name].annotations.readOnlyHint is (
        name not in WRITE_TOOLS
    )


def test_destructive_tools_are_flagged() -> None:
    assert TOOLS_BY_NAME["frappe_delete_doc"].annotations.destructiveHint is True
    assert TOOLS_BY_NAME["frappe_run_method"].annotations.destructiveHint is True
    assert TOOLS_BY_NAME["frappe_create_doc"].annotations.destructiveHint is False


@pytest.mark.parametrize("name", ALL_NAMES)
def test_tool_has_title_and_output_schema(name: str) -> None:
    tool = TOOLS_BY_NAME[name]
    assert tool.title
    assert tool.outputSchema is not None
    assert tool.outputSchema["type"] == "object"
    jsonschema.Draft202012Validator.check_schema(tool.outputSchema)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_input_schema_is_valid_and_closed(name: str) -> None:
    schema = TOOLS_BY_NAME[name].inputSchema
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("additionalProperties") is False


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_parameter_is_described(name: str) -> None:
    for prop, spec in TOOLS_BY_NAME[name].inputSchema["properties"].items():
        assert spec.get("description"), f"{name}.{prop} lacks a description"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_description_covers_the_scored_dimensions(name: str) -> None:
    """Descriptions state usage guidance, behaviour and return shape."""
    desc = TOOLS_BY_NAME[name].description
    assert desc.startswith(("Check", "Retrieve", "Search", "Create", "Update", "Permanently", "Call"))
    assert "\nUse " in desc
    assert "\nBehavior: " in desc
    assert "\nParameters: " in desc
    assert "\nReturns: " in desc


@pytest.mark.parametrize("name", ALL_NAMES)
def test_description_names_a_sibling_tool(name: str) -> None:
    """Usage guidance must point at an alternative, not just this tool."""
    desc = TOOLS_BY_NAME[name].description
    siblings = [n for n in ALL_NAMES if n != name]
    if name == "frappe_ping":
        pytest.skip("ping is a diagnostic with no data-tool alternative")
    assert any(s in desc for s in siblings), f"{name} names no sibling"


# ------------------------------------------------------------------ #
#  Structured output
# ------------------------------------------------------------------ #


class _FakeClient:
    """Stands in for FrappeClient, returning a canned payload."""

    url = "https://example.test"

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __getattr__(self, _name: str):
        return lambda *a, **k: self._payload


async def _call(monkeypatch, tool: str, payload: object, arguments: dict):
    monkeypatch.setattr(server, "_get_client", lambda: _FakeClient(payload))
    return await server.call_tool(tool, arguments)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "payload", "arguments"),
    [
        ("frappe_ping", {"message": "pong"}, {}),
        (
            "frappe_get_doc",
            {"data": {"name": "SINV-00001", "docstatus": 1}},
            {"doctype": "Sales Invoice", "name": "SINV-00001"},
        ),
        (
            "frappe_search_docs",
            {"data": [{"name": "SINV-00001"}]},
            {"doctype": "Sales Invoice"},
        ),
        (
            "frappe_create_doc",
            {"data": {"name": "TODO-00001"}},
            {"doctype": "ToDo", "data": {"subject": "x"}},
        ),
        (
            "frappe_update_doc",
            {"data": {"name": "TODO-00001", "status": "Closed"}},
            {"doctype": "ToDo", "name": "TODO-00001", "data": {"status": "Closed"}},
        ),
        (
            "frappe_delete_doc",
            {"message": "ok"},
            {"doctype": "ToDo", "name": "TODO-00001"},
        ),
        (
            "frappe_run_method",
            {"message": "Administrator"},
            {"method": "frappe.auth.get_logged_user"},
        ),
    ],
)
async def test_structured_output_matches_declared_schema(
    monkeypatch, tool: str, payload: dict, arguments: dict
) -> None:
    content, structured = await _call(monkeypatch, tool, payload, arguments)
    jsonschema.validate(instance=structured, schema=TOOLS_BY_NAME[tool].outputSchema)
    # The text block stays a faithful copy of the same payload, so
    # clients that ignore structuredContent see no change.
    assert json.loads(content[0].text) == structured == payload


@pytest.mark.anyio
async def test_non_object_payload_is_wrapped(monkeypatch) -> None:
    content, structured = await _call(
        monkeypatch, "frappe_search_docs", [{"name": "A"}], {"doctype": "ToDo"}
    )
    assert structured == {"data": [{"name": "A"}]}
    jsonschema.validate(
        instance=structured, schema=TOOLS_BY_NAME["frappe_search_docs"].outputSchema
    )


@pytest.mark.anyio
async def test_errors_return_is_error_not_structured_content(monkeypatch) -> None:
    """Errors must bypass outputSchema validation, not fail it."""

    class _Boom(_FakeClient):
        def __getattr__(self, _name: str):
            def _raise(*a, **k):
                raise server.FrappeNotFoundError("nope")

            return _raise

    monkeypatch.setattr(server, "_get_client", lambda: _Boom(None))
    result = await server.call_tool(
        "frappe_get_doc", {"doctype": "ToDo", "name": "missing"}
    )
    assert result.isError is True
    assert "error" in json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_unknown_tool_is_an_error(monkeypatch) -> None:
    monkeypatch.setattr(server, "_get_client", lambda: _FakeClient({}))
    result = await server.call_tool("frappe_nope", {})
    assert result.isError is True
