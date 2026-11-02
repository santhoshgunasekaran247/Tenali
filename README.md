# Tenali Web

This folder contains the web application structure for the project.

## Separate Render UI and API (native runtimes)

The UI uses relative `/api` requests. On the free Render Static Site, configure
these rules as **Rewrite**, not Redirect, in this order:

1. `/api/*` -> `https://tenali-api.onrender.com/api/*`
2. `/*` -> `/index.html`

For the paid Python API service, configure these environment variables for the
current temporary UI hostname:

```text
TENALI_ENV=production
TENALI_API_HOST=tenali-api.onrender.com
TENALI_PUBLIC_ORIGIN=https://tenali-web-dq3a.onrender.com
TENALI_BASE_DOMAIN=tenali-web-dq3a.onrender.com
CORS_ORIGINS=https://tenali-web-dq3a.onrender.com
```

`TENALI_API_HOST` and `TENALI_PUBLIC_ORIGIN` are opt-in and must be set together.
Only requests to that exact API hostname are mapped to the configured public
origin before tenant, login and CSRF validation. Caller-supplied forwarding
headers cannot select the public origin. This is deployment routing, not API
authentication: protected endpoints still require the appropriate session and
write protection. Leave both variables unset for existing same-host deployments.

Use `/platform` for platform administrators and `/c/<tenant-slug>` for workspace
storefronts. This fixed-origin rewrite supports one public UI origin and path-based
workspace selection; it does not forward arbitrary tenant/custom domain identity.
Do not treat tenant subdomains or custom storefront domains as supported by this
configuration without separate routing verification.

Once `tenali.biz` is connected to the UI and HTTPS is ready, change
`TENALI_PUBLIC_ORIGIN` to `https://tenali.biz`, `TENALI_BASE_DOMAIN` to `tenali.biz`
and `CORS_ORIGINS` to `https://tenali.biz`. Keep `TENALI_API_HOST` unchanged.
Use that canonical UI origin for login; other UI origins are not interchangeable
for authentication. Verify health, login, cookies and authenticated writes after
redeploying. Health alone does not establish database or login readiness.

Keep database, encryption and Supabase storage secrets in the API service's
Render Environment settings, never in the static UI or the repository.
