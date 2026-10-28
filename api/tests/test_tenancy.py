import unittest
import os
from contextlib import ExitStack
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.services.tenant_security import Login, Registration, normalize_domain, password_hash, password_matches, token_digest


class TenantSecurityTests(unittest.TestCase):
    def test_password_hashes_are_salted_and_verified(self):
        password = "A long test password 123!"
        first, second = password_hash(password), password_hash(password)
        self.assertNotEqual(first, second)
        self.assertNotIn(password, first)
        self.assertTrue(password_matches(password, first))
        self.assertFalse(password_matches("incorrect", first))
        self.assertFalse(password_matches(password, "invalid"))
        self.assertNotEqual(token_digest("one"), token_digest("two"))

    def test_workspace_and_registration_validation(self):
        payload = dict(company_name=" Example ", slug="example-company", email=" OWNER@EXAMPLE.COM ", display_name=" Owner ", password="A long test password 123!")
        registration = Registration(**payload)
        self.assertEqual(registration.email, "owner@example.com")
        for values in [{"slug": "admin"}, {"slug": "../other"}, {"email": "invalid"}, {"password": "short"}]:
            with self.assertRaises(ValidationError):
                Registration(**{**payload, **values})

    def test_domain_normalization_and_unsafe_hosts(self):
        self.assertEqual(normalize_domain(" Shop.Example.COM. "), "shop.example.com")
        for value in ["https://example.com", "127.0.0.1", "*.example.com", "example.com/path", "tenant.localhost", "user@example.com", "example.com:443"]:
            with self.assertRaises(ValueError):
                normalize_domain(value)


