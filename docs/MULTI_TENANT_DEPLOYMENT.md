# Multi-tenant application

## Customer flow

1. Open the platform `/register`, create a company/workspace address and owner login.
2. The company starts with its own categories and no products, stock, accounts,
   invoices, files or vendor records copied from another company.
3. Configure company details, branding and tax data, then add vendors/products/accounts.
4. The storefront is available at `/c/<workspace-address>` locally or on the platform.
   With a platform base domain and wildcard DNS, `<workspace>.<base-domain>` resolves
   the same company. Staff sign in to a specific workspace. The same email can have
   independent credentials in different workspaces; sessions cannot switch companies.
   Creating another workspace requires a new workspace password.
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

## Shopper accounts and checkout

The storefront's **Shopper Account** opens `/account`, with store-specific signup at
`/account/register`. These identities and cookies are separate from workspace staff
(`/login`) and platform operators (`/platform`). A shopper account in one workspace
cannot access another workspace or any operational API, even with the same email.

Owners/admins open **Shopper Checkout & Orders** at `/portal/checkout`, now presented
as **Payments, Delivery & Shopper Orders** with **Setup & activation** and **Manage
orders** views. The guided setup covers account/KYC links, API keys, webhook delivery,
pickup configuration, testing and the separate storefront visibility switch.
Checkout is disabled until configured. Each workspace supplies its own Razorpay key
ID/secret/webhook secret and dedicated Shiprocket API-user email/password. Credentials
are encrypted with Fernet using a server-only `TENALI_CREDENTIAL_KEY`, bound to the
company, never returned by settings APIs, and snapshotted per order. Do not log request
bodies for provider settings or authentication. Use HTTPS even for administrator setup.

On the first save, all provider credentials are required. On later saves, leave
credential fields blank to keep their saved values. Replace the Razorpay key ID and
secret together, or the Shiprocket API email/password together; a webhook secret can
be replaced independently. Changing shipping or switching Add to Cart off does not
require re-entering secrets. The UI accepts shipping in **rupees** and converts to
integer paise on the API. The settings response reports only the saved key mode
(`test`/`live`) and non-secret settings; neither prefix nor enabled status proves
provider approval.

**Check Razorpay connection** reads `/v1/orders?count=1` with the saved keys.
**Check Shiprocket connection** authenticates the API user and reads the pickup
locations, requiring the exact saved location name. These admin-only, CSRF-protected,
rate-limited checks are workspace-scoped and do not create payments, orders or
shipments. Results explicitly report failure or pass, with a timestamp for this
session; edits invalidate the displayed checks and must be saved before rechecking.
Checks do **not** establish KYC approval, webhook delivery, settlement readiness,
wallet balance, pickup approval or delivery serviceability. Confirm those in the
provider dashboards and complete an end-to-end payment test.

KYC documents go directly to the respective provider, not to this settings form.
Razorpay requirements depend on the business type and include its requested business,
identity and bank verification. Public website review includes contact, pricing,
terms, privacy and refund information; this form does not create legal-policy pages.
Use **Store Policies** (`/portal/policies`) to draft, preview and explicitly publish
those documents separately, as described below.
Use a dedicated **shopper** reviewer login if requested, never workspace/admin access.
Its API-key guide states website review within 3 working days; this is not a guaranteed
overall account-activation SLA. Shiprocket's KYC guide states manual review may take
2-3 business days. Approval and pending-document requests remain provider-controlled.

