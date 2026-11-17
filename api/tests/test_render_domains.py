import unittest
from unittest.mock import patch

from fastapi import HTTPException
import httpx

from app.services import render_domains


CONFIG = render_domains.RenderDomainConfig(
    api_key="render-test-secret",
    web_service_id="srv-web",
    api_service_id="srv-api",
    web_host="tenali-web.onrender.com",
    api_host="tenali-api.onrender.com",
)


def render_domain(
    domain_id: str,
    name: str,
    *,
    redirect_for_name: str = "",
    verification_status: str = "unverified",
) -> dict[str, str]:
    return {
        "id": domain_id,
        "name": name,
        "domainType": "apex" if len(name.split(".")) == 2 else "subdomain",
        "publicSuffix": name.split(".")[-1],
        "verificationStatus": verification_status,
        "createdAt": "2026-01-01T00:00:00Z",
        "redirectForName": redirect_for_name,
    }


def response(status: int, payload=None) -> httpx.Response:
    return httpx.Response(status, json=payload)


class RenderDomainTests(unittest.TestCase):
    def test_config_is_disabled_only_when_all_required_values_are_missing(self):
        env = {name: "" for name in render_domains._REQUIRED_ENV}
        with patch.dict("os.environ", env, clear=True):
            self.assertIsNone(render_domains.get_render_domain_config())

        env["TENALI_RENDER_API_KEY"] = "secret"
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(HTTPException) as error:
                render_domains.get_render_domain_config()
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("secret", str(error.exception.detail))

    def test_config_validates_render_cname_targets_and_defaults_apex_ip(self):
        env = {
            "TENALI_RENDER_API_KEY": "secret",
            "TENALI_RENDER_WEB_SERVICE_ID": "web",
            "TENALI_RENDER_API_SERVICE_ID": "api",
            "TENALI_RENDER_WEB_HOST": "Web-Site.onrender.com",
            "TENALI_RENDER_API_HOST": "api-site.onrender.com",
        }
        with patch.dict("os.environ", env, clear=True):
            config = render_domains.get_render_domain_config()
        self.assertEqual(config.web_host, "web-site.onrender.com")
        self.assertEqual(config.apex_ip, "216.24.57.1")

        env["TENALI_RENDER_WEB_HOST"] = "attacker.example"
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(HTTPException):
                render_domains.get_render_domain_config()

    def test_provision_lists_before_add_and_exposes_render_www_alias(self):
        root = render_domain("dom-root", "sourcedbysru.in")
        www = render_domain("dom-www", "www.sourcedbysru.in", redirect_for_name="sourcedbysru.in")
        api = render_domain("dom-api", "api.sourcedbysru.in")
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "GET" and "srv-web" in url:
                return response(200, [])
            if method == "POST" and "srv-web" in url:
                return response(201, [root, www])
            if method == "GET" and "srv-api" in url:
                return response(200, [])
            if method == "POST" and "srv-api" in url:
                return response(201, [api])
            self.fail(f"Unexpected Render request: {method} {url}")

        with patch.object(render_domains.httpx, "request", side_effect=fake_request):
            result = render_domains.provision_tenant_domains(CONFIG, "SourcedBySru.in")

        self.assertEqual(
            [method for method, _, _ in calls],
            ["GET", "POST", "GET", "POST"],
        )
        self.assertEqual(result.frontend_hostname, "sourcedbysru.in")
        self.assertEqual(result.api_hostname, "api.sourcedbysru.in")
        self.assertEqual({domain.hostname for domain in result.aliases}, {"www.sourcedbysru.in"})
        self.assertTrue(all(domain.created_by_this_call for domain in result.domains))
        self.assertTrue(all(domain.id for domain in result.domains))
        for _, _, kwargs in calls:
            self.assertEqual(kwargs["timeout"], render_domains.RENDER_TIMEOUT_SECONDS)
        self.assertEqual(calls[0][2]["headers"]["Authorization"], "Bearer render-test-secret")

    def test_existing_domains_are_reported_but_not_marked_owned(self):
        frontend = render_domain("manual-front", "sourcedbysru.in")
        www = render_domain("manual-www", "www.sourcedbysru.in", redirect_for_name="sourcedbysru.in")
        api = render_domain("manual-api", "api.sourcedbysru.in")

        def fake_request(method, url, **_kwargs):
            self.assertEqual(method, "GET")
            return response(
                200,
                [{"customDomain": item, "cursor": f"cursor-{item['id']}"} for item in
                 ([frontend, www] if "srv-web" in url else [api])],
            )

        with patch.object(render_domains.httpx, "request", side_effect=fake_request) as request:
            result = render_domains.provision_tenant_domains(CONFIG, "sourcedbysru.in")

        self.assertEqual(request.call_count, 2)
        self.assertEqual({domain.hostname for domain in result.domains}, {
            "sourcedbysru.in", "www.sourcedbysru.in", "api.sourcedbysru.in"
        })
        self.assertTrue(all(domain.found_before_write for domain in result.domains))
        self.assertFalse(any(domain.created_by_this_call for domain in result.domains))

    def test_list_paginates_using_render_item_cursor(self):
        first = render_domain("dom-one", "sourcedbysru.in")
        second = render_domain("dom-two", "www.sourcedbysru.in", redirect_for_name="sourcedbysru.in")
        api = render_domain("dom-api", "api.sourcedbysru.in")
        cursors = []

        def fake_request(_method, url, **kwargs):
            if "srv-web" in url:
                cursors.append(kwargs["params"].get("cursor"))
                if len(cursors) == 1:
                    page = [{"customDomain": first, "cursor": "first"}]
                    page.extend(
                        {
                            "customDomain": render_domain(f"unrelated-{index}", f"other{index}.example.com"),
                            "cursor": f"cursor-{index}",
                        }
                        for index in range(1, 99)
                    )
                    page.append({"customDomain": render_domain("last", "last.example.com"), "cursor": "next-page"})
                    return response(200, page)
                return response(200, [{"customDomain": second, "cursor": ""}])
            return response(200, [{"customDomain": api, "cursor": ""}])

        with patch.object(render_domains.httpx, "request", side_effect=fake_request):
            result = render_domains.provision_tenant_domains(CONFIG, "sourcedbysru.in")

        self.assertEqual(cursors, [None, "next-page"])
        self.assertEqual({domain.hostname for domain in result.domains}, {
            "sourcedbysru.in", "www.sourcedbysru.in", "api.sourcedbysru.in"
        })

    def test_www_frontend_is_rejected_before_render_requests(self):
        with patch.object(render_domains.httpx, "request") as request:
            with self.assertRaises(HTTPException) as error:
                render_domains.provision_tenant_domains(CONFIG, "www.sourcedbysru.in")
        self.assertEqual(error.exception.status_code, 422)
        request.assert_not_called()

    def test_timeout_after_add_is_actionable_and_not_retried(self):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(method)
            if method == "GET":
                return response(200, [])
            raise httpx.ReadTimeout("sensitive request context")

        with patch.object(render_domains.httpx, "request", side_effect=fake_request):
            with self.assertRaises(HTTPException) as error:
                render_domains.provision_tenant_domains(CONFIG, "sourcedbysru.in")

        self.assertEqual(error.exception.status_code, 504)
        self.assertIn("Check the Render service's Custom Domains list", error.exception.detail)
        self.assertNotIn("sensitive", str(error.exception.detail))
        self.assertEqual(calls, ["GET", "POST"])

    def test_server_error_after_write_warns_to_reconcile_before_retry(self):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(method)
            if method == "GET":
                return response(200, [])
            return response(500, {"message": "render-test-secret"})

        with patch.object(render_domains.httpx, "request", side_effect=fake_request):
            with self.assertRaises(HTTPException) as error:
                render_domains.provision_tenant_domains(CONFIG, "sourcedbysru.in")

        self.assertEqual(error.exception.status_code, 503)
        self.assertIn("Check the service's Custom Domains list", error.exception.detail)
        self.assertNotIn("render-test-secret", str(error.exception.detail))
        self.assertEqual(calls, ["GET", "POST"])

    def test_verify_and_status_use_selected_service_and_persisted_id(self):
        domain = render_domain("domain-id", "api.sourcedbysru.in", verification_status="verified")
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url))
            if method == "POST":
                return response(202)
            return response(200, domain)

        with patch.object(render_domains.httpx, "request", side_effect=fake_request):
            render_domains.verify_tenant_domain(CONFIG, "api", "domain-id")
            status = render_domains.get_tenant_domain_status(CONFIG, "api", "domain-id")

        self.assertEqual(status.verification_status, "verified")
        self.assertTrue(all("srv-api" in url for _, url in calls))
        self.assertTrue(calls[0][1].endswith("/domain-id/verify"))

    def test_delete_requires_persisted_ownership_and_is_idempotent_if_missing(self):
        with patch.object(render_domains.httpx, "request") as request:
            with self.assertRaises(HTTPException) as error:
                render_domains.delete_tenant_domain(
                    CONFIG,
                    "web",
                    "manual-domain",
                    expected_hostname="example.com",
                    created_by_tenant_flow=False,
                )
        self.assertEqual(error.exception.status_code, 409)
        request.assert_not_called()

        with patch.object(
            render_domains.httpx,
            "request",
            side_effect=[response(404), response(404)],
        ) as request:
            render_domains.delete_tenant_domain(
                CONFIG,
                "web",
                "owned-domain",
                expected_hostname="example.com",
                created_by_tenant_flow=True,
            )
        self.assertEqual(request.call_args_list[0].args[0], "GET")
        self.assertIn("owned-domain", request.call_args_list[0].args[1])
        self.assertEqual(request.call_count, 1)

    def test_delete_checks_expected_hostname_before_deleting(self):
        manual = render_domain("owned-id", "different.example.com")
        with patch.object(render_domains.httpx, "request", return_value=response(200, manual)) as request:
            with self.assertRaises(HTTPException) as error:
                render_domains.delete_custom_domain(
                    CONFIG,
                    "web",
                    "owned-id",
                    "expected.example.com",
                    provider_owned=True,
                )
        self.assertEqual(error.exception.status_code, 409)
        request.assert_called_once()

    def test_ensure_custom_domain_exposes_created_alias_and_ready_status(self):
        root = render_domain("root-id", "example.com", verification_status="verified")
        www = render_domain("www-id", "www.example.com", redirect_for_name="example.com")

        def fake_request(method, url, **kwargs):
            if method == "GET":
                return response(200, [])
            return response(201, [root, www])

        with patch.object(render_domains.httpx, "request", side_effect=fake_request):
            result = render_domains.ensure_custom_domain(CONFIG, "api", "example.com")

        self.assertEqual(result.id, "root-id")
        self.assertEqual(result.hostname, "example.com")
        self.assertTrue(result.ready)
        self.assertTrue(result.provider_owned)
        self.assertEqual([alias.hostname for alias in result.aliases], ["www.example.com"])
        self.assertTrue(all(alias.created_by_this_call for alias in result.aliases))
        self.assertTrue(all(alias.provider_owned for alias in result.aliases))

    def test_find_custom_domain_is_exact_read_only_and_marks_existing_unowned(self):
        desired = render_domain("existing-id", "api.example.com", verification_status="verified")
        unrelated = render_domain("unrelated-id", "other.example.com")
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return response(
                200,
                [
                    {"customDomain": unrelated, "cursor": "other"},
                    {"customDomain": desired, "cursor": ""},
                ],
            )

        with patch.object(render_domains.httpx, "request", side_effect=fake_request):
            found = render_domains.find_custom_domain(CONFIG, "api", "API.Example.com.")
            missing = render_domains.find_custom_domain(CONFIG, "api", "missing.example.com")

        self.assertEqual(found.id, "existing-id")
        self.assertEqual(found.hostname, "api.example.com")
        self.assertTrue(found.found_before_write)
        self.assertFalse(found.provider_owned)
        self.assertTrue(found.ready)
        self.assertIsNone(missing)
        self.assertTrue(all(method == "GET" for method, _, _ in calls))
        self.assertTrue(all("srv-api" in url for _, url, _ in calls))

    def test_ensure_returns_aliases_for_a_preexisting_exact_domain(self):
        root = render_domain("existing-root", "example.com")
        www = render_domain("existing-www", "www.example.com", redirect_for_name="example.com")
        api = render_domain("existing-api", "api.example.com")

        def fake_request(_method, url, **_kwargs):
            entries = [root, www] if "srv-web" in url else [api]
            return response(
                200,
                [{"customDomain": entry, "cursor": ""} for entry in entries],
            )

        with patch.object(render_domains.httpx, "request", side_effect=fake_request):
            result = render_domains.ensure_custom_domain(CONFIG, "web", "example.com")

        self.assertEqual(result.id, "existing-root")
        self.assertFalse(result.provider_owned)
        self.assertEqual(len(result.aliases), 1)
        self.assertEqual(result.aliases[0].hostname, "www.example.com")
        self.assertFalse(result.aliases[0].provider_owned)
        self.assertTrue(result.aliases[0].found_before_write)

    def test_render_errors_do_not_leak_api_key_or_response_body(self):
        with patch.object(
            render_domains.httpx,
            "request",
            return_value=httpx.Response(401, text="render-test-secret"),
        ):
            with self.assertRaises(HTTPException) as error:
                render_domains.get_tenant_domain_status(CONFIG, "web", "domain-id")
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("render-test-secret", str(error.exception.detail))

    def test_invalid_hostnames_are_rejected(self):
        for hostname in [
            "",
            "http://example.com",
            "*.example.com",
            "localhost",
            "bad..example.com",
            "127.0.0.1",
        ]:
            with self.subTest(hostname=hostname):
                with self.assertRaises((HTTPException, ValueError)):
                    render_domains.provision_tenant_domains(CONFIG, hostname)


if __name__ == "__main__":
    unittest.main()
