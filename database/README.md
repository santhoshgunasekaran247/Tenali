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
