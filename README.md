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

## Inventory and customers

- Inventory has separate Products, Reorder Alerts and Stock check tabs. Stock
  check shows problems first, with optional matching entries and store filtering.
  It compares on-hand balances with recorded activity, not a physical count.
  Missing document evidence does not change stock quantities.
- Product search matches words across names, product IDs, SKUs, brands,
  categories and variant details. Vendor selection and inactive products remain
  separate filters.
- Owners and administrators can delete unused products after typing the product
  code. Stock, movements, enquiries, invoices, purchases, orders and transfer
  history block deletion; make those products inactive instead. Deletion removes
  variants and vendor mappings, but does not delete shared storage objects.
  Apply Alembic migration `033_inventory_product_deletion` before enabling this
  endpoint: it adds DELETE privileges on just products, zero balances and vendor
  mappings to the existing row-level-security-constrained runtime role. The API
  additionally requires an owner/admin identity and blocks business history.
- Online customer accounts are under `/portal/online-customers`, separate from
  Parties. Owner/admin access and explicit identity-confirmed counter-customer
  linking remain required; matching phone numbers never automatically merge users.
