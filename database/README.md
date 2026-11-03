# SRU Global database foundation

Two schema views are now maintained:

- `schema.sql`: single-file baseline (current compatible source for existing workflows).
- `schema/`: scalable modular schema organized by domain.

## Modular schema execution order

1. `schema/01_extensions.sql`
2. `schema/10_core_company_and_access.sql`
3. `schema/20_catalog_and_inventory.sql`
4. `schema/30_commerce_and_finance.sql`
5. `schema/40_people_documents_ui_audit.sql`
6. `schema/90_indexes.sql`

## Migration guidance

Do not paste schema SQL manually into Supabase dashboard for production changes.
Use Alembic migrations from `api/alembic` and `api/migrations`:

    alembic upgrade head

The modular SQL files are intended for maintainability, domain review, and future migration generation.

## Public platform and tenant policies

Migration `034_public_policies` adds `legal_policies`. A null `company_id` identifies
platform policies; a non-null company identifies a tenant's independent documents.
Each policy stores a private draft revision and a separate published snapshot with
its version and publication time. Saving a draft never changes the public copy.
New templates are unpublished until an authorised operator reviews and publishes them.

Policy endpoints use explicitly scoped identity sessions; runtime roles are not
granted access to drafts. Publishing and draft changes are audited in the existing
tenant/platform audit tables. Include policy and audit tables in database backups.
See [deployment policy guidance](../docs/MULTI_TENANT_DEPLOYMENT.md#public-policies-and-integration-review)
for editing, public URLs and external-provider review requirements.

## Purchase and payment attachments

Purchase bills and business-payment receipts use `documents` and `document_links`.
Uploaded file bytes are stored in `documents.file_content` (PostgreSQL `bytea`), not
in a public asset directory. Include these tables in database backups and restores.

PDF, JPEG, PNG and WebP files are supported: up to 5 MB per file, 5 files per record,
and 20 MB total per record. Files selected during record creation save in the same
transaction as the purchase or payment. Additional files can be uploaded later;
existing evidence is retained rather than deleted by the attachment UI.

## Product-first inventory

Inventory and the customer catalog use the same `products` records. Child size/colour
variations live in `product_variants`; `vendor_contributions` links supplier offers to
a product or variant. Supplier MRP, buying price, availability and lead time remain
on the offer. Product-level summaries derive these fields from the preferred active
supplier; changing supplier does not create another product.

Catalog price and discount belong to the product. The pricing rule records which
value stays fixed when preferred MRP changes. Variants inherit the parent's rule
unless explicitly overridden. Visibility, best-seller/special flags and ordering are
configured on the product. Customer responses omit supplier identity/contact and
buying-price fields.

Supplier availability is not owned stock. Owned quantities are recorded separately
through stock-in/out adjustments with movement history and negative-stock checks.
Existing free-text purchase/invoice lines do not automatically move inventory.
Product-linked sales now deduct stock atomically; confirming receipt of a product-linked
purchase adds stock once. Service lines do not move owned quantities. Select a child
variant when the product has active variants, and map purchased items to the vendor.
Reorder thresholds, restock targets and dates produce persistent in-app alerts and
reminders, not email/SMS notifications.

Inventory migration: `009_product_inventory`. Rollback-only database regression
tests can be enabled with `TENALI_TEST_DB=1` when running `api/tests/test_inventory.py`.

## Operational completion controls

- AR/AP aging reconstructs payments and dated reversals through the cutoff, rather
    than using current paid totals. Legacy payments with no dated source evidence
    still require opening-balance reconciliation; do not invent receipt dates.
- Clients should supply `idempotency_key` on invoice/purchase creation, business
    payments and manual stock adjustments. Identical retries return the saved result;
    changing values under the same key is rejected. Keys remain optional for legacy clients.
- Unpaid invoices and purchases can be cancelled with a reason/date and atomic stock
    reversal. Reverse their payments first. Cancellation does not issue a bank refund,
    replace a partial return, or generate a statutory credit/debit note.
- Reports includes transactions, journal, sales/purchases and historical AR/AP aging.
    GSTR-2B comparison accepts the downloadable normalized CSV template and exports
    match/mismatch/missing/duplicate review rows. It is not portal integration, an ITC
    eligibility determination or a filing format; legacy vendor GSTINs need review.
- Brands/categories support editing and activation while keeping codes stable.
    Product-page contacts follow Company Setup. Audit Events captures future operational
    changes; file bytes/signatures are excluded, and local-mode actors are unattributed.
- Apply Alembic through `013_runtime_schema`. Migrated requests skip the legacy
    request-time DDL that could deadlock with active postings/audit triggers.

## Stores, per-store stock and the online channel

- `stores` holds shops (`offline`), `warehouse`s and `online` stores per company.
  Shops and warehouses hold stock; the online store sells from its
  `fulfilment_store_id`. Every company has exactly one default stock-holding store
  (`MAIN` is created by migration 022 and at workspace registration).
- `stock_balances` and `stock_movements` carry `store_id`; balances are unique per
  `(company, store, product, variant)`. Negative stock is checked **per store**.
  `stock_transfers` move stock between two stores with paired `TRANSFER_OUT` /
  `TRANSFER_IN` movements; mistakes are corrected with a reverse transfer.
- Invoices, purchases, receivables, payments, account transactions and borrowings
  carry `store_id`. The `tenali_default_store` trigger derives it from the parent
  document or the default store when a caller omits it.
- Numbering is per store and per month from `document_sequences`:
  `INV-<CODE>-YYYYMM-NNNNN` and an internal `PUR-<CODE>-YYYYMM-NNNNN` voucher
  (`purchases.voucher_number`); the vendor's `bill_number` stays as entered.
  Counters start at 1 at cut-over; `invoice_sequences` was dropped.
- Selling prices are **GST-inclusive** (`companies.prices_include_gst`, true for all
  tenants): sales lines back out GST per line; purchase lines stay exclusive.
- Online orders (`shop_orders`) record `payment_method` (prepaid / cod /
  pay_at_pickup) and `fulfilment_method` (delivery / pickup). Stock is **held** by a
  reservation while an order is active and is booked OUT, with the invoice created,
  at dispatch (delivery) or collection (pay-at-pickup). Prepaid captures post a
  customer advance (`source_type='shop_order'`) to the online store's settlement
  account; dispatch attaches that transaction to the invoice. COD invoices stay
  UNPAID until a courier remittance is recorded in `cod_settlements`; shortfalls
  require a reason. `enquiries` records WhatsApp enquiries; `checkout_settings`
  holds the channel policy (COD limit/approval window, pickup hold, shipping SAC and
  rate). The runtime role may read only the policy columns (026), never credentials.
- **GST registration** (`companies.gst_registered`, 027): businesses below the GST
  threshold set this to false. Their itemized documents are issued as **Bills of
  Supply** with 0% on every line and no GSTIN requirement; purchases still record the
  GST vendors charge. Registered businesses must hold a valid 15-character GSTIN.
- **Team access** (027): owners and administrators always have every store and
  module. Staff and read-only members may be limited with
  `tenant_memberships.store_ids` and `modules` (null = all). Store limits apply to
  stock adjustments, transfers, billing, purchases and their listings; module limits
  are enforced on the API path (`/billing`, `/purchases`, `/inventory`,
  `/collections`, `/accounts`, `/settlements`, `/reports`, `/parties`, `/masters`,
  `/checkout-admin`). Store administration is owner/admin only.

## Shopper identities and customer contacts (028)

- Shopper registration/login uses Supabase social providers (migration 030); handwritten
  email/password registration is disabled (`410`). Workspace staff authentication
  is unchanged. Accounts are keyed by `(company_id, supabase_uid)` and remain
  independent across tenants.
- New shoppers supply a name and phone. The backend gets the email from the
  authenticated social identity profile, not client input or editable Supabase
  user metadata. Phone numbers are user-entered and **unverified**: no OTP, SMS,
  WhatsApp verification, or phone sign-in is enabled.
- Online shopper accounts remain separate from `parties`, even if email or phone
  matches. Owners/admins can explicitly link one active shopper to one active
  counter customer in **Customers and vendors > Online customer accounts** after
  confirming identity directly. Cross-tenant links and conflicting links are
  rejected, and successful links are audited. A link affects future online invoices
  only; past invoices/ledgers and shopper order ownership are never rewritten.
  Unlinked online orders continue using the existing internal online-shopper party.
- New counter customers require a phone; email remains optional. Vendors may
  record both contacts. Shared phone numbers are allowed and never imply a merge.
  Billing has inline customer creation without discarding the invoice draft.
  Customer/vendor selectors search name, nickname, email and phone; labels show
  name and contact details to distinguish similar names.
- Phone normalization uses India for local numbers and E.164 for international
  numbers. Existing missing contacts are not invented or silently verified.
- Legacy shopper email/password accounts and their orders are preserved, but old
  sessions/password sign-in are not accepted. An email collision requires
  administrator-assisted account recovery; it is not an automatic identity merge.

### Recovering a platform administrator password

Platform administration is not part of a client workspace. Open `/platform`
directly on the platform host using a separate platform administrator account.
Tenant paths/domains, tenant-selection headers, and active workspace or shopper
sessions are rejected, even when a platform session cookie is also present.
Sign out of the tenant/shopper session first or use a separate browser profile
for platform operations. Tenant sign-in pages do not link to this console.

There is no public platform password-recovery endpoint. An authorized server
operator can reset an existing active platform administrator from a local terminal:

```powershell
Set-Location D:\GitRepo\Tenali\api
& ..\.venv\Scripts\python.exe -m app.bootstrap_platform --email santhoshgunasekaran2@gmail.com --reset-password
```

Enter and confirm a new password (12-128 characters) at the hidden prompts. Never
put passwords in command arguments, source files, or chat. The command uses the
API's configured database, preserves the administrator's identity, revokes all
of that administrator's platform sessions, and records `PASSWORD_RESET` in
`platform_audit` atomically. It does not change workspace or customer accounts,
create missing accounts, or reactivate disabled administrators. Sign in again on
the platform host's `/platform` page after resetting.

### Free social-login setup

1. Use the existing Supabase project:
   [Authentication providers](https://supabase.com/dashboard/project/nbtufrknknzmrfmvuqyh/auth/providers).
   The [Free plan](https://supabase.com/pricing) includes 50,000 monthly active
   users, 500 MB database space and 1 GB file storage; inactive projects may pause
   after a week. No paid upgrade or phone/SMS authentication is needed here.
2. Enable Google and/or Facebook under Authentication > Sign In / Providers.
   Configure provider client IDs/secrets in Supabase, with the callback
   `https://nbtufrknknzmrfmvuqyh.supabase.co/auth/v1/callback` in each provider's
   developer console. Yahoo is not built in: create an OIDC custom provider with
   identifier `custom:yahoo`, Yahoo's issuer and email/profile scopes, following
   [Custom OAuth/OIDC providers](https://supabase.com/docs/guides/auth/custom-oauth-providers).
   The Free plan currently allows three custom providers. Enable Yahoo in Tenali
   only after its custom provider is configured and tested. OAuth app approval
   may be needed for public users; provider accounts must supply an email.
3. Open the platform host's **`/platform/authentication`** page and sign in using a
   **platform administrator** account (not a tenant owner/staff account). In
   **Authentication > Social login** section (separate from Client administration),
   save the Supabase Project URL
   (`https://nbtufrknknzmrfmvuqyh.supabase.co`), public publishable or legacy anon
   key (from Supabase Project Settings > API Keys), enabled providers and enabled
   switch. Never use a secret/service-role key. Settings are shared
   by every tenant, shopper and workspace owner, and saved in
   `platform_auth_settings` (migrations 029-030); no tenant can override them.
   The platform navigation separates **Client administration** (`/platform`) from
   **Authentication** (`/platform/authentication`). The old `/platform#social-login`
   link redirects to Authentication. Only platform administrators can access
   either section; authentication settings do not appear in client administration.
   Existing server environment values remain a fallback until portal settings
   are saved:

       TENALI_SUPABASE_URL=https://nbtufrknknzmrfmvuqyh.supabase.co
       TENALI_SUPABASE_PUBLIC_KEY=<public-publishable-or-anon-key>
       TENALI_SUPABASE_PROVIDERS=google,facebook
       TENALI_SUPABASE_AUTH_ENABLED=true

4. Under Supabase Authentication > URL Configuration, allow the callback for
   every actual platform/storefront origin, including query parameters, e.g.
   `http://127.0.0.1:5173/social-login?**` and
   `http://localhost:5173/social-login?**`. Production callbacks must use HTTPS
   and explicitly allowed hostnames (not a broad wildcard hostname). The callback
   stays at the origin root even for `/c/<tenant>` pages. OAuth provider secrets
   belong only in Supabase/provider consoles. No Firebase service-account JSON
   or Supabase service-role key is required by Tenali's login verification.
5. The portal's public configuration takes effect without a restart. Restart the
   API only when changing server environment. The frontend reads only public configuration from
   `/api/shop/auth-config`; it shows an explicit setup notice until configured.
   Supabase access tokens are authenticated server-side through `/auth/v1/user`;
   issuer, subject, user role and OAuth authentication method are checked before
   accepting a configured social identity's email. Tokens are then
   converted into the existing tenant-scoped HttpOnly shopper session.
   OAuth runs in a popup with PKCE. The temporary verifier uses popup
   sessionStorage, is cleared after callback, and access tokens remain in memory;
   no persistent localStorage social session is created. Refresh tokens are not
   retained. Existing application sessions keep their established lifetimes.
6. Test each enabled provider with its test users before public release. Provider
   popups must be allowed. A blocked popup or failed exchange is reported, and
   an abandoned login times out after three minutes. The application never sends OTP.

The frontend uses the Supabase SDK; it does not access tenant tables directly.
Tenant data access remains through the API's existing Postgres role/RLS boundary.
Provider setup, external OAuth approval, and real social login cannot be validated
without the public key and configured provider applications.
Migration 030 refuses to run if Firebase identities already exist, rather than
silently matching email or substituting a Supabase UID into a Firebase namespace.
Legacy Firebase UID columns remain preserved but are not accepted for new login.

### Workspace owner social authentication (029)

- New workspace creation (including **Add another company**) requires a social
  login. `/auth/register-social` accepts company name, workspace slug and a signed
  Supabase access token (the existing field name is `id_token`); email/name come
  from the social provider. Handwritten-email
  `/auth/register` and password-based `/auth/workspaces` creation return `410`.
- Workspace owners use **Workspace social sign-in** at their workspace address
  thereafter. Accounts are keyed by `(company_id,supabase_uid)`. The same social
  identity may create multiple independent companies, but signing in always
  requires the chosen company and its membership. A matching email does not link
  a pre-existing staff account or grant membership.
- Existing staff password sign-in and password changes remain available.
  Social-only owners have no local password and manage recovery/security with
  their provider. Shopper, workspace staff/owners and platform-admin sessions
  remain separate. A shopper registration cannot grant workspace access.
- Portal settings writes require platform authentication and CSRF protection,
  and are recorded in `platform_audit`. The Supabase project cannot be changed
  once any social identity exists; that would require a managed identity
  migration. Disabling social login blocks new social authentication, but does
  not revoke already-issued sessions or disable legacy password authentication.
- Saving public settings is not a provider connection test. Provider secrets,
  app approval and OAuth callback configuration still belong in Supabase/provider
  consoles. Never upload private credentials to the portal.

- An invoice's `document_data` JSON is the current itemized sales document; a
  purchase's `line_items` JSON is the current itemized purchase document. The
  legacy `invoice_items` and `purchase_items` tables are not maintained by
  these posting workflows. Likewise, current business payments are represented
  by `account_transactions`, and borrowing/repayment entries by `borrowings`;
  the legacy `expenses` and `settlements` tables are not parallel ledgers.
  Do not infer missing history or backfill those tables without reviewing source
  documents and migration requirements.
- Invoice receipts combine the unreversed initial account transaction with
  unreversed `receivable_payments`. Purchase totals use unreversed
  `purchase_payments`. A reversal posts a separate account transaction and
  updates the related document's totals and status. Reconciliation rejects
  mismatched invoice/receivable links or stored receipts unsupported by recorded
  history; investigate those legacy records before posting further changes.
- Itemized sales and purchase previews round each taxable line to paise, then
  round that line's GST to paise, using the same half-up rule as the server.
  The maximum supported document total is INR 999,999,999,999.99.
- Payments cannot predate their invoice or purchase; account-transaction
  reversals cannot predate the original. A repayment cannot exceed the
  borrowing balance on its date or make a later dated balance negative.
  Borrowing reversals take effect on their own dates, not retroactively.
  Reversing a borrowing is blocked if linked repayments would become uncovered.
  Legacy business-payment borrowings without a reliable source link are not
  guessed: potentially linked reversals return a conflict for manual review.
- Closing an accounting period also blocks manual inventory adjustments and
  receivable status/write-off changes, using the server's current date for
  those actions. Other dated postings use their own transaction date. A bad-debt
  change requires a reason and is not a payment or a bank refund.
- Inventory's **Stock reconciliation** compares recorded balances with recorded
  movements and flags missing invoice/purchase references. It does not verify a
  physical count, reconstruct deleted documents, establish a historical opening
  date, or value stock. Any approved baseline adjustment must be explicitly
  described as an unverified current quantity until physically checked.
  A movement whose in-system source document no longer exists is listed under the
  reconciliation panel; the owner can attribute it to an external document (for
  example a paper vendor bill) with a reference and filing note. This changes only
  the attribution and notes, never quantities, and is allowed only while the source
  is actually missing.

### Day-to-day resolutions for common situations

- **Company GSTIN is missing or not 15 characters:** header-only invoices and
  purchases still post; itemized tax invoices are blocked until an authorised owner
  saves the correct GSTIN and company address in Company Setup.
- **Unverified stock baselines:** count the physical stock, then post a manual
  stock adjustment IN/OUT for the difference with a note such as
  "Physical count on <date>". Do not edit balances directly.
- **Cancelling a paid invoice or purchase:** reverse its payment transactions
  first (Accounts → Reverse); cancellation never issues a refund.
- **Cancelling a received purchase whose goods were already sold:** cancellation is
  rejected because stock would go negative and the purchase stays posted. Record a
  vendor credit as an account transaction and correct stock with a noted manual
  adjustment if goods are physically returned.
- **Recovering a written-off receivable:** change its status back to the
  ledger-derived status (UNPAID or PARTIAL), then collect; collections on BAD_DEBT
  are rejected.
- **Zero-value documents:** invoices and purchases must have a positive total.
  Record free samples or replacements as a manual stock adjustment OUT with notes.
- **Posting blocked by a closed period:** reopen the lock with a reason, post, and
  close it again; manual stock and status changes use today's date.

Deploy the application together with Alembic migrations through
`027_gst_registration_and_access`. Revision `020_borrowing_source_links` adds a
nullable transaction link for new borrowing entries; it does not guess legacy
links. Revision `021_unique_invoice_receivable` refuses to run if a company has
multiple receivables for the same invoice and adds a partial unique index.
Review and resolve duplicates with an accountant before upgrading, and take
appropriate backups. These are shared-schema migrations affecting all tenants;
apply them before deploying code that relies on them.

The shared tax-preview regression can be run from the repository root with
`node --test web\tests\taxTotals.test.cjs` after installing the existing web
development dependencies.

Authentication and tenant membership are now enforced. Apply migrations through
`021_unique_invoice_receivable`; the baseline SQL alone does not provision identity/RLS policies.
See [multi-tenant deployment](../docs/MULTI_TENANT_DEPLOYMENT.md) for registration,
owner bootstrap, role isolation and standalone-domain/HTTPS setup. Existing companies
must be bootstrapped by an administrator; public registration creates new companies only.
Company Setup also controls tenant storefront copy, display name, logo, theme and the
customer-facing `/c/<workspace-address>`. Changed workspace addresses retain their old
paths as aliases and redirect to the current address.
Workspace staff credentials are independent per company. Shopper accounts, platform
operators and their sessions are separate. Revision 018 also adds encrypted workspace
checkout settings and tenant-scoped orders; deploy the server credential-encryption
key before configuring Razorpay/Shiprocket. Unpaid checkout reservations protect
owned stock for 30 minutes. See the deployment guide for migration, bootstrap,
payment verification, fulfillment reconciliation and live-provider release gates.
SMTP/SMS provider delivery is not configured. Full chart-of-accounts accounting, verified opening balances, inventory
valuation policy, partial credit/debit notes/refunds and accountant-approved statutory
returns remain separate implementation/setup gates. The current money-movement
reports must not be presented as a complete trial balance, P&L or balance sheet.

## Operations dashboard

The live dashboard is a separate screen at `/portal/dashboard`, linked from the
Operations Portal and workspace account menu, with a link back to the portal.
The portal itself retains its workflow checklists and module navigation without
loading dashboard data. The dashboard uses the sales/inventory overview layout.
`/api/dashboard` aggregates all matching records (not the first
page of module lists). Its optional `month=YYYY-MM-01` and `store_id=<uuid>` filters
are validated; tenant/company overrides and unassigned stores are rejected.

- Reporting month controls posted purchase/invoice totals, top five billed
  products by quantity and the sales-order channel table. Cancelled purchase
  bills/invoices are excluded. Header-only invoices count in totals but not in
  product rankings.
- Pending order activity and unreceived purchase quantities include all dates.
  Stale payment/COD/confirmation holds are excluded from pending counts and shown
  as closed in the channel table. There is no invented "packed" status.
- Product/category counts and the active-product percentage describe the shared
  workspace catalogue. On-hand quantities and low-stock checks use only the
  selected/accessible stores. Low-stock counts include active products/variants
  with enabled reorder thresholds, not merely inactive/unconfirmed catalogue rows.
  Mixed-unit sums are operational counts, not inventory valuation.
- Module restrictions also apply to dashboard data: unavailable sections are
  omitted, not loaded in the browser and hidden afterward. Order summaries follow
  the existing owner/admin-only checkout administration permission. Borrowing
  remains explicitly workspace-wide and is omitted for store-filtered/restricted
  users; the application does not allocate borrowing to a store.
- Empty results are shown as empty/zero; failures show a retry action rather than
  successful-looking zero totals. Workflow checklists are scoped to workspace and
  user in this browser; they are not shared closing approvals.

## Supabase file storage

Apply migrations through `032_document_storage_scope` before deploying file-storage
support. Set these **server-only** environment variables (local development uses
the ignored `api\.env`):

- `TENALI_SUPABASE_URL`: the hosted project's `https://<project>.supabase.co` URL.
- `TENALI_SUPABASE_STORAGE_KEY`: a Supabase server secret/service-role key with
  Storage access. Never put this in a `VITE_` variable, source control, or browser
  configuration. This is separate from the public key on Platform > Authentication.

Run the following from `api` using the project's Python environment:

```powershell
python -m app.migrate_storage
python -m app.migrate_storage --apply
python -m app.migrate_storage
```

The first command reports embedded/local references without changing data.
`--apply` creates or verifies the `tenali-public` and `tenali-private` buckets,
uploads files, reads them back to check their size and SHA-256, then replaces
database content with references. Run during a maintenance window, back up the
database first, and retain original local assets. Each completed row is committed;
failed rows retain their original content and the command can be retried safely.
Historical invoice snapshots, configuration JSON and image-bearing audit payloads
are included. Audit image payloads are processed last, so an apply count can exceed
the initial scan count when updates generate new audit entries.

- Product/category photos and company logos use public Storage URLs. Only upload
  images intended to be visible to anyone.
- Signatures and finance attachments use the **private** bucket and stable,
  authenticated Tenali API URLs. The backend checks the tenant and the relevant
  module/store permissions before returning the bytes. Do not make this bucket
  public or add anonymous read policies.
- Browser Supabase users do not need upload policies; uploads go through Tenali.
  Keep both buckets closed to browser writes. Uploads use immutable,
  tenant-prefixed, content-addressed paths, so repeat saves reuse the same content.
- The database stores object metadata/references, not new file bytes or base64.
  The existing forms still send base64 transiently in upload requests; pressing
  Save uploads the file. Existing external public image URLs remain unchanged.
- Image forms accept PNG/JPEG/WebP up to 1 MB; finance attachments retain the
  5 MB/file, five-files/record and 20 MB/record limits. Storage rejects files over
  5 MB. Supabase quotas are shared across tenants and its free allowance is not
  unlimited; monitor storage and bandwidth in the Supabase dashboard.

Do not delete or rename buckets/objects or change the storage project without a
separate migration: historical invoices can still reference old images. A verified
upload followed by a failed parent database save can leave an unreferenced object;
retries reuse it, but automatic orphan deletion is deliberately not enabled.
Database backups alone do not back up Storage objects; protect both.