Official references:
- [Razorpay KYC](https://razorpay.com/docs/payments/kyc/)
- [Razorpay API keys and Test/Live modes](https://razorpay.com/docs/payments/dashboard/account-settings/api-keys/)
- [Razorpay website review](https://razorpay.com/docs/payments/dashboard/account-settings/business-website-details/)
- [Shiprocket KYC](https://support.shiprocket.in/support/solutions/articles/43000662578-what-documents-are-required-for-kyc-verification-)
- [Shiprocket API-user setup](https://support.shiprocket.in/support/solutions/articles/43000337456-shiprocket-api-document-helpsheet)

### Turning a storefront off

Owners and admins can switch **Storefront open to the public** off in Company Setup
(`companies.storefront_enabled`, revision `036_storefront_enabled`; existing
workspaces stay open). Apply that revision before deploying the API, because the
public company endpoint reads the column.

While the storefront is off:

- Visitors see an "unavailable" page with the store's contact details instead of
  the home, brand, product, cart and checkout pages. Catalog navigation and the
  cart link are hidden.
- `/catalog/home`, `/catalog/list`, `/catalog/products/*`, `/shop/availability`,
  `/shop/nearby`, `/shop/enquiries`, `/shop/quote` and `POST /shop/orders` return
  403 "This storefront is currently unavailable".
- `/catalog/company` still answers (it reports `storefront_enabled`), and these
  keep working: public store policies, shopper sign-in and existing order tracking,
  payment confirmation and Razorpay webhooks for orders already placed, and the
  Operations Portal.

Omitting `storefront_enabled` from a company update keeps the current setting.

### Purchase bills, stock and draft products

Apply revision `037_product_drafts` (`products.is_draft`, default false) before
deploying the API, because line resolution and the inventory list read it.

- **HSN on products without one:** a sales or purchase line for a product with no
  HSN/SAC uses the active code chosen on the line, and that code is saved to the
  product. Products that already have a code always use their own.
- **New items on a purchase bill:** choose "New item - add to inventory as draft".
  Posting creates a product named after the line description, with the chosen
  HSN, mapped to the bill's vendor at the line's taxable unit rate. It is hidden
  from the storefront. A name matching an active product is rejected with 409, so
  the existing product is picked instead. Drafts can be bought again but cannot be
  sold or made visible on the storefront until **Confirm product** is used in
  Product Inventory (`POST /inventory/products/{id}/confirm`).
- **Merging a draft:** owners and admins can instead merge a draft into an
  existing active product (`POST /inventory/products/{id}/merge` with
  `target_product_id`, plus `target_variant_id` when the target has active
  variants). Store balances are added to the target, and stock movements and
  purchase/transfer lines are re-pointed, so later receipts and cancellations act
  on the target. Vendor offers move across unless the target already has an offer
  from that vendor (the existing offer is kept). The target's empty HSN and
  preferred vendor are filled from the draft. The draft is then deleted.
- **Manual / service lines** never touch stock.
- **Goods received now** (`received_now`, unticked by default) books product lines
  into the posting store's stock and marks the bill RECEIVED in the same
  transaction. It is ignored for SERVICE bills. Otherwise stock is added when the
  receipt is confirmed later.
- **Transfers from a product:** the product's Owned Stock tab has **Transfer
  between stores** when the tenant has two or more stock stores and the product
  has stock. It opens the stock transfer dialog with the product on the first
  line and the store holding the most of it as the source.
- **Reorder alerts** only appear when alerts are enabled on the product or
  variant and stock is at or below the reorder level. Entering a level in the
  editor turns alerts on and raises the target to at least the level; a level
  with alerts off is flagged in the editor.

### Public policies and integration review

Apply Alembic revision `034_public_policies` before deploying the policy editor.
It adds policy storage, not published legal statements. No policy is automatically
published and checkout is not blocked by policy status.

Platform operators use **Platform > Public policies** (`/platform/policies`).
The initial drafts identify **Sru Global**, **Tenali**, `tenali.biz` and
`sourcedbysru@gmail.com`. Review the supplied address (including the full PIN code)
and actual data-handling practices before publication. Anonymous visitors now see
a platform homepage with an app description and public policy links; signed-in
workspace/storefront routing is preserved.

Tenant owners/admins use **Store Policies** (`/portal/policies`), also linked from
Company Setup. Each tenant gets independent, editable privacy, terms, shipping and
delivery, payment, cancellation/refund/returns/exchanges, account/data-deletion and
contact/business-information drafts. Business name and contact are suggested from
the workspace profile or signed-in administrator email; review the email before
making it public. All commercial amounts are INR. Supply the actual business address,
jurisdiction, shipping estimates/charges, cancellation and return rules, refund
processing times and other `[[...]]` details. Templates are starting copy, not legal
advice or certification.

**Save draft** never changes the published page. **Publish this version** requires
saved, completed contact/business fields, no template placeholders, and explicit
review confirmation. The server validates these independently of the UI. Publication
records a version and timestamp and is audited. Stale edits/publications are rejected;
reload the latest draft rather than overwriting another operator's work. Only the
latest published snapshot is exposed publicly; drafts and publishing APIs require
the appropriate tenant administrator or platform-operator session and CSRF protection.
Previously published snapshots are not an order-by-order legal acceptance archive.
Editing policies does not record customer consent, alter existing orders, change
authentication settings or automatically issue refunds/deletions.

Public links (no sign-in required after publication):

| Scope | Policy index | Example privacy page |
|---|---|---|
| Platform | `https://tenali.biz/policies/platform` | `https://tenali.biz/policies/platform/privacy` |
| Tenant path | `/c/<slug>/policies/tenant` | `/c/<slug>/policies/tenant/privacy` |
| Tenant verified domain | `/policies/tenant` | `/policies/tenant/privacy` |

Other page slugs are `terms`, `shipping`, `payment`, `returns`, `data-deletion` and
`contact` (platform has privacy, terms, deletion and contact only). The footer,
sign-in and checkout pages link to the relevant scope. Draft-only pages explicitly
report that they are unpublished; do not submit these URLs for provider review until
the policies are reviewed and published.

Integration checklist:

- **Google OAuth / Supabase social sign-in:** configure the production app homepage,
  privacy and terms URLs on a verified domain, with correct app identity and only
  the required scopes. The main privacy/terms documents cover authentication data;
  no separate authentication-policy page is added. Check each enabled provider's
  current requirements rather than assuming these templates complete verification.
- **Facebook Login:** supply the published platform privacy and
  `https://tenali.biz/policies/platform/data-deletion` instructions URL where the
  provider accepts deletion instructions. This implementation describes a manual
  email request, not a signed-request callback or automated deletion/status service.
  If Meta requires a callback for the app's configuration, implement and verify that
  workflow separately. Removing an app in a provider's settings alone does not erase
  Tenali/tenant records.
- **Razorpay:** submit the tenant seller's published terms, privacy, returns/refunds
  and contact pages, plus the required business/about and actual product/pricing
  information. Contact templates include a store description; the catalogue remains
  the pricing source. Publish shipping/payment terms that match the store's actual
  operations. Provider KYC, review, live-key and webhook checks remain separate.
- **Shiprocket/couriers:** confirm dispatch/transit windows, service areas, charges,
  tracking, failed delivery and returns with the actual shipping configuration.
  Publish disclosures of the delivery/contact data shared with fulfilment providers.
- Arrange real support handling, retention/deletion procedures and required legal
  review. These pages do not implement a grievance desk, automatic erasure, consent
  tracking or guaranteed integration approval.

Official policy references:
- [Google OAuth policies (including public homepage requirements)](https://developers.google.com/identity/protocols/oauth2/policies)
- [Meta data-deletion requests](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback/)
- [Razorpay business website review](https://razorpay.com/docs/payments/dashboard/account-settings/business-website-details/)

Generate and store the encryption key in the deployment secret manager (not Git or
browser environment variables):

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the key with encrypted backups. Losing or replacing it without re-encrypting
existing settings **and order snapshots** makes those credentials unavailable. Replacing
workspace settings is not a master-encryption-key rotation. Keep prior provider keys
valid until their orders, webhook events and shipments are reconciled.

Shoppers use **Add to Cart** on product pages and can buy multiple products/variants
in one payment, with a shopper login and an India delivery address. The browser saves
a separate cart for each workspace ID on the current origin; carts contain only
product/variant IDs and quantities, not credentials or delivery details. These are
browser-local carts, not account-synchronised carts. Sign-in is required at checkout,
not while browsing or adding items. Prices are computed from numeric catalog pricing,
not client amounts or display strings. Store selling prices must include applicable
taxes. Shipping is an explicitly configured **flat rate in paise**, not a live courier
quote or serviceability guarantee. Operators must confirm their supported delivery
areas and shipping costs before enabling checkout. A quote must be reviewed before
creating the Razorpay order; changed totals are rejected. Quote-only or unpriced items
and unavailable stock cannot be purchased.
In **Inventory → Edit Product**, set **Minimum online order quantity** (default 1).
Migration 019 adds this setting to existing products without changing their minimum
from 1. The setting is an integer from 1 to 100 and applies separately to each selected
variant, not a sum across sizes/colours. Product quantity starts at this minimum;
the cart lets shoppers change quantity or remove lines. Both quote and order APIs
recheck the current minimum, price, variant, workspace and stock. Existing carts
below a newly raised minimum must be corrected before payment. Online limits remain
30 different product/variant lines and 100 units per line. A completed payment removes
the purchased quantities from the cart; cancelled or failed payments retain them.
**WhatsApp enquiry** is for discussions,
bulk quotes, customisation and availability: it does not create an order, reserve
stock or take payment in Tenali. The phone comes from Company Setup; enquiry can
remain available with online checkout disabled. Product pages explain both paths,
and their explanatory text can be edited in Company Setup's storefront copy fields.

Checkout requests are idempotent. Unpaid orders reserve stock for 30 minutes; other
checkouts and operational stock withdrawals respect these reservations. Expired
reservations stop blocking stock without a background job. Payment is **not** accepted
from a browser callback alone: the server checks its signature and fetches the payment,
requiring captured status, the stored Razorpay order ID, INR currency and the exact
stored amount. Capture books one stock sale per order. A captured payment arriving
after stock is unavailable is marked `payment_review`; it cannot ship automatically.
Contact the shopper and resolve/refund through Razorpay rather than silently treating
it as fulfilled. There is no automated refund or invoice/account-ledger posting here.

Enable automatic capture in each workspace's Razorpay account and register a
`payment.captured` webhook:

```text
https://app.<platform-domain>/api/shop/webhooks/razorpay/<workspace-address>
```

The webhook secret must match that workspace's settings. Signed duplicate events are
safe; the server also fetches the captured payment. Keep the old URL configured when
changing a workspace address until existing orders are reconciled (aliases resolve).
Shoppers and administrators can also explicitly **Verify Payment** after a lost
callback/webhook. Do not ask a shopper to pay again merely because verification is pending.

For initial testing, use Razorpay **Test Mode** keys and its official test-payment
details on a store you are testing. Confirm a captured/verified payment in both
Tenali and the Razorpay Test dashboard. Test orders still exercise stock allocation,
so use dedicated test stock. Public HTTPS is required to receive provider webhooks;
localhost and HTTP cannot establish working webhook delivery. Check payment.captured
delivery in Razorpay's webhook logs separately from browser confirmation.

Shiprocket does not become a sandbox merely because Razorpay is in Test Mode.
Tenali blocks shipment submission for orders made using `rzp_test_` keys, on the
server as well as in the order UI. Only paid **live-key** orders may be submitted.
After provider approval, replace test keys/webhook configuration with matching live
settings, rerun checks, and make an authorised small real purchase. Real payments,
refunds and shipping can incur fees. Before opening sales to shoppers, confirm
provider approval, live capture, webhook delivery, shipping readiness and the
storefront switch. Keep online checkout off if any prerequisite is unresolved.

An administrator enters actual packed dimensions (cm) and weight (kg), then submits
a verified paid order to Shiprocket. Fulfillment is deliberately a post-payment,
operator-triggered step. Shiprocket order creation does not mean AWB assignment,
pickup or delivery occurred: arrange those in Shiprocket. Reconcile using its returned
order ID to record shipment/AWB/courier information. An uncertain network response
leaves `shipping_pending` and blocks blind resubmission; find the order using the
Tenali order UUID in Shiprocket, then reconcile that provider ID. Never reset it to
paid and retry without establishing whether the external order already exists.

Order history and fulfillment are tenant-scoped and shopper history is additionally
filtered to the signed-in shopper. Payment/fulfillment routes never trust a client
company ID. A workspace suspension hides its storefront and revokes staff/shopper
sessions, but must be coordinated with outstanding payments: provider callbacks for a
suspended workspace are rejected until re-enabled, then replayed or reconciled.

## Platform superadmin

The distinct console at `/platform` works only on the platform host, without a
workspace path/header. It uses separate operator accounts, sessions and CSRF cookies.
There is no public operator signup, staff impersonation or provider-secret export.
Operators can page through workspaces and enable/disable them; changes are audited.
Provision the first operator privately:

```powershell
Set-Location api
..\.venv\Scripts\python.exe -m app.bootstrap_platform --email <operator-email> --name <operator-name>
```

The command prompts for the password and refuses to replace an existing account.

## Upgrading existing installations

Back up the database and stop application writes before applying Alembic revision
`019_product_minimum_order` (normally `alembic upgrade head` from `api`). Deploy the matching
API and web code together. The migration splits existing multi-workspace staff
identities into one user per membership, preserving the existing password hash,
membership role, active state, company-specific sessions and audit actor association.
Subsequent password changes and revocations affect only that workspace identity.
Historical orphan users without memberships cannot sign in.

Platform `/login` now requires a workspace address instead of selecting the first
membership. Cross-workspace session switching returns an explicit error. The migration
is intentionally irreversible: do not downgrade and merge independent credentials or
discard order history.

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
TENALI_CREDENTIAL_KEY=<server-secret-manager-value>
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

## Request concurrency and billing loading

Tenant boundary database checks use Starlette's worker thread pool, not the async
event-loop thread. Each request still creates and closes its own identity session
and performs the same host, tenant, role, module and CSRF checks. No authorization
results are cached. Database network latency can still affect individual requests,
but a waiting database check must not block other requests on the event loop.

The billing page displays each reference dataset as it arrives. Invoice history and
reconciliation history load independently; invoice filters and audit pagination
do not refetch customers, accounts, HSN masters, products or company settings.
Posting, cancellation, reconciliation and manual Refresh reload billing data.
Failed reference requests are displayed with a retry action and prevent submission.
Responses from superseded filters or unmounted pages are ignored.

Deploy both API and web changes for these improvements; no migration is required.
From `api`, run `python -m unittest discover -s tests -p test_tenant_concurrency.py`.
From `web`, run `node --test tests/billing-loading.test.cjs`.
The concurrency regression uses simulated database latency and does not measure
production response times.

## Verification and release gates

### Form feedback and navigation drafts

Purchase reference datasets display independently as their requests finish; a
failed history/account request does not hide successfully loaded products.
Failures identify the dataset and offer a retry. Purchase product choices require
an active mapping to the selected vendor, matching posting validation; for
variant products the mapping must belong to an active variant. The items editor
explains empty vendor-filtered lists and links to Product Inventory to manage
vendor offers without losing the purchase draft.

Client-side navigation starts each new page at the top, including browser Back and
Forward. Query-only filter changes do not reset scrolling. Section links still
scroll to their target, including sections rendered after an asynchronous load.
The shared route-scroll handler disables native history scroll restoration while
mounted so the browser cannot reapply another page's position.

Apply revision `035_invoice_store_codes` before deploying the new API. It adds
immutable two-character store invoice IDs without renumbering existing invoices
or resetting counters. New invoices use `I<STOREID>YYYYMMDDNNNNN` (16 characters).
The store/month limit is 99999 invoices, and a workspace supports 1295 store IDs.

Temporary messages use shared floating alerts throughout the app: success messages
close after five seconds, errors remain until dismissed, and every alert has a close
button. Persistent setup notices, record-specific problems and validation guidance
stay inline. Required native controls have a visible `* Required` marker and a
distinct border, including invoice/purchase payment fields when a payment is entered.

Operational drafts are held only in React memory, scoped to the signed-in user and
workspace. Navigation preserves billing and purchase lines, shipping/payment fields,
attachments already read into the form, idempotency keys, parties, accounts,
settlements, receivables, business payments, HSN/brand/category/store forms, inventory
editors, company settings and custom-domain input. Saved/reset forms clear their
input using their normal reset actions. Reloading, signing out or changing identity
destroys the in-memory scope. No drafts are written to browser storage. Password
and provider-credential forms are intentionally excluded; policy drafts still use
their explicit Save draft workflow. In-progress file reads must finish before
navigating for their completed result to remain available.

From `web`, run `node --test tests/drafts.test.cjs tests/notifications.test.cjs
tests/billing-loading.test.cjs` and `npx tsc --noEmit`.

Use `api/requirements-dev.txt` for tests. `TENALI_TEST_DB=1` enables rollback-only tenant
HTTP/RLS tests covering unauthenticated access, company overrides, record tampering,
cross-company foreign keys, read-only roles, CSRF, domain ownership and revocation.
No customer identities or business data should be retained by those tests.

Real DNS propagation, certificate issuance and internet-host routing require deployment
and domain ownership; they cannot be proved by localhost tests alone. Before a paid
public launch, add verified-email onboarding, expiring email invitations and provider-
backed forgotten-password recovery, monitoring, recovery-tested backups and an
independent security review. Team creation refuses to overwrite an existing account
within that workspace. Signup/password changes are available; verified-email onboarding
and email-based password recovery are not implemented for shoppers or staff yet.
Platform administrator MFA/recovery and automated refunds also remain production
hardening requirements.

Run focused account/provider checks with `PYTHONPATH` including `api` and `api/tests`:
`python -m unittest test_tenancy test_shopper_checkout`. Database tests require
`TENALI_TEST_DB=1` and run in a rollback-only transaction, including revision 018 when
testing against a revision-017 database. Provider tests use mocks: real Razorpay
test-mode checkout/webhook delivery and Shiprocket API-user/pickup verification must
be completed on a staging deployment before enabling live checkout.

Only branding/product catalog fields are public. Company settings, signature images,
documents, vendor contacts, buying prices, financial data and audits require membership.
Each new tenant needs its real GST/master data; demo tax classifications are not copied.