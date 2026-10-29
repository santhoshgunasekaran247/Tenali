"""Administrator-only bootstrap for an existing company's initial owner."""

import argparse
import getpass

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.tenant_security import Registration,password_hash


def main():
    parser=argparse.ArgumentParser(description="Create an owner for an existing company; passwords are entered privately in the terminal.")
    parser.add_argument("--company-id",required=True)
    parser.add_argument("--email",required=True)
    parser.add_argument("--name",required=True)
    args=parser.parse_args()
    password=getpass.getpass("Owner password (minimum 12 characters): ")
    if password!=getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords did not match")
    validated=Registration(company_name="Bootstrap",slug="bootstrap-owner",email=args.email,display_name=args.name,password=password)
    with SessionLocal() as db:
        company=db.execute(text("select id,tenant_slug from companies where id=:id and is_active=true for update"),{"id":args.company_id}).mappings().first()
        if not company:
            raise SystemExit("Company not found")
        if db.execute(text("select user_id from tenant_memberships where company_id=:company and role='owner' and is_active=true"),{"company":args.company_id}).first():
            raise SystemExit("Company already has an owner; use normal team administration")
        user=db.execute(text("insert into tenant_users(company_id,email,display_name,password_hash) values(:company,:email,:name,:hash) returning id"),
                        {"company":args.company_id,"email":validated.email,"name":validated.display_name,"hash":password_hash(password)}).scalar_one()
        db.execute(text("insert into tenant_memberships(company_id,user_id,role) values(:company,:user,'owner')"),{"company":args.company_id,"user":user})
        db.commit()
        print("Owner created. Workspace address:",company["tenant_slug"])


if __name__=="__main__":
    main()