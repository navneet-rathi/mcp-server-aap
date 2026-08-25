"""
HTTP clients for Ansible Automation Platform components:
- AAP Controller (job/inventory/project/credential management)
- Event-Driven Ansible (EDA) controller
- Private Automation Hub (Galaxy NG API for collections/repositories)

All three services share the same basic pattern (token-authenticated REST
APIs served over HTTPS), so a small shared base class does the heavy lifting
and each subclass just points at the right base path.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx


class AAPAPIError(RuntimeError):
    """Raised when an AAP-family API returns a non-2xx response."""

    def __init__(self, status_code: int, url: str, detail: Any):
        self.status_code = status_code
        self.url = url
        self.detail = detail
        super().__init__(f"{status_code} error calling {url}: {detail}")


class BaseAAPClient:
    """Thin wrapper around httpx for token-authenticated AAP-family APIs."""

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ):
        if not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url.rstrip("/")

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        auth = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            auth = (username, password)
        else:
            raise ValueError("Either a token or a username/password must be provided")

        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            auth=auth,
            verify=verify_ssl,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BaseAAPClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- internal request helper -------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> Any:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise AAPAPIError(response.status_code, str(response.url), detail)
        if response.status_code == 204 or not response.content:
            return {"status": "ok", "status_code": response.status_code}
        return response.json()

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json_body: Optional[dict] = None) -> Any:
        return self._request("POST", path, json=json_body)

    def patch(self, path: str, json_body: Optional[dict] = None) -> Any:
        return self._request("PATCH", path, json=json_body)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)


def _paginated_params(
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    search: Optional[str] = None,
    order_by: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if page_size is not None:
        params["page_size"] = page_size
    if search:
        params["search"] = search
    if order_by:
        params["order_by"] = order_by
    if extra:
        params.update({k: v for k, v in extra.items() if v is not None})
    return params


class ControllerClient(BaseAAPClient):
    """AAP Controller (automation controller / awx) API, /api/controller/v2/."""

    API_PREFIX = "/api/controller/v2"

    def _p(self, path: str) -> str:
        return f"{self.API_PREFIX}/{path.strip('/')}/"

    # Job templates ---------------------------------------------------------
    def list_job_templates(self, page=None, page_size=None, search=None, order_by=None):
        return self.get(self._p("job_templates"), _paginated_params(page, page_size, search, order_by))

    def get_job_template(self, template_id: int):
        return self.get(self._p(f"job_templates/{template_id}"))

    def launch_job_template(self, template_id: int, extra_vars: Optional[dict] = None,
                             limit: Optional[str] = None, inventory: Optional[int] = None):
        body: dict[str, Any] = {}
        if extra_vars:
            body["extra_vars"] = extra_vars
        if limit:
            body["limit"] = limit
        if inventory:
            body["inventory"] = inventory
        return self.post(self._p(f"job_templates/{template_id}/launch"), body or None)

    # Workflow job templates -------------------------------------------------
    def list_workflow_job_templates(self, page=None, page_size=None, search=None, order_by=None):
        return self.get(self._p("workflow_job_templates"), _paginated_params(page, page_size, search, order_by))

    def launch_workflow_job_template(self, template_id: int, extra_vars: Optional[dict] = None):
        body = {"extra_vars": extra_vars} if extra_vars else None
        return self.post(self._p(f"workflow_job_templates/{template_id}/launch"), body)

    # Jobs --------------------------------------------------------------------
    def list_jobs(self, page=None, page_size=None, search=None, status: Optional[str] = None, order_by="-created"):
        return self.get(self._p("jobs"), _paginated_params(page, page_size, search, order_by, {"status": status}))

    def get_job(self, job_id: int):
        return self.get(self._p(f"jobs/{job_id}"))

    def get_job_stdout(self, job_id: int, fmt: str = "txt"):
        response = self._client.get(f"{self.API_PREFIX}/jobs/{job_id}/stdout/", params={"format": fmt})
        if response.status_code >= 400:
            raise AAPAPIError(response.status_code, str(response.url), response.text)
        return response.text

    def cancel_job(self, job_id: int):
        return self.post(self._p(f"jobs/{job_id}/cancel"))

    # Workflow jobs -------------------------------------------------------------
    def list_workflow_jobs(self, page=None, page_size=None, search=None, status: Optional[str] = None):
        return self.get(self._p("workflow_jobs"), _paginated_params(page, page_size, search, extra={"status": status}))

    def get_workflow_job(self, workflow_job_id: int):
        return self.get(self._p(f"workflow_jobs/{workflow_job_id}"))

    # Inventories ---------------------------------------------------------------
    def list_inventories(self, page=None, page_size=None, search=None, order_by=None):
        return self.get(self._p("inventories"), _paginated_params(page, page_size, search, order_by))

    def get_inventory(self, inventory_id: int):
        return self.get(self._p(f"inventories/{inventory_id}"))

    def list_hosts(self, page=None, page_size=None, search=None, inventory_id: Optional[int] = None):
        if inventory_id:
            return self.get(self._p(f"inventories/{inventory_id}/hosts"), _paginated_params(page, page_size, search))
        return self.get(self._p("hosts"), _paginated_params(page, page_size, search))

    def get_host(self, host_id: int):
        return self.get(self._p(f"hosts/{host_id}"))

    def list_groups(self, page=None, page_size=None, search=None, inventory_id: Optional[int] = None):
        if inventory_id:
            return self.get(self._p(f"inventories/{inventory_id}/groups"), _paginated_params(page, page_size, search))
        return self.get(self._p("groups"), _paginated_params(page, page_size, search))

    def sync_inventory_source(self, source_id: int):
        return self.post(self._p(f"inventory_sources/{source_id}/update"))

    # Projects --------------------------------------------------------------
    def list_projects(self, page=None, page_size=None, search=None):
        return self.get(self._p("projects"), _paginated_params(page, page_size, search))

    def sync_project(self, project_id: int):
        return self.post(self._p(f"projects/{project_id}/update"))

    # Organizations / teams / users -----------------------------------------
    def list_organizations(self, page=None, page_size=None, search=None):
        return self.get(self._p("organizations"), _paginated_params(page, page_size, search))

    def list_teams(self, page=None, page_size=None, search=None):
        return self.get(self._p("teams"), _paginated_params(page, page_size, search))

    def list_users(self, page=None, page_size=None, search=None):
        return self.get(self._p("users"), _paginated_params(page, page_size, search))

    def whoami(self):
        return self.get(self._p("me"))

    # Credentials -------------------------------------------------------------
    def list_credentials(self, page=None, page_size=None, search=None):
        return self.get(self._p("credentials"), _paginated_params(page, page_size, search))

    def list_credential_types(self, page=None, page_size=None, search=None):
        return self.get(self._p("credential_types"), _paginated_params(page, page_size, search))

    # Execution environments / instances --------------------------------------
    def list_execution_environments(self, page=None, page_size=None, search=None):
        return self.get(self._p("execution_environments"), _paginated_params(page, page_size, search))

    def list_instances(self, page=None, page_size=None, search=None):
        return self.get(self._p("instances"), _paginated_params(page, page_size, search))

    def list_instance_groups(self, page=None, page_size=None, search=None):
        return self.get(self._p("instance_groups"), _paginated_params(page, page_size, search))

    # Activity stream ----------------------------------------------------------
    def list_activity_stream(self, page=None, page_size=None, search=None):
        return self.get(self._p("activity_stream"), _paginated_params(page, page_size, search))


class EDAClient(BaseAAPClient):
    """Event-Driven Ansible controller API, /api/eda/v1/."""

    API_PREFIX = "/api/eda/v1"

    def _p(self, path: str) -> str:
        return f"{self.API_PREFIX}/{path.strip('/')}/"

    # Rulebook activations -------------------------------------------------------
    def list_activations(self, page=None, page_size=None, search=None):
        return self.get(self._p("activations"), _paginated_params(page, page_size, search))

    def get_activation(self, activation_id: int):
        return self.get(self._p(f"activations/{activation_id}"))

    def enable_activation(self, activation_id: int):
        return self.post(self._p(f"activations/{activation_id}/enable"))

    def disable_activation(self, activation_id: int):
        return self.post(self._p(f"activations/{activation_id}/disable"))

    def restart_activation(self, activation_id: int):
        return self.post(self._p(f"activations/{activation_id}/restart"))

    def delete_activation(self, activation_id: int):
        return self.delete(self._p(f"activations/{activation_id}"))

    def list_activation_instances(self, page=None, page_size=None, activation_id: Optional[int] = None):
        params = _paginated_params(page, page_size, extra={"activation_id": activation_id})
        return self.get(self._p("activation-instances"), params)

    def get_activation_instance_logs(self, instance_id: int, page=None, page_size=None):
        return self.get(self._p(f"activation-instances/{instance_id}/logs"), _paginated_params(page, page_size))

    # Rulebooks / rules -----------------------------------------------------------
    def list_rulebooks(self, page=None, page_size=None, search=None):
        return self.get(self._p("rulebooks"), _paginated_params(page, page_size, search))

    def get_rulebook(self, rulebook_id: int):
        return self.get(self._p(f"rulebooks/{rulebook_id}"))

    def list_audit_rules(self, page=None, page_size=None, search=None):
        return self.get(self._p("audit-rules"), _paginated_params(page, page_size, search))

    # Event streams -----------------------------------------------------------------
    def list_event_streams(self, page=None, page_size=None, search=None):
        return self.get(self._p("event-streams"), _paginated_params(page, page_size, search))

    # Decision environments -----------------------------------------------------------
    def list_decision_environments(self, page=None, page_size=None, search=None):
        return self.get(self._p("decision-environments"), _paginated_params(page, page_size, search))

    # Projects / credentials (EDA keeps its own copies) --------------------------------
    def list_projects(self, page=None, page_size=None, search=None):
        return self.get(self._p("projects"), _paginated_params(page, page_size, search))

    def list_credentials(self, page=None, page_size=None, search=None):
        return self.get(self._p("eda-credentials"), _paginated_params(page, page_size, search))


class HubClient(BaseAAPClient):
    """Private Automation Hub API (Galaxy NG / pulp_ansible), /api/galaxy/."""

    API_PREFIX = "/api/galaxy"

    def _p(self, path: str) -> str:
        return f"{self.API_PREFIX}/{path.strip('/')}/"

    # Collections ---------------------------------------------------------------
    def list_collections(self, repository: str = "published", page=None, page_size=None, search=None):
        path = f"content/{repository}/v3/collections"
        return self.get(self._p(path), _paginated_params(page, page_size, search))

    def get_collection(self, namespace: str, name: str, repository: str = "published"):
        path = f"content/{repository}/v3/collections/{namespace}/{name}"
        return self.get(self._p(path))

    def list_collection_versions(self, namespace: str, name: str, repository: str = "published",
                                  page=None, page_size=None):
        path = f"content/{repository}/v3/collections/{namespace}/{name}/versions"
        return self.get(self._p(path), _paginated_params(page, page_size))

    def get_collection_version(self, namespace: str, name: str, version: str, repository: str = "published"):
        path = f"content/{repository}/v3/collections/{namespace}/{name}/versions/{version}"
        return self.get(self._p(path))

    # Namespaces -----------------------------------------------------------------
    def list_namespaces(self, page=None, page_size=None, search=None):
        return self.get(self._p("v3/namespaces"), _paginated_params(page, page_size, search))

    def get_namespace(self, name: str):
        return self.get(self._p(f"v3/namespaces/{name}"))

    # Repositories ------------------------------------------------------------------
    def list_repositories(self, page=None, page_size=None, search=None):
        return self.get(self._p("v3/plugin/ansible/content/repositories"), _paginated_params(page, page_size, search))

    # Remotes / sync (for mirrored repos, e.g. syncing from Ansible Galaxy/Red Hat) --------
    def list_remotes(self, page=None, page_size=None, search=None):
        return self.get(self._p("v3/plugin/ansible/content/remotes"), _paginated_params(page, page_size, search))

    def sync_repository(self, distro_base_path: str):
        path = f"content/{distro_base_path}/v3/sync"
        return self.post(self._p(path))

    # Execution environments (container registry side of the Hub) -----------------------
    def list_execution_environments(self, page=None, page_size=None, search=None):
        return self.get(self._p("v3/plugin/execution-environments/repositories"),
                         _paginated_params(page, page_size, search))

    def get_execution_environment(self, name: str):
        return self.get(self._p(f"v3/plugin/execution-environments/repositories/{name}"))


def client_from_env(kind: str) -> BaseAAPClient:
    """Build a client from environment variables.

    kind: one of "controller", "eda", "hub"
    Expected env vars (prefix depends on kind), e.g. for "controller":
        AAP_CONTROLLER_URL, AAP_CONTROLLER_TOKEN
        (or AAP_CONTROLLER_USERNAME / AAP_CONTROLLER_PASSWORD)
        AAP_CONTROLLER_VERIFY_SSL (default: true)

    Falls back to shared AAP_URL / AAP_TOKEN / AAP_USERNAME / AAP_PASSWORD /
    AAP_VERIFY_SSL if the component-specific vars aren't set, since many AAP
    deployments expose all three services behind the same gateway host.
    """
    kind_upper = kind.upper()
    base_url = os.environ.get(f"AAP_{kind_upper}_URL") or os.environ.get("AAP_URL")
    token = os.environ.get(f"AAP_{kind_upper}_TOKEN") or os.environ.get("AAP_TOKEN")
    username = os.environ.get(f"AAP_{kind_upper}_USERNAME") or os.environ.get("AAP_USERNAME")
    password = os.environ.get(f"AAP_{kind_upper}_PASSWORD") or os.environ.get("AAP_PASSWORD")
    verify_ssl_raw = (
        os.environ.get(f"AAP_{kind_upper}_VERIFY_SSL")
        or os.environ.get("AAP_VERIFY_SSL")
        or "true"
    )
    verify_ssl = verify_ssl_raw.strip().lower() not in ("false", "0", "no")

    classes = {"controller": ControllerClient, "eda": EDAClient, "hub": HubClient}
    if kind not in classes:
        raise ValueError(f"Unknown client kind: {kind}")

    return classes[kind](
        base_url=base_url,
        token=token,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )
