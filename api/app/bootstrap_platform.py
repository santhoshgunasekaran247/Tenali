"""Provision platform operators locally; no public administrator registration."""

import argparse
import getpass

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.tenant_security import MemberCreate, password_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Platform password (minimum 12 characters): ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords did not match")
    payload = MemberCreate(email=args.email, display_name=args.name, password=password, role="admin")
    with SessionLocal() as db:
        if db.execute(text("select id from platform_admins where email=:email"), {"email": payload.email}).first():
            raise SystemExit("Platform administrator already exists; refusing to overwrite credentials")
        db.execute(text("insert into platform_admins(email,display_name,password_hash) values(:email,:name,:hash)"),
                   {"email": payload.email, "name": payload.display_name, "hash": password_hash(password)})
        db.commit()
    print("Platform administrator created.")


if __name__ == "__main__":
    main()
