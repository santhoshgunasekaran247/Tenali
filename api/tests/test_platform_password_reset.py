import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text

from app.bootstrap_platform import main
from app.services.tenant_security import password_hash, password_matches
from test_tenancy import TenantDatabaseCase


class PlatformPasswordResetTests(TenantDatabaseCase):
    def reset(self, email, password="New platform password 123!"):
        with patch("sys.argv", ["bootstrap_platform", "--email", email, "--reset-password"]), \
                patch("app.bootstrap_platform.getpass.getpass", side_effect=[password, password]), \
                patch("app.bootstrap_platform.SessionLocal", self.factory):
            main()

    def test_reset_revokes_only_target_sessions_and_audits(self):
        target, other = uuid4(), uuid4()
        email = "reset-" + self.suffix + "@example.com"
        old_hash = password_hash("Old platform password 123!")
        with self.factory() as db:
            for admin, address in [(target, email), (other, "other-" + email)]:
                db.execute(text("""insert into platform_admins(id,email,display_name,password_hash)
                    values(:id,:email,'Reset fixture',:hash)"""),
                    {"id": admin, "email": address, "hash": old_hash})
                db.execute(text("""insert into platform_sessions(token_hash,admin_id,expires_at)
                    values(:token,:admin,now()+interval '1 hour')"""), {"token": str(admin), "admin": admin})
            db.commit()
        self.reset("  " + email.upper() + "  ")
        with self.factory() as db:
            admins = dict(db.execute(text("select id,password_hash from platform_admins where id in (:a,:b)"),
                                     {"a": target, "b": other}).all())
            self.assertTrue(password_matches("New platform password 123!", admins[target]))
            self.assertFalse(password_matches("Old platform password 123!", admins[target]))
            self.assertEqual(admins[other], old_hash)
            self.assertEqual(db.execute(text("select admin_id from platform_sessions where admin_id in (:a,:b)"),
                                        {"a": target, "b": other}).scalars().all(), [other])
            self.assertEqual(db.execute(text("select action from platform_audit where admin_id=:id"),
                                        {"id": target}).scalars().all(), ["PASSWORD_RESET"])

    def test_missing_and_inactive_accounts_are_not_changed(self):
        email = "inactive-" + self.suffix + "@example.com"
        with self.assertRaisesRegex(SystemExit, "not found"):
            self.reset(email)
        old_hash = password_hash("Old platform password 123!")
        with self.factory() as db:
            db.execute(text("""insert into platform_admins(email,display_name,password_hash,is_active)
                values(:email,'Inactive fixture',:hash,false)"""), {"email": email, "hash": old_hash})
            db.commit()
        with self.assertRaisesRegex(SystemExit, "inactive"):
            self.reset(email)
        with self.factory() as db:
            row = db.execute(text("select password_hash,is_active from platform_admins where email=:email"),
                             {"email": email}).one()
            self.assertEqual(row.password_hash, old_hash)
            self.assertFalse(row.is_active)


class PlatformPasswordPromptTests(unittest.TestCase):
    def test_invalid_or_mismatched_password_never_opens_database(self):
        for passwords in [("short", "short"), ("x" * 129, "x" * 129), ("First password 123!", "Different password 123!")]:
            with self.subTest(length=len(passwords[0])), \
                    patch("sys.argv", ["bootstrap_platform", "--email", "operator@example.com", "--reset-password"]), \
                    patch("app.bootstrap_platform.getpass.getpass", side_effect=passwords), \
                    patch("app.bootstrap_platform.SessionLocal") as factory:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertNotIn(passwords[0], str(error.exception))
                factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
