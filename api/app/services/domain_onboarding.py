import asyncio
import logging
import os
import secrets
import http.client
import json
import socket
import ssl
from contextlib import asynccontextmanager

import dns.exception
import dns.resolver
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.core.database import SessionLocal
from app.services.custom_domain_routing import custom_domains_enabled
from app.services.tenant_security import normalize_domain

logger = logging.getLogger(__name__)
DOMAIN_COLUMNS = "id,company_id,hostname,verification_token,verified_at,hosting_status,hosting_error"


def domain_hostnames(hostname):
    if hostname.startswith(("www.", "api.")):
        raise HTTPException(422, "Enter the storefront domain without www. or api.; those hostnames are managed automatically.")
    try:
        api = normalize_domain("api." + hostname)
        return [(normalize_domain(hostname), "web"), (normalize_domain("www." + hostname), "alias"),
                (api, "api"), (normalize_domain("www." + api), "alias")]
    except ValueError as error:
        raise HTTPException(422, "This domain is too long or invalid for its managed API and www hostnames") from error


def validate_custom_hostname(hostname):
    base = os.getenv("TENALI_BASE_DOMAIN", "").lower().strip(".")
    if hostname.endswith(".onrender.com") or (base and (hostname == base or hostname.endswith("." + base))):
        raise HTTPException(422, "Platform and Render domains cannot be claimed as custom domains")
    if custom_domains_enabled():
        domain_hostnames(hostname)


def txt_matches(hostname, token):
    try:
        answers = dns.resolver.resolve("_tenali-verification." + hostname, "TXT", lifetime=5)
        values = [b"".join(answer.strings).decode() for answer in answers]
    except (dns.exception.DNSException, UnicodeDecodeError) as error:
        raise HTTPException(422, "Verification TXT record is not visible yet. Check DNS and try again.") from error
    if token not in values:
        raise HTTPException(422, "DNS ownership token does not match")


def reserve_bindings(db, row):
    # Serialize claims across frontend, API and provider-created aliases.
    db.execute(text("select pg_advisory_xact_lock(604213821)"))
    for hostname, kind in domain_hostnames(row["hostname"]):
        conflict = db.execute(text("""
            select id from tenant_domains
            where hostname=:host and verified_at is not null and id<>:id
        """), {"host": hostname, "id": str(row["id"])}).scalar_one_or_none()
        if conflict:
            raise HTTPException(409, "A required storefront or API hostname is already assigned to another domain")
        db.execute(text("""
            insert into tenant_domain_bindings(hostname,domain_id,kind)
            values(:host,:id,:kind) on conflict(hostname) do nothing
        """), {"host": hostname, "id": str(row["id"]), "kind": kind})
        owner = db.execute(text("select domain_id from tenant_domain_bindings where hostname=:host"),
                           {"host": hostname}).scalar_one()
        if str(owner) != str(row["id"]):
            raise HTTPException(409, "A required storefront or API hostname is already assigned to another domain")


def verify_ownership(db, row):
    txt_matches(row["hostname"], row["verification_token"])
    if custom_domains_enabled():
        reserve_bindings(db, row)
    else:
        db.execute(text("select pg_advisory_xact_lock(604213821)"))
        conflict = db.execute(text("""
            select domain_id from tenant_domain_bindings where hostname=:host and domain_id<>:id
        """), {"host": row["hostname"], "id": str(row["id"])}).scalar_one_or_none()
        if conflict:
            raise HTTPException(409, "This hostname is reserved by another storefront")
        db.execute(text("""
            insert into tenant_domain_bindings(hostname,domain_id,kind) values(:host,:id,'web')
            on conflict(hostname) do nothing
        """), {"host": row["hostname"], "id": str(row["id"])})
    db.execute(text("""
        update tenant_domains set verified_at=coalesce(verified_at,now()),
            hosting_status=:status,hosting_error=null,next_check_at=now() where id=:id
    """), {"id": str(row["id"]), "status": "provisioning" if custom_domains_enabled() else "manual"})


def create_claim(db, company_id, hostname):
    validate_custom_hostname(hostname)
    db.execute(text("""
        insert into tenant_domains(company_id,hostname,verification_token,hosting_status)
        values(:company,:host,:token,:status)
    """), {"company": company_id, "host": hostname, "token": secrets.token_urlsafe(32),
           "status": "dns_pending" if custom_domains_enabled() else "manual"})


def dns_records(hostname, token, web_host, api_host, apex_ip):
    # A records also work for delegated storefront subdomains; no public-suffix guessing.
    return [
        {"type": "TXT", "name": "_tenali-verification." + hostname, "value": token},
        {"type": "A", "name": hostname, "value": apex_ip},
        {"type": "CNAME", "name": "www." + hostname, "value": web_host},
        {"type": "CNAME", "name": "api." + hostname, "value": api_host},
    ]