@unittest.skipUnless(os.getenv('TENALI_TEST_DB')=='1','Set TENALI_TEST_DB=1 for rollback-only tenant HTTP/database tests')
class TenantBoundaryTests(unittest.TestCase):
    def setUp(self):
        from dotenv import load_dotenv
        load_dotenv('api/.env')
        from sqlalchemy.orm import Session
        from app.core.database import engine
        from app.main import app
        from fastapi.testclient import TestClient
        self.connection=engine.connect()
        self.outer=self.connection.begin()
        self.stack=ExitStack()
        connection=self.connection
        class FixtureSession(Session):
            def close(inner):
                super().close()
                if connection.in_transaction():
                    connection.exec_driver_sql('RESET ROLE')
                    connection.exec_driver_sql("select set_config('app.tenant_id','',true),set_config('app.actor_user_id','',true)")
        self.factory=lambda:FixtureSession(bind=self.connection,join_transaction_mode='create_savepoint')
        for target in ['app.core.database.SessionLocal','app.services.tenant_context.SessionLocal','app.api.routes.auth.SessionLocal','app.main.SessionLocal']:
            self.stack.enter_context(patch(target,self.factory))
        self.stack.enter_context(patch.dict(os.environ,{'TENALI_ENV':'development','TENALI_BASE_DOMAIN':'tenali-business.com'}))
        self.client=self.stack.enter_context(TestClient(app,base_url='http://localhost'))
        self.suffix=uuid4().hex[:8]

    def tearDown(self):
        self.stack.close()
        self.outer.rollback()
        self.connection.close()

    def register(self,prefix):
        email=f'{prefix}-{self.suffix}@example.com'
        response=self.client.post('/auth/register',json={'company_name':prefix+' Tenant','slug':prefix+'-'+self.suffix,'display_name':'Owner','email':email,'password':'Test password for tenancy 123!'},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,201,response.text)
        result=response.json()
        cookies=dict(self.client.cookies)
        return result,cookies,email

    def headers(self,cookies):
        return {'Origin':'http://localhost','X-CSRF-Token':cookies['tenali_csrf']}

    def use_cookies(self,cookies):
        self.client.cookies.clear()
        self.client.cookies.update(cookies)

    def test_registration_isolation_id_tampering_roles_and_download_boundary(self):
        from sqlalchemy import text
        self.assertEqual(self.client.get('/accounts').status_code,401)
        first,cookies_a,_=self.register('tenant-a')
        party_a=self.client.post('/parties',json={'party_type':'customer','legal_name':'Private A'},headers=self.headers(cookies_a))
        self.assertEqual(party_a.status_code,201,party_a.text)
        second,cookies_b,_=self.register('tenant-b')
        self.assertNotEqual(first['user']['company_id'],second['user']['company_id'])
        self.assertEqual(self.client.get('/parties').json()['items'],[])
        override=self.client.get('/parties',params={'company_id':first['user']['company_id']})
        self.assertEqual(override.status_code,403)
        self.assertEqual(self.client.patch('/parties/'+party_a.json()['id'],json={'legal_name':'Stolen'},headers=self.headers(cookies_b)).status_code,404)
        self.assertEqual(self.client.post('/accounts',json={'nickname':'Cross link','account_type':'bank','party_id':party_a.json()['id']},headers=self.headers(cookies_b)).status_code,422)
        no_csrf=self.client.post('/parties',json={'party_type':'customer','legal_name':'No CSRF'})
        self.assertEqual(no_csrf.status_code,403)
        self.assertEqual(self.client.post('/parties',json={'party_type':'customer','legal_name':'Cross origin'},headers={**self.headers(cookies_b),'Origin':'https://evil.example.com'}).status_code,403)
        self.assertEqual(self.client.get('/documents/'+str(uuid4())+'/download').status_code,404)
        self.use_cookies(cookies_a)
        self.assertEqual(len(self.client.get('/parties').json()['items']),1)
        viewer_email='viewer-'+self.suffix+'@example.com'
        created=self.client.post('/auth/team',json={'display_name':'Viewer','email':viewer_email,'password':'Viewer test password 123!','role':'viewer'},headers=self.headers(cookies_a))
        self.assertEqual(created.status_code,201,created.text)
        self.client.cookies.clear()
        login=self.client.post('/auth/login',json={'email':viewer_email,'password':'Viewer test password 123!'},headers={'Origin':'http://localhost'})
        self.assertEqual(login.status_code,200,login.text)
        viewer_cookies=dict(self.client.cookies)
        self.assertEqual(self.client.get('/parties').status_code,200)
        self.assertEqual(self.client.post('/parties',json={'party_type':'customer','legal_name':'Forbidden'},headers=self.headers(viewer_cookies)).status_code,403)
        self.assertEqual(self.client.get('/auth/team').status_code,403)
        with self.factory() as db:
            db.info['tenant_context']=first['user']
            self.assertEqual(len(db.execute(text('select id from parties')).all()),1)
            db.commit()
            self.assertTrue(all(str(row.company_id)==first['user']['company_id'] for row in db.execute(text('select company_id from parties'))))

    def test_public_storefront_domain_claims_and_session_revocation(self):
        first,cookies,email=self.register('public-a')
        slug=first['user']['tenant_slug']
        self.assertEqual(self.client.get('/catalog/home').status_code,404)
        storefront=self.client.get('/catalog/company',headers={'X-Tenant-Slug':slug})
        self.assertEqual(storefront.status_code,200,storefront.text)
        self.assertEqual(storefront.json()['id'],first['user']['company_id'])
        self.assertNotIn('invoice_settings',storefront.json())
        self.assertEqual(self.client.get('/catalog/company',params={'company_id':str(uuid4())},headers={'X-Tenant-Slug':slug}).status_code,403)
        host='shop-'+self.suffix+'.example.com'
        added=self.client.post('/auth/domains',json={'hostname':host},headers=self.headers(cookies))
        self.assertEqual(added.status_code,201,added.text)
        domain=added.json()['items'][0]
        self.assertEqual(self.client.get('/catalog/company',headers={'Host':host}).status_code,404)
        class Txt:
            strings=[domain['verification_token'].encode()]
        with patch('app.api.routes.auth.dns.resolver.resolve',return_value=[Txt()]):
            verified=self.client.post('/auth/domains/'+domain['id']+'/verify',headers=self.headers(cookies))
        self.assertEqual(verified.status_code,200,verified.text)
        public=self.client.get('/catalog/company',headers={'Host':host})
        self.assertEqual(public.status_code,200,public.text)
        self.assertEqual(public.json()['id'],first['user']['company_id'])
        self.assertEqual(self.client.get('/domain-authorization',params={'domain':host}).status_code,200)
        self.assertEqual(self.client.get('/domain-authorization',params={'domain':'not-verified.example.com'}).status_code,403)
        logout=self.client.post('/auth/logout',headers=self.headers(cookies))
        self.assertEqual(logout.status_code,200,logout.text)
        self.use_cookies(cookies)
        self.assertEqual(self.client.get('/accounts').status_code,401)

    def test_workspace_address_change_keeps_alias_and_rejects_cross_tenant_claim(self):
        first,cookies_a,_=self.register('slug-a')
        second,cookies_b,_=self.register('slug-b')
        new_slug='custom-'+self.suffix
        headers=self.headers(cookies_a)
        self.use_cookies(cookies_a)
        changed=self.client.put('/company',json={'company_name':first['user']['company_name'],'tenant_slug':new_slug},headers=headers)
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(changed.json()['tenant_slug'],new_slug)
        self.assertEqual(self.client.get('/catalog/company',headers={'X-Tenant-Slug':new_slug}).json()['id'],first['user']['company_id'])
        self.assertEqual(self.client.get('/catalog/company',headers={'X-Tenant-Slug':first['user']['tenant_slug']}).json()['id'],first['user']['company_id'])
        self.use_cookies(cookies_b)
        conflict=self.client.put('/company',json={'company_name':second['user']['company_name'],'tenant_slug':first['user']['tenant_slug']},headers=self.headers(cookies_b))
        self.assertEqual(conflict.status_code,409,conflict.text)

    def test_real_financial_inventory_and_file_ids_stay_private(self):
        import base64
        first,cookies_a,_=self.register('assets-a')
        account=self.client.post('/accounts',json={'nickname':'Private bank','account_type':'bank','is_company_account':True},headers=self.headers(cookies_a))
        self.assertEqual(account.status_code,201,account.text)
        master=self.client.post('/masters/hsn',json={'code':'8516','description':'Own tax code','gst_rate':18,'is_active':True},headers=self.headers(cookies_a))
        self.assertEqual(master.status_code,201,master.text)
        product=self.client.post('/inventory/products',json={'name':'Private product','hsn_code':'8516','selling_price':100,'catalog_visible':True},headers=self.headers(cookies_a))
        self.assertEqual(product.status_code,201,product.text)
        product_id=product.json()['id']
        stock=self.client.post('/inventory/products/'+product_id+'/stock',json={'direction':'IN','quantity':3,'notes':'Tenant fixture','idempotency_key':str(uuid4())},headers=self.headers(cookies_a))
        self.assertEqual(stock.status_code,200,stock.text)
        payment=self.client.post('/accounts/business-payments',json={'from_account_id':account.json()['id'],'purpose':'expense','amount':10,'idempotency_key':str(uuid4()),
            'attachments':[{'file_name':'private.pdf','mime_type':'application/pdf','data_base64':base64.b64encode(b'%PDF-1.4 private tenant fixture').decode()}]},headers=self.headers(cookies_a))
        self.assertEqual(payment.status_code,201,payment.text)
        transaction=payment.json()['account_transaction']['id']
        files=self.client.get('/documents/business_payment/'+transaction)
        self.assertEqual(files.status_code,200,files.text)
        file_id=files.json()['items'][0]['id']
        self.assertEqual(self.client.get('/documents/'+file_id+'/download').status_code,200)
        second,cookies_b,_=self.register('assets-b')
        self.assertEqual(self.client.get('/accounts').json()['items'],[])
        self.assertEqual(self.client.get('/inventory/products').json()['items'],[])
        self.assertEqual(self.client.get('/inventory/products/'+product_id).status_code,404)
        self.assertEqual(self.client.get('/documents/'+file_id+'/download').status_code,404)
        self.assertEqual(self.client.get('/documents/business_payment/'+transaction).status_code,404)
        self.assertEqual(self.client.post('/inventory/products/'+product_id+'/stock',json={'direction':'OUT','quantity':1,'notes':'Forbidden'},headers=self.headers(cookies_b)).status_code,404)
        self.assertEqual(self.client.post('/accounts/business-payments',json={'from_account_id':account.json()['id'],'purpose':'expense','amount':1},headers=self.headers(cookies_b)).status_code,404)
        self.assertEqual(self.client.post('/auth/switch',json={'company_id':first['user']['company_id']},headers=self.headers(cookies_b)).status_code,403)
        own=self.client.post('/auth/workspaces',json={'company_name':'Additional own company','slug':'extra-'+self.suffix},headers=self.headers(cookies_b))
        self.assertEqual(own.status_code,201,own.text)
        self.assertEqual(len(own.json()['workspaces']),2)
        own_cookies=dict(self.client.cookies)
        switched=self.client.post('/auth/switch',json={'company_id':second['user']['company_id']},headers=self.headers(own_cookies))
        self.assertEqual(switched.status_code,200,switched.text)
        self.assertEqual(switched.json()['user']['company_id'],second['user']['company_id'])