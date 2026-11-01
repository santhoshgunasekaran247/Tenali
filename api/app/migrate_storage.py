"""Move existing tenant files to Supabase, verifying bytes before replacing references."""
import argparse
import json

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.object_storage import FileStore, ObjectStorage

IMAGE_KEYS = {"image_url", "image_urls", "logo_url", "signature_image", "storage_path"}
JSON_COLUMNS = {
    "companies": ["invoice_settings", "storefront_content"],
    "invoices": ["document_data"],
    "purchases": ["line_items"],
    "page_configurations": ["configuration"],
    "theme_settings": ["configuration"],
    "dashboard_widgets": ["configuration"],
    "posting_requests": ["response"],
    # Audit references are rewritten last so old inline bytes are not retained there.
    "audit_events": ["old_value", "new_value"],
}
TEXT_COLUMNS = {"companies": ["logo_url"], "products": ["image_url", "image_urls"],
                "product_categories": ["image_url"], "product_images": ["storage_path"]}


class StorageMigration:
    def __init__(self, db, apply=False):
        self.db = db
        self.apply = apply
        self.files = FileStore(db)
        self.cache = {}
        self.references = 0

    def image(self, company, value, private=False):
        if not value or value.startswith(("http://", "https://", "/api/company/assets/", "/api/documents/", "database://")):
            return value
        key = (str(company), value, private)
        self.references += 1
        if not self.apply:
            return value
        if key not in self.cache:
            self.cache[key] = self.files.image(str(company), value, private)
        return self.cache[key]

    def transform(self, company, value, key=""):
        if isinstance(value, dict):
            return {name: self.transform(company, item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [self.transform(company, item, key) for item in value]
        if isinstance(value, str) and (value.startswith("data:") or key in IMAGE_KEYS):
            if key == "image_urls":
                return "|".join(self.image(company, part) for part in value.split("|") if part)
            return self.image(company, value, private=key == "signature_image")
        return value

    def migrate_documents(self):
        rows = self.db.execute(text("select id,company_id,file_content,mime_type from documents where file_content is not null")).mappings().all()
        for row in rows:
            self.references += 1
            if not self.apply:
                continue
            stored = self.files.save(str(row["company_id"]), bytes(row["file_content"]), row["mime_type"])
            self.db.execute(text("""update documents set stored_file_id=:file,file_content=null,storage_path=:url
                where id=:id and company_id=:company"""), {"file": stored["id"], "id": row["id"],
                "company": row["company_id"], "url": f"/api/documents/{row['id']}/download"})
            self.db.commit()

    def migrate_table(self, table, columns, json_columns=False):
        ownership = "source.id" if table == "companies" else "source.company_id"
        join = ""
        if table == "product_images":
            ownership = "product.company_id"
            join = " join products product on product.id=source.product_id"
        keys = ["company_id", "operation", "request_key"] if table == "posting_requests" else ["id"]
        selected = ",".join("source." + name for name in dict.fromkeys(keys + columns))
        rows = self.db.execute(text(f"select {selected},{ownership} as owner_company from {table} source{join}")).mappings().all()
        for row in rows:
            changes = {}
            for column in columns:
                value = row[column]
                converted = self.transform(row["owner_company"], value, column)
                if converted != value:
                    changes[column] = converted
            if not self.apply or not changes:
                continue
            params = {name: row[name] for name in keys}
            params.update({name: json.dumps(value) if json_columns else value for name, value in changes.items()})
            setters = ",".join(f"{name}=cast(:{name} as jsonb)" if json_columns else f"{name}=:{name}" for name in changes)
            where = " and ".join(f"{name}=:{name}" for name in keys)
            self.db.execute(text(f"update {table} set {setters} where {where}"), params)
            self.db.commit()

    def run(self):
        if self.apply:
            ObjectStorage().ensure_buckets()
        self.migrate_documents()
        for table, columns in TEXT_COLUMNS.items():
            self.migrate_table(table, columns)
        for table, columns in JSON_COLUMNS.items():
            self.migrate_table(table, columns, json_columns=True)
        return self.references


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Upload, verify and replace references (otherwise read-only scan)")
    args = parser.parse_args()
    with SessionLocal() as db:
        migration = StorageMigration(db, apply=args.apply)
        count = migration.run()
    print(f"{'Migrated' if args.apply else 'Found'} {count} embedded/local file references.")
    if not args.apply:
        print("Run with --apply to migrate. Existing HTTP(S) URLs and bundled application UI assets are unchanged.")


if __name__ == "__main__":
    main()
