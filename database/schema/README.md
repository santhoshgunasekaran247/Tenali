# Modular schema layout

This folder organizes SQL by domain for scalability and easier review.

Order of execution:
1. `01_extensions.sql`
2. `10_core_company_and_access.sql`
3. `20_catalog_and_inventory.sql`
4. `30_commerce_and_finance.sql`
5. `40_people_documents_ui_audit.sql`
6. `90_indexes.sql`

Current source of truth for existing workflows remains `../schema.sql`.
The modular files are aligned to the same table model and are intended for future maintenance and domain-specific updates.
