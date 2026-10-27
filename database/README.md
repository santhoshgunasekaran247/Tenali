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
