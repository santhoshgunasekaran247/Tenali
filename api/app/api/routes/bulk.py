import hashlib
import json
from datetime import date, datetime, time
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.dependencies import get_db
from app.services.bulk_import import BulkImport
from app.services.bulk_workbooks import FIELDS, MAX_EXPANDED_BYTES, MAX_ROWS, MAX_UPLOAD_BYTES, read_workbook, workbook

router = APIRouter()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024


class SelectedRecords(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[UUID] = Field(min_length=1, max_length=MAX_ROWS)


def bulk_service(request: Request, db: Session = Depends(get_db)):
    tenant = request.state.tenant
    if tenant.get("role") not in {"owner", "admin"}:
        raise HTTPException(403, "Only workspace owners and administrators can use bulk workbooks.")
    return BulkImport(db, tenant["company_id"])


def download(content, name, media_type=XLSX, headers=None):
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Content-Type-Options": "nosniff",
        **(headers or {}),
    })


@router.get("/templates/{kind}")
def template(kind: str, service: BulkImport = Depends(bulk_service)):
    return download(workbook(kind, lookups=service.suggestions()), f"tenali-{kind}-template.xlsx")


@router.post("/exports/{kind}")
def export(kind: str, selection: SelectedRecords, service: BulkImport = Depends(bulk_service)):
    rows = service.export_rows(kind, selection.ids)
    return download(workbook(kind, rows, service.suggestions()), f"tenali-{kind}-selected.xlsx")


def image_upload(content, kind="images"):
    if not content or len(content) > MAX_IMAGE_UPLOAD_BYTES:
        raise HTTPException(413, "Image ZIP must be nonempty and at most 20 MiB.")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
                raise HTTPException(413, "Image ZIP expands beyond the permitted size.")
            if any(item.flag_bits & 1 for item in entries):
                raise HTTPException(422, "Encrypted ZIP files are not supported.")
            names = [entry.filename for entry in entries if not entry.is_dir()]
            if len(names) != len(set(names)):
                raise HTTPException(422, "ZIP filenames must be unique.")
            if "[Content_Types].xml" in names:
                return read_workbook(kind, content), {}
            manifests = [name for name in ("manifest.xlsx", "failure.xlsx") if name in names]
            if len(manifests) != 1:
                raise HTTPException(422, "Include exactly one manifest.xlsx or failure.xlsx at the ZIP root.")
            rows = read_workbook(kind, archive.read(manifests[0]))
            images = {}
            total = 0
            for entry in entries:
                if entry.is_dir() or entry.filename in manifests or (manifests == ["failure.xlsx"] and entry.filename == "success.xlsx"):
                    continue
                prefix = "images/"
                name = entry.filename[len(prefix):] if entry.filename.startswith(prefix) else ""
                if not name or name in {".", ".."} or "/" in name or "\\" in name:
                    raise HTTPException(422, "Put image files directly in the ZIP images/ folder.")
                if entry.file_size > 1024 * 1024:
                    raise HTTPException(422, f"Image '{name}' exceeds 1 MiB.")
                total += entry.file_size
                if total > 8 * 1024 * 1024:
                    raise HTTPException(413, "Images in one ZIP must total at most 8 MiB.")
                images[name] = archive.read(entry)
            return rows, images
    except (BadZipFile, OSError, ValueError, KeyError) as error:
        raise HTTPException(422, "Upload a valid XLSX or image ZIP.") from error


def result_package(kind, success, failures, images, suggestions):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("success.xlsx", workbook(kind, success, suggestions))
        archive.writestr("failure.xlsx", workbook(kind, failures, suggestions, reasons=True))
        if kind in {"images", "products", "variants", "brands", "categories"}:
            for name in {row[field] for row in failures for field in ("image_file", "brand_image_file", "category_image_file") if row.get(field) in images}:
                archive.writestr(f"images/{name}", images[name])
    return download(output.getvalue(), f"tenali-{kind}-results.zip", "application/zip",
                    {"X-Bulk-Success-Count": str(len(success)), "X-Bulk-Failure-Count": str(len(failures)),
                     "Cache-Control": "private, no-store"})


def job_scope(service):
    return {"company": service.company_id, "user": str(service.db.info["tenant_context"]["user_id"])}


def job_summary(row):
    total = row["total"] if "total" in row else len(row["rows"])
    failures = row["failures"] if "failures" in row else sum("failure_reason" in item for item in row["outcomes"])
    return {"id": str(row["id"]), "kind": row["kind"], "processed": row["next_row"],
            "total": total, "completed": row["next_row"] == total,
            "success": row["next_row"] - failures, "failures": failures,
            "created_at": row["created_at"], "expires_at": row["expires_at"]}


def job_row(service, job_id, *, lock=False):
    row = service.db.execute(text("""select * from bulk_import_jobs
        where id=:id and company_id=:company and user_id=:user and expires_at>now()""" +
        (" for update" if lock else "")), {**job_scope(service), "id": str(job_id)}).mappings().first()
    if not row:
        raise HTTPException(404, "Bulk import not found or expired.")
    return row


