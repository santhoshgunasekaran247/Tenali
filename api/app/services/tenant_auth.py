import secrets
import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.services.tenant_security import PASSWORD_ITERATIONS, Registration, password_hash, password_matches, token_digest


class TenantAuth:
    def __init__(self, db):
        self.db = db

    def audit(self,company_id:str,user_id:str,action:str,entity_id:str|None=None,details:dict|None=None):
        self.db.execute(text("""insert into audit_events(company_id,actor_user_id,action,entity_type,entity_id,new_value,source_type)
            values(:company,:user,:action,'tenant_access',:entity,cast(:details as jsonb),'authentication')"""),
            {'company':company_id,'user':user_id,'action':action,'entity':entity_id,'details':json.dumps(details or {})})

    def throttle(self, bucket: str, limit: int = 20):
        attempts = self.db.execute(text("""insert into tenant_auth_attempts(bucket) values(:bucket)
            on conflict(bucket) do update set attempts=case when tenant_auth_attempts.window_start<now()-interval '15 minutes' then 1 else tenant_auth_attempts.attempts+1 end,
            window_start=case when tenant_auth_attempts.window_start<now()-interval '15 minutes' then now() else tenant_auth_attempts.window_start end
            returning attempts"""), {"bucket": token_digest(bucket)}).scalar_one()
        self.db.commit()
        if attempts > limit:
            raise HTTPException(429, "Too many attempts. Please try again later.")

    def session(self, user_id: str, company_id: str):
        token = secrets.token_urlsafe(48)
        self.db.execute(text("delete from tenant_sessions where expires_at<now()"))
        self.db.execute(text("insert into tenant_sessions(token_hash,user_id,company_id,expires_at) values(:token,:user,:company,:expires)"),
                        {"token": token_digest(token), "user": user_id, "company": company_id, "expires": datetime.now(timezone.utc)+timedelta(hours=12)})
        self.db.commit()
        return token

    def identity(self, token: str | None):
        if not token:
            raise HTTPException(401, "Sign in to your workspace")
        row = self.db.execute(text("""select account.id as user_id,account.email,account.display_name,member.company_id,member.role,
            company.company_name,company.nickname,company.logo_url,company.tenant_slug
            from tenant_sessions session join tenant_users account on account.id=session.user_id and account.is_active=true
            join tenant_memberships member on member.user_id=account.id and member.company_id=session.company_id and member.is_active=true
            join companies company on company.id=member.company_id and company.is_active=true
            where session.token_hash=:token and session.expires_at>now()"""), {"token": token_digest(token)}).mappings().first()
        if not row:
            raise HTTPException(401, "Your session has expired. Please sign in again.")
        return dict(row)

    def memberships(self, user_id: str):
        return [dict(row) for row in self.db.execute(text("""select company.id as company_id,company.company_name,company.tenant_slug,member.role
            from tenant_memberships member join companies company on company.id=member.company_id and company.is_active=true
            where member.user_id=:user and member.is_active=true order by company.company_name"""), {"user": user_id}).mappings()]

    def register(self, payload: Registration):
        try:
            slug_taken=self.db.execute(text("""select 1 from companies company where company.tenant_slug=:slug
                union all select 1 from tenant_slug_aliases alias where alias.tenant_slug=:slug limit 1"""),{"slug":payload.slug}).first()
            if slug_taken:
                raise HTTPException(409,"Email or workspace address is already registered. Sign in if you already have an account.")
            user = self.db.execute(text("insert into tenant_users(email,display_name,password_hash) values(:email,:name,:hash) returning id"),
                                   {"email": payload.email, "name": payload.display_name, "hash": password_hash(payload.password)}).scalar_one()
            company = self.db.execute(text("insert into companies(company_name,tenant_slug) values(:name,:slug) returning id"),
                                      {"name": payload.company_name, "slug": payload.slug}).scalar_one()
            self.db.execute(text("insert into tenant_memberships(company_id,user_id,role) values(:company,:user,'owner')"), {"company": company, "user": user})
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise HTTPException(409, "Email or workspace address is already registered. Sign in if you already have an account.") from error
        return self.session(str(user), str(company))

    def login(self, email: str, password: str, tenant_id: str | None = None):
        row = self.db.execute(text("select id,password_hash,is_active from tenant_users where email=:email"), {"email": email.strip().lower()}).mappings().first()
        if not row:
            password_matches(password, f"pbkdf2_sha256${PASSWORD_ITERATIONS}$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        if not row or not row["is_active"] or not password_matches(password, row["password_hash"]):
            raise HTTPException(401, "Email or password is incorrect")
        memberships = self.memberships(str(row["id"]))
        chosen = next((member for member in memberships if str(member["company_id"]) == tenant_id), None) if tenant_id else next(iter(memberships), None)
        if not chosen:
            raise HTTPException(403, "This account does not have access to this workspace")
        return self.session(str(row["id"]), str(chosen["company_id"]))

    def switch(self, identity: dict, company_id: str):
        if not any(str(member["company_id"]) == company_id for member in self.memberships(str(identity["user_id"]))):
            raise HTTPException(403, "Workspace access denied")
        return self.session(str(identity["user_id"]), company_id)

    def create_workspace(self,user_id:str,name:str,slug:str):
        try:
            slug_taken=self.db.execute(text("""select 1 from companies company where company.tenant_slug=:slug
                union all select 1 from tenant_slug_aliases alias where alias.tenant_slug=:slug limit 1"""),{"slug":slug}).first()
            if slug_taken:
                raise HTTPException(409,"This workspace address is already registered")
            self.db.execute(text('select id from tenant_users where id=:id and is_active=true'),{'id':user_id}).scalar_one()
            company=self.db.execute(text('insert into companies(company_name,tenant_slug) values(:name,:slug) returning id'),{'name':name,'slug':slug}).scalar_one()
            self.db.execute(text("insert into tenant_memberships(company_id,user_id,role) values(:company,:user,'owner')"),{'company':company,'user':user_id})
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise HTTPException(409,'This workspace address is already registered') from error
        return self.session(user_id,str(company))

    def team(self, company_id: str):
        return [dict(row) for row in self.db.execute(text("""select account.id,account.email,account.display_name,member.role,member.is_active
            from tenant_memberships member join tenant_users account on account.id=member.user_id
            where member.company_id=:company order by member.created_at"""), {"company": company_id}).mappings()]

    def add_member(self, company_id: str, payload, actor_id:str|None=None):
        try:
            user_id = self.db.execute(text("insert into tenant_users(email,display_name,password_hash) values(:email,:name,:password) returning id"),
                                      {"email": payload.email, "name": payload.display_name.strip(), "password": password_hash(payload.password)}).scalar_one()
            self.db.execute(text("insert into tenant_memberships(company_id,user_id,role) values(:company,:user,:role)"), {"company": company_id, "user": user_id, "role": payload.role})
            if actor_id:self.audit(company_id,actor_id,'TEAM_MEMBER_CREATED',str(user_id),{'role':payload.role})
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise HTTPException(409, "This email is already registered. Existing accounts must join through a verified invitation, not a password reset here.") from error
        return self.team(company_id)

    def update_member(self, company_id: str, user_id: str, role: str, active: bool, actor_id:str|None=None):
        existing = self.db.execute(text("select role from tenant_memberships where company_id=:company and user_id=:user for update"), {"company": company_id, "user": user_id}).scalar_one_or_none()
        if not existing:
            raise HTTPException(404, "Team member not found")
        if existing == "owner":
            raise HTTPException(422, "The workspace owner cannot be changed through team administration")
        self.db.execute(text("update tenant_memberships set role=:role,is_active=:active where company_id=:company and user_id=:user"),
                        {"role": role, "active": active, "company": company_id, "user": user_id})
        self.db.execute(text("delete from tenant_sessions where company_id=:company and user_id=:user"), {"company": company_id, "user": user_id})
        if actor_id:self.audit(company_id,actor_id,'TEAM_ACCESS_CHANGED',user_id,{'previous_role':existing,'role':role,'is_active':active})
        self.db.commit()
        return self.team(company_id)