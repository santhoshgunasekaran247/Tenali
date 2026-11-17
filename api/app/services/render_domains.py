"""Synchronous, typed adapter for Render custom-domain management.

Render's Custom Domains API is documented at https://api-docs.render.com/
reference/list-custom-domains. Add/list/retrieve/verify/delete endpoints are
scoped to an individual web service or static site.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import re
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import HTTPException

RENDER_API_BASE = "https://api.render.com/v1"
RENDER_TIMEOUT_SECONDS = 10.0
DEFAULT_APEX_IP = "216.24.57.1"
ServiceKind = Literal["web", "api"]

_REQUIRED_ENV = (
    "TENALI_RENDER_API_KEY",
    "TENALI_RENDER_WEB_SERVICE_ID",
    "TENALI_RENDER_API_SERVICE_ID",
    "TENALI_RENDER_WEB_HOST",
    "TENALI_RENDER_API_HOST",
)
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class RenderDomainConfig:
    """Render credentials, service IDs, and Render-provided DNS targets."""

    api_key: str
    web_service_id: str
    api_service_id: str
    web_host: str
    api_host: str
    apex_ip: str = DEFAULT_APEX_IP

    def service_id(self, service_kind: ServiceKind) -> str:
        if service_kind == "web":
            return self.web_service_id
        if service_kind == "api":
            return self.api_service_id
        raise ValueError("service_kind must be 'web' or 'api'")


@dataclass(frozen=True)
class RenderDomainBinding:
    """A Render domain and the facts needed for safe tenant ownership tracking."""

    service_kind: ServiceKind
    id: str
    hostname: str
    verification_status: str
    domain_type: str
    redirect_for_name: str | None
    is_requested: bool
    found_before_write: bool
    created_by_this_call: bool

    @property
    def ready(self) -> bool:
        """Whether Render has completed DNS verification and TLS provisioning."""
        return self.verification_status == "verified"

    @property
    def provider_owned(self) -> bool:
        """Whether this adapter call observed the domain returned from its POST."""
        return self.created_by_this_call


@dataclass(frozen=True)
class TenantDomainProvisioning:
    """Requested hostnames and any Render-created redirect aliases."""

    frontend_hostname: str
    api_hostname: str
    domains: tuple[RenderDomainBinding, ...]

    @property
    def aliases(self) -> tuple[RenderDomainBinding, ...]:
        """Return Render-created counterpart domains, such as ``www``."""
        return tuple(domain for domain in self.domains if not domain.is_requested)


@dataclass(frozen=True)
class EnsureCustomDomainResult:
    """The requested domain and any automatic Render counterpart aliases."""

    domain: RenderDomainBinding
    aliases: tuple[RenderDomainBinding, ...]

    @property
    def id(self) -> str:
        return self.domain.id

    @property
    def hostname(self) -> str:
        return self.domain.hostname

    @property
    def ready(self) -> bool:
        return self.domain.ready

    @property
    def provider_owned(self) -> bool:
        """Whether the domain was first returned by this call's successful POST."""
        return self.domain.created_by_this_call