def json_value(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    raise TypeError(f"Unsupported workbook value: {type(value).__name__}")


def create_job(kind, content, client_key, service):
    if kind not in FIELDS:
        raise HTTPException(422, "Unknown bulk workbook type.")
    rows, _ = image_upload(content, kind) if kind in {"images", "products", "variants", "brands", "categories"} else (read_workbook(kind, content), {})
    if not rows:
        raise HTTPException(422, "The workbook contains no data rows.")
    scope = job_scope(service)
    digest = hashlib.sha256(content).hexdigest()
    service.db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"),
                       {"key": f"bulk:{scope['company']}:{scope['user']}"})
    service.db.execute(text("delete from bulk_import_jobs where company_id=:company and user_id=:user and expires_at<=now()"), scope)
    existing = service.db.execute(text("""select * from bulk_import_jobs
        where company_id=:company and user_id=:user and client_key=:key"""),
        {**scope, "key": str(client_key)}).mappings().first()
    if existing:
        if existing["kind"] != kind or existing["input_hash"] != digest:
            raise HTTPException(409, "This upload reference was already used for a different workbook.")
        result = job_summary(existing)
        service.db.commit()
        return result
    count = service.db.execute(text("select count(*) from bulk_import_jobs where company_id=:company and user_id=:user"), scope).scalar_one()
    if count >= 10:
        raise HTTPException(422, "Remove an old bulk import before starting another (maximum ten).")
    row = service.db.execute(text("""insert into bulk_import_jobs(id,company_id,user_id,client_key,kind,input_hash,content,rows)
        values(:id,:company,:user,:key,:kind,:hash,:content,cast(:rows as jsonb)) returning *"""),
        {**scope, "id": str(uuid4()), "key": str(client_key), "kind": kind, "hash": digest,
         "content": content, "rows": serialize_rows(rows)}).mappings().one()
    result = job_summary(row)
    service.db.commit()
    return result


def serialize_rows(rows):
    try:
        return json.dumps(rows, default=json_value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise HTTPException(422, "The workbook contains unsupported cell values.") from error


def advance_job(job_id, service):
    for _ in range(3):
        job = job_row(service, job_id, lock=True)
        index = job["next_row"]
        if index == len(job["rows"]):
            service.db.commit()
            return job_summary(job)
        images = image_upload(job["content"], job["kind"])[1] if job["kind"] in {"images", "products", "variants", "brands", "categories"} else {}
        try:
            with service.db.begin_nested():
                record_id = service.apply_row(job["kind"], job["rows"][index], images)
            outcome = {"id": str(record_id)}
        except ValidationError as error:
            outcome = {"failure_reason": "; ".join(
                f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors(include_url=False))}
        except HTTPException as error:
            outcome = {"failure_reason": str(error.detail)}
        except IntegrityError:
            outcome = {"failure_reason": "The record conflicts with existing data or has an invalid relationship."}
        updated = service.db.execute(text("""update bulk_import_jobs
            set next_row=next_row+1,outcomes=outcomes || jsonb_build_array(cast(:outcome as jsonb))
            where id=:id and company_id=:company and user_id=:user
            returning id,kind,next_row,jsonb_array_length(rows) as total,created_at,expires_at,
                (select count(*) from jsonb_array_elements(outcomes) item where item ? 'failure_reason') as failures"""),
            {**job_scope(service), "id": str(job_id), "outcome": json.dumps(outcome)}).mappings().one()
        result = job_summary(updated)
        service.db.commit()
        if result["completed"]:
            return result
    return result


@router.get("/jobs")
def jobs(service: BulkImport = Depends(bulk_service)):
    scope = job_scope(service)
    service.db.execute(text("delete from bulk_import_jobs where company_id=:company and user_id=:user and expires_at<=now()"), scope)
    rows = service.db.execute(text("""select id,kind,next_row,jsonb_array_length(rows) as total,created_at,expires_at,
        (select count(*) from jsonb_array_elements(outcomes) item where item ? 'failure_reason') as failures
        from bulk_import_jobs where company_id=:company and user_id=:user
        and expires_at>now() order by created_at desc limit 10"""), scope).mappings().all()
    result = [job_summary(row) for row in rows]
    service.db.commit()
    return {"items": result}


@router.post("/jobs/{kind}")
async def upload(kind: str, request: Request, client_key: UUID, service: BulkImport = Depends(bulk_service)):
    content = bytearray()
    limit = MAX_IMAGE_UPLOAD_BYTES if kind in {"images", "products", "variants", "brands", "categories"} else MAX_UPLOAD_BYTES
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > limit:
            raise HTTPException(413, f"Upload must be at most {limit // (1024 * 1024)} MiB.")
    return await run_in_threadpool(create_job, kind, bytes(content), client_key, service)


@router.post("/jobs/{job_id}/advance")
def advance(job_id: UUID, service: BulkImport = Depends(bulk_service)):
    return advance_job(job_id, service)


@router.get("/jobs/{job_id}/results")
def results(job_id: UUID, service: BulkImport = Depends(bulk_service)):
    job = job_row(service, job_id)
    if job["next_row"] != len(job["rows"]):
        raise HTTPException(409, "Resume this import before downloading its final results.")
    successes, failures = [], []
    for row, outcome in zip(job["rows"], job["outcomes"]):
        if "failure_reason" in outcome:
            failures.append({**row, **outcome})
        else:
            successes.append({**row, **outcome})
    images = image_upload(job["content"], job["kind"])[1] if job["kind"] in {"images", "products", "variants", "brands", "categories"} else {}
    return result_package(job["kind"], successes, failures, images, service.suggestions())


@router.delete("/jobs/{job_id}")
def delete_job(job_id: UUID, service: BulkImport = Depends(bulk_service)):
    job_row(service, job_id, lock=True)
    service.db.execute(text("delete from bulk_import_jobs where id=:id and company_id=:company and user_id=:user"),
                       {**job_scope(service), "id": str(job_id)})
    service.db.commit()
    return {"removed": True}
