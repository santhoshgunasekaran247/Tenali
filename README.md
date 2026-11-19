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
- Cart, checkout summaries and shopper/staff orders show product thumbnails and
  linked names that open the product page with the selected variant. Order images
  use the current catalogue; unavailable images show a placeholder without
  changing the order's saved quantities or prices.
- After Razorpay checkout, the browser confirms payment with the server and
  watches the shopper-owned order status for webhook updates. A lost callback
  triggers server-side reconciliation after three minutes; verification
  requests time out after 30 seconds instead of leaving checkout spinning.
  Cart items are removed and My Orders opens only after server-verified payment.
  If verification remains uncertain, use My Orders / Verify Payment before
  paying again. Leaving checkout cancels its browser-side polling.
- For prepaid orders, configure a settlement (Razorpay clearing) account on the
  Online store in Stores. A captured payment remains paid if advance posting is
  blocked; Online Orders shows the reason and allows staff to retry after fixing
  the account or accounting period. Retry only reports success once the advance
  exists and does not charge the shopper again. Dispatch requires that advance.
  Staff ledger attribution uses the tenant audit trail, not the legacy
  user-profile field on account transactions.
- Shiprocket delivery orders must be submitted to Shiprocket (package weight and
  dimensions are entered on each order card) before Dispatch & invoice unlocks.
  Orders dispatched (or marked delivered) before this rule can still be submitted,
  or recovered with their Shiprocket order ID; they return to dispatched without
  touching the invoice or stock. Mark delivered also waits for a Shiprocket
  booking and asks for confirmation. When Shiprocket rejects a submission (HTTP
  4xx) nothing is created: the order is restored, the rejected field names are
  shown, and it can be corrected and resubmitted. A timeout or 5xx is
  unconfirmed and must be recovered; if the Tenali order ID is not in
  Shiprocket, staff can use "Not in Shiprocket: allow resubmission" to retry.

- Inventory has separate Products, Reorder Alerts and Stock check tabs. Stock
  check shows problems first, with optional matching entries and store filtering.
  It compares on-hand balances with recorded activity, not a physical count.
  Missing document evidence does not change stock quantities.
- Billing keeps document creation on the left and stacks quotations, invoices
  and reconciliation history in the wider right column. On smaller screens the
  records follow the form; wide invoice tables scroll within their card.
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
