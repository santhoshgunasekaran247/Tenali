from fastapi import HTTPException
from app.services.feature_controls import company_features

STOREFRONT_DISABLED = "This storefront is currently unavailable"


def ensure_storefront_enabled(db, company_id) -> None:
    status = company_features(db, company_id)
    if not status["storefront"]["effective_enabled"]:
        raise HTTPException(403, STOREFRONT_DISABLED)
