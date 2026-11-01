import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.services.dashboard_service import DashboardService
from app.services.tenant_security import token_digest
from test_tenancy import TenantDatabaseCase


class OperationsDashboardTests(TenantDatabaseCase):
    def test_scoped_totals_statuses_months_and_module_permissions(self):
        tenant, cookies, _ = self.register("dashboard")
        company = tenant["user"]["company_id"]
        with self.factory() as db:
            main = db.execute(text("select id from stores where company_id=:company and is_default"), {"company": company}).scalar_one()
            second = db.execute(text("""insert into stores(company_id,code,name,kind,holds_stock,state_code)
                values(:company,'SECOND','Second shop','offline',true,'33') returning id"""), {"company": company}).scalar_one()
            party = db.execute(text("""insert into parties(company_id,party_type,legal_name)
                values(:company,'customer_vendor','Dashboard party') returning id"""), {"company": company}).scalar_one()
            product = db.execute(text("""insert into products(company_id,portal_product_id,name,uom,is_active,reorder_enabled,reorder_level)
                values(:company,:code,'Dashboard product','pcs',true,true,5) returning id"""),
                {"company": company, "code": str(uuid4())}).scalar_one()
            db.execute(text("""insert into stock_balances(company_id,store_id,product_id,quantity)
                values(:company,:main,:product,2.5),(:company,:second,:product,9)"""),
                {"company": company, "main": main, "second": second, "product": product})
            for number, store, day, status, quantity, total in [
                ("A", main, "2026-01-01", "POSTED", "2.5", 250),
                ("B", second, "2026-01-31", "POSTED", "3", 300),
                ("C", main, "2026-02-01", "POSTED", "100", 10000),
                ("D", main, "2026-01-15", "CANCELLED", "100", 10000),
            ]:
                db.execute(text("""insert into invoices(company_id,store_id,customer_party_id,invoice_number,invoice_date,
                    subtotal,gst_total,total,status,document_data) values(:company,:store,:party,:number,:day, :total,0,:total,:status,cast(:data as jsonb))"""),
                    {"company": company, "store": store, "party": party, "number": number, "day": date.fromisoformat(day),
                     "total": total, "status": status, "data": json.dumps({"lines": [{"product_id": str(product),
                        "description": "Snapshot product", "quantity": quantity}]})})
            db.execute(text("""insert into invoices(company_id,store_id,customer_party_id,invoice_number,invoice_date,
                subtotal,gst_total,total,status)
                select :company,:store,:party,'BULK-'||n,'2026-03-01',0.01,0,0.01,'POSTED'
                from generate_series(1,501) n"""), {"company": company, "store": main, "party": party})
            for store, receipt, kind, status, quantity in [
                (main, "PENDING", "PRODUCT", "POSTED", "4.5"),
                (second, "PENDING", "PRODUCT", "POSTED", "7"),
                (main, "RECEIVED", "PRODUCT", "POSTED", "10"),
                (main, "PENDING", "SERVICE", "POSTED", "10"),
                (main, "PENDING", "PRODUCT", "CANCELLED", "10"),
            ]:
                db.execute(text("""insert into purchases(company_id,store_id,vendor_party_id,purchase_date,subtotal,gst_total,total,
                    amount_paid,payment_status,receipt_status,receipt_type,status,line_items)
                    values(:company,:store,:party,'2026-01-10',10,0,10,0,'UNPAID',:receipt,:kind,:status,cast(:lines as jsonb))"""),
                    {"company": company, "store": store, "party": party, "receipt": receipt, "kind": kind, "status": status,
                     "lines": json.dumps([{"quantity": quantity}])})
            shopper = db.execute(text("""insert into shopper_accounts(company_id,email,display_name,supabase_uid)
                values(:company,'dashboard@example.com','Dashboard shopper',:uid) returning id"""),
                {"company": company, "uid": str(uuid4())}).scalar_one()
            for index, (status, store, expired, channel, fulfilment) in enumerate([
                ("cod_requested", main, False, "web", "delivery"),
                ("cod_requested", main, True, "web", "delivery"),
                ("shipping_pending", main, False, "web", "delivery"),
                ("dispatched", main, False, "whatsapp", "delivery"),
                ("ready_for_pickup", main, False, "web", "pickup"),
                ("fulfilment_review", main, False, "web", "delivery"),
                ("cancelled", main, False, "web", "delivery"),
                ("paid", second, False, "web", "delivery"),
            ]):
                db.execute(text("""insert into shop_orders(company_id,shopper_id,request_key,request_hash,status,items,address,
                    subtotal_paise,shipping_paise,total_paise,pickup_location,store_id,channel,fulfilment_method,pickup_store_id,created_at,expires_at)
                    values(:company,:shopper,:key,:hash,:status,'[]','{}',100,0,100,'',:store,:channel,:fulfilment,:pickup,
                    '2026-01-10',case when :expired then now()-interval '1 hour' else null end)"""),
                    {"company": company, "shopper": shopper, "key": uuid4(), "hash": str(index), "status": status,
                     "store": store, "channel": channel, "fulfilment": fulfilment, "pickup": main if fulfilment == "pickup" else None,
                     "expired": expired})
            db.commit()
        response = self.client.get("/api/dashboard", params={"month": "2026-01-01"})
        self.assertEqual(response.status_code, 200, response.text)
        summary = response.json()
        self.assertEqual(summary["sales"]["invoices"], 2)
        self.assertEqual(summary["sales"]["total"], 550)
        self.assertEqual(summary["sales"]["top_items"][0]["quantity"], 5.5)
        self.assertEqual(summary["inventory"]["quantity_in_hand"], 11.5)
        self.assertEqual(summary["inventory"]["low_stock_items"], 0)
        self.assertEqual(summary["purchases"]["quantity_to_receive"], 11.5)
        self.assertEqual(summary["orders"]["to_confirm"], 1)
        self.assertEqual(summary["orders"]["to_ship"], 2)
        self.assertEqual(summary["orders"]["to_deliver"], 1)
        self.assertEqual(summary["orders"]["to_collect"], 1)
        self.assertEqual(summary["orders"]["needs_review"], 1)
        for channel in summary["orders"]["channels"]:
            self.assertEqual(channel["total"], sum(channel[key] for key in
                ["awaiting_payment", "confirmed", "to_ship", "dispatched", "ready_for_pickup", "needs_review", "completed", "closed"]))
        scoped = self.client.get("/dashboard", params={"month": "2026-01-01", "store_id": str(main)}).json()
        self.assertEqual(scoped["sales"]["total"], 250)
        self.assertEqual(scoped["inventory"]["low_stock_items"], 1)
        self.assertEqual(scoped["purchases"]["quantity_to_receive"], 4.5)
        self.assertIsNone(scoped["borrowing_outstanding"])
        bulk = self.client.get("/dashboard", params={"month": "2026-03-01"}).json()
        self.assertEqual(bulk["sales"]["invoices"], 501)
        self.assertEqual(bulk["sales"]["total"], 5.01)
        self.assertEqual(bulk["sales"]["top_items"], [])
        self.assertEqual(self.client.get("/dashboard", params={"month": "2026-01-02"}).status_code, 422)
        self.assertEqual(self.client.get("/dashboard", params={"store_id": str(uuid4())}).status_code, 404)
        with self.factory() as db:
            identity = {**tenant["user"], "role": "staff", "modules": ["inventory"], "store_ids": [str(main)]}
            db.info["tenant_context"] = identity
            scoped = DashboardService(db).summary(date(2026, 1, 1))
            self.assertEqual(scoped["inventory"]["quantity_in_hand"], Decimal("2.5"))
            self.assertIsNone(scoped["sales"])
            self.assertIsNone(scoped["orders"])
            self.assertIsNone(scoped["purchases"])
            self.assertIsNone(scoped["receivables"])
            with self.assertRaises(HTTPException) as failure:
                DashboardService(db).summary(store_id=str(second))
            self.assertEqual(failure.exception.status_code, 403)
            identity["store_ids"] = []
            empty = DashboardService(db).summary()
            self.assertEqual(empty["inventory"]["quantity_in_hand"], 0)
            self.assertEqual(empty["inventory"]["low_stock_items"], 0)
            identity["modules"] = ["orders"]
            self.assertIsNone(DashboardService(db).summary()["orders"])
            identity["role"] = "admin"
            self.assertIsNotNone(DashboardService(db).summary()["sales"])
        other, _, _ = self.register("dashboard-other")
        self.assertEqual(self.client.get("/dashboard", params={"company_id": company}).status_code, 403)
        empty = self.client.get("/dashboard", params={"month": "2026-01-01"}).json()
        self.assertEqual(empty["sales"]["total"], 0)
        self.assertEqual(empty["inventory"]["total_products"], 0)
        self.assertEqual(empty["orders"]["channels"], [])
        self.assertNotEqual(other["user"]["company_id"], company)

    def test_platform_rejects_tenant_sessions_hosts_and_headers_even_with_admin_cookie(self):
        tenant, cookies, _ = self.register("platform-boundary")
        admin_token = str(uuid4())
        with self.factory() as db:
            admin = db.execute(text("""insert into platform_admins(email,display_name,password_hash)
                values(:email,'Fixture platform admin','unusable-fixture-hash') returning id"""),
                {"email": self.suffix + "@platform.example.com"}).scalar_one()
            db.execute(text("""insert into platform_sessions(token_hash,admin_id,expires_at)
                values(:token,:admin,now()+interval '1 hour')"""), {"token": token_digest(admin_token), "admin": admin})
            db.commit()
        self.client.cookies.set("tenali_platform", admin_token)
        for prefix in ["/platform", "/api/platform"]:
            for path in ["/session", "/workspaces", "/social-login"]:
                self.assertEqual(self.client.get(prefix + path).status_code, 403)
            self.assertEqual(self.client.post(prefix + "/login", json={"email": "owner@example.com",
                "password": "Tenant cannot log into platform 123!"}, headers=self.headers(cookies)).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/platform/workspaces").status_code, 401)
        self.client.cookies.set("tenali_platform", admin_token)
        self.assertEqual(self.client.get("/platform/session").status_code, 200)
        self.assertEqual(self.client.get("/platform/workspaces", headers={"X-Tenant-Slug": tenant["user"]["tenant_slug"]}).status_code, 403)
        self.assertEqual(self.client.get("/platform/session", headers={"Host": tenant["user"]["tenant_slug"] + ".tenali-business.com"}).status_code, 403)
        self.client.cookies.set("tenali_session", "expired-tenant-session")
        self.assertEqual(self.client.get("/platform/session").status_code, 200)
        self.client.cookies.clear()
        with self.factory() as db:
            shopper = db.execute(text("""insert into shopper_accounts(company_id,email,display_name,supabase_uid)
                values(:company,'boundary@example.com','Boundary shopper',:uid) returning id"""),
                {"company": tenant["user"]["company_id"], "uid": str(uuid4())}).scalar_one()
            db.execute(text("""insert into shopper_sessions(token_hash,company_id,shopper_id,expires_at)
                values(:token,:company,:shopper,now()+interval '1 hour')"""),
                {"token": token_digest("fixture-shopper"), "company": tenant["user"]["company_id"], "shopper": shopper})
            db.commit()
        self.client.cookies.set("tenali_shopper", "fixture-shopper")
        self.client.cookies.set("tenali_platform", admin_token)
        self.assertEqual(self.client.get("/platform/session").status_code, 403)
