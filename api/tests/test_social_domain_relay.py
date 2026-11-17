import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.services import social_domain_relay as relay


class SocialDomainRelayTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TENALI_CREDENTIAL_KEY": Fernet.generate_key().decode()})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = MagicMock()
        self.row = {"id": str(uuid4()), "company_id": str(uuid4()), "hostname": "sourcedbysru.in", "result_ciphertext": None}
        self.db.execute.return_value.mappings.return_value.first.return_value = self.row

    def test_completion_encrypts_tokens_and_poll_consumes_once(self):
        result = {"accessToken": "private-fixture-token", "email": "fixture@example.com", "expiresAt": 9999999999}
        relay.complete_relay(self.db, self.row["id"], "secret-key", result, "sourcedbysru.in")
        ciphertext = self.db.execute.call_args.args[1]["result"]
        self.assertNotIn(result["accessToken"], ciphertext)
        self.row["result_ciphertext"] = ciphertext
        response = relay.poll_relay(self.db, self.row["id"], "secret-key", self.row["company_id"], "sourcedbysru.in")
        self.assertEqual(response, {"pending": False, "result": result})
        self.assertIn("delete from tenant_social_relays", str(self.db.execute.call_args.args[0]))

    def test_foreign_tenant_and_domain_cannot_poll(self):
        for company, host in [(str(uuid4()), "sourcedbysru.in"), (self.row["company_id"], "other.in")]:
            with self.assertRaises(HTTPException) as error:
                relay.poll_relay(self.db, self.row["id"], "key", company, host)
            self.assertEqual(error.exception.status_code, 403)
        self.db.commit.assert_not_called()

    def test_expired_or_invalid_secret_fails_explicitly(self):
        self.db.execute.return_value.mappings.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as error:
            relay.relay_row(self.db, self.row["id"], "wrong-key")
        self.assertEqual(error.exception.status_code, 410)

    def test_pending_result_never_returns_a_token_and_secrets_are_hashed(self):
        response = relay.poll_relay(self.db, self.row["id"], "fixture-secret", self.row["company_id"], "sourcedbysru.in")
        self.assertEqual(response, {"pending": True})
        query = self.db.execute.call_args.args[1]
        self.assertNotEqual(query["key"], "fixture-secret")
        self.assertEqual(len(query["key"]), 64)
