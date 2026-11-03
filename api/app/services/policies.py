import re

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.schemas.policies import PolicyContent, PolicyPublish, PolicySave
from app.services.customer_contacts import normalize_email
from app.services.policy_templates import PLATFORM_KINDS, TENANT_KINDS, template

SCOPE = "company_id is not distinct from cast(:company as uuid)"


def kinds(company_id: str | None) -> tuple[str, ...]:
    return TENANT_KINDS if company_id else PLATFORM_KINDS


def check_kind(company_id: str | None, kind: str) -> None:
    if kind not in kinds(company_id):
        raise HTTPException(404, "Policy not available for this scope")


def publication_issues(content: PolicyContent) -> list[str]:
    issues = []
    for field in ("business_name", "address", "contact_email", "jurisdiction"):
        if not getattr(content, field):
            issues.append(f"Complete {field.replace('_', ' ')}.")
    try:
        if not normalize_email(content.contact_email):
            issues.append("Enter a valid contact email.")
    except ValueError:
        issues.append("Enter a valid contact email.")
    if re.search(r"\[\[|\]\]", content.model_dump_json()):
        issues.append("Replace every [[...]] template placeholder before publishing.")
    return issues


def row_for(db, company_id, kind, lock=False):
    return db.execute(text(f"""select * from legal_policies where {SCOPE} and kind=:kind
        {"for update" if lock else ""}"""), {"company": company_id, "kind": kind}).mappings().first()


def editor_document(row, kind, content):
    draft = PolicyContent.model_validate(row["draft"] if row else content)
    return {
        "kind": kind, "revision": row["revision"] if row else 0, "content": draft.model_dump(),
        "published": row["published"] if row else None,
        "published_revision": row["published_revision"] if row else None,
        "published_at": row["published_at"] if row else None,
        "issues": publication_issues(draft),
    }


def drafts(db, company_id: str | None, owner_email: str = "") -> dict:
    company = None
    if company_id:
        company = db.execute(text("select company_name,address,email from companies where id=:id"),
                             {"id": company_id}).mappings().one()
        company = dict(company)
    rows = {row["kind"]: row for row in db.execute(text(f"select * from legal_policies where {SCOPE}"),
                                                   {"company": company_id}).mappings()}
    return {"items": [editor_document(rows.get(kind), kind, template(kind, company, owner_email))
                      for kind in kinds(company_id)]}


def audit(db, company_id, actor_id, kind, action, revision):
    if company_id:
        db.execute(text("""insert into audit_events
            (company_id,actor_user_id,action,entity_type,new_value,source_type)
            values(:company,:actor,:action,'legal_policy',
                jsonb_build_object('kind',cast(:kind as text),'revision',cast(:revision as integer)),
                'policy_administration')"""),
            {"company": company_id, "actor": actor_id, "action": action, "kind": kind, "revision": revision})
    else:
        db.execute(text("insert into platform_audit(admin_id,action) values(:actor,:action)"),
                   {"actor": actor_id, "action": f"{action}:{kind}:{revision}"})


def save_draft(db, company_id, kind, payload: PolicySave, actor_id):
    check_kind(company_id, kind)
    row = row_for(db, company_id, kind, lock=True)
    if (row["revision"] if row else 0) != payload.revision:
        raise HTTPException(409, "Policy changed. Reload the latest draft before saving.")
    params = {"company": company_id, "kind": kind, "draft": payload.content.model_dump_json()}
    try:
        if row:
            row = db.execute(text(f"""update legal_policies set draft=cast(:draft as jsonb),
                revision=revision+1,updated_at=now() where {SCOPE} and kind=:kind returning *"""),
                params).mappings().one()
        else:
            row = db.execute(text("""insert into legal_policies(company_id,kind,draft)
                values(:company,:kind,cast(:draft as jsonb)) returning *"""), params).mappings().one()
    except IntegrityError as error:
        db.rollback()
        if getattr(error.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(409, "Policy changed. Reload the latest draft before saving.") from error
    result = editor_document(row, kind, None)
    audit(db, company_id, actor_id, kind, "POLICY_DRAFT_SAVED", row["revision"])
    db.commit()
    return result


def publish(db, company_id, kind, payload: PolicyPublish, actor_id):
    check_kind(company_id, kind)
    row = row_for(db, company_id, kind, lock=True)
    if not row or row["revision"] != payload.revision:
        raise HTTPException(409, "Save and reload the latest draft before publishing.")
    if not payload.reviewed:
        raise HTTPException(422, "Confirm the policy has been reviewed for your business before publishing.")
    issues = publication_issues(PolicyContent.model_validate(row["draft"]))
    if issues:
        raise HTTPException(422, " ".join(issues))
    if row["published_revision"] == row["revision"]:
        return editor_document(row, kind, None)
    row = db.execute(text(f"""update legal_policies set published=draft,
        published_revision=revision,published_at=now() where {SCOPE} and kind=:kind returning *"""),
        {"company": company_id, "kind": kind}).mappings().one()
    result = editor_document(row, kind, None)
    audit(db, company_id, actor_id, kind, "POLICY_PUBLISHED", row["revision"])
    db.commit()
    return result


def published_list(db, company_id):
    rows = db.execute(text(f"""select kind,published->>'title' as title,published_at,published_revision
        from legal_policies where {SCOPE} and published is not null order by kind"""),
        {"company": company_id}).mappings()
    return {"items": [dict(row) for row in rows]}


def published_document(db, company_id, kind):
    check_kind(company_id, kind)
    row = row_for(db, company_id, kind)
    if not row or row["published"] is None:
        raise HTTPException(404, "This policy has not been published. Contact the business for details.")
    return {"kind": kind, "content": row["published"], "published_at": row["published_at"],
            "published_revision": row["published_revision"]}
