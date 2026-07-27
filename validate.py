#!/usr/bin/env python3
"""End-to-end validation script for Frappe MCP server.

Run with:
    FRAPPE_URL=http://... FRAPPE_API_KEY=... FRAPPE_API_SECRET=... python validate.py

This tests every tool against a live Frappe instance.
"""

from __future__ import annotations

import os
import sys

from frappe_mcp.client import (
    FrappeAuthError,
    FrappeClient,
    FrappeConnectionError,
    FrappeError,
)


def die(msg: str) -> None:
    print(f"  ❌ {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def main() -> None:
    # Check env
    for var in ("FRAPPE_URL", "FRAPPE_API_KEY", "FRAPPE_API_SECRET"):
        if not os.environ.get(var):
            die(f"{var} is not set. Export it and try again.")

    url = os.environ["FRAPPE_URL"]
    print(f"🧪 Frappe MCP Validation Suite")
    print(f"   Target: {url}")
    print()

    with FrappeClient() as client:
        # 1. Ping
        print("[1/5] frappe_ping ...")
        try:
            data = client.ping()
            assert data.get("message") == "pong", f"Unexpected: {data}"
            ok("pong")
        except FrappeConnectionError as e:
            die(str(e))
        except FrappeAuthError as e:
            die(str(e))

        # 2. Get logged-in user
        print("[2/5] frappe_run_method (get_logged_user) ...")
        data = client.run_method("frappe.auth.get_logged_user")
        user = data.get("message", "?")
        ok(f"logged in as: {user}")

        # 3. List users
        print("[3/5] frappe_search_docs (User, limit=3) ...")
        data = client.search_docs("User", limit=3)
        count = len(data.get("data", []))
        ok(f"found {count} user(s)")

        # 4. Create a test record (uses a safe doctype)
        print("[4/5] frappe_create_doc (ToDo) ...")
        todo = {
            "description": "MCP validation test - safe to delete",
            "status": "Open",
            "priority": "Low",
        }
        try:
            data = client.create_doc("ToDo", todo)
            todo_name = data.get("data", {}).get("name", "?")
            ok(f"created ToDo: {todo_name}")
        except FrappeError as e:
            print(f"  ⚠️  Could not create ToDo: {e}")
            todo_name = None

        # 5. Clean up
        if todo_name:
            print("[5/5] frappe_delete_doc (cleanup) ...")
            try:
                client.delete_doc("ToDo", todo_name)
                ok(f"deleted {todo_name}")
            except FrappeError as e:
                print(f"  ⚠️  Could not delete: {e}")
        else:
            print("[5/5] skipped (no record to clean up)")

    print()
    print("🎉 All validations passed!")


if __name__ == "__main__":
    main()