def get_render_domain_config() -> RenderDomainConfig | None:
    """Load Render settings; return ``None`` only when every required value is absent.

    ``TENALI_RENDER_APEX_IP`` is optional and defaults to Render's documented
    load-balancer address for apex A records. The two ``*_HOST`` values must be
    Render-provided ``.onrender.com`` hostnames used as CNAME targets.
    """
    values = {name: os.getenv(name, "").strip() for name in _REQUIRED_ENV}
    configured = {name: value for name, value in values.items() if value}
    apex_ip_value = os.getenv("TENALI_RENDER_APEX_IP", "").strip()
    if not configured and not apex_ip_value:
        return None

    missing = [name for name, value in values.items() if not value]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "Render domain provisioning is partially configured. Set all "
                "of the TENALI_RENDER_* settings: "
                + ", ".join(_REQUIRED_ENV)
                + "."
            ),
        )

    try:
        web_host = _normalize_hostname(values["TENALI_RENDER_WEB_HOST"])
        api_host = _normalize_hostname(values["TENALI_RENDER_API_HOST"])
        if not web_host.endswith(".onrender.com") or web_host == "onrender.com":
            raise ValueError
        if not api_host.endswith(".onrender.com") or api_host == "onrender.com":
            raise ValueError
        if web_host == api_host or values["TENALI_RENDER_WEB_SERVICE_ID"] == values["TENALI_RENDER_API_SERVICE_ID"]:
            raise ValueError
        apex_ip = str(ipaddress.IPv4Address(apex_ip_value or DEFAULT_APEX_IP))
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Invalid Render domain configuration. WEB_HOST and API_HOST "
                "must be hostnames ending in .onrender.com, and APEX_IP must "
                "be an IPv4 address."
            ),
        ) from exc

    return RenderDomainConfig(
        api_key=values["TENALI_RENDER_API_KEY"],
        web_service_id=values["TENALI_RENDER_WEB_SERVICE_ID"],
        api_service_id=values["TENALI_RENDER_API_SERVICE_ID"],
        web_host=web_host,
        api_host=api_host,
        apex_ip=apex_ip,
    )


def get_config() -> RenderDomainConfig | None:
    """Compatibility entry point for tenant-domain workers."""
    return get_render_domain_config()


def find_custom_domain(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    hostname: str,
) -> RenderDomainBinding | None:
    """Read-only exact hostname lookup in the selected Render service's domain list."""
    try:
        normalized_hostname = _normalize_hostname(hostname)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Enter a valid custom-domain hostname.",
        ) from exc

    domains = _list_service_domains(config, config.service_id(service_kind))
    for domain in domains:
        if _safe_hostname(domain.get("name")) == normalized_hostname:
            return _binding_from_data(
                domain,
                service_kind,
                is_requested=True,
                found_before_write=True,
                created_by_this_call=False,
            )
    return None


def ensure_custom_domain(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    hostname: str,
) -> EnsureCustomDomainResult:
    """Ensure one exact hostname exists and return IDs plus any Render aliases.

    A hostname found by GET is returned with ``created_by_this_call=False`` and
    must not be adopted as tenant-owned without a matching persisted binding.
    """
    try:
        normalized_hostname = _normalize_hostname(hostname)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Enter a valid custom-domain hostname.",
        ) from exc
    bindings = _provision_for_service(config, service_kind, normalized_hostname)
    requested = next(binding for binding in bindings if binding.is_requested)
    aliases = tuple(binding for binding in bindings if not binding.is_requested)
    return EnsureCustomDomainResult(domain=requested, aliases=aliases)


def provision_tenant_domains(
    config: RenderDomainConfig,
    frontend_hostname: str,
) -> TenantDomainProvisioning:
    """Ensure ``frontend_hostname`` and ``api.<frontend_hostname>`` exist in Render.

    The frontend must be an apex/root hostname, not ``www``: Render automatically
    creates the corresponding ``www`` redirect domain when a root domain is added.
    Results distinguish domains found by the initial GET from domains returned by
    this call's POST. Callers must persist ``created_by_this_call`` before treating
    a domain as tenant-owned; an already-present Render domain is not adopted.
    """
    try:
        frontend = _normalize_hostname(frontend_hostname)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Enter a valid root domain hostname, such as example.com.",
        ) from exc
    if frontend.startswith("www."):
        raise HTTPException(
            status_code=422,
            detail=(
                "Use the root frontend hostname, not a www hostname. Render "
                "automatically creates and redirects the www counterpart."
            ),
        )
    try:
        api_hostname = _normalize_hostname(f"api.{frontend}")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="The frontend hostname is too long to create its api subdomain.",
        ) from exc

    domains: list[RenderDomainBinding] = []
    domains.extend(_provision_for_service(config, "web", frontend))
    domains.extend(_provision_for_service(config, "api", api_hostname))

    return TenantDomainProvisioning(
        frontend_hostname=frontend,
        api_hostname=api_hostname,
        domains=tuple(_deduplicate_bindings(domains)),
    )


