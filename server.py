"""
MCP server for Red Hat Ansible Automation Platform (AAP).

Exposes tools covering three AAP components over the Model Context Protocol:
  * AAP Controller     - job templates, jobs, inventories, hosts, projects,
                          credentials, organizations, execution environments
  * Event-Driven Ansible (EDA) - rulebook activations, activation instances,
                          rulebooks, event streams, decision environments
  * Private Automation Hub    - collections, namespaces, repositories,
                          execution-environment images

Transport defaults to stdio (for use with Claude Desktop / Claude Code style
MCP clients) but can be switched to streamable-http for remote deployment.

Configuration (environment variables):
    AAP_URL / AAP_TOKEN                 shared base URL + token, used as a
                                         fallback for all three components
    AAP_CONTROLLER_URL / _TOKEN         Controller-specific overrides
    AAP_EDA_URL / _TOKEN                EDA-specific overrides
    AAP_HUB_URL / _TOKEN                Automation Hub-specific overrides
    AAP_*_USERNAME / AAP_*_PASSWORD     basic-auth alternative to a token
    AAP_*_VERIFY_SSL                    "false" to disable TLS verification
                                         (default: true)
    AAP_MCP_TRANSPORT                   "stdio" (default) or "streamable-http"
    AAP_MCP_HOST / AAP_MCP_PORT         used only for streamable-http

Example (stdio, single gateway host):
    export AAP_URL="https://aap.example.com"
    export AAP_TOKEN="eyJhbGciOi..."
    python server.py
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

from aap_client import AAPAPIError, client_from_env

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aap-mcp-server")

mcp = FastMCP(
    "ansible-automation-platform",
    instructions=(
        "Tools for managing Red Hat Ansible Automation Platform: the "
        "automation controller (job templates, jobs, inventories, "
        "projects, credentials), Event-Driven Ansible (rulebook "
        "activations, event streams), and Private Automation Hub "
        "(collections, namespaces, repositories, execution environments)."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client(kind: str):
    """Create a fresh, short-lived client per call.

    AAP tokens can be rotated/expired between calls and this server may be
    used over a long-running stdio session, so we avoid caching connections
    and instead build a lightweight client per tool invocation.
    """
    return client_from_env(kind)


def _run(kind: str, fn_name: str, **kwargs) -> str:
    """Call `fn_name(**kwargs)` on a fresh client of the given kind and
    return a JSON string, translating API errors into readable tool output
    instead of raising (so the MCP client gets a useful error message).
    """
    client = _get_client(kind)
    try:
        fn = getattr(client, fn_name)
        result = fn(**{k: v for k, v in kwargs.items() if v is not None})
        return json.dumps(result, indent=2, default=str)
    except AAPAPIError as e:
        return json.dumps(
            {"error": True, "status_code": e.status_code, "url": e.url, "detail": e.detail},
            indent=2,
            default=str,
        )
    except httpx.RequestError as e:
        return json.dumps(
            {"error": True, "message": f"Network error contacting {kind}: {e}"},
            indent=2,
        )
    except ValueError as e:
        return json.dumps({"error": True, "message": str(e)}, indent=2)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Controller: job templates & jobs
# ---------------------------------------------------------------------------

@mcp.tool()
def list_job_templates(search: Optional[str] = None, page: Optional[int] = None,
                        page_size: Optional[int] = None, order_by: Optional[str] = None) -> str:
    """List job templates on the AAP Controller. Supports free-text search on name/description."""
    return _run("controller", "list_job_templates", search=search, page=page, page_size=page_size, order_by=order_by)


@mcp.tool()
def get_job_template(template_id: int) -> str:
    """Get full details (survey, playbook, credentials, inventory) for one job template."""
    return _run("controller", "get_job_template", template_id=template_id)


@mcp.tool()
def launch_job_template(template_id: int, extra_vars: Optional[dict] = None,
                         limit: Optional[str] = None, inventory: Optional[int] = None) -> str:
    """Launch a job template. extra_vars is a dict of survey/extra variables;
    limit restricts execution to a host pattern; inventory overrides the
    template's default inventory ID."""
    return _run("controller", "launch_job_template", template_id=template_id,
                extra_vars=extra_vars, limit=limit, inventory=inventory)


@mcp.tool()
def list_workflow_job_templates(search: Optional[str] = None, page: Optional[int] = None,
                                 page_size: Optional[int] = None) -> str:
    """List workflow job templates (multi-step automation pipelines)."""
    return _run("controller", "list_workflow_job_templates", search=search, page=page, page_size=page_size)


@mcp.tool()
def launch_workflow_job_template(template_id: int, extra_vars: Optional[dict] = None) -> str:
    """Launch a workflow job template."""
    return _run("controller", "launch_workflow_job_template", template_id=template_id, extra_vars=extra_vars)


