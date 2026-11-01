import csv
import os
import unittest
from datetime import date
from decimal import Decimal
from io import StringIO
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError


class FinanceInputTests(unittest.TestCase):
    def test_money_bounds_and_account_validation(self):
        from app.schemas.accounts import AccountCreate, AccountTransactionCreate, AccountUpdate, BusinessPaymentCreate
        from app.schemas.billing import InvoiceCreate
        from app.schemas.collections import ReceivableCreate, ReceivablePaymentCreate
        from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate
        from app.schemas.settlements import BorrowingEntryCreate

        identifier = str(uuid4())
        constructors = (
            lambda value: InvoiceCreate(customer_party_id=identifier, total=value),
            lambda value: PurchaseCreate(vendor_party_id=identifier, total=value),
            lambda value: ReceivableCreate(party_id=identifier, amount_due=value),
            lambda value: ReceivablePaymentCreate(amount=value, account_id=identifier,
                                                  payment_mode="bank", idempotency_key="key"),
            lambda value: PurchasePaymentCreate(amount=value, account_id=identifier,
                                                payment_mode="bank", idempotency_key="key"),
            lambda value: BorrowingEntryCreate(party_id=identifier, direction="borrow", amount=value),
            lambda value: AccountTransactionCreate(amount=value),
            lambda value: BusinessPaymentCreate(from_account_id=identifier, purpose="expense", amount=value),
        )
        for constructor in constructors:
            for value in ("NaN", "Infinity", "-Infinity", "0.001", "1000000000000.00", "-1"):
                with self.subTest(constructor=constructor, value=value):
                    with self.assertRaises(ValidationError):
                        constructor(value)
        self.assertEqual(
            InvoiceCreate(customer_party_id=identifier, subtotal="999999999999.99").subtotal,
            Decimal("999999999999.99"),
        )
        for values in (
            {"nickname": " ", "account_type": "bank"},
            {"nickname": "Test", "account_type": "unknown"},
        ):
            with self.assertRaises(ValidationError):
                AccountCreate(**values)
        for values in ({"nickname": " "}, {"account_type": "bad"}, {"opening_balance": None}):
            with self.assertRaises(ValidationError):
                AccountUpdate(**values)
        self.assertEqual(AccountCreate(nickname=" Bank ", account_type=" BANK ").account_type, "bank")
        for payment in (ReceivablePaymentCreate, PurchasePaymentCreate):
            with self.assertRaises(ValidationError):
                payment(amount=1, account_id=identifier, payment_mode="bank", idempotency_key="  ")

    def test_legacy_float_idempotency_hash_is_preserved(self):
        from app.schemas.billing import InvoiceCreate
        from app.schemas.purchases import PurchaseCreate
        from app.schemas.accounts import BusinessPaymentCreate
        from app.services.posting_service import legacy_money_request_hash, request_hash

        class OldInvoice(InvoiceCreate):
            subtotal: float = 0
            gst_total: float = 0
            total: float | None = None
            amount_received: float = 0

        class OldPurchase(PurchaseCreate):
            subtotal: float = 0
            gst_total: float = 0
            total: float | None = None
            amount_paid: float = 0

        class OldBusinessPayment(BusinessPaymentCreate):
            amount: float

        identifier = str(uuid4())
        cases = (
            (InvoiceCreate, OldInvoice, {"customer_party_id": identifier, "subtotal": "100.25",
                                         "gst_total": "18.05", "total": "118.30", "notes": "Test café"}),
            (PurchaseCreate, OldPurchase, {"vendor_party_id": identifier, "subtotal": "1.01",
                                           "gst_total": "0.01", "total": "1.02", "amount_paid": "0.01"}),
            (BusinessPaymentCreate, OldBusinessPayment, {"from_account_id": identifier, "amount": "0.01",
                                                         "purpose": "expense"}),
        )
        for new_class, old_class, values in cases:
            with self.subTest(model=new_class.__name__):
                self.assertEqual(legacy_money_request_hash(new_class(**values)), request_hash(old_class(**values)))


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only finance tests")
class FinanceIntegrityTests(unittest.TestCase):
    def setUp(self):
        from dotenv import load_dotenv
        from sqlalchemy import text
        from sqlalchemy.orm import Session

        load_dotenv("api/.env")
        from app.core.database import engine
        from app.schemas.accounts import AccountCreate
        from app.services.accounts_service import AccountsService
        from app.services.billing_service import BillingService
        from app.services.collections_service import CollectionsService
        from app.services.purchases_service import PurchasesService

        self.text = text
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        self.company, self.party, self.other_party = (str(uuid4()) for _ in range(3))
        self.db.execute(
            text("insert into companies(id, company_name) values(:id, 'Finance integrity regression')"),
            {"id": self.company},
        )
        from schema_support import ensure_default_store
        self.store_id = ensure_default_store(self.db, self.company)
        for party in (self.party, self.other_party):
            self.db.execute(
                text(
                    """
                    insert into parties(id, company_id, party_type, legal_name)
                    values(:id, :company, 'customer_vendor', 'Finance regression party')
                    """
                ),
                {"id": party, "company": self.company},
            )
        self.accounts = AccountsService(self.db)
        self.billing = BillingService(self.db)
        self.collections = CollectionsService(self.db)
        self.purchases = PurchasesService(self.db)
        self.account = self.accounts.create_account(
            self.company, AccountCreate(nickname="Regression bank", account_type="bank")
        )

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def invoice(self, amount=150, initial=50, auto_create=True):
        from app.schemas.billing import InvoiceCreate

        return self.billing.create_invoice(
            self.company,
            InvoiceCreate(
                customer_party_id=self.party,
                invoice_date=date(2026, 9, 10),
                subtotal=amount,
                total=amount,
                amount_received=initial,
                account_id=self.account["id"] if initial else None,
                payment_mode="bank" if initial else None,
                auto_create_receivable=auto_create,
            ),
        )

    def collect(self, receivable_id, amount, payment_date=date(2026, 9, 11)):
        from app.schemas.collections import ReceivablePaymentCreate

        return self.collections.collect_receivable(
            receivable_id,
            self.company,
            ReceivablePaymentCreate(
                amount=amount,
                account_id=self.account["id"],
                payment_mode="bank",
                idempotency_key=str(uuid4()),
                payment_date=payment_date,
            ),
        )

    def receivable_state(self, receivable_id):
        return dict(
            self.db.execute(
                self.text(
                    """
                    select r.amount_received, r.status, i.amount_received as invoice_received,
                           i.collection_status
                    from receivables r join invoices i on i.id = r.invoice_id
                    where r.id = :id
                    """
                ),
                {"id": receivable_id},
            ).mappings().one()
        )

    def reverse(self, source_type, source_id, reversal_date=date(2026, 9, 15)):
        from app.schemas.accounts import TransactionReverseCreate

        transaction = self.db.execute(
            self.text(
                """
                select id from account_transactions
                where company_id = :company and source_type = :source_type and source_id = :source_id
                """
            ),
            {"company": self.company, "source_type": source_type, "source_id": source_id},
        ).scalar_one()
        return self.accounts.reverse_transaction(
            str(transaction), self.company, TransactionReverseCreate(transaction_date=reversal_date)
        )

    def test_initial_and_later_collections_reconcile_and_reverse(self):
        invoice = self.invoice()
        receivable_id = str(self.collections.list_receivables(self.company)["items"][0]["id"])
        later = self.collect(receivable_id, 50)
        self.assertEqual(self.receivable_state(receivable_id)["amount_received"], Decimal("100"))
        with self.assertRaises(HTTPException) as error:
            self.collect(receivable_id, "50.01")
        self.assertEqual(error.exception.status_code, 422)
        final = self.collect(receivable_id, 50)
        state = self.receivable_state(receivable_id)
        self.assertEqual((state["amount_received"], state["status"]), (Decimal("150"), "SETTLED"))
        self.assertEqual(state["invoice_received"], Decimal("150"))
        self.reverse("receivable_payment", later["id"])
        self.assertEqual(self.receivable_state(receivable_id)["amount_received"], Decimal("100"))
        self.reverse("invoice", invoice["id"])
        self.assertEqual(self.receivable_state(receivable_id)["amount_received"], Decimal("50"))
        self.reverse("receivable_payment", final["id"])
        state = self.receivable_state(receivable_id)
        self.assertEqual((state["amount_received"], state["status"]), (Decimal("0"), "UNPAID"))
        self.assertEqual((state["invoice_received"], state["collection_status"]), (Decimal("0"), "UNPAID"))
        aging = list(csv.DictReader(StringIO(self.collections.export_ar_aging_csv(self.company, "2026-09-12"))))
        self.assertEqual(aging, [])

    def test_fully_paid_invoice_has_receivable_for_later_reversal(self):
        invoice = self.invoice(amount=50, initial=50)
        receivable = self.collections.list_receivables(self.company)["items"][0]
        self.assertEqual(receivable["status"], "SETTLED")
        self.reverse("invoice", invoice["id"])
        self.assertEqual(self.receivable_state(str(receivable["id"]))["status"], "UNPAID")

    def test_manual_link_checks_invoice_and_initial_receipt(self):
        from app.schemas.collections import ReceivableCreate

        invoice = self.invoice(auto_create=False)
        for party, amount in ((self.other_party, 150), (self.party, 149)):
            with self.assertRaises(HTTPException):
                self.collections.create_receivable(
                    self.company, ReceivableCreate(party_id=party, invoice_id=invoice["id"], amount_due=amount)
                )
        receivable = self.collections.create_receivable(
            self.company, ReceivableCreate(party_id=self.party, invoice_id=invoice["id"], amount_due=150)
        )
        self.assertEqual(receivable["amount_received"], Decimal("50"))
        with self.assertRaises(HTTPException) as error:
            self.collections.create_receivable(
                self.company, ReceivableCreate(party_id=self.party, invoice_id=invoice["id"], amount_due=150)
            )
        self.assertEqual(error.exception.status_code, 409)

    def test_reconciliation_heals_ledger_and_rejects_ambiguous_data(self):
        invoice = self.invoice()
        receivable_id = str(self.collections.list_receivables(self.company)["items"][0]["id"])
        self.collect(receivable_id, 50)
        self.db.execute(
            self.text("update receivables set amount_received = 50 where id = :id"), {"id": receivable_id}
        )
        self.db.execute(
            self.text("update invoices set amount_received = 50 where id = :id"), {"id": invoice["id"]}
        )
        self.assertEqual(self.billing.reconcile_invoices(self.company)["healed_count"], 1)
        self.assertEqual(self.receivable_state(receivable_id)["amount_received"], Decimal("100"))
        self.db.execute(
            self.text("update invoices set amount_received = 125 where id = :id"), {"id": invoice["id"]}
        )
        with self.assertRaises(HTTPException) as error:
            self.billing.reconcile_invoices(self.company)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.receivable_state(receivable_id)["invoice_received"], Decimal("125"))

    def test_reminders_accept_null_empty_and_nonempty_notes_via_http(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes.collections import router
        from app.dependencies import get_db
        from app.schemas.collections import ReceivableCreate

        receivable = self.collections.create_receivable(
            self.company, ReceivableCreate(party_id=self.party, amount_due=100)
        )
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        with TestClient(app) as client:
            for notes in (None, "", "Called the customer"):
                response = client.post(
                    f"/receivables/{receivable['id']}/remind",
                    params={"company_id": self.company},
                    json={"next_reminder_date": "2026-09-20", "notes": notes},
                )
                self.assertEqual(response.status_code, 200, response.text)
        history = self.collections.list_reminder_history(str(receivable["id"]), self.company)["items"]
        self.assertEqual(len(history), 3)
        self.assertEqual(sum(row["notes"] == "Called the customer" for row in history), 1)

    def test_payment_and_reversal_chronology(self):
        from app.schemas.accounts import TransactionReverseCreate
        from app.schemas.purchases import PurchaseCreate, PurchasePaymentCreate

        invoice = self.invoice()
        receivable_id = str(self.collections.list_receivables(self.company)["items"][0]["id"])
        with self.assertRaises(HTTPException):
            self.collect(receivable_id, 1, date(2026, 9, 9))
        transaction = self.db.execute(
            self.text("select id from account_transactions where source_type = 'invoice' and source_id = :id"),
            {"id": invoice["id"]},
        ).scalar_one()
        with self.assertRaises(HTTPException):
            self.accounts.reverse_transaction(
                str(transaction), self.company, TransactionReverseCreate(transaction_date=date(2026, 9, 9))
            )
        purchase = self.purchases.create_purchase(
            self.company, PurchaseCreate(vendor_party_id=self.party, subtotal=100, purchase_date=date(2026, 9, 10))
        )
        with self.assertRaises(HTTPException):
            self.purchases.add_purchase_payment(
                str(purchase["id"]), self.company,
                PurchasePaymentCreate(amount=1, account_id=self.account["id"], payment_mode="bank",
                                      idempotency_key=str(uuid4()), payment_date=date(2026, 9, 9)),
            )

    def test_backdated_borrowing_changes_respect_dated_reversals(self):
        from app.schemas.accounts import TransactionReverseCreate
        from app.schemas.settlements import BorrowingEntryCreate
        from app.services.settlements_service import SettlementsService

        service = SettlementsService(self.db)
        borrowing = service.create_borrowing(
            self.company, BorrowingEntryCreate(
                party_id=self.party, direction="borrow", amount=100, account_id=self.account["id"],
                transaction_date=date(2026, 9, 10),
            )
        )
        repayment = service.create_borrowing(
            self.company, BorrowingEntryCreate(
                party_id=self.party, direction="repay", amount=100, account_id=self.account["id"],
                transaction_date=date(2026, 9, 11),
            )
        )
        transactions = {
            str(row["source_id"]): str(row["id"])
            for row in self.db.execute(
                self.text("""select id, source_id from account_transactions
                    where company_id=:company and source_type='borrowing'"""),
                {"company": self.company},
            ).mappings()
        }
        self.accounts.reverse_transaction(
            transactions[str(repayment["id"])], self.company,
            TransactionReverseCreate(transaction_date=date(2026, 9, 20)),
        )
        with self.assertRaises(HTTPException) as error:
            service.create_borrowing(
                self.company, BorrowingEntryCreate(
                    party_id=self.party, direction="repay", amount=1,
                    transaction_date=date(2026, 9, 15),
                )
            )
        self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(HTTPException) as error:
            self.accounts.reverse_transaction(
                transactions[str(borrowing["id"])], self.company,
                TransactionReverseCreate(transaction_date=date(2026, 9, 15)),
            )
        self.assertEqual(error.exception.status_code, 422)
        service.create_borrowing(
            self.company, BorrowingEntryCreate(
                party_id=self.party, direction="repay", amount=100,
                transaction_date=date(2026, 9, 20),
            )
        )
        self.assertEqual(service.summarize_borrowings(self.company)["items"][0]["net_outstanding"], 0)

    def test_legacy_business_payment_borrowing_is_not_guessed(self):
        from app.schemas.accounts import AccountCreate, BusinessPaymentCreate, TransactionReverseCreate
        from app.services.settlements_service import SettlementsService

        account = self.accounts.create_account(
            self.company, AccountCreate(nickname="Legacy lender", account_type="bank", party_id=self.party)
        )
        payment = self.accounts.create_business_payment(
            self.company, BusinessPaymentCreate(
                from_account_id=account["id"], purpose="expense", amount=25,
                transaction_date=date(2026, 9, 10),
            )
        )
        self.db.execute(
            self.text("update borrowings set source_transaction_id=null where id=:id"),
            {"id": payment["borrowing_id"]},
        )
        with self.assertRaises(HTTPException) as error:
            self.accounts.reverse_transaction(
                str(payment["account_transaction"]["id"]), self.company,
                TransactionReverseCreate(transaction_date=date(2026, 9, 11)),
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(
            SettlementsService(self.db).summarize_borrowings(self.company)["items"][0]["net_outstanding"],
            Decimal("25"),
        )
        self.assertEqual(
            self.db.execute(
                self.text("select count(*) from account_transactions where reversal_of_transaction_id=:id"),
                {"id": payment["account_transaction"]["id"]},
            ).scalar_one(), 0,
        )

    def test_status_matches_ledger_and_bad_debt_needs_reason(self):
        from app.schemas.collections import ReceivableCreate, ReceivableStatusUpdate

        receivable = self.collections.create_receivable(
            self.company, ReceivableCreate(party_id=self.party, amount_due=100)
        )
        rid = str(receivable["id"])
        for payload in (
            ReceivableStatusUpdate(status="SETTLED"),
            ReceivableStatusUpdate(status="PARTIAL"),
            ReceivableStatusUpdate(status="BAD_DEBT", bad_debt_reason="  "),
        ):
            with self.assertRaises(HTTPException):
                self.collections.update_receivable_status(rid, self.company, payload)
        result = self.collections.update_receivable_status(
            rid, self.company, ReceivableStatusUpdate(status="BAD_DEBT", bad_debt_reason="Customer insolvent")
        )
        self.assertEqual(result["status"], "BAD_DEBT")
        result = self.collections.update_receivable_status(
            rid, self.company, ReceivableStatusUpdate(status="UNPAID")
        )
        self.assertEqual(result["status"], "UNPAID")

    def test_purchase_response_and_idempotent_replay_include_lines(self):
        from fastapi.encoders import jsonable_encoder
        from app.schemas.masters import HsnMasterCreate
        from app.schemas.purchases import PurchaseCreate
        from app.services.masters_service import MastersService

        MastersService(self.db).create_hsn(HsnMasterCreate(code="8516", description="Test", gst_rate=18), self.company)
        payload = PurchaseCreate(
            vendor_party_id=self.party,
            idempotency_key=str(uuid4()),
            lines=[{"description": "Test item", "hsn": "8516", "quantity": 2, "rate": 50}],
        )
        first = self.purchases.create_purchase(self.company, payload)
        replay = self.purchases.create_purchase(
            self.company,
            PurchaseCreate(
                vendor_party_id=self.party,
                idempotency_key=payload.idempotency_key,
                lines=[{"description": "Test item", "hsn": "8516", "quantity": 2, "rate": 50}],
            ),
        )
        self.assertEqual(len(first["line_items"]), 1)
        self.assertEqual(jsonable_encoder(first), replay)

    def test_inconsistent_totals_and_blank_payment_mode_are_rejected(self):
        from app.schemas.billing import InvoiceCreate
        from app.schemas.purchases import PurchaseCreate

        for create, payload in (
            (self.billing.create_invoice, InvoiceCreate(customer_party_id=self.party, subtotal=100, gst_total=18, total=1)),
            (self.purchases.create_purchase, PurchaseCreate(vendor_party_id=self.party, subtotal=100, gst_total=18, total=1)),
            (self.billing.create_invoice, InvoiceCreate(customer_party_id=self.party, subtotal="999999999999.99", gst_total="0.01")),
            (self.purchases.create_purchase, PurchaseCreate(vendor_party_id=self.party, subtotal="999999999999.99", gst_total="0.01")),
            (self.billing.create_invoice, InvoiceCreate(customer_party_id=self.party, subtotal=100, amount_received=1,
                                                       account_id=self.account["id"], payment_mode=" ")),
            (self.purchases.create_purchase, PurchaseCreate(vendor_party_id=self.party, subtotal=100, amount_paid=1,
                                                            account_id=self.account["id"], payment_mode=" ")),
        ):
            with self.subTest(payload=type(payload).__name__):
                with self.assertRaises(HTTPException) as error:
                    create(self.company, payload)
                self.assertEqual(error.exception.status_code, 422)

    def test_closed_period_blocks_status_and_manual_stock_adjustment(self):
        from app.schemas.collections import ReceivableCreate, ReceivableStatusUpdate
        from app.schemas.inventory import ProductInput, StockAdjustment
        from app.services.inventory_service import InventoryService

        receivable = self.collections.create_receivable(
            self.company, ReceivableCreate(party_id=self.party, amount_due=100)
        )
        inventory = InventoryService(self.db, self.company)
        product = inventory.save_product(ProductInput(name="Locked stock fixture"))
        self.db.execute(
            self.text("""insert into accounting_period_locks(company_id, period_start, period_end)
                values(:company, :today, :today)"""),
            {"company": self.company, "today": date.today()},
        )
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            self.collections.update_receivable_status(
                str(receivable["id"]), self.company,
                ReceivableStatusUpdate(status="BAD_DEBT", bad_debt_reason="Insolvent"),
            )
        self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(HTTPException) as error:
            inventory.adjust_stock(
                str(product["id"]), StockAdjustment(direction="IN", quantity=1, notes="Locked period regression")
            )
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(inventory.detail(str(product["id"]))["stock_qty"], 0)

    def test_inventory_reconciliation_detects_gaps_and_missing_source(self):
        from app.schemas.inventory import ProductInput, StockAdjustment
        from app.services.inventory_service import InventoryService

        inventory = InventoryService(self.db, self.company)
        product = inventory.save_product(ProductInput(name="Reconciliation fixture"))
        product_id = str(product["id"])
        inventory.adjust_stock(
            product_id, StockAdjustment(direction="IN", quantity=2, notes="Synthetic receipt"),
            commit=False, reference_type="purchase_receipt", reference_id=str(uuid4()),
        )
        self.db.execute(
            self.text("update stock_balances set quantity=3 where company_id=:company and product_id=:product"),
            {"company": self.company, "product": product_id},
        )
        row = inventory.stock_reconciliation()["items"][0]
        self.assertEqual(
            (row["balance_quantity"], row["movement_quantity"], row["difference"], row["missing_document_references"]),
            (Decimal("3"), Decimal("2"), Decimal("1"), 1),
        )
        from app.schemas.inventory import ExternalMovementSource

        missing = inventory.missing_movement_sources()["items"]
        self.assertEqual([item["reference_type"] for item in missing], ["purchase_receipt"])
        valid_movement = str(self.db.execute(
            self.text("select id from stock_movements where company_id=:company and reference_type='manual_inventory' limit 1"),
            {"company": self.company},
        ).scalar_one_or_none() or uuid4())
        with self.assertRaises(HTTPException) as error:
            inventory.attribute_external_source(valid_movement, ExternalMovementSource(external_reference="B-1", notes="x"))
        self.assertEqual(error.exception.status_code, 422)
        updated = inventory.attribute_external_source(
            str(missing[0]["id"]), ExternalMovementSource(external_reference="Vendor bill 4471", notes="Paper bill filed")
        )
        self.assertEqual((updated["reference_type"], updated["reference_id"], updated["quantity"]),
                         ("external_document", None, Decimal("2.000")))
        row = inventory.stock_reconciliation()["items"][0]
        self.assertEqual((row["movement_quantity"], row["difference"], row["missing_document_references"]),
                         (Decimal("2"), Decimal("1"), 0))
        self.assertEqual(inventory.missing_movement_sources()["items"], [])

    def test_failed_reminder_history_insert_rolls_back_metadata(self):
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes.collections import router
        from app.dependencies import get_db
        from app.schemas.collections import ReceivableCreate

        receivable = self.collections.create_receivable(
            self.company, ReceivableCreate(party_id=self.party, amount_due=100, notes="Original")
        )
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        execute = self.db.execute

        def fail_history(statement, *args, **kwargs):
            if "insert into receivable_reminders" in str(statement):
                raise RuntimeError("Simulated history insert failure")
            return execute(statement, *args, **kwargs)

        with patch.object(self.db, "execute", side_effect=fail_history):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    f"/receivables/{receivable['id']}/remind",
                    params={"company_id": self.company},
                    json={"next_reminder_date": "2026-09-20", "notes": "Must roll back"},
                )
                self.assertEqual(response.status_code, 500)
        self.db.rollback()
        row = self.db.execute(
            self.text("select notes, last_reminded_at, reminder_date from receivables where id=:id"),
            {"id": receivable["id"]},
        ).mappings().one()
        self.assertEqual((row["notes"], row["last_reminded_at"], row["reminder_date"]), ("Original", None, None))
        self.assertEqual(self.collections.list_reminder_history(str(receivable["id"]), self.company)["items"], [])

    def stocked_product(self, quantity):
        from app.schemas.inventory import ProductInput, VendorOfferInput
        from app.schemas.masters import HsnMasterCreate
        from app.schemas.purchases import PurchaseCreate, PurchaseReceiptConfirm
        from app.services.inventory_service import InventoryService
        from app.services.masters_service import MastersService

        MastersService(self.db).create_hsn(HsnMasterCreate(code="8516", description="Test", gst_rate=18), self.company)
        self.db.execute(
            self.text("update companies set address='Chennai', gst_number='33ABCDE1234F1Z5' where id=:id"),
            {"id": self.company},
        )
        inventory = InventoryService(self.db, self.company)
        product = inventory.save_product(ProductInput(name="Edge case product", hsn_code="8516", selling_price=100))
        product_id = str(product["id"])
        inventory.save_offer(product_id, VendorOfferInput(vendor_id=self.party, mrp=150, buying_price=80))
        purchase = self.purchases.create_purchase(
            self.company,
            PurchaseCreate(vendor_party_id=self.party, purchase_date=date(2026, 9, 1),
                           lines=[{"product_id": product_id, "description": "x", "hsn": "8516",
                                   "quantity": quantity, "rate": 80}]),
        )
        self.purchases.confirm_purchase_receipt(str(purchase["id"]), self.company, PurchaseReceiptConfirm())
        return inventory, product_id, str(purchase["id"])

    def test_zero_value_documents_are_rejected_consistently(self):
        from app.schemas.billing import InvoiceCreate
        from app.schemas.purchases import PurchaseCreate

        for create, payload in (
            (self.billing.create_invoice, InvoiceCreate(customer_party_id=self.party, subtotal=0)),
            (self.purchases.create_purchase, PurchaseCreate(vendor_party_id=self.party, subtotal=0)),
        ):
            with self.subTest(payload=type(payload).__name__):
                with self.assertRaises(HTTPException) as error:
                    create(self.company, payload)
                self.assertEqual(error.exception.status_code, 422)
                self.db.rollback()

    def test_purchase_cancellation_after_stock_was_sold_is_rejected_atomically(self):
        from app.schemas.billing import InvoiceCreate
        from app.services.document_cancellation import Cancellation, cancel_document

        inventory, product_id, purchase_id = self.stocked_product(5)
        self.billing.create_invoice(
            self.company,
            InvoiceCreate(customer_party_id=self.party, invoice_date=date(2026, 9, 10), place_of_supply="33 - Tamil Nadu",
                          billing_address="Chennai",
                          lines=[{"product_id": product_id, "description": "x", "hsn": "8516", "quantity": 4, "rate": 100}]),
        )
        self.assertEqual(inventory.detail(product_id)["stock_qty"], 1)
        with self.assertRaises(HTTPException) as error:
            cancel_document(self.db, self.company, "purchase", purchase_id,
                            Cancellation(reason="Wrong bill", cancellation_date=date(2026, 9, 12)))
        self.assertEqual(error.exception.status_code, 422)
        self.db.rollback()
        status = self.db.execute(
            self.text("select status from purchases where id=:id"), {"id": purchase_id}
        ).scalar_one()
        self.assertEqual((status, inventory.detail(product_id)["stock_qty"]), ("POSTED", 1))

    def test_bad_debt_recovery_requires_reverting_status_first(self):
        from app.schemas.collections import ReceivableCreate, ReceivableStatusUpdate

        receivable = self.collections.create_receivable(
            self.company, ReceivableCreate(party_id=self.party, amount_due=100)
        )
        rid = str(receivable["id"])
        self.collections.update_receivable_status(
            rid, self.company, ReceivableStatusUpdate(status="BAD_DEBT", bad_debt_reason="Customer closed")
        )
        with self.assertRaises(HTTPException) as error:
            self.collect(rid, 40)
        self.assertEqual(error.exception.status_code, 422)
        self.collections.update_receivable_status(rid, self.company, ReceivableStatusUpdate(status="UNPAID"))
        self.collect(rid, 40)
        row = self.db.execute(
            self.text("select status, amount_received, bad_debt_reason from receivables where id=:id"), {"id": rid}
        ).mappings().one()
        self.assertEqual((row["status"], row["amount_received"], row["bad_debt_reason"]), ("PARTIAL", Decimal("40"), None))

    def test_oversized_itemized_totals_are_rejected_with_422(self):
        from app.schemas.billing import InvoiceCreate
        from app.schemas.masters import HsnMasterCreate
        from app.schemas.purchases import PurchaseCreate
        from app.services.masters_service import MastersService

        MastersService(self.db).create_hsn(HsnMasterCreate(code="8516", description="Test", gst_rate=18), self.company)
        line = {"description": "Huge", "hsn": "8516", "quantity": "999999999.999", "rate": "9999999999.99"}
        for create, payload in (
            (self.billing.create_invoice, InvoiceCreate(customer_party_id=self.party, lines=[line])),
            (self.purchases.create_purchase, PurchaseCreate(vendor_party_id=self.party, lines=[line])),
        ):
            with self.subTest(payload=type(payload).__name__):
                with self.assertRaises(HTTPException) as error:
                    create(self.company, payload)
                self.assertEqual(error.exception.status_code, 422)
                self.db.rollback()

    def test_invoice_cancellation_restores_stock_and_closes_receivable(self):
        from app.schemas.billing import InvoiceCreate
        from app.services.document_cancellation import Cancellation, cancel_document

        inventory, product_id, _ = self.stocked_product(5)
        invoice = self.billing.create_invoice(
            self.company,
            InvoiceCreate(customer_party_id=self.party, invoice_date=date(2026, 9, 10), amount_received=50,
                          account_id=self.account["id"], payment_mode="bank", place_of_supply="33 - Tamil Nadu", billing_address="Chennai",
                          lines=[{"product_id": product_id, "description": "x", "hsn": "8516", "quantity": 2, "rate": 100}]),
        )
        invoice_id = str(invoice["id"])
        with self.assertRaises(HTTPException) as error:
            cancel_document(self.db, self.company, "invoice", invoice_id, Cancellation(reason="Paid"))
        self.assertEqual(error.exception.status_code, 422)
        self.reverse("invoice", invoice_id)
        with self.assertRaises(HTTPException):
            cancel_document(self.db, self.company, "invoice", invoice_id,
                            Cancellation(reason="Too early", cancellation_date=date(2026, 9, 9)))
        cancel_document(self.db, self.company, "invoice", invoice_id,
                        Cancellation(reason="Customer returned", cancellation_date=date(2026, 9, 16)))
        self.assertEqual(inventory.detail(product_id)["stock_qty"], 5)
        self.assertNotIn(invoice_id, self.collections.export_ar_aging_csv(self.company, "2026-09-30"))
        with self.assertRaises(HTTPException) as error:
            receivable = self.db.execute(
                self.text("select id from receivables where invoice_id=:id"), {"id": invoice_id}
            ).scalar_one()
            self.collect(str(receivable), 10, payment_date=date(2026, 9, 17))
        self.assertEqual(error.exception.status_code, 422)
