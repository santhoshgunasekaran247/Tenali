import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import get_args, get_origin
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from app.ai.actions import ACTIONS, ActionKey, ActionPolicyUpdate, DraftCreate, DraftEdit, TenantActionUpdate
from app.ai.capabilities import current_identity
from app.services.access import allowed_stores, check_module, check_store
from app.services.feature_controls import audit_platform, company_features, lock_policy, platform_settings
from app.services.runtime_schema import managed_schema
from app.services.stores_service import get_store


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def action_policies(db, company=None):
    if company is not None and not db.execute(
        text("select id from companies where id=:id"), {"id": str(company)}
    ).first():
        raise HTTPException(404, "Workspace not found")
    rows = db.execute(text("""select a.*,coalesce(t.allowed,false) as tenant_allowed,
        coalesce(t.version,0) as tenant_version from ai_action_controls a
        left join ai_tenant_action_controls t on t.action_key=a.key and t.company_id=cast(:company as uuid)
        order by a.key"""), {"company": str(company) if company else None}).mappings()
    items = []
    for row in rows:
        action = ACTIONS.get(row["key"])
        items.append({**dict(row), "description": action.description if action else "Adapter not deployed",
                      "compatible": bool(action and row["fingerprint"] == action.fingerprint),
                      "safety": "approved_execution", "execution_enabled": row["execution_enabled"],
                      "schema": action.schema.model_json_schema() if action else {},
                      "high_impact": bool(action and action.high_impact),
                      "module_path": action.path if action else None,
                      "target_required": bool(action and action.target)})
    return {"items": items}


def save_action_policy(db, key: ActionKey, payload: ActionPolicyUpdate, admin):
    lock_policy(db)
    row = db.execute(text("select * from ai_action_controls where key=:key"), {"key": key}).mappings().first()
    if not row:
        raise HTTPException(404, "Action not found")
    if row["version"] != payload.expected_version:
        raise HTTPException(409, "Action policy changed. Refresh.")
    fingerprint = ACTIONS[key].fingerprint if payload.approve_contract else row["fingerprint"]
    if payload.enabled and fingerprint != ACTIONS[key].fingerprint:
        raise HTTPException(409, "Review the current draft contract before enabling.")
    if payload.execution_enabled and (not payload.enabled or fingerprint != ACTIONS[key].fingerprint):
        raise HTTPException(409, "Execution requires an enabled, reviewed action contract.")
    db.execute(text("""update ai_action_controls set enabled=:enabled,fingerprint=:fingerprint,
        execution_enabled=:execution,version=version+1,updated_by=:admin,updated_at=now() where key=:key"""),
        {"key": key, "enabled": payload.enabled, "execution": payload.execution_enabled, "fingerprint": fingerprint, "admin": admin})
    audit_platform(db, admin, f"AI_DRAFT_{key.upper()}_POLICY")
    db.commit()
    return action_policies(db)


def save_tenant_action(db, company, key: ActionKey, payload: TenantActionUpdate, admin):
    lock_policy(db)
    if not db.execute(text("select id from companies where id=:id"), {"id": str(company)}).first():
        raise HTTPException(404, "Workspace not found")
    row = db.execute(text("""select version from ai_tenant_action_controls
        where company_id=:company and action_key=:key"""), {"company": str(company), "key": key}).first()
    if (row[0] if row else 0) != payload.expected_version:
        raise HTTPException(409, "Tenant action policy changed. Refresh.")
    db.execute(text("""insert into ai_tenant_action_controls(company_id,action_key,allowed,updated_by)
        values(:company,:key,:allowed,:admin) on conflict(company_id,action_key) do update
        set allowed=excluded.allowed,version=ai_tenant_action_controls.version+1,
        updated_by=excluded.updated_by,updated_at=now()"""),
        {"company": str(company), "key": key, "allowed": payload.allowed, "admin": admin})
    audit_platform(db, admin, f"AI_TENANT_DRAFT_{key.upper()}_POLICY", str(company))
    db.commit()
    return action_policies(db, company)


