import json
import os
import runpy
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch
from uuid import uuid4
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai.actions import ACTIONS, ActionAssistantOutput, OfferDraft, VariantUpdateDraft
from app.ai.capabilities import REGISTRY, execute_lookup
from app.ai.drafts import available_actions
from app.ai.execution import ExecutionService
from app.ai.operations_writes import OPERATIONS_ACTIONS
from app.ai.reports import download, generate
from app.ai.schemas import BusinessLookupArguments, ReadLookup
from app.ai.service import AssistantService
from app.ai.provider import response_schema
from test_ai_execution import AIDatabaseFixture

NEW_READS = {"borrowing_entries", "stock_transfers", "stock_movements", "movement_sources", "variants",
             "vendor_offers", "collection_reminders", "reminder_history", "account_journal", "audit_events", "product_details", "business_payments"}


class OperationsContractTests(unittest.TestCase):
    def test_report_exact_record_and_byte_limits(self):
        from app.ai.reports import MAX_REPORT_BYTES
        db = Mock()
        db.info = {"tenant_context": {"role": "owner", "modules": None, "store_ids": None}}
        db.execute.return_value.scalar_one.return_value = 5000
        content = ("h" * 4999 + "\n") + ("x" * 998 + "\n") * 5000
        values = {"kind": "account_transactions", "from_date": "2026-01-01", "to_date": "2026-01-02"}
        with patch("app.ai.reports.AccountsService.export_transactions_csv", return_value=content) as export:
            raw, preview = generate(db, str(uuid4()), "report_export", values)
            self.assertEqual((len(raw), preview["bytes"], preview["rows"]), (MAX_REPORT_BYTES, MAX_REPORT_BYTES, 5000))
            export.return_value = content + "x"
            with self.assertRaises(HTTPException) as too_large:
                generate(db, str(uuid4()), "report_export", values)
            self.assertEqual(too_large.exception.status_code, 422)
            export.reset_mock()
            db.execute.return_value.scalar_one.return_value = 5001
            with self.assertRaises(HTTPException):
                generate(db, str(uuid4()), "report_export", values)
            export.assert_not_called()

    def test_all_enabled_contracts_fit_the_existing_paid_input_bound(self):
        db = Mock()
        db.execute.side_effect = [
            Mock(mappings=Mock(return_value=Mock(one=Mock(return_value={"company_name": "Synthetic", "gst_registered": False})))),
            Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[])))),
            Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[])))),
            Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[])))),
            Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[])))),
        ]
        service = AssistantService(db, {"company_id": str(uuid4()), "user_id": str(uuid4())})
        actions = [{"key": key, "schema": action.schema.model_json_schema(), "description": action.description,
                    "target_required": bool(action.target)} for key, action in ACTIONS.items()]
        reads = [{"key": key, "description": item.description} for key, item in REGISTRY.items()]
        schema_bytes = len(json.dumps(response_schema(ActionAssistantOutput)).encode())
        budget = min(15000, 20000 - 4000 - schema_bytes - 512)
        context = service.context(uuid4(), reads, max_bytes=budget, actions=actions)
        self.assertLessEqual(len(context.encode()) + 4000 + schema_bytes + 512, 20000)
        for key in [*ACTIONS, *REGISTRY]:
            self.assertIn(key, context)
        self.assertIn("draft_contracts", context)
        from app.ai.service import SYSTEM
        data = json.loads(context[len(SYSTEM):])
        for action in ("purchase_create", "invoice_create", "stock_transfer"):
            contract = data["draft_contracts"][data["available_draft_actions"][action][1]]
            self.assertIn("product_id", contract["nested"]["lines"])
            self.assertIn("quantity", contract["nested"]["lines"])
        purchase = data["draft_contracts"][data["available_draft_actions"]["purchase_create"][1]]
        self.assertIn("selling_price", purchase["nested"]["lines"])
        self.assertIn("price_includes_gst", purchase["nested"]["lines"])
        self.assertIn("fully_paid", purchase["fields"])

    def test_filters_and_manual_boundaries_are_explicit(self):
        self.assertFalse({"period_close", "period_reopen", "reset_all", "invoice_delete", "online_customer_link"} & set(ACTIONS))
        for key in NEW_READS:
            lookup = ReadLookup(capability=key, arguments=BusinessLookupArguments(
                query="", limit=2, store_id=None, from_date=None, to_date=None, as_of=None, status=None))
            self.assertEqual(lookup.capability, key)
        self.assertTrue(ACTIONS["receivable_status"].high_impact)
        self.assertTrue(ACTIONS["product_merge"].high_impact)
        self.assertTrue(ACTIONS["account_transaction_reverse"].high_impact)
        self.assertTrue(ACTIONS["stock_transfer_reverse"].high_impact)


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Authorised isolated database required")
class OperationsMigrationTests(unittest.TestCase):
    def test_upgrade_roundtrip_defaults_and_executed_outcome_guard(self):
        from app.core.database import engine
        migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic" / "versions" / "049_ai_operations.py"))
        with engine.connect() as connection:
            name = connection.execute(text("select current_database()")).scalar_one()
            if not name.startswith("tenali_ai_write_test_") or name != os.getenv("TENALI_AI_ISOLATED_DB"):
                raise RuntimeError("Operations migration tests refuse a non-isolated database.")
            connection.rollback()
            transaction = connection.begin()
            schema = "ai_operations_migration_" + uuid4().hex[:12]
            try:
                connection.exec_driver_sql(f'create schema "{schema}"; set local search_path to "{schema}",public')
                connection.exec_driver_sql("""
                    create table tenant_users(company_id uuid,id uuid,primary key(company_id,id));
                    create table ai_executions(id uuid primary key,company_id uuid,user_id uuid,draft_id uuid);
                    create table stock_transfers(id uuid primary key,lines jsonb,reversal_of_transfer_id uuid);
                    create table ai_action_controls(key text primary key,enabled bool default false,execution_enabled bool default false,
                        fingerprint text not null default '',version int default 1);
                    create table ai_capabilities(key text primary key,enabled bool default false,schema_fingerprint text not null default '',version int default 1);
                    create table ai_action_drafts(id uuid primary key,action_key text,status text,payload jsonb,validation jsonb,
                        approved_version int,approved_at timestamptz,version int default 1);
                """)
                with Operations.context(MigrationContext.configure(connection)):
                    migration["upgrade"]()
                    self.assertEqual(connection.execute(text("select count(*) from ai_action_controls where not enabled and not execution_enabled and fingerprint=''")).scalar_one(), 27)
                    self.assertEqual(connection.execute(text("select count(*) from ai_capabilities where not enabled and schema_fingerprint=''")).scalar_one(), 12)
                    connection.execute(text("""insert into ai_action_drafts(id,action_key,status,payload,approved_version,approved_at)
                        values(:id,'account_create','approved','{"nickname":"synthetic"}',1,now())"""), {"id": uuid4()})
                    migration["downgrade"]()
                    row = connection.execute(text("select status,payload,approved_version from ai_action_drafts")).mappings().one()
                    self.assertEqual((row["status"], row["payload"], row["approved_version"]), ("discarded", {}, None))
                    migration["upgrade"]()
                    connection.execute(text("""insert into ai_executions(id,company_id,user_id,draft_id)
                        select :id,:company,:user,id from ai_action_drafts"""),
                        {"id": uuid4(), "company": uuid4(), "user": uuid4()})
                    with self.assertRaises(DBAPIError):
                        with connection.begin_nested():
                            migration["downgrade"]()
                    self.assertEqual(connection.execute(text("select count(*) from ai_executions")).scalar_one(), 1)
                    self.assertIsNotNone(connection.execute(text("select to_regclass('ai_report_files')")).scalar_one())
            finally:
                transaction.rollback()


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Authorised isolated committed database required")
class OperationsDatabaseTests(AIDatabaseFixture):
    def test_changed_merge_dependencies_and_private_report_expiry(self):
        from app.schemas.inventory import ProductInput, VendorOfferInput
        from app.services.inventory_service import InventoryService
        with self.factory() as db:
            assistant = self.service(db)
            company = self.identity["company_id"]
            vendor = str(db.execute(text("""insert into parties(company_id,party_type,legal_name)
                values(:company,'vendor','Merge dependency fixture') returning id"""), {"company": company}).scalar_one())
            db.commit()
            inventory = InventoryService(db, company)
            draft = str(inventory.save_product(ProductInput(name="Merge changing draft", selling_price="10", catalog_visible=False))["id"])
            target = str(inventory.save_product(ProductInput(name="Merge target", selling_price="10", catalog_visible=False))["id"])
            db.execute(text("update products set is_draft=true where id=:id"), {"id": draft})
            db.commit()
            inventory.save_offer(draft, VendorOfferInput(vendor_id=vendor, mrp="20", buying_price="8"))
            assistant, row, approval = self.approved(db, action="product_merge", target_id=draft,
                                                   payload={"target_product_id": target})
            self.assertIn("dependency_hashes", row["validation"]["preview"])
            db.execute(text("update vendor_contributions set buying_price=9 where product_id=:id"), {"id": draft})
            db.commit()
            approval.confirm_text = row["validation"]["preview"]["confirm_text"]
            with self.assertRaises(HTTPException) as stale:
                ExecutionService(assistant).execute(row["id"], approval)
            self.assertEqual(stale.exception.status_code, 409)
            self.assertIsNotNone(db.execute(text("select id from products where id=:id"), {"id": draft}).scalar_one_or_none())
            db.rollback()
            today = date.today().isoformat()
            assistant, row, approval = self.approved(db, action="report_export",
                payload={"kind": "account_transactions", "from_date": today, "to_date": today})
            outcome = ExecutionService(assistant).execute(row["id"], approval)
            self.assertEqual(outcome["status"], "succeeded", outcome)
            with patch("app.ai.drafts.current_identity", return_value={**self.identity, "role": "staff", "modules": ["reports"]}):
                with self.assertRaises(HTTPException) as revoked:
                    download(self.service(db), outcome["id"])
                self.assertEqual(revoked.exception.status_code, 403)
            self.service(db)
            db.execute(text("update ai_report_files set expires_at=now()-interval '1 second' where id=:id"), {"id": outcome["id"]})
            db.commit()
            with self.assertRaises(HTTPException) as expired:
                download(self.service(db), outcome["id"])
            self.assertEqual(expired.exception.status_code, 410)
            self.assertTrue(db.execute(text("select has_column_privilege('tenali_runtime','stock_transfers','lines','UPDATE')")).scalar_one())
            self.assertFalse(db.execute(text("select has_column_privilege('tenali_runtime','stock_transfers','reversal_of_transfer_id','UPDATE')")).scalar_one())

    def test_business_payment_purposes_and_linked_borrowing_reversal(self):
        today = date.today().isoformat()
        with self.factory() as db:
            def post(action, payload, target=None):
                assistant, row, approval = self.approved(db, action=action, payload=payload, target_id=target)
                if ACTIONS[action].high_impact:
                    approval.confirm_text = row["validation"]["preview"]["confirm_text"]
                result = ExecutionService(assistant).execute(row["id"], approval)
                self.assertEqual(result["status"], "succeeded", result)
                replay = ExecutionService(self.service(db)).execute(row["id"], approval)
                self.assertEqual(result["result"], replay["result"])
                return result["result"]
            party = str(post("party_create", {"party_type": "customer_vendor", "legal_name": "Standalone payment fixture"})["id"])
            account = str(post("account_create", {"nickname": "Standalone payment cash", "account_type": "cash",
                "party_id": party, "is_company_account": False, "opening_balance": "0"})["id"])
            results = []
            for purpose in ("purchase", "billing", "expense"):
                results.append(post("business_payment_create", {"from_account_id": account, "purpose": purpose,
                    "related_party_id": party, "amount": "1.25", "payment_mode": "Cash", "notes": "Standalone outflow",
                    "transaction_date": today, "create_borrowing": True}))
            self.assertTrue(all(result["borrowing_id"] for result in results))
            transaction = str(results[0]["id"])
            post("account_transaction_reverse", {"transaction_date": today, "notes": "Reverse standalone borrowing outflow"}, transaction)
            args = BusinessLookupArguments(query="business_", store_id=None, limit=10, from_date=None, to_date=None, as_of=None, status=None)
            payments = execute_lookup(db, self.identity, ReadLookup(capability="business_payments", arguments=args))
            self.assertEqual(len(payments["items"]), 3)
            self.assertTrue(all(row["direction"] == "OUTFLOW" for row in payments["items"]))
            self.assertEqual(sum(row["is_reversed"] for row in payments["items"]), 1)
            ledger = execute_lookup(db, self.identity, ReadLookup(capability="transactions", arguments=args))
            self.assertEqual(len(ledger["items"]), 4)
            self.assertEqual(sum(row["direction"] == "INFLOW" for row in ledger["items"]), 1)
            from app.services.settlements_service import SettlementsService
            summary = SettlementsService(db).summarize_borrowings(self.identity["company_id"], search="Standalone payment fixture", limit=2)
            self.assertEqual(str(summary["items"][0]["net_outstanding"]), "2.50")
            with self.assertRaises(HTTPException):
                self.approved(db, action="account_transaction_reverse", target_id=transaction,
                    payload={"transaction_date": today, "notes": "Duplicate reversal"})
            db.rollback()

    def test_variant_and_offer_outcomes_identify_the_saved_child_and_replay(self):
        from app.schemas.inventory import ProductInput
        from app.services.inventory_service import InventoryService
        with self.factory() as db:
            self.service(db)
            company = self.identity["company_id"]
            vendor = str(db.execute(text("""insert into parties(company_id,party_type,legal_name)
                values(:company,'vendor','Child outcome vendor') returning id"""), {"company": company}).scalar_one())
            db.commit()
            product = str(InventoryService(db, company).save_product(
                ProductInput(name="Child outcome product", selling_price="10", catalog_visible=False))["id"])

            def post(action, payload, target=None):
                assistant, row, approval = self.approved(db, action=action, payload=payload, target_id=target)
                outcome = ExecutionService(assistant).execute(row["id"], approval)
                self.assertEqual(outcome["status"], "succeeded", outcome)
                self.assertEqual(outcome["result"]["product_id"], product)
                self.assertNotEqual(outcome["result"]["id"], product)
                with self.factory() as retry:
                    replay = ExecutionService(self.service(retry)).execute(row["id"], approval)
                    self.assertEqual(replay["result"], outcome["result"])
                return outcome["result"]["id"]

            variant = post("variant_create", {"product_id": product, "variant_name": "Child variant",
                "pricing_mode": "price", "selling_price": "10"})
            self.assertEqual(post("variant_update", VariantUpdateDraft(product_id=product, variant_name="Updated child",
                pricing_mode="price", selling_price="11").model_dump(mode="json"), variant), variant)
            offer = post("offer_create", {"product_id": product, "vendor_id": vendor, "mrp": "20", "buying_price": "8"})
            self.assertEqual(post("offer_update", OfferDraft(product_id=product, vendor_id=vendor,
                mrp="21", buying_price="9").model_dump(mode="json"), offer), offer)
            self.assertEqual(str(db.execute(text("select id from product_variants where product_id=:id"),
                {"id": product}).scalar_one()), variant)
            self.assertEqual(str(db.execute(text("select id from vendor_contributions where product_id=:id"),
                {"id": product}).scalar_one()), offer)

    def test_every_new_action_and_read_with_replay_and_private_reports(self):
        from app.schemas.inventory import StockAdjustment
        from app.services.inventory_service import InventoryService
        today = date.today().isoformat()
        due = (date.today() - timedelta(days=1)).isoformat()
        completed = set()
        reports = []
        with self.factory() as db:
            company = self.identity["company_id"]
            db.execute(text("update companies set address='Synthetic Chennai',gst_registered=false where id=:company"), {"company": company})
            store = str(db.execute(text("select id from stores where company_id=:company and is_default"), {"company": company}).scalar_one())
            second = str(db.execute(text("""insert into stores(company_id,code,name,kind,holds_stock,state_code)
                values(:company,:code,'Synthetic second','offline',true,'33') returning id"""),
                {"company": company, "code": "O" + uuid4().hex[:5].upper()}).scalar_one())
            db.execute(text("""insert into hsn_masters(company_id,code,description,gst_rate,is_active)
                values(:company,'7408','Synthetic HSN',18,true) on conflict do nothing"""), {"company": company})
            db.commit()

            def post(action, payload, target=None):
                assistant, row, approval = self.approved(db, action=action, payload=payload, target_id=target)
                if ACTIONS[action].high_impact:
                    self.assertTrue(row["high_impact"])
                    with self.assertRaises(HTTPException) as missing:
                        ExecutionService(assistant).execute(row["id"], approval)
                    self.assertEqual(missing.exception.status_code, 422)
                    approval.confirm_text = row["validation"]["preview"]["confirm_text"]
                outcome = ExecutionService(assistant).execute(row["id"], approval)
                self.assertEqual(outcome["status"], "succeeded", outcome)
                with self.factory() as retry_db:
                    replay = ExecutionService(self.service(retry_db)).execute(row["id"], approval)
                    self.assertEqual(replay["id"], outcome["id"])
                    self.assertEqual(replay["result"], outcome["result"])
                completed.add(action)
                if "report_id" in outcome["result"]:
                    reports.append((row, outcome))
                return outcome["result"]

            party = str(post("party_create", {"party_type": "customer_vendor", "legal_name": "Operations fixture vendor", "address": "Synthetic Chennai"})["id"])
            account = str(post("account_create", {"nickname": "Operations cash", "account_type": "cash",
                "party_id": party, "is_company_account": False, "opening_balance": "123.45"})["id"])
            post("account_update", {"nickname": "Renamed Operations cash"}, account)
            post("business_payment_create", {"from_account_id": account, "purpose": "billing", "related_party_id": party,
                "amount": "2.25", "payment_mode": "Cash", "notes": "Standalone outflow, not customer collection",
                "transaction_date": today, "create_borrowing": False})
            self.assertEqual(str(db.execute(text("select party_id from accounts where id=:id"), {"id": account}).scalar_one()), party)
            manual = str(post("account_transaction_create", {"to_account_id": account, "amount": "10.25",
                "payment_mode": "Cash", "description": "Synthetic manual inflow", "transaction_date": today})["id"])
            post("account_transaction_reverse", {"transaction_date": today, "notes": "Synthetic correction"}, manual)
            with self.assertRaises(HTTPException):
                self.approved(db, action="account_update", target_id=account, payload={"opening_balance": "124.45"})
            db.rollback()
            post("borrowing_create", {"party_id": party, "direction": "borrow", "amount": "20.25",
                "account_id": account, "create_account_transaction": True, "transaction_date": today})
            post("borrowing_create", {"party_id": party, "direction": "repay", "amount": "5.25",
                "account_id": account, "create_account_transaction": True, "transaction_date": today})
            receivable = str(post("receivable_create", {"party_id": party, "amount_due": "30.25", "due_date": due})["id"])
            post("receivable_reminder", {"next_reminder_date": due, "notes": "Synthetic reminder"}, receivable)
            post("receivable_status", {"status": "BAD_DEBT", "bad_debt_reason": "Synthetic approved write-off",
                "reminder_date": due}, receivable)
            post("receivable_create", {"party_id": party, "amount_due": "8.25", "due_date": due})
            brand = str(post("brand_create", {"name": "Operations brand"})["id"])
            post("brand_update", {"name": "Updated Operations brand", "description": "Synthetic", "is_active": True}, brand)
            category = str(post("category_create", {"name": "Operations category"})["id"])
            post("category_update", {"name": "Updated Operations category", "description": "Synthetic", "is_active": True}, category)
            product = str(post("product_create", {"name": "Operations wire", "selling_price": "118", "hsn_code": "7408",
                "catalog_visible": False, "brand_id": brand, "category_id": category})["id"])
            variant = str(post("variant_create", {"product_id": product, "variant_name": "Small wire", "size": "Small", "pricing_mode": "price", "selling_price": "100"})["id"])
            post("variant_update", VariantUpdateDraft(product_id=product, variant_name="Updated small wire",
                size="Small", pricing_mode="price", selling_price="101").model_dump(mode="json"), variant)
            offer = str(post("offer_create", {"product_id": product, "vendor_id": party, "mrp": "200", "buying_price": "80"})["id"])
            post("offer_update", OfferDraft(product_id=product, vendor_id=party, mrp="210", buying_price="81").model_dump(mode="json"), offer)
            post("offer_create", {"product_id": product, "variant_id": variant, "vendor_id": party, "mrp": "210", "buying_price": "81"})
            other_vendor = str(post("party_create", {"party_type": "vendor", "legal_name": "Operations bulk vendor"})["id"])
            self.assertEqual(post("vendor_bulk_map", {"vendor_id": other_vendor, "product_ids": [product]})["mapped_count"], 1)
            post("reorder_reminder", {"variant_id": variant, "reminder_date": due}, product)
            draft_product = str(post("product_create", {"name": "Operations confirm draft", "hsn_code": "7408",
                "selling_price": "20", "catalog_visible": False})["id"])
            self.service(db)
            db.execute(text("update products set is_draft=true where id=:id"), {"id": draft_product})
            db.commit()
            post("product_confirm", {}, draft_product)
            merge_product = str(post("product_create", {"name": "Operations merge draft", "hsn_code": "7408",
                "selling_price": "20", "catalog_visible": False})["id"])
            self.service(db)
            db.execute(text("update products set is_draft=true where id=:id"), {"id": merge_product})
            db.commit()
            post("stock_adjust", {"store_id": store, "direction": "IN", "quantity": "3", "notes": "Synthetic draft stock"}, merge_product)
            post("product_merge", {"target_product_id": product, "target_variant_id": variant}, merge_product)
            self.assertEqual(db.execute(text("select quantity from stock_balances where product_id=:id and variant_id=:variant"),
                {"id": product, "variant": variant}).scalar_one(), 3)
            post("stock_adjust", {"store_id": store, "direction": "IN", "quantity": "10", "notes": "Synthetic base stock"}, product)
            transfer = str(post("stock_transfer", {"from_store_id": store, "to_store_id": second, "transfer_date": today,
                "notes": "Synthetic transfer", "lines": [{"product_id": product, "quantity": "2"}]})["id"])
            reversed_transfer = post("stock_transfer_reverse", {"notes": "Synthetic transfer correction"}, transfer)
            self.assertEqual(str(reversed_transfer["reversal_of_transfer_id"]), transfer)
            self.assertEqual(db.execute(text("select quantity from stock_balances where product_id=:product and store_id=:store and variant_id is null"),
                {"product": product, "store": second}).scalar_one(), 0)
            self.service(db)
            InventoryService(db, company).adjust_stock(product, StockAdjustment(store_id=store, direction="IN", quantity="1",
                notes="Synthetic missing source"), reference_type="invoice", reference_id=str(uuid4()))
            movement = str(db.execute(text("select id from stock_movements where product_id=:id and reference_type='invoice'"),
                {"id": product}).scalar_one())
            # Check the missing-source read before correcting its sole fixture.
            args = BusinessLookupArguments(query="", store_id=None, limit=2, from_date=None, to_date=None, as_of=None, status=None)
            missing = execute_lookup(db, self.identity, ReadLookup(capability="movement_sources", arguments=args))
            self.assertIn(movement, [str(row["id"]) for row in missing["items"]])
            post("movement_attribute", {"external_reference": "OUTSIDE-01", "notes": "Synthetic attribution"}, movement)
            self.assertEqual(db.execute(text("select reference_type from stock_movements where id=:id"), {"id": movement}).scalar_one(), "external_document")
            line = {"product_id": product, "variant_id": variant, "description": "Operations wire", "hsn": "7408", "quantity": "2", "rate": "100", "price_includes_gst": False}
            purchase = str(post("purchase_create", {"store_id": store, "vendor_party_id": party, "purchase_date": today,
                "received_now": False, "lines": [line]})["id"])
            post("purchase_receive", {"receipt_type": None, "received_at": None, "received_notes": "Received synthetic goods"}, purchase)
            post("purchase_payment", {"account_id": account, "amount": "25", "payment_mode": "Cash", "payment_date": today}, purchase)
            post("purchase_cancel", {"reason": "Synthetic cancellation", "cancellation_date": today, "reverse_payments": True}, purchase)
            refund = str(db.execute(text("select id from refund_settlements where document_id=:id"), {"id": purchase}).scalar_one())
            before = db.execute(text("select count(*) from account_transactions where company_id=:company"), {"company": company}).scalar_one()
            post("refund_settle", {"account_id": account, "settled_on": today, "payment_mode": "Cash", "notes": "Synthetic vendor refund"}, refund)
            self.assertEqual(db.execute(text("select count(*) from account_transactions where company_id=:company"), {"company": company}).scalar_one(), before)
            self.check_reads_and_reports(db, post, reports, product)
            self.assertEqual(completed & OPERATIONS_ACTIONS, OPERATIONS_ACTIONS)

    def check_reads_and_reports(self, db, post, reports, product):
        company = self.identity["company_id"]
        today = date.today().isoformat()
        # Audit content is trigger-owned; administrative fixtures must not weaken runtime grants.
        with self.factory() as admin:
            admin.execute(text("""insert into audit_events(company_id,action,entity_type,entity_id,old_value,new_value)
                values(:company,'SYNTHETIC','product',:id,'{"private":"old secret"}','{"private":"new secret"}')"""),
                {"company": company, "id": product})
            admin.commit()
        self.service(db)
        args = BusinessLookupArguments(query="", store_id=None, limit=2, from_date=None, to_date=None, as_of=None, status=None)
        for key in NEW_READS:
            with self.subTest(read=key):
                result = execute_lookup(db, self.identity, ReadLookup(capability=key, arguments=args))
                self.assertLessEqual(len(result["items"]), 2)
                self.assertEqual(set(result), {"capability", "items", "more_matches", "note"})
                for item in result["items"]:
                    self.assertEqual(set(item), set(REGISTRY[key].fields))
                self.assertNotIn("old secret", json.dumps(result, default=str))
                self.assertNotIn("new secret", json.dumps(result, default=str))
                if key == "product_details" and result["items"]:
                    self.assertIsInstance(result["items"][0]["image_urls"], list)
        for kind in ("account_transactions", "account_journal", "sales_register", "purchase_register", "ar_aging", "ap_aging"):
            post("report_export", {"kind": kind, **({"as_of": today} if kind.endswith("_aging") else {"from_date": today, "to_date": today})})
        post("gst_reconcile", {"from_date": today, "to_date": today,
            "csv_text": "supplier_gstin,invoice_number,invoice_date,taxable_value,cgst,sgst,igst,cess\n"})
        for row, outcome in reports:
            with self.subTest(report=outcome["result"]["report_id"]):
                response = download(self.service(db), outcome["id"])
                expected, _ = generate(db, company, row["action_key"], row["payload"])
                self.assertEqual(response.body, expected)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertNotIn("content", outcome["result"])
                self.assertNotIn("csv_text", outcome["result"])
        row, outcome = reports[0]
        self.service(db).delete(row["conversation_id"], 1)
        self.assertIsNone(db.execute(text("select content from ai_report_files where id=:id"), {"id": outcome["id"]}).scalar_one())
        with self.assertRaises(HTTPException):
            download(self.service(db), outcome["id"])
        with self.factory() as other_db:
            other_db.info["tenant_context"] = {**self.identity, "user_id": str(uuid4())}
            self.assertEqual(other_db.execute(text("select count(*) from ai_report_files")).scalar_one(), 0)

    def test_new_permissions_store_isolation_and_reference_changes(self):
        with self.factory() as db:
            assistant = self.service(db)
            identity = {**self.identity, "role": "staff", "store_ids": [], "modules": ["inventory"]}
            self.assertFalse({item["key"] for item in available_actions(db, identity)} & {
                "account_create", "account_update", "account_transaction_create", "borrowing_create",
                "report_export", "gst_reconcile", "product_merge", "stock_transfer_reverse", "receivable_status"})
            args = BusinessLookupArguments(query="", store_id=None, limit=2, from_date=None, to_date=None, as_of=None, status=None)
            for key in ("stock_transfers", "stock_movements", "movement_sources"):
                result = execute_lookup(db, identity, ReadLookup(capability=key, arguments=args))
                self.assertEqual(result["items"], [])
            for key in ("account_journal", "borrowing_entries", "audit_events"):
                with self.assertRaises(HTTPException) as denied:
                    execute_lookup(db, identity, ReadLookup(capability=key, arguments=args))
                self.assertEqual(denied.exception.status_code, 403)
            self.service(db)
            assistant, row, approval = self.approved(db, action="account_create",
                payload={"nickname": "Atomic unposted account", "account_type": "cash", "opening_balance": "0", "is_company_account": False})
            original = __import__("app.ai.execution", fromlist=["apply_action"]).apply_action
            def fail_after_new_write(*arguments, **keywords):
                original(*arguments, **keywords)
                raise HTTPException(422, "Synthetic late Operations failure")
            with patch("app.ai.execution.apply_action", side_effect=fail_after_new_write):
                result = ExecutionService(assistant).execute(row["id"], approval)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(db.execute(text("select count(*) from accounts where nickname='Atomic unposted account'")).scalar_one(), 0)


if __name__ == "__main__":
    unittest.main()