def get_tenant_domain_status(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    domain_id: str,
) -> RenderDomainBinding:
    """Retrieve a domain by its persisted Render ID and return its current status."""
    data = _render_request(
        config,
        "GET",
        _domain_path(config, service_kind, domain_id),
        expected_statuses={200},
    )
    return _binding_from_data(data, service_kind, is_requested=True)


def get_custom_domain_status(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    domain_id: str,
) -> RenderDomainBinding:
    """Retrieve the current domain state; ``binding.ready`` is the ready flag."""
    return get_tenant_domain_status(config, service_kind, domain_id)


def verify_tenant_domain(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    domain_id: str,
) -> None:
    """Trigger Render's asynchronous DNS verification for a persisted domain ID."""
    _render_request(
        config,
        "POST",
        _domain_path(config, service_kind, domain_id) + "/verify",
        expected_statuses={202},
        ambiguous_write=True,
    )


def verify_custom_domain(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    domain_id: str,
) -> None:
    """Trigger Render DNS verification; retrieve status to observe readiness."""
    verify_tenant_domain(config, service_kind, domain_id)


def delete_tenant_domain(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    domain_id: str,
    *,
    expected_hostname: str,
    created_by_tenant_flow: bool,
) -> None:
    """Idempotently delete an owned exact hostname by Render ID.

    ``created_by_tenant_flow`` must come from the caller's persistent binding
    record, populated only when ``created_by_this_call`` was true. Never pass an
    ID discovered only by listing Render domains. The expected hostname is
    retrieved and checked before deletion, so a stale/mismatched ID is not removed.
    """
    if not created_by_tenant_flow:
        raise HTTPException(
            status_code=409,
            detail="This Render domain was not created by tenant provisioning and cannot be deleted here.",
        )
    try:
        expected = _normalize_hostname(expected_hostname)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="A valid expected hostname is required for deletion.") from exc
    try:
        current = get_tenant_domain_status(config, service_kind, domain_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return
        raise
    if current.hostname != expected:
        raise HTTPException(
            status_code=409,
            detail="The stored Render domain ID no longer matches the expected hostname; it was not deleted.",
        )
    _render_request(
        config,
        "DELETE",
        _domain_path(config, service_kind, domain_id),
        expected_statuses={204},
        allow_not_found=True,
        ambiguous_write=True,
    )


def delete_custom_domain(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    domain_id: str,
    expected_hostname: str,
    *,
    provider_owned: bool,
) -> None:
    """Worker-facing deletion API; requires its persisted provider-ownership flag."""
    delete_tenant_domain(
        config,
        service_kind,
        domain_id,
        expected_hostname=expected_hostname,
        created_by_tenant_flow=provider_owned,
    )


def _provision_for_service(
    config: RenderDomainConfig,
    service_kind: ServiceKind,
    requested_hostname: str,
) -> list[RenderDomainBinding]:
    service_id = config.service_id(service_kind)
    initial_domains = _list_service_domains(config, service_id)
    existing_by_name = {
        _safe_hostname(domain.get("name")): domain
        for domain in initial_domains
        if _safe_hostname(domain.get("name"))
    }
    found_before_write_names = set(existing_by_name)

    if requested_hostname in existing_by_name:
        source_domains = initial_domains
        created_names: set[str] = set()
    else:
        try:
            response_data = _render_request(
                config,
                "POST",
                _service_domains_path(service_id),
                expected_statuses={201},
                json={"name": requested_hostname},
                ambiguous_write=True,
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            # A concurrent request may have won the race. Reconcile with GET;
            # never retry POST after a conflicting or ambiguous write.
            refreshed = _list_service_domains(config, service_id)
            existing_by_name = {
                _safe_hostname(domain.get("name")): domain
                for domain in refreshed
                if _safe_hostname(domain.get("name"))
            }
            if requested_hostname not in existing_by_name:
                raise
            source_domains = refreshed
            created_names = set()
        else:
            created_from_response = _decode_domain_list(response_data)
            if not any(
                _safe_hostname(domain.get("name")) == requested_hostname
                for domain in created_from_response
            ):
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Render accepted the domain request but returned no "
                        "matching custom domain. Check Render before retrying."
                    ),
                )
            source_domains = [*initial_domains, *created_from_response]
            created_names = {
                name
                for domain in created_from_response
                if (name := _safe_hostname(domain.get("name")))
                and name not in existing_by_name
            }

    selected: dict[str, RenderDomainBinding] = {}
    for domain in source_domains:
        name = _safe_hostname(domain.get("name"))
        if not name or not _is_relevant_hostname(
            name, requested_hostname, domain.get("redirectForName")
        ):
            continue
        is_requested = name == requested_hostname
        binding = _binding_from_data(
            domain,
            service_kind,
            is_requested=is_requested,
            found_before_write=name in found_before_write_names,
            created_by_this_call=name in created_names,
        )
        selected[name] = binding

    if requested_hostname not in selected:
        raise HTTPException(
            status_code=502,
            detail="Render's custom-domain response was incomplete. Check the service's domain list and retry.",
        )
    return list(selected.values())


