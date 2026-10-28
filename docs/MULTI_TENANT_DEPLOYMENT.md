# Multi-tenant application

## Customer flow

1. Open the platform `/register`, create a company/workspace address and owner login.
2. The company starts with its own categories and no products, stock, accounts,
   invoices, files or vendor records copied from another company.
3. Configure company details, branding and tax data, then add vendors/products/accounts.
4. The storefront is available at `/c/<workspace-address>` locally or on the platform.
   With a platform base domain and wildcard DNS, `<workspace>.<base-domain>` resolves
   the same company. An authenticated user can create another workspace and switch
   only among their memberships.
5. Owners/admins add team members, assign admin/staff/read-only roles, and deactivate
   access. Temporary passwords must be shared privately; members change them under
   Account. Changing a password revokes the user's other sessions.
6. Under Domains, add a hostname and publish its TXT ownership challenge. The app
   activates it only after successful DNS verification. Platform routing and HTTPS
   still need the deployment configuration below.

Company Setup controls the public display name, storefront address, logo, theme and
customer-facing text for navigation, home, catalogue and product pages. The URL uses
the editable workspace address rather than the registered company name. Changing it
keeps the previous path as an alias and directs visitors to the current address.

The storefront exposes the existing product catalog/enquiry workflow. This change
does not add shopping-cart checkout, shipping calculation or payment-gateway collection.

## Local development

- Start the API from the repository root with `.venv/Scripts/python -m uvicorn
  app.main:app --app-dir api --env-file api/.env --host 127.0.0.1 --port 8000`.
- Start Vite normally. Vite proxies `/api` to the API while preserving Host.
- The browser always uses same-origin `/api`, including CSVs, files and shared images.
- Signup/login work on localhost without DNS or email-provider setup. There is no
  authentication bypass and no HTTP fallback to the first company.
- Do not deploy the Vite development server publicly.

## Existing company owner

Public registration cannot claim an existing company. Existing company slugs are
`legacy-<company UUID without dashes>`. An administrator with database access runs:

```powershell
Set-Location api
..\.venv\Scripts\python.exe -m app.bootstrap_owner --company-id <UUID> --email <owner-email> --name <owner-name>
```

Alternatively run with `api` on `PYTHONPATH` from the repository root.
The command prompts privately for the password twice. Do not put passwords in command
arguments or chat. It refuses to overwrite an existing owner or existing email account.

## Production environment

Configure these on the API process, not in browser JavaScript:

```text
TENALI_ENV=production
TENALI_BASE_DOMAIN=your-platform-domain.com
TENALI_DOMAIN_TARGET=app.your-platform-domain.com
```

Configure platform apex/app DNS and wildcard tenant DNS to the reverse proxy. Customer
subdomains normally CNAME to `TENALI_DOMAIN_TARGET`. Apex domains may require provider
ALIAS/ANAME support. Do not claim TLS readiness merely because TXT ownership verified.

`config/Caddyfile.example` shows same-origin API/static routing and on-demand TLS.
Set `ACME_EMAIL` and `TENALI_WEB_ROOT` on Caddy, provide ports 80/443 and DNS access,
and run the API bound to loopback. Caddy asks `/domain-authorization` before issuing
certificates, allowing only configured platform hosts, real workspace subdomains and
verified customer domains. Keep the proxy's preserved Host and strip untrusted
forwarded headers; trust proxy headers only from the actual local proxy.

Database migrations need a privileged migration connection able to create policies,
functions and the non-login `tenali_runtime` role and grant membership. Business
requests SET LOCAL ROLE and tenant/actor settings on every transaction. RLS restricts
all tenant-owned operational tables; relationship triggers reject cross-tenant foreign
IDs and variant/product mismatches. Authentication/registration use a separate code
path with privileged identity access. Do not use the runtime role as a migration user.

Sessions are opaque, stored hashed, host-only HttpOnly cookies, SameSite=Lax, Secure in
production and expire in 12 hours. Unsafe requests require same-origin CSRF protection.
Changing roles/deactivating membership revokes that company's sessions for the member.

## Verification and release gates

Use `api/requirements-dev.txt` for tests. `TENALI_TEST_DB=1` enables rollback-only tenant
HTTP/RLS tests covering unauthenticated access, company overrides, record tampering,
cross-company foreign keys, read-only roles, CSRF, domain ownership and revocation.
No customer identities or business data should be retained by those tests.

Real DNS propagation, certificate issuance and internet-host routing require deployment
and domain ownership; they cannot be proved by localhost tests alone. Before a paid
public launch, add verified-email onboarding, expiring email invitations and provider-
backed forgotten-password recovery, monitoring, recovery-tested backups and an
independent security review. Current team creation deliberately refuses to overwrite
or attach an already-registered email without a verified invitation workflow.

Only branding/product catalog fields are public. Company settings, signature images,
documents, vendor contacts, buying prices, financial data and audits require membership.
Each new tenant needs its real GST/master data; demo tax classifications are not copied.