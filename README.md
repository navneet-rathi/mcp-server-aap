# AAP MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server for Red Hat
**Ansible Automation Platform**, covering all three core components:

- **AAP Controller** — job templates, jobs, workflows, inventories, hosts,
  projects, credentials, organizations, execution environments
- **Event-Driven Ansible (EDA)** — rulebook activations, activation
  instances/logs, rulebooks, event streams, decision environments
- **Private Automation Hub** — collections, namespaces, repositories,
  remotes, execution-environment images

52 tools total. Read-only by default in spirit (list/get), plus a handful of
explicit action tools (`launch_job_template`, `enable_eda_activation`,
`sync_project`, etc.) clearly named so a client/user can see what will change
state before calling them.

## Files

| File | Purpose |
|---|---|
| `aap_client.py` | Thin `httpx`-based REST clients for Controller, EDA, and Hub APIs |
| `server.py` | The MCP server — wraps each client method as an `@mcp.tool()` |
| `requirements.txt` | Python dependencies |
| `.env.example` | All supported environment variables |

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configure

Copy `.env.example` to `.env` and fill in your AAP details, or export the
variables directly:

```bash
export AAP_URL="https://aap.example.com"
export AAP_TOKEN="eyJhbGciOi..."          # Controller/EDA/Hub personal access token
```

If Controller, EDA, and Hub live on different hosts (common in larger
deployments), set the per-component variants instead:

```bash
export AAP_CONTROLLER_URL="https://controller.example.com"
export AAP_CONTROLLER_TOKEN="..."
export AAP_EDA_URL="https://eda.example.com"
export AAP_EDA_TOKEN="..."
export AAP_HUB_URL="https://hub.example.com"
export AAP_HUB_TOKEN="..."
```

Username/password (basic auth) is also supported via `AAP_USERNAME` /
`AAP_PASSWORD` (or the per-component equivalents) as an alternative to a
token. Self-signed certs in a lab environment: set `AAP_VERIFY_SSL=false`.

### Getting a token

In each AAP component's UI: **User menu → User Details → Tokens → Add token**
(Controller and EDA). For the Hub, generate an API token from **My account →
API token** or use basic auth.

## Run

**stdio** (for Claude Desktop, Claude Code, or any local MCP client):

```bash
python server.py
```

Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ansible-automation-platform": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/aap-mcp-server/server.py"],
      "env": {
        "AAP_URL": "https://aap.example.com",
        "AAP_TOKEN": "eyJhbGciOi..."
      }
    }
  }
}
```

**streamable-http** (remote/shared server):

```bash
export AAP_MCP_TRANSPORT=streamable-http
export AAP_MCP_HOST=0.0.0.0
export AAP_MCP_PORT=8000
python server.py
```

## Tool overview

### Controller
`list_job_templates`, `get_job_template`, `launch_job_template`,
`list_workflow_job_templates`, `launch_workflow_job_template`, `list_jobs`,
`get_job`, `get_job_stdout`, `cancel_job`, `list_workflow_jobs`,
`list_inventories`, `get_inventory`, `list_hosts`, `get_host`, `list_groups`,
`sync_inventory_source`, `list_projects`, `sync_project`,
`list_organizations`, `list_teams`, `list_users`, `whoami`,
`list_credentials`, `list_credential_types`, `list_execution_environments`,
`list_instances`, `list_instance_groups`, `list_activity_stream`

### EDA
`list_eda_activations`, `get_eda_activation`, `enable_eda_activation`,
`disable_eda_activation`, `restart_eda_activation`,
`list_eda_activation_instances`, `get_eda_activation_instance_logs`,
`list_eda_rulebooks`, `get_eda_rulebook`, `list_eda_audit_rules`,
`list_eda_event_streams`, `list_eda_decision_environments`,
`list_eda_projects`

### Private Automation Hub
`list_hub_collections`, `get_hub_collection`, `list_hub_collection_versions`,
`get_hub_collection_version`, `list_hub_namespaces`, `get_hub_namespace`,
`list_hub_repositories`, `list_hub_remotes`, `sync_hub_repository`,
`list_hub_execution_environments`, `get_hub_execution_environment`

## Notes

- Most `list_*` tools accept `search`, `page`, and `page_size` to filter and
  paginate large result sets.
- API errors (auth failures, 404s, validation errors) are returned as JSON
  (`{"error": true, "status_code": ..., "detail": ...}`) rather than raising,
  so the calling model/client gets a readable message.
- A new HTTP client is created per tool call rather than reused, since AAP
  tokens can expire or rotate during a long-lived stdio session.
- Credential *secrets* are never returned — the Controller API itself never
  exposes them, only metadata.
