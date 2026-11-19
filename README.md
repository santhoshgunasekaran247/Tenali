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

For self-service custom tenant domains while **keeping the static site and API as
two separate Render services**, use the optional automated onboarding described in
[Render tenant domains](docs/MULTI_TENANT_DEPLOYMENT.md#self-service-tenant-domains-on-two-render-services).
It pairs each storefront domain with `api.<storefront-domain>`, provisions Render
hostnames server-side and uses exact-origin credentialed requests. The existing
platform rewrite remains unchanged.

Once `tenali.biz` is connected to the UI and HTTPS is ready, change
`TENALI_PUBLIC_ORIGIN` to `https://tenali.biz`, `TENALI_BASE_DOMAIN` to `tenali.biz`
and `CORS_ORIGINS` to `https://tenali.biz`. Keep `TENALI_API_HOST` unchanged.
Use that canonical UI origin for login; other UI origins are not interchangeable
for authentication. Verify health, login, cookies and authenticated writes after
redeploying. Health alone does not establish database or login readiness.

Keep database, encryption and Supabase storage secrets in the API service's
Render Environment settings, never in the static UI or the repository.

## Inventory and customers

- Online checkout requires both the Add to Cart switch in Payments & Delivery
  Setup and an active Online store linked to an active stock-holding warehouse
  or shop in Stores. The setup status and public availability use the same
  readiness rules; blocked setup links to Stores instead of claiming checkout
  is visible.
- Razorpay mode comes from the keys saved in Tenali, not the dashboard's active
  mode. Replace the key ID and secret together and configure the matching live
  webhook secret when switching to real payments. Run the read-only connection
  check after saving. Provider HTTP errors distinguish authentication, account
  access, validation and availability without exposing provider response bodies
  or credentials. Reconcile uncertain payment attempts before retrying.
- Home and catalogue cards offer Add to Cart when checkout is available. Quick
  add checks current product details and adds the minimum quantity; products
  with variants open their detail page so shoppers can select a size / colour.
  Cart and checkout totals are estimates until the server confirms the quote.

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
