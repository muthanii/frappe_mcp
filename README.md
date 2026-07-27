# Frappe MCP Server

A **Model Context Protocol (MCP) server** for [Frappe Framework](https://frappeframework.com).
Connect Claude Desktop, VS Code Copilot, and other MCP clients to any Frappe/ERPNext site
via its REST API.

## Features

- **Document CRUD** — get, create, update, delete Frappe doctypes
- **Search** — full-text and filtered document search
- **Remote method calls** — invoke any server-side Python method
- **Authentication** — API key + secret (token-based auth)
- **Docker-first** — single `docker run` command, no Python install needed

## Quick start (Docker)

```bash
docker run -e FRAPPE_URL=https://your-site.com \
           -e FRAPPE_API_KEY=your-api-key \
           -e FRAPPE_API_SECRET=your-api-secret \
           muthanii/frappe-mcp
```

## Available tools

| Tool | Description |
|------|-------------|
| `frappe_ping` | Check connectivity to the Frappe site |
| `frappe_get_doc` | Retrieve a single document by doctype + name |
| `frappe_search_docs` | Search/list documents with filters |
| `frappe_create_doc` | Create a new document |
| `frappe_update_doc` | Update an existing document |
| `frappe_delete_doc` | Delete a document |
| `frappe_run_method` | Call a whitelisted server-side method |

## Configuration

| Environment variable | Required | Description |
|----------------------|----------|-------------|
| `FRAPPE_URL` | Yes | Base URL of your Frappe site (e.g. `https://erp.example.com`) |
| `FRAPPE_API_KEY` | Yes | Frappe API key |
| `FRAPPE_API_SECRET` | Yes | Frappe API secret |
| `FRAPPE_VERIFY_SSL` | No | Set to `false` to skip TLS verification (default: `true`) |
| `FRAPPE_TIMEOUT` | No | Request timeout in seconds (default: `30`) |

## MCP client config

Add this to your `claude_desktop_config.json` or Copilot config:

```json
{
  "mcpServers": {
    "frappe": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "FRAPPE_URL",
        "-e", "FRAPPE_API_KEY",
        "-e", "FRAPPE_API_SECRET",
        "muthanii/frappe-mcp"
      ],
      "env": {
        "FRAPPE_URL": "https://your-site.com",
        "FRAPPE_API_KEY": "your-api-key",
        "FRAPPE_API_SECRET": "your-api-secret"
      }
    }
  }
}
```

## Local development

```bash
pip install -e .
frappe-mcp
```

## License

MIT