def _list_service_domains(config: RenderDomainConfig, service_id: str) -> list[dict[str, Any]]:
    path = _service_domains_path(service_id)
    cursor: str | None = None
    seen_cursors: set[str] = set()
    results: list[dict[str, Any]] = []

    while True:
        params: dict[str, str | int] = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = _render_request(
            config,
            "GET",
            path,
            expected_statuses={200},
            params=params,
        )
        if not isinstance(page, list):
            raise HTTPException(status_code=502, detail="Render returned an invalid custom-domain list.")

        page_domains: list[dict[str, Any]] = []
        next_cursor: str | None = None
        for item in page:
            if not isinstance(item, dict):
                raise HTTPException(status_code=502, detail="Render returned an invalid custom-domain list.")
            if isinstance(item.get("customDomain"), dict):
                page_domains.append(item["customDomain"])
                if isinstance(item.get("cursor"), str) and item["cursor"]:
                    next_cursor = item["cursor"]
            else:
                page_domains.append(item)
        results.extend(page_domains)

        if len(page) < 100 or not next_cursor:
            break
        if next_cursor in seen_cursors:
            raise HTTPException(status_code=502, detail="Render returned an invalid pagination cursor.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return results


def _decode_domain_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("customDomain"), dict):
            return [value["customDomain"]]
        return [value]
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                result.extend(_decode_domain_list(item))
        return result
    return []


def _binding_from_data(
    data: dict[str, Any],
    service_kind: ServiceKind,
    *,
    is_requested: bool,
    found_before_write: bool = False,
    created_by_this_call: bool = False,
) -> RenderDomainBinding:
    domain_id = data.get("id")
    hostname = _safe_hostname(data.get("name"))
    if not isinstance(domain_id, str) or not domain_id or hostname is None:
        raise HTTPException(status_code=502, detail="Render returned an invalid custom-domain record.")
    redirect_for_name = _safe_hostname(data.get("redirectForName"))
    return RenderDomainBinding(
        service_kind=service_kind,
        id=domain_id,
        hostname=hostname,
        verification_status=str(data.get("verificationStatus") or "unknown"),
        domain_type=str(data.get("domainType") or "unknown"),
        redirect_for_name=redirect_for_name,
        is_requested=is_requested,
        found_before_write=found_before_write,
        created_by_this_call=created_by_this_call,
    )


def _is_relevant_hostname(
    name: str,
    requested: str,
    redirect_for_name: Any,
) -> bool:
    if name == requested:
        return True
    if name == f"www.{requested}":
        return True
    return _safe_hostname(redirect_for_name) == requested


