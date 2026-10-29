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

## Verification and release gates

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