def available_actions(db, identity):
    result = []
    for item in action_policies(db, identity["company_id"])["items"]:
        if not item["enabled"] or not item["compatible"] or not item["tenant_allowed"]:
            continue
        if ACTIONS[item["key"]].high_impact and (identity.get("role") not in {"owner", "admin"} or allowed_stores(identity) is not None):
            continue
        try:
            check_module(identity, ACTIONS[item["key"]].path)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            continue
        if (item["key"] == "expense_create" or ACTIONS[item["key"]].company_wide) and allowed_stores(identity) is not None:
            continue
        if item["key"] == "refund_settle":
            try:
                check_module(identity, "/accounts")
            except HTTPException as error:
                if error.status_code != 403:
                    raise
                continue
        if allowed_stores(identity) == [] and item["key"] in {
            "purchase_create", "invoice_create", "stock_adjust", "stock_transfer", "purchase_payment", "collection_payment",
        }:
            continue
        result.append(item)
    return result


def bounded_payload(payload: dict):
    pending = [(payload, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 8:
            raise HTTPException(422, "Draft fields exceed the maximum nesting depth (8).")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
    try:
        encoded = json.dumps(payload, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise HTTPException(422, "Draft fields must contain finite, JSON-compatible values.") from error
    if len(encoded) > 16000:
        raise HTTPException(422, "Draft payload is too large (maximum 16000 encoded bytes).")
    if any(key in payload for key in ("company_id", "user_id", "idempotency_key", "attachments")):
        raise HTTPException(422, "Identity, submission keys and attachments cannot be supplied in an AI draft.")


def reject_extra_fields(schema: type[BaseModel], payload: dict):
    if set(payload) - set(schema.model_fields):
        raise HTTPException(422, "Unknown draft fields: " + ", ".join(sorted(set(payload) - set(schema.model_fields))))
    for key, value in payload.items():
        annotation = schema.model_fields[key].annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel) and isinstance(value, dict):
            reject_extra_fields(annotation, value)
        elif get_origin(annotation) is list and isinstance(value, list):
            nested = get_args(annotation)[0]
            if isinstance(nested, type) and issubclass(nested, BaseModel):
                for item in value:
                    if isinstance(item, dict):
                        reject_extra_fields(nested, item)


class DraftService:
    def __init__(self, assistant):
        self.assistant = assistant
        self.db = assistant.db
        self.scope = assistant.scope

    def gate(self, action):
        self.assistant.require_enabled()
        identity = current_identity(self.db, self.assistant.identity)
        self.assistant.identity = identity
        policy = next((item for item in available_actions(self.db, identity) if item["key"] == action), None)
        if not policy:
            raise HTTPException(403, "This draft action is not permitted. Check platform, tenant and module settings.")
        return identity, policy

    def get(self, draft_id):
        row = self.db.execute(text("""select * from ai_action_drafts where id=:id
            and company_id=:company and user_id=:user and status<>'discarded' and expires_at>now()"""),
            {**self.scope, "id": str(draft_id)}).mappings().first()
        if not row:
            raise HTTPException(404, "Draft not found")
        self.assistant.conversation(row["conversation_id"])
        return {**dict(row), "high_impact": bool(ACTIONS.get(row["action_key"]) and ACTIONS[row["action_key"]].high_impact)}

    def list(self, conversation_id, offset=0):
        self.assistant.conversation(conversation_id)
        rows = self.db.execute(text("""select * from ai_action_drafts where conversation_id=:conversation
            and company_id=:company and user_id=:user and status<>'discarded' and expires_at>now()
            order by created_at desc,id limit 30 offset :offset"""),
            {**self.scope, "conversation": str(conversation_id), "offset": offset}).mappings()
        return {"items": [{**dict(row), "high_impact": bool(ACTIONS.get(row["action_key"]) and ACTIONS[row["action_key"]].high_impact)}
                          for row in rows]}

    def create(self, conversation_id, payload: DraftCreate, *, commit=True):
        self.assistant.lock_conversation(conversation_id)
        conversation = self.assistant.conversation(conversation_id)
        if conversation["status"] != "active":
            raise HTTPException(409, "Restore the conversation before drafting.")
        bounded_payload(payload.payload)
        expected_hash = digest({"action": payload.action, "target": payload.target_id, "payload": payload.payload})
        old = self.db.execute(text("""select * from ai_action_drafts where company_id=:company and user_id=:user
            and conversation_id=:conversation and client_key=:key"""),
            {**self.scope, "conversation": str(conversation_id), "key": payload.client_key}).mappings().first()
        if old:
            if old["request_hash"] != expected_hash:
                raise HTTPException(409, "Draft reference was already used with different values.")
            # Retries return the current edited draft; they cannot reset approval or resurrect discarded content.
            return self.get(old["id"])
        self.gate(payload.action)
        reject_extra_fields(ACTIONS[payload.action].schema, payload.payload)
        action = ACTIONS[payload.action]
        if bool(action.target) != bool(payload.target_id):
            raise HTTPException(422, "Select a target for updates/payments; creation must not have a target.")
        if payload.target_id:
            self.reference(action.target, payload.target_id, allow_inactive=payload.action in {
                "account_update", "variant_update", "offer_update", "brand_update", "category_update"})
        expires = min(conversation["expires_at"], datetime.now(timezone.utc) + timedelta(days=7))
        row = self.db.execute(text("""insert into ai_action_drafts(company_id,user_id,conversation_id,client_key,
            action_key,target_id,payload,payload_hash,request_hash,expires_at)
            values(:company,:user,:conversation,:key,:action,:target,cast(:payload as jsonb),:hash,:hash,:expires) returning *"""),
            {**self.scope, "conversation": str(conversation_id), "key": payload.client_key, "action": payload.action,
             "target": payload.target_id, "payload": json.dumps(payload.payload), "hash": expected_hash, "expires": expires}).mappings().one()
        self.assistant.audit(conversation_id, "ACTION_DRAFT_CREATED", payload.client_key)
        if commit:
            self.db.commit()
        return dict(row)

    def lock(self, draft_id, version):
        current = self.get(draft_id)
        self.assistant.lock_conversation(current["conversation_id"])
        self.db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": f"ai-draft:{self.scope['company']}:{draft_id}"})
        row = self.get(draft_id)
        if row["version"] != version:
            raise HTTPException(409, "Draft changed. Refresh before continuing.")
        if row["status"] == "executed":
            raise HTTPException(409, "This draft has already been executed. View its saved outcome.")
        conversation = self.assistant.conversation(row["conversation_id"])
        if conversation["status"] != "active":
            raise HTTPException(409, "Restore the conversation before editing or approving.")
        return row

    def edit(self, draft_id, payload: DraftEdit):
        row = self.lock(draft_id, payload.expected_version)
        self.gate(row["action_key"])
        bounded_payload(payload.payload)
        hashed = digest({"action": row["action_key"], "target": row["target_id"], "payload": payload.payload})
        self.db.execute(text("""update ai_action_drafts set payload=cast(:payload as jsonb),payload_hash=:hash,
            status='editing',validation=null,approved_version=null,approved_at=null,version=version+1,updated_at=now()
            where id=:id and company_id=:company and user_id=:user"""),
            {**self.scope, "id": str(draft_id), "payload": json.dumps(payload.payload), "hash": hashed})
        self.assistant.audit(row["conversation_id"], "ACTION_DRAFT_EDITED", uuid4())
        self.db.commit()
        return self.get(draft_id)

    def reference(self, table, record_id, *, lock=False, allow_inactive=False):
        if table not in {"parties", "products", "product_variants", "accounts", "stores", "purchases", "invoices", "receivables", "brands", "product_categories",
                         "vendor_contributions", "account_transactions", "refund_settlements", "stock_movements", "stock_transfers"}:
            raise ValueError("Invalid reference table")
        if table in {"product_variants", "vendor_contributions"}:
            sql = f"select v.* from {table} v join products p on p.id=v.product_id where v.id=:id and p.company_id=:company"
        else:
            sql = f"select * from {table} where id=:id and company_id=:company"
        if lock:
            sql += " for update of v" if table in {"product_variants", "vendor_contributions"} else " for update"
        row = self.db.execute(text(sql), {**self.scope, "id": str(record_id)}).mappings().first()
        if not row:
            raise HTTPException(422, f"Referenced {table} record does not belong to this workspace.")
        if row.get("is_active") is False and not allow_inactive:
            raise HTTPException(422, f"Referenced {table} record is inactive.")
        if table == "stores":
            check_store(self.assistant.identity, dict(row))
            get_store(self.db, self.scope["company"], str(record_id))
        if table == "stock_transfers":
            self.reference("stores", row["from_store_id"])
            self.reference("stores", row["to_store_id"])
        if table in {"purchases", "invoices", "receivables", "refund_settlements", "stock_movements"}:
            store_id = row.get("store_id")
            if table == "receivables":
                store_id = self.db.execute(text("select store_id from invoices where id=:id and company_id=:company"),
                    {**self.scope, "id": row["invoice_id"]}).scalar_one_or_none()
            if table == "refund_settlements":
                source = "invoices" if row["document_type"] == "invoice" else "purchases"
                store_id = self.db.execute(text(f"select store_id from {source} where id=:id and company_id=:company"),
                    {**self.scope, "id": row["document_id"]}).scalar_one_or_none()
            permitted = allowed_stores(self.assistant.identity)
            if permitted is not None and (not store_id or str(store_id) not in permitted):
                raise HTTPException(403, "Target document is outside your permitted stores.")
        return dict(row)

    def preflight(self, row):
        identity, policy = self.gate(row["action_key"])
        if not managed_schema(self.db):
            raise HTTPException(503, "Draft validation requires migrated schema.")
        action = ACTIONS[row["action_key"]]
        values = row["payload"]
        bounded_payload(values)
        reject_extra_fields(action.schema, values)
        # Submission identity is server-owned, even in schema/preflight.
        supplied = {**values}
        if "idempotency_key" in action.schema.model_fields:
            supplied["idempotency_key"] = f"ai-draft-{row['id']}"
        try:
            model = action.schema.model_validate(supplied)
        except ValidationError as error:
            raise HTTPException(422, error.errors(include_context=False, include_input=False)) from error
        normalized = model.model_dump(mode="json", exclude={"idempotency_key", "attachments"},
                                      exclude_unset=action.key in {"party_update", "account_update"})
        if action.key == "account_update" and not normalized:
            raise HTTPException(422, "Provide at least one changed account field.")
        preview = None
        if action.key in {"purchase_create", "invoice_create"}:
            if not normalized["lines"] or not normalized.get("store_id"):
                raise HTTPException(422, "Select an explicit store and at least one document line.")
            from app.ai.business_writes import document_preview
            normalized, preview = document_preview(self.db, self.scope["company"], action.key, normalized)
        if action.high_impact:
            from app.ai.business_writes import destructive_preview
            preview = destructive_preview(self.db, self.scope["company"], action.key, row["target_id"], normalized)
        if action.key in {"product_create", "product_update"}:
            for source in [normalized.get("image_url"), *normalized.get("image_urls", [])]:
                if source and not source.startswith(("https://", "http://")):
                    raise HTTPException(422, "Upload product images through Inventory first and use their published URL; AI posting cannot perform external file writes.")
        snapshots = []
        if action.target:
            allow_inactive = action.key in {"account_update", "variant_update", "offer_update", "brand_update", "category_update"}
            target = self.reference(action.target, row["target_id"], allow_inactive=allow_inactive)
            snapshot = {"table": action.target, "id": str(row["target_id"]), "hash": digest(target)}
            if allow_inactive:
                snapshot["allow_inactive"] = True
            snapshots.append(snapshot)
        mappings = {"vendor_party_id": "parties", "customer_party_id": "parties", "related_party_id": "parties",
                    "vendor_id": "parties", "preferred_vendor_id": "parties", "account_id": "accounts", "from_account_id": "accounts",
                    "store_id": "stores", "stock_store_id": "stores", "from_store_id": "stores", "to_store_id": "stores",
                    "product_id": "products", "variant_id": "product_variants", "brand_id": "brands", "category_id": "product_categories",
                    "party_id": "parties", "to_account_id": "accounts", "invoice_id": "invoices",
                    "target_product_id": "products", "target_variant_id": "product_variants"}
        def visit(value):
            if isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key in mappings and child:
                        record = self.reference(mappings[key], child)
                        snapshots.append({"table": mappings[key], "id": str(child), "hash": digest(record)})
                    elif key == "product_ids" and isinstance(child, list):
                        for product_id in sorted(set(child)):
                            record = self.reference("products", product_id)
                            snapshots.append({"table": "products", "id": str(product_id), "hash": digest(record)})
                    elif isinstance(child, (dict, list)):
                        visit(child)
        visit(normalized)
        if action.key in {"party_create", "party_update"}:
            from app.services.parties_service import ALLOWED_PARTY_TYPES
            if "party_type" in normalized:
                kind = normalized["party_type"]
                if not isinstance(kind, str) or kind.strip().lower() not in ALLOWED_PARTY_TYPES:
                    raise HTTPException(422, "Invalid party type.")
                normalized["party_type"] = kind.strip().lower()
            if "is_active" in normalized and normalized["is_active"] is None:
                raise HTTPException(422, "Party active status cannot be null.")
            if "legal_name" in normalized and (not normalized["legal_name"] or not normalized["legal_name"].strip()):
                raise HTTPException(422, "Party legal name cannot be blank.")
            if action.key == "party_update" and not normalized:
                raise HTTPException(422, "Provide at least one changed field.")
        if action.key == "expense_create":
            if normalized["purpose"] != "expense" or not normalized.get("payment_mode") or not normalized.get("transaction_date") or "create_borrowing" not in values:
                raise HTTPException(422, "Expense needs purpose=expense, explicit date/mode and create_borrowing choice.")
        if action.key in {"purchase_create", "invoice_create"}:
            if not normalized["lines"] or not normalized.get("store_id"):
                raise HTTPException(422, "Select an explicit store and at least one document line.")
            if action.key == "purchase_create" and "received_now" not in values:
                raise HTTPException(422, "Explicitly choose whether goods are received now.")
        if action.key == "stock_adjust" and not normalized.get("store_id"):
            raise HTTPException(422, "Select an explicit stock store.")
        if not action.high_impact and action.key not in {"purchase_create", "invoice_create"}:
            from app.ai.business_writes import operational_preview
            preview = operational_preview(self.db, self.scope["company"], action.key, row["target_id"], normalized)
        if action.key == "collection_payment" and not normalized["payment_mode"].strip():
            raise HTTPException(422, "Choose a payment mode.")
        date_fields = {"purchase_create": "purchase_date", "invoice_create": "invoice_date",
                       "purchase_payment": "payment_date", "collection_payment": "payment_date",
                       "stock_transfer": "transfer_date"}
        if action.key in date_fields and not normalized.get(date_fields[action.key]):
            raise HTTPException(422, f"Provide an explicit {date_fields[action.key]} before approving.")
        if action.key in {"product_update", "variant_update", "offer_update", "brand_update", "category_update"}:
            missing = set(action.schema.model_fields) - set(values)
            if missing:
                raise HTTPException(422, "Full replacement requires every field to prevent accidental resets: " + ", ".join(sorted(missing)))
        when = next((normalized.get(key) for key in ("transaction_date", "purchase_date", "invoice_date", "payment_date", "transfer_date", "cancellation_date", "settled_on")
                     if normalized.get(key)), None)
        if action.key in {"stock_adjust", "stock_transfer_reverse", "receivable_status", "purchase_receive"}:
            from datetime import date
            when = date.today().isoformat()
        if when:
            locked = self.db.execute(text("""select id from accounting_period_locks where company_id=:company
                and is_active and cast(:date as date) between period_start and period_end limit 1"""),
                {**self.scope, "date": when}).first()
            if locked:
                raise HTTPException(422, "The selected date is in a locked accounting period.")
        preview = json.loads(json.dumps(preview, default=str))
        report = {"snapshots": snapshots, "policy_version": policy["version"], "tenant_version": policy["tenant_version"],
                  "features_hash": digest(company_features(self.db, self.scope["company"])),
                  "platform_version": platform_settings(self.db)["version"], "identity_hash": digest(identity),
                  "contract": action.fingerprint, "execution_contract": 1, "preview": preview,
                  "effective_date": when,
                  "checks": "Current permissions, references, dates and shared business tax calculations checked.",
                  "warning": "Nothing has been posted. Submission repeats validation; any changed approved values or rejected business rule roll back the complete operation.",
                  "side_effects": action.description}
        return normalized, report

    def validate(self, draft_id, version):
        row = self.lock(draft_id, version)
        lock_policy(self.db)
        normalized, report = self.preflight(row)
        hashed = digest({"action": row["action_key"], "target": row["target_id"], "payload": normalized})
        self.db.execute(text("""update ai_action_drafts set payload=cast(:payload as jsonb),payload_hash=:hash,
            validation=cast(:validation as jsonb),status='validated',version=version+1,approved_version=null,
            approved_at=null,updated_at=now() where id=:id and company_id=:company and user_id=:user"""),
            {**self.scope, "id": str(draft_id), "payload": json.dumps(normalized), "hash": hashed, "validation": json.dumps(report)})
        self.assistant.audit(row["conversation_id"], "ACTION_DRAFT_VALIDATED", uuid4())
        self.db.commit()
        return self.get(draft_id)

    def approve(self, draft_id, payload):
        row = self.lock(draft_id, payload.expected_version)
        lock_policy(self.db)
        if row["payload_hash"] != payload.expected_hash or row["status"] not in {"validated", "approved"}:
            raise HTTPException(409, "Validate and review the current draft before approving.")
        normalized, report = self.preflight(row)
        if report != row["validation"] or digest({"action": row["action_key"], "target": row["target_id"], "payload": normalized}) != row["payload_hash"]:
            self.db.execute(text("""update ai_action_drafts set status='editing',validation=null,approved_at=null,
                approved_version=null,version=version+1 where id=:id and company_id=:company and user_id=:user"""),
                {**self.scope, "id": str(draft_id)})
            self.db.commit()
            raise HTTPException(409, "Referenced records or permissions changed. Revalidate and approve again.")
        if row["status"] != "approved":
            self.db.execute(text("""insert into ai_draft_approvals(company_id,user_id,conversation_id,draft_id,
                draft_version,payload_hash,contract_fingerprint,snapshot_hash)
                values(:company,:user,:conversation,:draft,:version,:hash,:contract,:snapshot)"""),
                {**self.scope, "conversation": row["conversation_id"], "draft": str(draft_id), "version": row["version"],
                 "hash": row["payload_hash"], "contract": report["contract"], "snapshot": digest(report)})
            self.db.execute(text("""update ai_action_drafts set status='approved',approved_version=version,
                approved_at=now(),updated_at=now() where id=:id and company_id=:company and user_id=:user"""),
                {**self.scope, "id": str(draft_id)})
            self.assistant.audit(row["conversation_id"], "ACTION_DRAFT_APPROVED", uuid4())
            self.db.commit()
        return self.get(draft_id)

    def discard(self, draft_id, version):
        row = self.lock(draft_id, version)
        self.db.execute(text("""update ai_action_drafts set status='discarded',payload='{}',validation=null,
            approved_version=null,approved_at=null,version=version+1 where id=:id and company_id=:company and user_id=:user"""),
            {**self.scope, "id": str(draft_id)})
        self.assistant.audit(row["conversation_id"], "ACTION_DRAFT_DISCARDED", uuid4())
        self.db.commit()
        return {"discarded": True}
