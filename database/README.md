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

Authentication and tenant membership are now enforced. Apply migrations through
`017_tenant_slug_aliases`; the baseline SQL alone does not provision identity/RLS policies.
See [multi-tenant deployment](../docs/MULTI_TENANT_DEPLOYMENT.md) for registration,
owner bootstrap, role isolation and standalone-domain/HTTPS setup. Existing companies
must be bootstrapped by an administrator; public registration creates new companies only.
Company Setup also controls tenant storefront copy, display name, logo, theme and the
customer-facing `/c/<workspace-address>`. Changed workspace addresses retain their old
paths as aliases and redirect to the current address.
SMTP/SMS provider delivery is not configured. Full chart-of-accounts accounting, verified opening balances, inventory
valuation policy, partial credit/debit notes/refunds and accountant-approved statutory
returns remain separate implementation/setup gates. The current money-movement
reports must not be presented as a complete trial balance, P&L or balance sheet.