@mcp.tool()
def list_jobs(search: Optional[str] = None, status: Optional[str] = None,
              page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List jobs (run history). status can be e.g. 'successful', 'failed', 'running', 'pending'."""
    return _run("controller", "list_jobs", search=search, status=status, page=page, page_size=page_size)


@mcp.tool()
def get_job(job_id: int) -> str:
    """Get details and current status for a single job run."""
    return _run("controller", "get_job", job_id=job_id)


@mcp.tool()
def get_job_stdout(job_id: int) -> str:
    """Get the plain-text console output (stdout) of a job run."""
    client = _get_client("controller")
    try:
        return client.get_job_stdout(job_id)
    except AAPAPIError as e:
        return json.dumps({"error": True, "status_code": e.status_code, "detail": e.detail})
    except httpx.RequestError as e:
        return json.dumps({"error": True, "message": f"Network error contacting controller: {e}"})
    finally:
        client.close()


@mcp.tool()
def cancel_job(job_id: int) -> str:
    """Cancel a running or pending job."""
    return _run("controller", "cancel_job", job_id=job_id)


@mcp.tool()
def list_workflow_jobs(search: Optional[str] = None, status: Optional[str] = None,
                        page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List workflow job runs (run history for workflow job templates)."""
    return _run("controller", "list_workflow_jobs", search=search, status=status, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Controller: inventories, hosts, groups
# ---------------------------------------------------------------------------

@mcp.tool()
def list_inventories(search: Optional[str] = None, page: Optional[int] = None,
                      page_size: Optional[int] = None) -> str:
    """List inventories."""
    return _run("controller", "list_inventories", search=search, page=page, page_size=page_size)


@mcp.tool()
def get_inventory(inventory_id: int) -> str:
    """Get details for a single inventory."""
    return _run("controller", "get_inventory", inventory_id=inventory_id)


@mcp.tool()
def list_hosts(search: Optional[str] = None, inventory_id: Optional[int] = None,
                page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List hosts, optionally scoped to a single inventory_id."""
    return _run("controller", "list_hosts", search=search, inventory_id=inventory_id, page=page, page_size=page_size)


@mcp.tool()
def get_host(host_id: int) -> str:
    """Get details (facts, variables, group membership) for a single host."""
    return _run("controller", "get_host", host_id=host_id)


@mcp.tool()
def list_groups(search: Optional[str] = None, inventory_id: Optional[int] = None,
                 page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List inventory groups, optionally scoped to a single inventory_id."""
    return _run("controller", "list_groups", search=search, inventory_id=inventory_id, page=page, page_size=page_size)


@mcp.tool()
def sync_inventory_source(source_id: int) -> str:
    """Trigger a sync (inventory update) for a dynamic inventory source."""
    return _run("controller", "sync_inventory_source", source_id=source_id)


# ---------------------------------------------------------------------------
# Controller: projects, orgs, credentials, EEs, instances
# ---------------------------------------------------------------------------

@mcp.tool()
def list_projects(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List projects (SCM sources for playbooks)."""
    return _run("controller", "list_projects", search=search, page=page, page_size=page_size)


@mcp.tool()
def sync_project(project_id: int) -> str:
    """Trigger a project SCM sync (update)."""
    return _run("controller", "sync_project", project_id=project_id)


@mcp.tool()
def list_organizations(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List organizations."""
    return _run("controller", "list_organizations", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_teams(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List teams."""
    return _run("controller", "list_teams", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_users(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List platform users."""
    return _run("controller", "list_users", search=search, page=page, page_size=page_size)


@mcp.tool()
def whoami() -> str:
    """Return the identity of the currently authenticated Controller user/token."""
    return _run("controller", "whoami")


@mcp.tool()
def list_credentials(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List credentials (metadata only - secrets are never exposed by the API)."""
    return _run("controller", "list_credentials", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_credential_types(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List available credential types (SSH, Vault, cloud provider, etc.)."""
    return _run("controller", "list_credential_types", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_execution_environments(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List execution environments (container images used to run jobs)."""
    return _run("controller", "list_execution_environments", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_instances(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List controller/execution node instances and their capacity."""
    return _run("controller", "list_instances", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_instance_groups(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List instance groups (pools of nodes jobs can be routed to)."""
    return _run("controller", "list_instance_groups", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_activity_stream(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List Controller activity stream entries (audit log of changes)."""
    return _run("controller", "list_activity_stream", search=search, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# EDA: rulebook activations
# ---------------------------------------------------------------------------

@mcp.tool()
def list_eda_activations(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List EDA rulebook activations (running or stopped rule engines)."""
    return _run("eda", "list_activations", search=search, page=page, page_size=page_size)


@mcp.tool()
def get_eda_activation(activation_id: int) -> str:
    """Get details and current status for one EDA rulebook activation."""
    return _run("eda", "get_activation", activation_id=activation_id)


@mcp.tool()
def enable_eda_activation(activation_id: int) -> str:
    """Enable (start) an EDA rulebook activation."""
    return _run("eda", "enable_activation", activation_id=activation_id)


@mcp.tool()
def disable_eda_activation(activation_id: int) -> str:
    """Disable (stop) an EDA rulebook activation."""
    return _run("eda", "disable_activation", activation_id=activation_id)


@mcp.tool()
def restart_eda_activation(activation_id: int) -> str:
    """Restart an EDA rulebook activation."""
    return _run("eda", "restart_activation", activation_id=activation_id)


@mcp.tool()
def list_eda_activation_instances(activation_id: Optional[int] = None,
                                   page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List EDA activation instances (individual run history of an activation),
    optionally scoped to one activation_id."""
    return _run("eda", "list_activation_instances", activation_id=activation_id, page=page, page_size=page_size)


@mcp.tool()
def get_eda_activation_instance_logs(instance_id: int, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """Get log lines for an EDA activation instance run."""
    return _run("eda", "get_activation_instance_logs", instance_id=instance_id, page=page, page_size=page_size)


@mcp.tool()
def list_eda_rulebooks(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List EDA rulebooks (the rule definitions activations run)."""
    return _run("eda", "list_rulebooks", search=search, page=page, page_size=page_size)


@mcp.tool()
def get_eda_rulebook(rulebook_id: int) -> str:
    """Get the full definition (rules/conditions/actions) of one EDA rulebook."""
    return _run("eda", "get_rulebook", rulebook_id=rulebook_id)


@mcp.tool()
def list_eda_audit_rules(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List EDA audit rules (a record of rules that have fired, with matching events)."""
    return _run("eda", "list_audit_rules", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_eda_event_streams(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List EDA event streams (webhook-style external event sources)."""
    return _run("eda", "list_event_streams", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_eda_decision_environments(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List EDA decision environments (container images that run rulebook activations)."""
    return _run("eda", "list_decision_environments", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_eda_projects(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List EDA projects (SCM sources for rulebooks)."""
    return _run("eda", "list_projects", search=search, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Private Automation Hub: collections, namespaces, repositories, EEs
# ---------------------------------------------------------------------------

@mcp.tool()
def list_hub_collections(repository: str = "published", search: Optional[str] = None,
                          page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List Ansible content collections in a Private Automation Hub repository
    (default repository: 'published'; other common values: 'community', 'rh-certified')."""
    return _run("hub", "list_collections", repository=repository, search=search, page=page, page_size=page_size)


@mcp.tool()
def get_hub_collection(namespace: str, name: str, repository: str = "published") -> str:
    """Get details for one collection (namespace.name) in a Hub repository."""
    return _run("hub", "get_collection", namespace=namespace, name=name, repository=repository)


@mcp.tool()
def list_hub_collection_versions(namespace: str, name: str, repository: str = "published",
                                  page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List published versions of one collection."""
    return _run("hub", "list_collection_versions", namespace=namespace, name=name,
                repository=repository, page=page, page_size=page_size)


@mcp.tool()
def get_hub_collection_version(namespace: str, name: str, version: str, repository: str = "published") -> str:
    """Get details (dependencies, docs, contents) for a specific collection version."""
    return _run("hub", "get_collection_version", namespace=namespace, name=name,
                version=version, repository=repository)


@mcp.tool()
def list_hub_namespaces(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List collection namespaces on the Hub."""
    return _run("hub", "list_namespaces", search=search, page=page, page_size=page_size)


@mcp.tool()
def get_hub_namespace(name: str) -> str:
    """Get details for one Hub namespace."""
    return _run("hub", "get_namespace", name=name)


@mcp.tool()
def list_hub_repositories(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List content repositories configured on the Hub."""
    return _run("hub", "list_repositories", search=search, page=page, page_size=page_size)


@mcp.tool()
def list_hub_remotes(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List remotes (external sync sources, e.g. galaxy.ansible.com or Red Hat certified content)."""
    return _run("hub", "list_remotes", search=search, page=page, page_size=page_size)


@mcp.tool()
def sync_hub_repository(distro_base_path: str) -> str:
    """Trigger a sync of a Hub repository from its configured remote.
    distro_base_path is the repository's distribution base path (e.g. 'rh-certified')."""
    return _run("hub", "sync_repository", distro_base_path=distro_base_path)


@mcp.tool()
def list_hub_execution_environments(search: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None) -> str:
    """List container execution-environment images stored in the Hub's registry."""
    return _run("hub", "list_execution_environments", search=search, page=page, page_size=page_size)


@mcp.tool()
def get_hub_execution_environment(name: str) -> str:
    """Get details for one execution-environment image repository on the Hub."""
    return _run("hub", "get_execution_environment", name=name)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    transport = os.environ.get("AAP_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.settings.host = os.environ.get("AAP_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("AAP_MCP_PORT", "8000"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
