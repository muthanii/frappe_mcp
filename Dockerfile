FROM python:3.12-slim

LABEL org.opencontainers.image.title="Frappe MCP Server"
LABEL org.opencontainers.image.description="MCP server for Frappe Framework — interact with Frappe/ERPNext sites via MCP clients"
LABEL org.opencontainers.image.source="https://hub.docker.com/r/muthanii/frappe-mcp"
LABEL org.opencontainers.image.licenses="MIT"

# Create non-root user
RUN groupadd -r frappe && useradd -r -g frappe -d /app frappe

WORKDIR /app

# Copy and install
COPY pyproject.toml ./
COPY frappe_mcp/ ./frappe_mcp/
RUN pip install --no-cache-dir -e .

# Drop root for runtime
USER frappe

# MCP runs over stdio — no ports exposed
ENTRYPOINT ["frappe-mcp"]
