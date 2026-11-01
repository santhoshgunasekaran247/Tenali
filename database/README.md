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
