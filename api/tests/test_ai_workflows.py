import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.actions import ACTIONS, DraftProposal
from app.ai.service import SYSTEM
from app.ai.workflows import (REFERENCES, REPLACEMENTS, TARGETS, WorkflowCreate,
    WorkflowEdit, WorkflowService, business_payload, choice_value, coerce_payload, keep_line_products, merge_known, missing_fields, next_entries,
    normalize_choices, normalize_document_proposal, normalize_purchase_proposal, reference_fields, required_fields, step, validate_workflow_payload,
    workflow_schema, workflow_view)


class WorkflowTests(unittest.TestCase):
    def service(self):
        assistant = Mock()
        assistant.scope = {"company": str(uuid4()), "user": str(uuid4())}
        assistant.identity = {"company_id": assistant.scope["company"], "user_id": assistant.scope["user"],
                              "role": "owner", "modules": None, "store_ids": None}
        assistant.conversation.return_value = {"status": "active", "expires_at": datetime.now(timezone.utc) + timedelta(days=30)}
        assistant.db = MagicMock()
        service = WorkflowService(assistant)
        service.actions = set(ACTIONS)
        service.capabilities = {spec[0] for spec in REFERENCES.values()} | {spec[0] for spec in TARGETS.values()} | {"product_details"}
        service.cache = {}
        service.drafts = Mock()
        service.invoice_context = Mock()
        service.drafts.create.side_effect = lambda *args, **kwargs: {"id": uuid4(), "status": "editing"}
        return service

    def workflow(self, action, payload, target=None):
        return {"id": uuid4(), "conversation_id": uuid4(), "status": "active", "version": 1,
                "plan": {"steps": [step(action, payload, target)], "next": []}}

    def test_every_registered_operation_has_a_workflow_and_target_resolver(self):
        for key, action in ACTIONS.items():
            with self.subTest(action=key):
                request = WorkflowCreate(action=key, payload={}, client_key=uuid4())
                self.assertEqual(request.action, key)
                if action.target:
                    self.assertIn(action.target, TARGETS)
                service = self.service()
                row = service.prepare(self.workflow(key, {}))
                root = row["plan"]["steps"][0]
                self.assertTrue(root["issues"] or root["draft_id"])
                service.assistant.db.commit.assert_not_called()
        self.assertIn("For EVERY Operations add/update", SYSTEM)
        self.assertIn("No conversational interrogation", SYSTEM)

    def test_create_workflows_ignore_stray_target_names_from_model_or_legacy_plan(self):
        service = self.service()
        row = self.workflow("party_create", {"legal_name": "Vendor", "party_type": "vendor"}, target="Vendor")
        self.assertIsNone(row["plan"]["steps"][0]["target"])
        row["plan"]["steps"][0]["target"] = "Legacy vendor name"
        prepared = service.prepare(row)
        self.assertIsNone(prepared["plan"]["steps"][0]["target"])
        self.assertIsNone(service.drafts.create.call_args.args[1].target_id)

    def test_known_answers_false_and_zero_are_retained_without_inventing_values(self):
        current = {"received_now": True, "lines": [{"rate": "10", "gst_rate": "5", "price_includes_gst": True}]}
        merged = merge_known(current, {"received_now": False, "amount_paid": 0,
                                      "lines": [{"rate": None, "quantity": "100"}]})
        self.assertIs(merged["received_now"], False)
        self.assertEqual(merged["amount_paid"], 0)
        self.assertEqual(merged["lines"][0], {"rate": "10", "gst_rate": "5",
                                            "price_includes_gst": True, "quantity": "100"})
        self.assertNotIn("purchase_date", merged)
        self.assertEqual(current["received_now"], True)

    def test_incomplete_purchase_collects_missing_fields_together(self):
        payload = {"vendor_party_id": str(uuid4()), "store_id": str(uuid4()), "purchase_date": "2026-11-12",
                   "received_now": True, "amount_paid": 0,
                   "lines": [{"description": "Brass jar", "hsn": "1234", "quantity": "100", "rate": "10",
                              "gst_rate": "5", "price_includes_gst": True}]}
        self.assertEqual(missing_fields("purchase_create", payload), [])
        incomplete = deepcopy(payload)
        del incomplete["purchase_date"]
        del incomplete["lines"][0]["price_includes_gst"]
        fields = {item["field"] for item in missing_fields("purchase_create", incomplete)}
        self.assertEqual(fields, {"purchase_date", "lines.0.price_includes_gst"})
        self.assertIs(payload["lines"][0]["price_includes_gst"], True)

    def test_sale_keeps_invoice_root_and_customer_creation_as_a_bound_prerequisite(self):
        service = self.service()
        product, customer = str(uuid4()), str(uuid4())
        payload = normalize_document_proposal("invoice_create", {
            "customer_party_id": "Vijay", "lines": [{"item_name": "Copper bottle", "quantity": 10,
                "unit_price": 30, "gst_inclusive": True, "gst_rate": 5, "hsn": "1234"}]})
        row = self.workflow("invoice_create", payload)
        def lookup(spec, query):
            rows = [{"id": product, "name": "Copper bottle"}] if spec[0] == "products" else (
                [{"code": "1234", "gst_rate": 5}] if spec[0] == "hsn" else [])
            return {"items": rows, "more_matches": False}
        with patch.object(service, "lookup", side_effect=lookup):
            prepared = service.prepare(row)
        root, child = prepared["plan"]["steps"]
        self.assertEqual(root["action"], "invoice_create")
        self.assertEqual(child["action"], "party_create")
        self.assertEqual(child["payload"], {"legal_name": "Vijay", "party_type": "customer"})
        self.assertEqual(root["bindings"]["customer_party_id"]["step_id"], child["id"])
        self.assertEqual(root["payload"]["lines"][0]["product_id"], product)
        self.assertEqual(root["payload"]["lines"][0]["quantity"], 10)
        self.assertEqual(root["payload"]["lines"][0]["rate"], 30)
        child["draft_id"] = str(uuid4())
        service.drafts.get.return_value = {"id": child["draft_id"], "version": 1,
            "status": "executed", "payload": child["payload"]}
        service.db.execute.return_value.mappings.return_value.one.return_value = {"result": {"id": customer}}
        with patch.object(service, "lookup", side_effect=lookup):
            continued = service.prepare(prepared)
        root = continued["plan"]["steps"][0]
        self.assertEqual(root["payload"]["customer_party_id"], customer)
        self.assertEqual(continued["status"], "active")
        self.assertEqual({issue["field"] for issue in root["issues"]},
                         {"store_id", "invoice_date", "amount_received", "billing_address", "place_of_supply"})
        self.assertEqual(len(continued["plan"]["steps"]), 2)

    def test_sales_cannot_create_unstocked_inventory_as_a_hidden_prerequisite(self):
        service = self.service()
        root = step("invoice_create", {"lines": [{"product_id": "Missing bottle"}]})
        steps = [root]
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            service.resolve(root, ("lines", 0, "product_id"), "Missing bottle", REFERENCES["product_id"], steps)
            choices = service.search_choices("invoice_create", "lines.0.product_id", "Missing bottle")
        self.assertEqual(len(steps), 1)
        self.assertFalse(choices["can_create"])
        self.assertFalse(root["choices"][0]["can_create"])
        self.assertEqual(choices["manual_path"], "/portal/inventory")

    def test_fully_received_sale_uses_computed_invoice_total_and_no_duplicate_actions(self):
        service = self.service()
        row = self.workflow("invoice_create", {"store_id": str(uuid4()), "customer_party_id": str(uuid4()),
            "invoice_date": "2026-11-13", "fully_paid": True, "account_id": str(uuid4()), "payment_mode": "CASH",
            "billing_address": "Test billing address", "place_of_supply": "33 - Tamil Nadu",
            "lines": [{"product_id": str(uuid4()), "description": "Copper bottle", "quantity": 10,
                       "rate": 30, "gst_rate": 5, "hsn": "1234", "price_includes_gst": True}]})
        computed = {**business_payload("invoice_create", row["plan"]["steps"][0]["payload"]), "total": "300.00"}
        with patch.object(service, "lookup", return_value={"items": [{"code": "1234", "gst_rate": 5}], "more_matches": False}), \
             patch("app.ai.business_writes.document_preview", return_value=(computed, {})) as preview:
            service.prepare(row)
        preview.assert_called_once()
        self.assertEqual(preview.call_args.args[3]["amount_received"], "0")
        created = service.drafts.create.call_args.args[1]
        self.assertEqual(created.action, "invoice_create")
        self.assertEqual(created.payload["amount_received"], "300.00")
        self.assertNotIn("fully_paid", created.payload)
        self.assertNotIn("amount_paid", created.payload)
        self.assertEqual(len(row["plan"]["steps"]), 1)
        settled = next_entries("invoice_create", {}, {"id": uuid4(), "total": "300", "amount_received": "300"})
        unpaid = next_entries("invoice_create", {}, {"id": uuid4(), "total": "300", "amount_received": "0"})
        self.assertEqual([entry["action"] for entry in settled], ["invoice_create"])
        self.assertEqual([entry["action"] for entry in unpaid], ["collection_payment", "invoice_create"])

    def test_chat_edits_a_prerequisite_without_losing_its_parent_or_bindings(self):
        service = self.service()
        row = self.workflow("invoice_create", {"customer_party_id": "Vijay", "lines": [{"quantity": 10}]})
        row["action_key"] = "invoice_create"
        child = step("party_create", {"legal_name": "Vijay", "party_type": "customer"})
        child["draft_id"] = str(uuid4())
        row["plan"]["steps"].append(child)
        root = row["plan"]["steps"][0]
        root["bindings"]["customer_party_id"] = {"step_id": child["id"], "path": ["customer_party_id"]}
        old_id = child["id"]
        service.get = Mock(return_value=row)
        service.policies = Mock()
        service.prepare = Mock(side_effect=lambda row: row)
        service.save = Mock(side_effect=lambda row: row)
        service.drafts.get.return_value = {"id": child["draft_id"], "version": 1, "status": "editing",
                                           "payload": child["payload"]}
        service.drafts.lock.return_value = service.drafts.get.return_value
        result = service.from_proposal(row["conversation_id"], DraftProposal(action="party_create",
            workflow_id=row["id"], target_id=None, payload_json='{"nickname":"Vijay shop"}'), uuid4())
        root, child = result["plan"]["steps"]
        self.assertEqual(result["action_key"], "invoice_create")
        self.assertEqual(root["payload"]["lines"][0]["quantity"], 10)
        self.assertEqual(child["payload"]["nickname"], "Vijay shop")
        self.assertNotEqual(child["id"], old_id)
        self.assertEqual(root["bindings"]["customer_party_id"]["step_id"], child["id"])

    def test_invoice_reuses_saved_customer_address_and_blocks_missing_seller_setup(self):
        service = self.service()
        root = step("invoice_create", {"customer_party_id": str(uuid4()), "store_id": str(uuid4())})
        service.drafts.reference.side_effect = [
            {"address": "Saved customer billing address"},
            {"address": None, "gst_number": None}]
        service.db.execute.return_value.mappings.return_value.one.return_value = {
            "address": None, "gst_number": None, "gst_registered": True}
        WorkflowService.invoice_context(service, root)
        self.assertEqual(root["payload"]["billing_address"], "Saved customer billing address")
        self.assertEqual(root["issues"][0]["field"], "store_id")
        self.assertIn("seller address", root["issues"][0]["message"])
        self.assertIn("GSTIN", root["issues"][0]["message"])
        self.assertEqual([link["path"] for link in root["issues"][0]["links"]], ["/portal/company", "/portal/stores"])

    def test_invoice_place_of_supply_defaults_from_customer_or_store_state(self):
        service = self.service()
        root = step("invoice_create", {"customer_party_id": str(uuid4()), "store_id": str(uuid4()), "billing_address": "x"})
        service.drafts.reference.side_effect = [{"gst_number": None}, {"address": "Shop", "gst_number": None, "state_code": "33"}]
        service.db.execute.return_value.mappings.return_value.one.return_value = {
            "address": "Shop", "gst_number": "33ABCDE1234F1Z5", "gst_registered": True}
        WorkflowService.invoice_context(service, root)
        self.assertEqual(root["payload"]["place_of_supply"], "33 - Tamil Nadu")
        self.assertEqual(root["issues"], [])

    def test_follow_up_line_description_does_not_replace_linked_product(self):
        current = {"lines": [{"product_id": "steel plates", "quantity": 50}]}
        incoming = normalize_document_proposal("purchase_create", {"receipt_type": "goods received",
            "lines": [{"description": "product desc", "hsn": "1234", "gst_rate": 5}]})
        self.assertEqual(incoming["lines"][0]["product_id"], "product desc")
        keep_line_products(current, incoming)
        merged = merge_known(current, incoming)
        self.assertEqual(merged["lines"][0], {"product_id": "steel plates", "quantity": 50,
                                              "description": "product desc", "hsn": "1234", "gst_rate": 5})
        issues = missing_fields("purchase_create", {"lines": [{}]})
        self.assertEqual(len([issue for issue in issues if issue["field"] == "lines.0.description"]), 1)

    def test_chat_answers_are_coerced_and_dropdowns_reject_free_text(self):
        payload = {"purchase_date": "11 Nov 2026", "received_now": "yes", "fully_paid": "Yes", "receipt_type": "goods received",
                   "payment_mode": "Cash", "lines": [{"gst_rate": "5%", "new_product": "no", "rate": "Rs 10", "price_includes_gst": "y"}]}
        coerce_payload("purchase_create", payload)
        issues = []
        normalize_choices(payload, issues)
        self.assertEqual(payload["purchase_date"], "2026-11-11")
        self.assertIs(payload["received_now"], True)
        self.assertIs(payload["fully_paid"], True)
        self.assertEqual(payload["payment_mode"], "cash")
        self.assertEqual(payload["lines"][0], {"gst_rate": "5", "new_product": False, "rate": "10", "price_includes_gst": True})
        self.assertNotIn("receipt_type", payload)
        self.assertEqual(issues[0]["field"], "receipt_type")
        invoice = {"invoice_date": "11 14 2026", "place_of_supply": "33", "amount_received": "1,000"}
        coerce_payload("invoice_create", invoice)
        normalize_choices(invoice, [])
        self.assertEqual(invoice, {"invoice_date": "2026-11-14", "place_of_supply": "33 - Tamil Nadu", "amount_received": "1000"})
        self.assertEqual(choice_value("place_of_supply", "Tamil Nadu"), "33 - Tamil Nadu")
        self.assertIsNone(choice_value("place_of_supply", "99"))
        schema = workflow_schema("purchase_create")
        self.assertEqual(schema["properties"]["receipt_type"]["enum"], ["PRODUCT", "STOCK", "SERVICE"])
        self.assertIn("33 - Tamil Nadu", workflow_schema("invoice_create")["properties"]["place_of_supply"]["enum"])
        from app.services.parties_service import ALLOWED_PARTY_TYPES
        for action in ("party_create", "party_update"):
            party_type = workflow_schema(action)["properties"]["party_type"]
            self.assertEqual(set(party_type["enum"]), ALLOWED_PARTY_TYPES)
            self.assertEqual(party_type["x-enum-labels"]["customer_vendor"], "Customer + Vendor")
        for said, value in {"Supplier": "vendor", "customers": "customer", "both": "customer_vendor",
                            "Customer + Vendor": "customer_vendor", "customer vendor": "customer_vendor"}.items():
            self.assertEqual(choice_value("party_type", said), value)
        self.assertIsNone(choice_value("party_type", "landlord"))
        party, issues = {"party_type": "landlord"}, []
        normalize_choices(party, issues)
        self.assertNotIn("party_type", party)
        self.assertEqual(issues[0]["field"], "party_type")
        direction = workflow_schema("borrowing_create")["properties"]["direction"]
        self.assertEqual(direction["enum"], ["borrow", "repay", "lend", "collect"])
        self.assertEqual(direction["x-enum-labels"]["lend"], "Lent to them (money out)")

    def test_loan_settlement_direction_follows_the_party_balances(self):
        service, party = self.service(), str(uuid4())
        balances = {"repay": Decimal("0"), "collect": Decimal("10000")}
        with patch("app.services.borrowing_ledger.available_repayment",
                   side_effect=lambda db, company, party_id, when, side: balances[side]):
            item = {"payload": {"party_id": party, "direction": "repay", "amount": 4000, "transaction_date": "2026-11-14"}, "labels": {}}
            service.loan_direction(item)
            self.assertEqual(item["payload"]["direction"], "collect")
            self.assertIn("they owe you ₹10,000.00", item["labels"]["direction"]["label"])
            # Ambiguity stays with the user when both balances are open or neither covers the amount.
            for repay, collect in (("500", "10000"), ("0", "100")):
                balances.update(repay=Decimal(repay), collect=Decimal(collect))
                item = {"payload": {"party_id": party, "direction": "repay", "amount": 4000}, "labels": {}}
                service.loan_direction(item)
                self.assertEqual(item["payload"]["direction"], "repay")
                self.assertEqual(item["labels"], {})

    def test_document_estimate_shows_totals_and_stock_before_after(self):
        service = self.service()
        product, store = str(uuid4()), str(uuid4())
        item = step("invoice_create", {"store_id": store, "lines": [
            {"product_id": product, "quantity": 10, "rate": 30, "gst_rate": 5, "price_includes_gst": True}]})
        item["labels"]["lines.0.product_id"] = {"value": product, "label": "Copper bottle"}
        results = iter([{"gst_registered": True, "prices_include_gst": True}, {"name": "Main store", "fulfilment_store_id": None}])
        service.db.execute.return_value.mappings.return_value.one.side_effect = lambda: next(results)
        service.db.execute.return_value.mappings.return_value.first.side_effect = lambda: next(results)
        service.db.execute.return_value.scalar_one.return_value = 100
        estimate = WorkflowService.document_estimate(service, item)
        self.assertEqual((estimate["subtotal"], estimate["gst_total"], estimate["total"]), ("285.71", "14.29", "300.00"))
        self.assertEqual(estimate["stock"], [{"product": "Copper bottle", "store": "Main store", "current": "100",
                                              "change": "-10", "after": "90"}])
        item["payload"]["lines"][0].pop("gst_rate")
        results = iter([{"gst_registered": True, "prices_include_gst": True}])
        self.assertIsNone(WorkflowService.document_estimate(service, item))

    def test_required_metadata_retains_completed_conditional_and_nested_fields(self):
        payload = {"fully_paid": True, "account_id": str(uuid4()), "payment_mode": "CASH",
                   "lines": [{"gst_rate": 0, "price_includes_gst": False}]}
        fields = required_fields("purchase_create", payload)
        self.assertIn("account_id", fields)
        self.assertIn("payment_mode", fields)
        self.assertIn("lines.0.gst_rate", fields)
        self.assertIn("lines.0.price_includes_gst", fields)
        self.assertNotIn("amount_paid", fields)
        issues = {issue["field"] for issue in missing_fields("purchase_create", payload)}
        self.assertNotIn("lines.0.gst_rate", issues)
        self.assertNotIn("lines.0.price_includes_gst", issues)
        self.assertNotIn("account_id", required_fields("purchase_create", {"amount_paid": 0}))
        self.assertIn("selling_price", required_fields("product_create", {"selling_price": 15}))
        self.assertNotIn("selling_price", required_fields("product_create", {"pricing_mode": "margin"}))

    def test_workflow_read_metadata_does_not_mutate_saved_plan(self):
        row = self.workflow("purchase_create", {"fully_paid": True})
        row["plan"]["steps"][0]["required_fields"] = ["stale"]
        original = deepcopy(row)
        view = workflow_view(row)
        self.assertIn("account_id", view["plan"]["steps"][0]["required_fields"])
        self.assertNotIn("stale", view["plan"]["steps"][0]["required_fields"])
        self.assertEqual(row, original)

    def test_purchase_repro_preserves_model_line_facts_instead_of_rejecting_workflow(self):
        values = {"vendor_party_id": "Tiger Brass Chennai", "received_now": True,
                  "lines": [{"item_name": "Brass bottle", "quantity": 100, "unit_cost": 10,
                             "gst_inclusive": True, "selling_price": 15}]}
        normalized = normalize_purchase_proposal(values)
        validate_workflow_payload("purchase_create", normalized)
        line = normalized["lines"][0]
        self.assertEqual(line["description"], "Brass bottle")
        self.assertEqual(line["product_id"], "Brass bottle")
        self.assertEqual(line["rate"], 10)
        self.assertIs(line["price_includes_gst"], True)
        self.assertEqual(line["selling_price"], 15)
        self.assertNotIn("gst_rate", line)
        self.assertNotIn("item_name", line)
        self.assertIn("item_name", values["lines"][0])

    def test_purchase_alias_conflicts_unknown_fields_and_invalid_facts_are_rejected(self):
        with self.assertRaises(HTTPException):
            normalize_purchase_proposal({"lines": [{"unit_cost": 10, "rate": 12}]})
        for payload in ({"company_id": str(uuid4())}, {"lines": [{"unknown": True}]},
                        {"lines": [{"selling_price": -1}]}, {"fully_paid": "yes"},
                        {"lines": [{"selling_price": "1.999"}]}):
            with self.subTest(payload=payload), self.assertRaises(HTTPException):
                validate_workflow_payload("purchase_create", payload)
        with self.assertRaises(HTTPException):
            validate_workflow_payload("invoice_create", {"lines": [{"selling_price": 15}]})

    def test_purchase_unknown_null_totals_do_not_become_spurious_form_requirements(self):
        payload = normalize_purchase_proposal({"fully_paid": True, "subtotal": None, "gst_total": None,
            "amount_paid": None, "receipt_type": None, "lines": [{"description": "Bottle",
            "quantity": 100, "rate": 10, "new_product": None, "gst_rate": None}]})
        fields = {item["field"] for item in missing_fields("purchase_create", payload)}
        self.assertFalse({"subtotal", "gst_total", "amount_paid", "receipt_type", "lines.0.new_product"} & fields)
        self.assertIn("lines.0.gst_rate", fields)
        self.assertIn("account_id", fields)
        self.assertIn("payment_mode", fields)

    def test_purchase_selling_price_seeds_product_prerequisite_not_business_line(self):
        service = self.service()
        payload = normalize_purchase_proposal({"lines": [{"description": "Bottle", "selling_price": 15,
                                                         "hsn": "1234", "new_product": True}]})
        root = step("purchase_create", payload)
        steps = [root]
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            service.resolve(root, ("lines", 0, "product_id"), "Bottle", REFERENCES["product_id"], steps)
        self.assertEqual(steps[1]["payload"], {"name": "Bottle", "selling_price": 15, "hsn_code": "1234"})
        values = business_payload("purchase_create", {**payload, "fully_paid": True})
        self.assertNotIn("fully_paid", values)
        self.assertNotIn("selling_price", values["lines"][0])
        self.assertFalse(values["lines"][0]["new_product"])
        self.assertIn("selling_price", workflow_schema("purchase_create")["$defs"]["InvoiceLineCreate"]["properties"])
        self.assertNotIn("selling_price", ACTIONS["purchase_create"].schema.model_json_schema()["$defs"]["InvoiceLineCreate"]["properties"])

    def test_full_payment_waits_for_details_then_uses_authoritative_total(self):
        service = self.service()
        product, vendor = str(uuid4()), str(uuid4())
        payload = {"vendor_party_id": vendor, "store_id": str(uuid4()), "purchase_date": "2026-11-12",
                   "fully_paid": True, "account_id": str(uuid4()), "payment_mode": "Bank",
                   "received_now": True, "lines": [{"product_id": product, "description": "Bottle",
                       "hsn": "1234", "quantity": 100, "rate": 10, "gst_rate": 18,
                       "price_includes_gst": False, "selling_price": 15}]}
        incomplete = deepcopy(payload)
        del incomplete["account_id"]
        del incomplete["lines"][0]["gst_rate"]
        fields = {item["field"] for item in missing_fields("purchase_create", incomplete)}
        self.assertIn("account_id", fields)
        self.assertIn("lines.0.gst_rate", fields)
        self.assertNotIn("amount_paid", fields)
        # The authoritative HSN rate may replace the supplied rate before computing payment.
        normalized = {**business_payload("purchase_create", payload), "total": "1120.00"}
        with patch.object(service, "lookup", side_effect=lambda spec, query: {"items":
                [{"code": query}] if spec[0] == "hsn" else [
                    {"product_id": product, "vendor_id": vendor, "variant_id": None, "is_active": True}],
                "more_matches": False}), patch("app.ai.business_writes.document_preview",
                                              return_value=(normalized, {})) as preview:
            purchase = self.workflow("purchase_create", payload)
            purchase["plan"]["steps"][0]["target"] = "Legacy vendor name"
            row = service.prepare(purchase)
        self.assertEqual(preview.call_args.args[3]["amount_paid"], "0")
        self.assertEqual(service.drafts.create.call_args.args[1].payload["amount_paid"], "1120.00")
        self.assertIsNone(service.drafts.create.call_args.args[1].target_id)
        self.assertTrue(row["plan"]["steps"][0]["payload"]["fully_paid"])
        self.assertNotIn("selling_price", service.drafts.create.call_args.args[1].payload["lines"][0])
        service.drafts.create.reset_mock()
        with patch.object(service, "lookup", side_effect=lambda spec, query: {"items":
                [{"code": query}] if spec[0] == "hsn" else [
                    {"product_id": product, "vendor_id": vendor, "variant_id": None, "is_active": True}],
                "more_matches": False}), patch("app.ai.business_writes.document_preview", return_value=(normalized, {})):
            conflict = service.prepare(self.workflow("purchase_create", {**payload, "amount_paid": 100}))
        service.drafts.create.assert_not_called()
        self.assertIn("amount_paid", {issue["field"] for issue in conflict["plan"]["steps"][0]["issues"]})

    def test_purchase_requires_vendor_product_mapping_and_waits_for_its_posting(self):
        service = self.service()
        product, vendor = str(uuid4()), str(uuid4())
        root = step("purchase_create", {"vendor_party_id": vendor, "lines": [{"product_id": product}]})
        steps = [root]
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            service.purchase_offers(root, steps)
        self.assertEqual(steps[1]["action"], "offer_create")
        self.assertEqual(steps[1]["payload"], {"product_id": product, "variant_id": None, "vendor_id": vendor})
        root["issues"] = []
        service.purchase_offers(root, steps)
        self.assertEqual(len(steps), 2)
        self.assertTrue(root["issues"])
        steps[1]["draft_status"] = "executed"
        root["issues"] = []
        service.purchase_offers(root, steps)
        self.assertEqual(root["issues"], [])

    def test_unavailable_or_truncated_offer_lookup_never_creates_mapping(self):
        service = self.service()
        for more in (False, True):
            root = step("purchase_create", {"vendor_party_id": str(uuid4()),
                                            "lines": [{"product_id": str(uuid4())}]})
            steps = [root]
            with patch.object(service, "lookup", side_effect=HTTPException(403, "Search unavailable") if not more else None,
                              return_value={"items": [], "more_matches": more}):
                service.purchase_offers(root, steps)
            self.assertEqual(len(steps), 1)
            self.assertTrue(root["issues"])

    def test_selected_product_and_hsn_supply_verified_missing_tax_facts(self):
        service = self.service()
        product = str(uuid4())
        root = step("invoice_create", {"lines": [{"product_id": product, "quantity": 1, "rate": 10}]})
        with patch.object(service, "lookup", return_value={"items": [
                {"id": product, "name": "Bottle", "hsn_code": "1234"}], "more_matches": False}):
            service.document_products(root)
        line = root["payload"]["lines"][0]
        self.assertEqual(line["description"], "Bottle")
        self.assertEqual(line["hsn"], "1234")
        self.assertNotIn("gst_rate", line)
        with patch.object(service, "lookup", return_value={"items": [
                {"code": "1234", "gst_rate": "18"}], "more_matches": False}):
            service.resolve(root, ("lines", 0, "hsn"), "1234", REFERENCES["hsn"], [root])
        self.assertEqual(line["gst_rate"], "18")
        self.assertNotIn("price_includes_gst", line)

    def test_linked_offer_cannot_be_repurposed_by_editing_the_purchase_or_offer(self):
        from app.ai.workflows import preserve_bindings
        service = self.service()
        product, vendor = str(uuid4()), str(uuid4())
        row = self.workflow("purchase_create", {"vendor_party_id": vendor, "lines": [{"product_id": product}]})
        root = row["plan"]["steps"][0]
        child = step("offer_create", {"product_id": product, "variant_id": None, "vendor_id": vendor})
        root["offer_steps"] = {f"{product}::{vendor}": child["id"]}
        row["plan"]["steps"].append(child)
        with self.assertRaises(HTTPException):
            preserve_bindings(root, {"vendor_party_id": str(uuid4()), "lines": [{"product_id": product}]})
        service.get = Mock(return_value=row)
        service.policies = Mock()
        with self.assertRaises(HTTPException) as changed:
            service.advance(row["id"], 1, WorkflowEdit(expected_version=1, step_id=child["id"],
                payload={**child["payload"], "vendor_id": str(uuid4())}))
        self.assertEqual(changed.exception.status_code, 409)

    def test_conditional_financial_inputs_are_not_silently_defaulted(self):
        cases = [
            ("borrowing_create", {"create_account_transaction": True}, "account_id"),
            ("business_payment_create", {"purpose": "purchase"}, "related_party_id"),
            ("receivable_status", {"status": "BAD_DEBT"}, "bad_debt_reason"),
            ("report_export", {"kind": "ar_aging"}, "as_of"),
            ("report_export", {"kind": "sales_register"}, "from_date"),
            ("product_create", {"name": "Jar"}, "selling_price"),
        ]
        for action, payload, expected in cases:
            with self.subTest(action=action):
                self.assertIn(expected, {item["field"] for item in missing_fields(action, payload)})

    def test_unique_exact_search_selects_without_questions_or_creation(self):
        service = self.service()
        identifier = str(uuid4())
        root = step("borrowing_create", {"party_id": "Tiger"})
        with patch.object(service, "lookup", return_value={"items": [
                {"id": identifier, "legal_name": "TIGER", "party_type": "vendor"}], "more_matches": False}):
            selected = service.resolve(root, ("party_id",), "Tiger", REFERENCES["party_id"], [root])
        self.assertEqual(selected, identifier)
        self.assertEqual(root["issues"], [])
        self.assertEqual(root["labels"]["party_id"]["label"], "Tiger")
        service.drafts.create.assert_not_called()

    def test_search_is_read_only_scoped_to_private_workflow_and_registered_field(self):
        service = self.service()
        row = self.workflow("purchase_create", {})
        root = row["plan"]["steps"][0]
        original = deepcopy(row)
        service.get = Mock(return_value=row)
        service.policies = Mock()
        identifier = str(uuid4())
        with patch.object(service, "lookup", return_value={"items": [
                {"id": identifier, "name": "Main store", "code": "MAIN"}], "more_matches": False}) as lookup:
            result = service.search(row["id"], root["id"], "store_id", "mai")
        lookup.assert_called_once_with(REFERENCES["store_id"], "mai")
        self.assertEqual(result["options"], [{"value": identifier, "label": "Main store · MAIN"}])
        self.assertFalse(result["can_create"])
        self.assertEqual(row, original)
        service.db.commit.assert_not_called()
        service.drafts.create.assert_not_called()
        for field in ("notes", "company_id", "target", "lines.0.unknown", "unknown.product_id"):
            with self.subTest(field=field), self.assertRaises(HTTPException):
                service.search(row["id"], root["id"], field, "mai")
        with self.assertRaises(HTTPException):
            service.search(row["id"], uuid4(), "store_id", "mai")
        service.actions = set()
        with self.assertRaises(HTTPException):
            service.search(row["id"], root["id"], "store_id", "mai")

    def test_search_nested_references_metadata_and_creation_permissions(self):
        from app.ai.workflows import search_reference
        self.assertEqual(search_reference("purchase_create", "lines.0.product_id"), REFERENCES["product_id"])
        self.assertEqual(search_reference("party_update", "target"), TARGETS["parties"])
        schema = workflow_schema("purchase_create")
        self.assertTrue(schema["properties"]["store_id"]["x-workflow-reference"])
        self.assertTrue(schema["$defs"]["InvoiceLineCreate"]["properties"]["hsn"]["x-workflow-reference"])
        self.assertNotIn("x-workflow-reference", ACTIONS["purchase_create"].schema.model_json_schema()["properties"]["store_id"])
        service = self.service()
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            self.assertTrue(service.search_choices("purchase_create", "lines.0.product_id", "Bottle")["can_create"])
            self.assertFalse(service.search_choices("product_update", "target", "Bottle")["can_create"])
            service.actions.remove("product_create")
            self.assertFalse(service.search_choices("purchase_create", "lines.0.product_id", "Bottle")["can_create"])
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": True}):
            self.assertFalse(service.search_choices("purchase_create", "lines.0.product_id", "Bottle")["can_create"])

    def test_search_selection_revalidates_option_and_retains_its_label(self):
        service = self.service()
        row = self.workflow("purchase_create", {})
        root = row["plan"]["steps"][0]
        service.get = Mock(return_value=row)
        service.policies = Mock()
        service.prepare = Mock(side_effect=lambda row, *_: row)
        service.save = Mock(side_effect=lambda row: row)
        identifier = str(uuid4())
        edit = WorkflowEdit(expected_version=1, step_id=root["id"], payload={"store_id": identifier},
                            selection_field="store_id", selection_query="mai")
        with patch.object(service, "lookup", return_value={"items": [
                {"id": identifier, "name": "Main store"}], "more_matches": False}):
            saved = service.advance(row["id"], 1, edit)
        self.assertEqual(saved["plan"]["steps"][0]["labels"]["store_id"],
                         {"value": identifier, "label": "Main store"})
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            with self.assertRaises(HTTPException) as changed:
                service.advance(row["id"], 1, edit)
        self.assertEqual(changed.exception.status_code, 409)

    def test_typeahead_creation_rechecks_search_without_mutating_during_search(self):
        service = self.service()
        row = self.workflow("purchase_create", {})
        root = row["plan"]["steps"][0]
        service.get = Mock(return_value=row)
        service.policies = Mock()
        service.prepare = Mock(side_effect=lambda row, *_: row)
        service.save = Mock(side_effect=lambda row: row)
        edit = WorkflowEdit(expected_version=1, step_id=root["id"],
                            payload={"vendor_party_id": "New vendor"}, create_field="vendor_party_id")
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            service.advance(row["id"], 1, edit)
        self.assertEqual(service.prepare.call_args.args[1], (root["id"], "vendor_party_id"))
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": True}):
            with self.assertRaises(HTTPException):
                service.advance(row["id"], 1, edit)

    def test_ambiguous_or_truncated_results_offer_selection_never_autocreate(self):
        service = self.service()
        for more, rows in [(False, [{"id": str(uuid4()), "name": "Jar"}, {"id": str(uuid4()), "name": "Jar"}]),
                           (True, [{"id": str(uuid4()), "name": "Jar"}])]:
            with self.subTest(more=more):
                root = step("stock_transfer", {"product_id": "Jar"})
                steps = [root]
                with patch.object(service, "lookup", return_value={"items": rows, "more_matches": more}):
                    self.assertEqual(service.resolve(root, ("product_id",), "Jar", REFERENCES["product_id"], steps), "Jar")
                self.assertEqual(len(steps), 1)
                self.assertEqual(len(root["choices"][0]["options"]), len(rows))
                self.assertEqual(root["choices"][0]["can_create"], not more)

    def test_missing_prerequisites_are_prepared_for_multiple_modules_not_just_purchases(self):
        cases = [("invoice_create", "customer_party_id", "Customer", "party_create", "customer"),
                 ("offer_create", "vendor_id", "Vendor", "party_create", "vendor"),
                 ("stock_transfer", "product_id", "Jar", "product_create", None),
                 ("collection_payment", "account_id", "Cash box", "account_create", None),
                 ("product_create", "brand_id", "Brand", "brand_create", None),
                 ("product_create", "category_id", "Category", "category_create", None)]
        for action, field, name, prerequisite, party_type in cases:
            with self.subTest(action=action, field=field):
                service = self.service()
                root = step(action, {field: name})
                steps = [root]
                with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
                    service.resolve(root, (field,), name, REFERENCES[field], steps)
                self.assertEqual(steps[1]["action"], prerequisite)
                if party_type:
                    self.assertEqual(steps[1]["payload"]["party_type"], party_type)
                self.assertEqual(root["bindings"][field]["step_id"], steps[1]["id"])
                service.drafts.create.assert_not_called()

    def test_repeated_line_references_share_one_prerequisite(self):
        service = self.service()
        root = step("purchase_create", {"lines": [{"product_id": "Jar", "hsn": "1234"}, {"product_id": "Jar", "hsn": "1234"}]})
        steps = [root]
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            for path, value, spec in reference_fields(root["payload"]):
                if path[-1] == "product_id":
                    service.resolve(root, path, value, spec, steps)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[1]["payload"], {"name": "Jar", "hsn_code": "1234"})
        self.assertEqual(len(root["bindings"]), 2)

    def test_select_create_option_checks_current_results_and_never_duplicates_exact_match(self):
        service = self.service()
        root = step("offer_create", {"vendor_id": "Tiger"})
        steps = [root]
        with patch.object(service, "lookup", return_value={"items": [
                {"id": str(uuid4()), "legal_name": "Tiger Brass"}], "more_matches": False}):
            service.resolve(root, ("vendor_id",), "Tiger", REFERENCES["vendor_id"], steps, force_create=True)
        self.assertEqual(len(steps), 2)
        identifier = str(uuid4())
        root = step("offer_create", {"vendor_id": "Tiger"})
        steps = [root]
        with patch.object(service, "lookup", return_value={"items": [
                {"id": identifier, "legal_name": "Tiger", "party_type": "vendor"}], "more_matches": False}):
            result = service.resolve(root, ("vendor_id",), "Tiger", REFERENCES["vendor_id"], steps, force_create=True)
        self.assertEqual(result, identifier)
        self.assertEqual(len(steps), 1)

    def test_missing_update_targets_do_not_turn_into_creates(self):
        service = self.service()
        root = step("product_update", {"selling_price": "10"}, "Missing")
        steps = [root]
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            service.resolve(root, ("target",), "Missing", TARGETS["products"], steps, target=True)
        self.assertEqual(len(steps), 1)
        self.assertFalse(root["choices"][0]["can_create"])

    def test_disabled_search_or_create_remains_explicit_and_never_bypasses_permissions(self):
        service = self.service()
        root = step("offer_create", {"vendor_id": "Tiger"})
        steps = [root]
        with patch.object(service, "lookup", side_effect=HTTPException(403, "Parties search disabled")):
            service.resolve(root, ("vendor_id",), "Tiger", REFERENCES["vendor_id"], steps)
        self.assertIn("disabled", root["issues"][0]["message"])
        service.actions.remove("party_create")
        root = step("offer_create", {"vendor_id": "Tiger"})
        with patch.object(service, "lookup", return_value={"items": [], "more_matches": False}):
            service.resolve(root, ("vendor_id",), "Tiger", REFERENCES["vendor_id"], [root])
        self.assertFalse(root["choices"][0]["can_create"])

    def test_posted_prerequisite_is_bound_and_next_step_prepared_automatically(self):
        service = self.service()
        root = step("offer_create", {"product_id": str(uuid4()), "vendor_id": "Tiger"})
        child = step("party_create", {"legal_name": "Tiger", "party_type": "vendor"})
        child["draft_id"] = str(uuid4())
        root["bindings"]["vendor_id"] = {"step_id": child["id"], "path": ["vendor_id"]}
        row = self.workflow("offer_create", {})
        row["plan"]["steps"] = [root, child]
        vendor_id = str(uuid4())
        service.drafts.get.return_value = {"id": child["draft_id"], "version": 1, "status": "executed", "payload": child["payload"]}
        service.db.execute.return_value.mappings.return_value.one.return_value = {"result": {"id": vendor_id}}
        prepared = service.prepare(row)
        self.assertEqual(prepared["plan"]["steps"][0]["payload"]["vendor_id"], vendor_id)
        service.drafts.create.assert_called_once()
        self.assertEqual(service.drafts.create.call_args.args[1].action, "offer_create")
        self.assertFalse(service.drafts.create.call_args.kwargs["commit"])
        service.drafts.create.reset_mock()
        root_draft = {"id": root["draft_id"], "version": 1, "status": "editing", "payload": root["payload"]}
        service.drafts.get.side_effect = lambda identifier: root_draft if identifier == root["draft_id"] else {
            "id": child["draft_id"], "version": 1, "status": "executed", "payload": child["payload"]}
        service.prepare(row)
        service.drafts.create.assert_not_called()

    def test_failed_or_unsubmitted_prerequisite_never_advances(self):
        service = self.service()
        row = self.workflow("offer_create", {"product_id": str(uuid4()), "vendor_id": "Tiger"})
        root = row["plan"]["steps"][0]
        child = step("party_create", {"legal_name": "Tiger", "party_type": "vendor"})
        child["draft_id"] = str(uuid4())
        root["bindings"]["vendor_id"] = {"step_id": child["id"], "path": ["vendor_id"]}
        row["plan"]["steps"].append(child)
        service.drafts.get.return_value = {"status": "approved"}
        prepared = service.prepare(row)
        self.assertIsNone(prepared["plan"]["steps"][0]["draft_id"])
        self.assertTrue(any("Complete the prerequisite" in issue["message"] for issue in root["issues"]))
        service.drafts.create.assert_not_called()

    def test_full_replacements_preserve_every_existing_contract_field(self):
        for action in REPLACEMENTS:
            with self.subTest(action=action):
                service = self.service()
                existing = {"name": "Existing", "variant_name": "Large", "description": "Keep me", "is_active": False,
                            "product_id": str(uuid4()), "vendor_id": str(uuid4()), "selling_price": "12.00",
                            "image_urls": "https://example.test/a.png|https://example.test/b.png",
                            "home_order": 17, "reorder_enabled": True, "reorder_level": "2", "reorder_target": "5"}
                service.drafts.reference.return_value = existing
                changes = {"description": "Requested"}
                row = service.prepare(self.workflow(action, changes, str(uuid4())))
                payload = row["plan"]["steps"][0]["payload"]
                self.assertEqual(payload["description"], "Requested")
                self.assertIs(payload["is_active"], False)
                for key in ("home_order", "selling_price", "reorder_enabled"):
                    if key in ACTIONS[action].schema.model_fields:
                        self.assertEqual(payload[key], existing[key])
                if action == "product_update":
                    self.assertEqual(payload["image_urls"], existing["image_urls"].split("|"))

    def test_workflow_forms_cannot_inject_identity_or_unknown_actions(self):
        with self.assertRaises(ValidationError):
            WorkflowCreate(action="company_update", client_key=uuid4())
        with self.assertRaises(ValidationError):
            WorkflowEdit(expected_version=1, step_id=uuid4(), payload={}, user_id=uuid4())
        service = self.service()
        row = self.workflow("party_create", {"legal_name": "Tiger"})
        service.get = Mock(return_value=row)
        service.policies = Mock()
        with self.assertRaises(HTTPException) as stale:
            service.advance(row["id"], 3)
        self.assertEqual(stale.exception.status_code, 409)
        service.save = Mock()
        for payload in ({"company_id": str(uuid4())}, {"unexpected": True}):
            with self.assertRaises(HTTPException):
                service.advance(row["id"], 1, WorkflowEdit(expected_version=1,
                    step_id=row["plan"]["steps"][0]["id"], payload=payload))
        service.save.assert_not_called()

    def test_get_and_list_are_private_and_expiry_scoped(self):
        service = self.service()
        service.db.execute.return_value.mappings.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as error:
            service.get(uuid4())
        self.assertEqual(error.exception.status_code, 404)
        sql = str(service.db.execute.call_args.args[0])
        for clause in ("company_id=:company", "user_id=:user", "expires_at>now()"):
            self.assertIn(clause, sql)

    def test_completed_workflow_prompts_relevant_next_entries_without_starting_them(self):
        service = self.service()
        row = self.workflow("purchase_create", {"received_now": False, "amount_paid": 0})
        root = row["plan"]["steps"][0]
        root["draft_id"] = str(uuid4())
        service.drafts.get.return_value = {"id": root["draft_id"], "version": 1, "status": "executed", "payload": root["payload"]}
        service.db.execute.return_value.mappings.return_value.one.return_value = {"result": {"id": str(uuid4()), "total": "100"}}
        completed = service.prepare(row)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual([entry["action"] for entry in completed["plan"]["next"]],
                         ["purchase_receive", "purchase_payment", "purchase_create"])
        service.drafts.create.assert_not_called()
        paid = next_entries("purchase_bundle_create", {"fully_paid": True, "received_now": True}, {"id": uuid4()})
        self.assertEqual(len(paid), 1)

    def test_chat_updates_one_existing_incomplete_workflow_and_keeps_confirmed_values(self):
        service = self.service()
        row = self.workflow("purchase_create", {"received_now": True, "amount_paid": 0, "lines": [{"rate": "10", "price_includes_gst": True}]})
        service.db.execute.return_value.mappings.return_value.all.return_value = [row]
        service.policies = Mock()
        service.prepare = Mock(side_effect=lambda row: row)
        service.save = Mock(side_effect=lambda row: row)
        result = service.from_proposal(row["conversation_id"], DraftProposal(action="purchase_create", target_id=None,
            payload_json=json.dumps({"purchase_date": "2026-11-12", "lines": [{"quantity": "100"}]})), uuid4())
        payload = result["plan"]["steps"][0]["payload"]
        self.assertEqual(payload["purchase_date"], "2026-11-12")
        self.assertEqual(payload["lines"][0]["rate"], "10")
        self.assertIs(payload["lines"][0]["price_includes_gst"], True)

    def test_chat_reuses_prepared_review_and_new_facts_invalidate_approval(self):
        service = self.service()
        row = self.workflow("party_create", {"legal_name": "Tiger", "party_type": "vendor"})
        root = row["plan"]["steps"][0]
        root["draft_id"] = str(uuid4())
        draft = {"id": root["draft_id"], "version": 4, "status": "approved", "payload": deepcopy(root["payload"])}
        service.db.execute.return_value.mappings.return_value.all.return_value = [row]
        service.drafts.get.return_value = draft
        service.drafts.lock.return_value = draft
        service.policies = Mock()
        service.prepare = Mock(side_effect=lambda row: row)
        service.save = Mock(side_effect=lambda row: row)
        proposal = DraftProposal(action="party_create", target_id=None, payload_json=json.dumps(root["payload"]))
        same = service.from_proposal(row["conversation_id"], proposal, uuid4())
        self.assertEqual(same["plan"]["steps"][0]["draft_id"], root["draft_id"])
        service.drafts.lock.assert_not_called()
        updated = service.from_proposal(row["conversation_id"], proposal.model_copy(
            update={"payload_json": '{"nickname":"New nickname"}'}), uuid4())
        new_root = updated["plan"]["steps"][0]
        self.assertIsNone(new_root["draft_id"])
        self.assertEqual(new_root["payload"]["nickname"], "New nickname")
        self.assertNotEqual(new_root["id"], root["id"])
        service.drafts.lock.assert_called_once_with(draft["id"], 4)
        sql = [str(call.args[0]) for call in service.db.execute.call_args_list]
        self.assertTrue(any("approved_version=null" in query and "discarded" in query for query in sql))

    def test_later_text_can_supply_a_missing_update_target_without_a_second_workflow(self):
        service = self.service()
        row = self.workflow("party_update", {"nickname": "New nickname"})
        service.db.execute.return_value.mappings.return_value.all.return_value = [row]
        service.policies = Mock()
        service.prepare = Mock(side_effect=lambda row: row)
        service.save = Mock(side_effect=lambda row: row)
        updated = service.from_proposal(row["conversation_id"], DraftProposal(action="party_update",
            target_id="Tiger", payload_json="{}"), uuid4())
        self.assertEqual(updated["plan"]["steps"][0]["target"], "Tiger")
        self.assertEqual(updated["plan"]["steps"][0]["payload"]["nickname"], "New nickname")

    def test_replay_checks_request_values_and_never_resurrects_discarded_work(self):
        from app.ai.drafts import digest
        service = self.service()
        request = WorkflowCreate(action="party_create", payload={"legal_name": "Tiger"}, client_key=uuid4())
        row = self.workflow("party_create", request.payload)
        row["request_hash"] = digest({"action": request.action, "target": request.target, "payload": request.payload})
        service.db.execute.return_value.mappings.return_value.first.return_value = row
        service.get = Mock(return_value=row)
        service.policies = Mock()
        self.assertEqual(service.create(row["conversation_id"], request)["id"], row["id"])
        with self.assertRaises(HTTPException) as error:
            service.create(row["conversation_id"], request.model_copy(update={"payload": {"legal_name": "Different"}}))
        self.assertEqual(error.exception.status_code, 409)

    def test_prepared_workflow_never_replaces_a_bound_prerequisite_silently(self):
        from app.ai.workflows import preserve_bindings
        root = step("offer_create", {"vendor_id": "Tiger"})
        root["bindings"]["vendor_id"] = {"step_id": str(uuid4()), "path": ["vendor_id"]}
        with self.assertRaises(HTTPException) as error:
            preserve_bindings(root, {"vendor_id": "Different"})
        self.assertEqual(error.exception.status_code, 409)

    def test_editing_a_review_rotates_its_step_and_preserves_parent_dependencies(self):
        service = self.service()
        row = self.workflow("offer_create", {"vendor_id": "Tiger"})
        child = step("party_create", {"legal_name": "Tiger", "party_type": "vendor"})
        old_id = child["id"]
        child["draft_id"] = str(uuid4())
        row["plan"]["steps"].append(child)
        row["plan"]["steps"][0]["bindings"]["vendor_id"] = {"step_id": old_id, "path": ["vendor_id"]}
        service.get = Mock(return_value=row)
        service.policies = Mock()
        service.prepare = Mock(side_effect=lambda row, request: row)
        service.save = Mock(side_effect=lambda row: row)
        service.drafts.get.return_value = {"id": child["draft_id"], "version": 4}
        updated = service.advance(row["id"], 1, WorkflowEdit(expected_version=1, step_id=old_id,
            draft_version=4, payload={**child["payload"], "nickname": "New nickname"}))
        new_child = updated["plan"]["steps"][1]
        self.assertNotEqual(new_child["id"], old_id)
        self.assertIsNone(new_child["draft_id"])
        self.assertEqual(updated["plan"]["steps"][0]["bindings"]["vendor_id"]["step_id"], new_child["id"])
        service.drafts.lock.assert_called_once_with(child["draft_id"], 4)

    def test_review_edits_require_the_exact_current_draft_version(self):
        service = self.service()
        row = self.workflow("party_create", {"legal_name": "Tiger", "party_type": "vendor"})
        root = row["plan"]["steps"][0]
        root["draft_id"] = str(uuid4())
        service.get = Mock(return_value=row)
        service.policies = Mock()
        service.drafts.get.return_value = {"id": root["draft_id"], "version": 4}
        with self.assertRaises(HTTPException) as error:
            service.advance(row["id"], 1, WorkflowEdit(expected_version=1, step_id=root["id"],
                draft_version=3, payload=root["payload"]))
        self.assertEqual(error.exception.status_code, 409)
        service.drafts.lock.assert_not_called()

    def test_explicit_new_entry_never_merges_another_active_operation(self):
        service = self.service()
        service.create = Mock(return_value={"id": uuid4()})
        proposal = DraftProposal(action="party_create", workflow_id=None, target_id=None,
                                 payload_json='{"legal_name":"A different vendor","party_type":"vendor"}')
        service.from_proposal(uuid4(), proposal, uuid4())
        service.create.assert_called_once()
        service.db.execute.assert_not_called()

    def test_model_can_only_resume_a_workflow_from_the_same_private_conversation_and_action(self):
        service = self.service()
        row = self.workflow("party_create", {"legal_name": "Tiger"})
        row["action_key"] = "party_create"
        service.get = Mock(return_value=row)
        proposal = DraftProposal(action="party_create", workflow_id=row["id"], target_id=None, payload_json="{}")
        with self.assertRaises(HTTPException) as error:
            service.from_proposal(uuid4(), proposal, uuid4())
        self.assertEqual(error.exception.status_code, 404)

    def test_provider_schema_requires_explicit_new_or_resumed_workflow(self):
        from app.ai.actions import ActionAssistantOutput
        from app.ai.provider import response_schema
        schema = response_schema(ActionAssistantOutput)["$defs"]["OperationProposal"]
        self.assertIn("workflow_id", schema["required"])
        self.assertNotIn("default", schema["properties"]["workflow_id"])
