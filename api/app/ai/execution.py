import json
import logging
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.ai.business_writes import apply_action
from app.ai.drafts import DraftService, digest
from app.ai.actions import ACTIONS
from app.services.feature_controls import lock_policy
from app.services.object_storage import FileStore
from app.services.product_images import display_image

logger = logging.getLogger(__name__)


def image_sources(value):
    """Every product image source (image_url / image_urls) anywhere in a draft payload."""
    if isinstance(value, dict):
        for name, item in value.items():
            if name == "image_url" and isinstance(item, str):
                yield item
            elif name == "image_urls" and isinstance(item, list):
                yield from (source for source in item if isinstance(source, str))
            else:
                yield from image_sources(item)
    elif isinstance(value, list):
        for item in value:
            yield from image_sources(item)


class ExecutionService:
    def __init__(self, assistant):
        self.assistant = assistant
        self.db = assistant.db
        self.scope = assistant.scope
        self.drafts = DraftService(assistant)

    def get(self, execution_id):
        row = self.db.execute(text("""select * from ai_executions where id=:id
            and company_id=:company and user_id=:user"""), {**self.scope, "id": str(execution_id)}).mappings().first()
        if not row:
            raise HTTPException(404, "Execution not found")
        self.assistant.conversation(row["conversation_id"])
        return dict(row)

    def for_draft(self, draft_id, version):
        self.drafts.get(draft_id)
        row = self.db.execute(text("""select * from ai_executions where draft_id=:id and draft_version=:version
            and company_id=:company and user_id=:user"""), {**self.scope, "id": str(draft_id), "version": version}).mappings().first()
        return dict(row) if row else None

    def prepare_images(self, draft_id):
        """Render product display images (AI segmentation and super-resolution take tens of seconds) before
        execution takes its locks, so the locked transaction only uploads cached results. Any problem is left
        for the locked execution to report."""
        files, photos = FileStore(self.db), []
        for source in dict.fromkeys(image_sources(self.drafts.get(draft_id)["payload"])):
            try:
                photo = files.product_photo(self.scope["company"], source)
            except HTTPException:
                continue
            if photo:
                photos.append(photo[0])
        if not photos:
            return
        self.db.commit()  # Nothing is written yet; do not hold a transaction open while rendering.
        for content in photos:
            try:
                display_image(content)
            except HTTPException:
                continue

    def record(self, row, execution_id, key, status, result):
        self.db.execute(text("""insert into ai_executions(id,company_id,user_id,conversation_id,draft_id,
            draft_version,payload_hash,request_key,status,result)
            values(:id,:company,:user,:conversation,:draft,:version,:hash,:key,:status,cast(:result as jsonb))"""),
            {**self.scope, "id": execution_id, "conversation": row["conversation_id"], "draft": row["id"],
             "version": row["version"], "hash": row["payload_hash"], "key": key, "status": status,
             "result": json.dumps(jsonable_encoder(result))})
        self.assistant.audit(row["conversation_id"], f"EXECUTION_{status.upper()}", execution_id)

    def execute(self, draft_id, approval):
        execution_id = uuid5(NAMESPACE_URL, f"tenali-ai:{self.scope['company']}:{draft_id}:{approval.expected_version}")
        key = f"ai-{execution_id}"
        if not self.for_draft(draft_id, approval.expected_version):
            self.prepare_images(draft_id)
        self.db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key})
        saved = self.for_draft(draft_id, approval.expected_version)
        if saved:
            if saved["payload_hash"] != approval.expected_hash:
                raise HTTPException(409, "This execution reference belongs to different approved values.")
            return saved
        row = self.drafts.lock(draft_id, approval.expected_version)
        lock_policy(self.db)
        _, policy = self.drafts.gate(row["action_key"])
        if not policy["execution_enabled"]:
            raise HTTPException(403, "Posting is disabled for this action. Contact the platform administrator.")
        if row["status"] != "approved" or row["approved_version"] != row["version"] or row["payload_hash"] != approval.expected_hash:
            raise HTTPException(409, "Review and approve the current draft before submitting.")
        if not row["validation"] or row["validation"].get("execution_contract") != 1:
            raise HTTPException(409, "This older approval cannot execute. Validate and approve a current business preview.")
        if ACTIONS[row["action_key"]].high_impact:
            expected = row["validation"]["preview"]["confirm_text"]
            if approval.confirm_text != expected:
                raise HTTPException(422, f"Type {expected} exactly to confirm this high-impact operation.")
        # Reference locks are held until business changes and the outcome commit together.
        for item in sorted(row["validation"]["snapshots"], key=lambda item: (item["table"], item["id"])):
            self.drafts.reference(item["table"], item["id"], lock=True, allow_inactive=item.get("allow_inactive", False))
        normalized, report = self.drafts.preflight(row)
        if report != row["validation"] or digest({"action": row["action_key"], "target": row["target_id"], "payload": normalized}) != row["payload_hash"]:
            # Like approval: send the draft back for review so the user can re-check it instead of being stuck.
            self.db.execute(text("""update ai_action_drafts set status='editing',validation=null,approved_at=null,
                approved_version=null,version=version+1,updated_at=now() where id=:id and company_id=:company and user_id=:user"""),
                {**self.scope, "id": str(draft_id)})
            self.db.commit()
            raise HTTPException(409, "References, amounts or settings changed since approval, so nothing was saved. Choose Review & check, then Confirm & save again.")
        proof = self.db.execute(text("""select 1 from ai_draft_approvals where draft_id=:id and draft_version=:version
            and company_id=:company and user_id=:user and payload_hash=:hash
            and contract_fingerprint=:contract and snapshot_hash=:snapshot"""), {
                **self.scope, "id": str(draft_id), "version": row["version"], "hash": row["payload_hash"],
                "contract": report["contract"], "snapshot": digest(report)}).first()
        if not proof:
            raise HTTPException(409, "Approval proof is missing or does not match. Validate and explicitly approve again.")
        validation_error = None
        try:
            with self.db.begin_nested():
                result = apply_action(self.db, self.scope["company"], row["action_key"],
                                      str(row["target_id"]) if row["target_id"] else None, normalized, key,
                                      report["preview"], approval.confirm_text)
                if row["action_key"] in {"purchase_create", "invoice_create"}:
                    from decimal import Decimal
                    if any(Decimal(str(result[name])) != Decimal(str(normalized[name]))
                           for name in ("subtotal", "gst_total", "total")):
                        raise HTTPException(409, "Business totals changed from the approved preview. No changes saved.")
                elif row["action_key"] == "purchase_bundle_create":
                    from decimal import Decimal
                    approved_purchase = report["preview"]["purchase_payload"]
                    if any(Decimal(str(result[name])) != Decimal(str(approved_purchase[name]))
                           for name in ("subtotal", "gst_total", "total")):
                        raise HTTPException(409, "Purchase totals changed from the approved preview. No changes saved.")
                elif row["action_key"] == "quotation_create":
                    if result["document_data"] != report["preview"]["document"]:
                        raise HTTPException(409, "Quotation details changed from the approved preview. No changes saved.")
                # Recovery only needs durable references, not copies of business/contact data.
                outcome = {name: result[name] for name in ("id", "status", "deleted", "deletion_id", "borrowing_id",
                    "subtotal", "gst_total", "total", "refunds", "mapped_count", "reversal_of_transaction_id",
                    "reversal_of_transfer_id", "report_id", "report_rows", "product_id", "vendor_created",
                    "product_name", "stock_received", "code", "quotation_number") if name in result}
                if "account_transaction" in result:
                    outcome["id"] = result["account_transaction"]["id"]
                self.record(row, execution_id, key, "succeeded", outcome)
                self.db.execute(text("""update ai_action_drafts set status='executed',updated_at=now()
                    where id=:id and company_id=:company and user_id=:user"""), {**self.scope, "id": str(draft_id)})
        except HTTPException as error:
            logger.warning("AI execution rejected by business validation: HTTP %s", error.status_code)
            validation_error = error.detail
            self.record(row, execution_id, key, "failed", {
                "detail": "Business validation rejected this operation. No business changes saved.",
                "status_code": error.status_code})
        except IntegrityError:
            logger.warning("AI execution rejected by database business constraints; all business writes rolled back")
            self.record(row, execution_id, key, "failed", {
                "detail": "A business relationship or duplicate constraint rejected this operation. No business changes saved; review the source record before editing and reapproving.",
                "status_code": 409})
        except DBAPIError:
            self.db.rollback()
            logger.error("AI execution database outcome is unconfirmed; recover using the same draft/version")
            raise HTTPException(503, "Submission outcome is unconfirmed. Refresh the saved outcome or retry the SAME draft/version; do not create a replacement.") from None
        try:
            self.db.commit()
        except DBAPIError:
            self.db.rollback()
            logger.error("AI execution commit outcome is unconfirmed")
            raise HTTPException(503, "Commit outcome is unconfirmed. Refresh or retry this SAME draft/version to recover safely.") from None
        try:
            outcome = self.get(execution_id)
        except DBAPIError:
            self.db.rollback()
            logger.error("AI execution outcome read failed after commit; recover the same draft/version")
            raise HTTPException(503, "Outcome could not be read after submission. Check or retry this SAME draft/version to recover safely.") from None
        if validation_error is not None:
            outcome["validation_error"] = validation_error
        return outcome
