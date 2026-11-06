from fastapi import HTTPException
from sqlalchemy import text

STOREFRONT_DISABLED = "This storefront is currently unavailable"


def ensure_storefront_enabled(db, company_id) -> None:
    enabled = db.execute(text("select storefront_enabled from companies where id=:company and is_active=true"),
                         {"company": str(company_id)}).scalar_one_or_none()
    if enabled is None:
        raise HTTPException(404, "Workspace not found")
    if not enabled:
        raise HTTPException(403, STOREFRONT_DISABLED)