def _safe_hostname(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _normalize_hostname(value)
    except ValueError:
        return None


def _normalize_hostname(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("hostname must be a string")
    value = value.strip()
    if value.endswith("."):
        value = value[:-1]
        if value.endswith("."):
            raise ValueError("invalid hostname")
    if not value or "://" in value or "/" in value or "*" in value or "@" in value:
        raise ValueError("invalid hostname")
    try:
        hostname = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("invalid hostname") from exc
    if len(hostname) > 253:
        raise ValueError("invalid hostname")
    labels = hostname.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("invalid hostname")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("hostname cannot be an IP address")
    return hostname


def _deduplicate_bindings(
    bindings: list[RenderDomainBinding],
) -> list[RenderDomainBinding]:
    by_service_and_name: dict[tuple[ServiceKind, str], RenderDomainBinding] = {}
    for binding in bindings:
        key = (binding.service_kind, binding.hostname)
        previous = by_service_and_name.get(key)
        if previous is None or binding.created_by_this_call:
            by_service_and_name[key] = binding
    return list(by_service_and_name.values())


def _service_domains_path(service_id: str) -> str:
    return f"/services/{quote(service_id, safe='')}/custom-domains"


def _domain_path(config: RenderDomainConfig, service_kind: ServiceKind, domain_id: str) -> str:
    if not domain_id.strip():
        raise HTTPException(status_code=422, detail="A Render custom-domain ID is required.")
    return (
        f"{_service_domains_path(config.service_id(service_kind))}/"
        f"{quote(domain_id, safe='')}"
    )


def _render_request(
    config: RenderDomainConfig,
    method: str,
    path: str,
    *,
    expected_statuses: set[int],
    json: dict[str, str] | None = None,
    params: dict[str, str | int] | None = None,
    allow_not_found: bool = False,
    ambiguous_write: bool = False,
) -> Any:
    try:
        response = httpx.request(
            method,
            RENDER_API_BASE + path,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Accept": "application/json",
            },
            json=json,
            params=params,
            timeout=RENDER_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
    except httpx.TimeoutException as exc:
        if ambiguous_write:
            detail = (
                "Render did not confirm the domain operation before the request "
                "timed out. Check the Render service's Custom Domains list "
                "before retrying."
            )
        else:
            detail = "Render could not be reached before the request timed out. Retry shortly."
        raise HTTPException(status_code=504, detail=detail) from exc
    except httpx.RequestError as exc:
        if ambiguous_write:
            detail = (
                "Render's response to the domain operation was not received. "
                "Check the Render service's Custom Domains list before retrying."
            )
        else:
            detail = "Render could not be reached. Retry shortly."
        raise HTTPException(status_code=502, detail=detail) from exc

    if response.status_code in expected_statuses:
        if response.status_code in {202, 204} and not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Render returned an invalid response. Check the service's Custom Domains list.",
            ) from exc
    if allow_not_found and response.status_code == 404:
        return None

    status = response.status_code
    if status == 401:
        raise HTTPException(
            status_code=503,
            detail="Render rejected its API key. Check TENALI_RENDER_API_KEY.",
        )
    if status == 403:
        raise HTTPException(
            status_code=503,
            detail="Render denied access. Check the API key's custom-domain permissions and service access.",
        )
    if status == 404:
        raise HTTPException(
            status_code=404,
            detail="Render service or custom domain was not found. Check the configured service ID and stored domain ID.",
        )
    if status == 409:
        raise HTTPException(
            status_code=409,
            detail="Render reports a domain conflict. Refresh the domain list before retrying.",
        )
    if status == 429:
        raise HTTPException(status_code=503, detail="Render rate-limited the domain request. Retry later.")
    if status >= 500:
        if ambiguous_write:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Render did not confirm the domain operation. Check the "
                    "service's Custom Domains list before retrying."
                ),
            )
        raise HTTPException(status_code=503, detail="Render is temporarily unavailable. Retry later.")
    raise HTTPException(
        status_code=422,
        detail=f"Render rejected the domain request (HTTP {status}). Check the hostname and service configuration.",
    )