def https_ready(hostname, target, apex_ip, expected_company=None, redirect_to=None):
    """Pin probes to configured Render addresses, never arbitrary tenant DNS."""
    try:
        addresses = {str(answer) for answer in dns.resolver.resolve(hostname, "A", lifetime=5)}
        allowed = {str(answer) for answer in dns.resolver.resolve(target, "A", lifetime=5)} | {apex_ip}
        if not addresses or not addresses <= allowed:
            raise HTTPException(422, f"DNS for {hostname} does not point to the configured Render hosting")
        with socket.create_connection((sorted(addresses)[0], 443), timeout=5) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname=hostname) as connection:
                path = "/api/auth/domain-health" if expected_company else "/"
                connection.sendall(f"GET {path} HTTP/1.1\r\nHost: {hostname}\r\nConnection: close\r\n\r\n".encode("ascii"))
                response = http.client.HTTPResponse(connection)
                response.begin()
                if redirect_to:
                    if response.status not in {301, 302, 307, 308} or response.getheader("Location", "").rstrip("/") != "https://" + redirect_to:
                        raise HTTPException(422, f"The www redirect for {redirect_to} is not ready yet")
                elif response.status != 200:
                    raise HTTPException(422, f"HTTPS routing for {hostname} is not ready yet")
                if expected_company:
                    body = json.loads(response.read(8192))
                    if not isinstance(body, dict) or body.get("company_id") != str(expected_company):
                        raise HTTPException(422, "API domain does not resolve to the expected tenant")
    except (dns.exception.DNSException, OSError, ssl.SSLError, http.client.HTTPException, ValueError) as error:
        raise HTTPException(422, f"DNS or HTTPS for {hostname} is not ready yet. Tenali will retry automatically.") from error


def save_provider_binding(db, domain_id, binding, owned):
    result = db.execute(text("""
        update tenant_domain_bindings set render_id=:remote,
            provider_owned=provider_owned or :owned where domain_id=:id and hostname=:host
        returning hostname
    """), {"id": str(domain_id), "host": binding.hostname, "remote": binding.id, "owned": owned}).scalar_one_or_none()
    if result is None:
        raise HTTPException(409, "Render returned an unreserved alias. Contact the platform administrator.")


def schedule(db, domain_id, status, seconds=60):
    db.execute(text("""
        update tenant_domains set hosting_status=:status,hosting_error=null,
            next_check_at=now()+make_interval(secs=>:seconds) where id=:id
    """), {"id": str(domain_id), "status": status, "seconds": seconds})


def provision_hosting(db, row):
    from app.services import render_domains as render
    config = render.get_config()
    if config is None:
        raise HTTPException(503, "Automatic Render hosting is not configured")
    bindings = db.execute(text("""
        select hostname,kind,render_id,provider_owned from tenant_domain_bindings
        where domain_id=:id order by hostname
    """), {"id": str(row["id"])}).mappings().all()
    ready = True
    for kind in ("web", "api"):
        binding = next((item for item in bindings if item["kind"] == kind), None)
        if binding is None:
            raise HTTPException(409, "Domain hostname reservations are missing. Verify ownership again.")
        if not binding["render_id"]:
            if not binding["provider_owned"]:
                existing = render.find_custom_domain(config, kind, binding["hostname"])
                if existing:
                    # Preserve external registrations instead of silently taking ownership.
                    result = render.ensure_custom_domain(config, kind, binding["hostname"])
                    save_provider_binding(db, row["id"], result.domain, result.provider_owned)
                    for alias in result.aliases:
                        save_provider_binding(db, row["id"], alias, alias.created_by_this_call)
                else:
                    alias_host = "www." + binding["hostname"]
                    alias_binding = next((item for item in bindings if item["hostname"] == alias_host), None)
                    if alias_binding and not alias_binding["render_id"] and not alias_binding["provider_owned"]:
                        alias = render.find_custom_domain(config, kind, alias_host)
                        db.execute(text("""
                            update tenant_domain_bindings set render_id=:remote,provider_owned=:owned
                            where domain_id=:id and hostname=:host
                        """), {"id": str(row["id"]), "host": alias_host,
                               "remote": alias.id if alias else None, "owned": alias is None})
                    db.execute(text("""
                        update tenant_domain_bindings set provider_owned=true
                        where domain_id=:id and hostname=:host
                    """), {"id": str(row["id"]), "host": binding["hostname"]})
                # Commit registration intent before any external write, including uncertain responses.
                schedule(db, row["id"], "provisioning", 0)
                return
            result = render.ensure_custom_domain(config, kind, binding["hostname"])
            save_provider_binding(db, row["id"], result.domain, True)
            for alias in result.aliases:
                previous = next((item for item in bindings if item["hostname"] == alias.hostname), None)
                owned = bool(previous and (previous["provider_owned"] or (
                    not previous["render_id"] and alias.created_by_this_call
                )))
                save_provider_binding(db, row["id"], alias, owned)
            schedule(db, row["id"], "provisioning", 0)
            return
        try:
            status = render.get_custom_domain_status(config, kind, binding["render_id"])
        except HTTPException as error:
            if error.status_code != 404:
                raise
            db.execute(text("""
                update tenant_domain_bindings set render_id=null where domain_id=:id and hostname=:host
            """), {"id": str(row["id"]), "host": binding["hostname"]})
            schedule(db, row["id"], "provisioning", 0)
            return
        if status.hostname != binding["hostname"]:
            raise HTTPException(409, "Render domain identity changed. Contact the platform administrator.")
        if not status.ready:
            render.verify_custom_domain(config, kind, binding["render_id"])
            ready = False
    schedule(db, row["id"], "tls_pending")
    if not ready:
        return
    try:
        https_ready(row["hostname"], config.web_host, config.apex_ip)
        https_ready("api." + row["hostname"], config.api_host, config.apex_ip, row["company_id"])
        https_ready("www." + row["hostname"], config.web_host, config.apex_ip, redirect_to=row["hostname"])
    except HTTPException as error:
        if error.status_code != 422:
            raise
        db.execute(text("update tenant_domains set hosting_error=:error where id=:id"),
                   {"id": str(row["id"]), "error": str(error.detail)})
        logger.info("Custom-domain job %s waiting for DNS/HTTPS", row["id"])
        return
    schedule(db, row["id"], "active")


