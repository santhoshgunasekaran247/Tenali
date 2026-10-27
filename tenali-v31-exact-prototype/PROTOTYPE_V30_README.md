# SRU Global HTML/CSV Prototype v30

This is the latest HTML/CSV prototype based on the v29 operations portal, updated for the latest architecture decisions.

## Added in v30
- Vendor Contributions as a first-class prototype concept.
- Vendor contribution attributes: SKU, size, colour, GTIN, unit count, weight, height, width, length, item name, description, MRP, buying price, selling price, vendor URL/reference.
- Product variants CSV.
- Product master extended with standard physical/commercial attribute columns.
- Product -> vendor contribution mapping.
- Vendor -> contribution -> product flow.
- CSV-driven theme configuration.
- CSV-driven pages and dashboard widgets.
- CSV-driven navigation/configuration examples.
- Prototype admin screen for Products, Contributions, Theme and Configuration.
- Existing v29 portal retained.

## Run locally
Use a local web server because browser `fetch()` cannot reliably read CSV files from `file://`.

Python:

    python -m http.server 8000

Then open:

    http://localhost:8000/

For the new configuration/contribution prototype:

    http://localhost:8000/prototype-admin.html

## Important
This remains a prototype. Changes made in the prototype are not written back to CSV files; browser persistence in the older operations portal uses localStorage. The production application will use FastAPI + PostgreSQL and will import these CSV master/configuration files.
