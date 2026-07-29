# Frappe MCP Server

[![PyPI](https://img.shields.io/pypi/v/frappe-mcp-server.svg?logo=pypi&logoColor=white)](https://pypi.org/project/frappe-mcp-server/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://pypi.org/project/frappe-mcp-server/)
[![Docker Hub](https://img.shields.io/docker/v/muthanii/frappe-mcp?sort=semver&logo=docker&logoColor=white&label=docker%20hub)](https://hub.docker.com/r/muthanii/frappe-mcp)
[![Docker pulls](https://img.shields.io/docker/pulls/muthanii/frappe-mcp.svg?logo=docker&logoColor=white)](https://hub.docker.com/r/muthanii/frappe-mcp)
[![GHCR](https://img.shields.io/badge/ghcr.io-frappe--mcp-181717?logo=github&logoColor=white)](https://github.com/muthanii/frappe_mcp/pkgs/container/frappe-mcp)
[![MCP Registry](https://img.shields.io/badge/MCP%20registry-io.github.muthanii%2Ffrappe__mcp-6E56CF)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.muthanii/frappe_mcp)
[![License](https://img.shields.io/github/license/muthanii/frappe_mcp.svg)](LICENSE)

[![frappe_mcp MCP server](https://glama.ai/mcp/servers/muthanii/frappe_mcp/badges/score.svg)](https://glama.ai/mcp/servers/muthanii/frappe_mcp)

mcp-name: io.github.muthanii/frappe_mcp

A **Model Context Protocol (MCP) server** for [Frappe Framework](https://frappeframework.com).
Connect Claude Desktop, VS Code Copilot, and other MCP clients to any Frappe/ERPNext site
via its REST API.

## Where to get it

| Distribution | Reference | Page |
|---|---|---|
| **PyPI** | `frappe-mcp-server` | [pypi.org/project/frappe-mcp-server](https://pypi.org/project/frappe-mcp-server/) |
| **Docker Hub** | `muthanii/frappe-mcp` | [hub.docker.com/r/muthanii/frappe-mcp](https://hub.docker.com/r/muthanii/frappe-mcp) |
| **GitHub Container Registry** | `ghcr.io/muthanii/frappe-mcp` | [ghcr package](https://github.com/muthanii/frappe_mcp/pkgs/container/frappe-mcp) |
| **MCP Registry** | `io.github.muthanii/frappe_mcp` | [registry API](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.muthanii/frappe_mcp) |
| **Glama** | — | [glama.ai/mcp/servers/muthanii/frappe_mcp](https://glama.ai/mcp/servers/muthanii/frappe_mcp) |
| **Source** | — | [github.com/muthanii/frappe_mcp](https://github.com/muthanii/frappe_mcp) |

## Features

- **Document CRUD** — get, create, update, delete Frappe doctypes
- **Search** — full-text and filtered document search
- **Remote method calls** — invoke any server-side Python method
- **Authentication** — API key + secret (token-based auth)
- **Docker-first** — single `docker run` command, no Python install needed

## Quick start

**With `uvx` (no install):**

```bash
FRAPPE_URL=https://your-site.com \
FRAPPE_API_KEY=your-api-key \
FRAPPE_API_SECRET=your-api-secret \
  uvx frappe-mcp-server
```

**With `pip`:**

```bash
pip install frappe-mcp-server
frappe-mcp-server
```

**With Docker (Docker Hub):**

```bash
docker run -i --rm \
  -e FRAPPE_URL=https://your-site.com \
  -e FRAPPE_API_KEY=your-api-key \
  -e FRAPPE_API_SECRET=your-api-secret \
  muthanii/frappe-mcp
```

**With Docker (GHCR):**

```bash
docker run -i --rm \
  -e FRAPPE_URL=https://your-site.com \
  -e FRAPPE_API_KEY=your-api-key \
  -e FRAPPE_API_SECRET=your-api-secret \
  ghcr.io/muthanii/frappe-mcp
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

Add this to your `claude_desktop_config.json` or Copilot config.

**Via `uvx`:**

```json
{
  "mcpServers": {
    "frappe": {
      "command": "uvx",
      "args": ["frappe-mcp-server"],
      "env": {
        "FRAPPE_URL": "https://your-site.com",
        "FRAPPE_API_KEY": "your-api-key",
        "FRAPPE_API_SECRET": "your-api-secret"
      }
    }
  }
}
```

**Via Docker:**

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

MIT — see [LICENSE](LICENSE).

---

[![frappe_mcp MCP server](https://glama.ai/mcp/servers/muthanii/frappe_mcp/badges/card.svg)](https://glama.ai/mcp/servers/muthanii/frappe_mcp)