def remove_hosting(db, row):
    from app.services import render_domains as render
    config = render.get_config()
    if config is None:
        raise HTTPException(503, "Automatic Render hosting is not configured")
    bindings = db.execute(text("""
        select hostname,kind,render_id,provider_owned from tenant_domain_bindings
        where domain_id=:id order by (kind='alias') desc,hostname
    """), {"id": str(row["id"])}).mappings().all()
    for binding in bindings:
        if not binding["provider_owned"]:
            if binding["render_id"]:
                logger.warning("Retaining externally managed Render hostname %s on domain removal", binding["hostname"])
            continue
        kind = "api" if binding["hostname"] in {"api." + row["hostname"], "www.api." + row["hostname"]} else "web"
        remote_id = binding["render_id"]
        if not remote_id:
            existing = render.find_custom_domain(config, kind, binding["hostname"])
            remote_id = existing.id if existing else None
        if remote_id:
            render.delete_custom_domain(config, kind, remote_id, binding["hostname"], provider_owned=True)
    db.execute(text("delete from tenant_domains where id=:id"), {"id": str(row["id"])})


async def provision_loop():
    while True:
        try:
            await run_in_threadpool(process_due_domains)
        except Exception:
            logger.exception("Custom-domain provisioning batch failed")
        await asyncio.sleep(30)


@asynccontextmanager
async def domain_lifespan(_app):
    task = None
    if custom_domains_enabled():
        from app.services.render_domains import get_config
        if get_config() is None:
            raise RuntimeError("Custom domains require the Render provisioning configuration")
        task = asyncio.create_task(provision_loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def process_due_domains():
    # The row lock makes jobs safe across multiple API workers and deployments.
    for _ in range(10):
        with SessionLocal() as db:
            row = db.execute(text(f"""
                select {DOMAIN_COLUMNS} from tenant_domains
                where hosting_status not in ('manual','active') and next_check_at<=now()
                order by next_check_at limit 1 for update skip locked
            """)).mappings().first()
            if not row:
                return
            try:
                with db.begin_nested():
                    if row["hosting_status"] == "removing":
                        remove_hosting(db, row)
                    else:
                        if not row["verified_at"]:
                            verify_ownership(db, row)
                        else:
                            provision_hosting(db, row)
            except HTTPException as error:
                db.execute(text("""
                    update tenant_domains set hosting_error=:error,next_check_at=now()+interval '60 seconds'
                    where id=:id
                """), {"id": str(row["id"]), "error": str(error.detail)})
                logger.warning("Custom-domain job %s pending: %s", row["id"], error.detail)
            except IntegrityError:
                db.execute(text("""
                    update tenant_domains set hosting_status='error',
                    hosting_error='A required domain is already assigned. Contact the platform administrator.',
                    next_check_at=now()+interval '10 minutes' where id=:id
                """), {"id": str(row["id"])})
                logger.warning("Custom-domain job %s has a conflicting claim", row["id"])
            db.commit()
