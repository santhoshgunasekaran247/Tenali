"""Provision platform operators locally; no public administrator registration."""

import argparse
import getpass
import warnings

from pydantic import ValidationError
from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.tenant_security import MemberCreate, password_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name")
    parser.add_argument("--reset-password", action="store_true",
                        help="Reset an existing active administrator's password and revoke its sessions")
    args = parser.parse_args()
    if not args.reset_password and not args.name:
        parser.error("--name is required when creating a platform administrator")
    if args.reset_password and args.name:
        parser.error("--name cannot be used with --reset-password")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Platform password (12-128 characters): ")
            confirmation = getpass.getpass("Confirm password: ")
    except getpass.GetPassWarning:
        raise SystemExit("A terminal with hidden password input is required") from None
    if password != confirmation:
        raise SystemExit("Passwords did not match")
    try:
        payload = MemberCreate(email=args.email, display_name=args.name or "Password reset", password=password, role="admin")
    except ValidationError as error:
        raise SystemExit("; ".join(item["msg"] for item in error.errors(include_input=False))) from None
    with SessionLocal() as db:
        admin = db.execute(text("select id,is_active from platform_admins where email=:email for update"),
                           {"email": payload.email}).mappings().first()
        if args.reset_password:
            if not admin:
                raise SystemExit("Platform administrator not found; no credentials changed")
            if not admin["is_active"]:
                raise SystemExit("Platform administrator is inactive; password reset does not reactivate accounts")
            db.execute(text("update platform_admins set password_hash=:hash where id=:admin"),
                       {"hash": password_hash(password), "admin": admin["id"]})
            db.execute(text("delete from platform_sessions where admin_id=:admin"), {"admin": admin["id"]})
            db.execute(text("insert into platform_audit(admin_id,action) values(:admin,'PASSWORD_RESET')"),
                       {"admin": admin["id"]})
            db.commit()
            print("Platform password reset. Existing platform sessions revoked.")
            return
        if admin:
            raise SystemExit("Platform administrator already exists; refusing to overwrite credentials")
        db.execute(text("insert into platform_admins(email,display_name,password_hash) values(:email,:name,:hash)"),
                   {"email": payload.email, "name": payload.display_name, "hash": password_hash(password)})
        db.commit()
    print("Platform administrator created.")


if __name__ == "__main__":
    main()
