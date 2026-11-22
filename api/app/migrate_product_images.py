"""Copy registered public images between configured storage providers without deleting source files."""
import argparse
import hashlib

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.object_storage import PUBLIC_BUCKET, image_storage


def copy_images(db, source, destination, *, apply=False):
    rows = db.execute(text("""select company_id, bucket, object_path, mime_type, file_size, sha256
        from stored_files where bucket=:bucket and file_kind='image' order by id"""),
        {"bucket": PUBLIC_BUCKET}).mappings()
    count = 0
    for row in rows:
        count += 1
        if not apply:
            continue
        content = source.read(row["bucket"], row["object_path"])
        if len(content) != row["file_size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise RuntimeError(f"Source image verification failed for object {count}; no storage configuration was changed")
        copied = destination.put_verified(str(row["company_id"]), content, row["mime_type"], public=True, kind="image")
        if copied["object_path"] != row["object_path"] or copied["sha256"] != row["sha256"]:
            raise RuntimeError(f"Destination image path or checksum mismatch for object {count}; no storage configuration was changed")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=["supabase", "s3"])
    parser.add_argument("--destination", required=True, choices=["supabase", "s3"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-maintenance", action="store_true",
                        help="Confirm all public image writes are stopped until storage is switched")
    args = parser.parse_args()
    if args.source == args.destination:
        parser.error("Source and destination must differ")
    if args.apply and not args.confirm_maintenance:
        parser.error("Stop all public image writes and pass --confirm-maintenance before copying")
    with SessionLocal() as db:
        source = image_storage(args.source) if args.apply else None
        destination = image_storage(args.destination) if args.apply else None
        if args.apply and args.destination == "supabase":
            destination.ensure_buckets()
        count = copy_images(db, source, destination, apply=args.apply)
    print(f"{'Verified and copied' if args.apply else 'Found'} {count} registered public images.")
    if args.apply:
        print("Source files were retained. Switch TENALI_IMAGE_STORAGE only after verifying the destination; keep all public image writes stopped until then.")


if __name__ == "__main__":
    main()
