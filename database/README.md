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
Reorder thresholds, restock targets and dates produce persistent in-app alerts and
reminders, not email/SMS notifications.

Inventory migration: `009_product_inventory`. Rollback-only database regression
tests can be enabled with `TENALI_TEST_DB=1` when running `api/tests/test_inventory.py`.
