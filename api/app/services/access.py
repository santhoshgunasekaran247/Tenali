"""Store-level and module-level access for team members.

Owners and administrators ("super roles") always see every store and module. Staff and read-only
members may be limited to specific stores (`store_ids`) and modules (`modules`); null means all.
"""

from __future__ import annotations

from fastapi import HTTPException

SUPER_ROLES = {"owner", "admin"}
MODULES = ("billing", "purchases", "inventory", "receivables", "accounts", "settlements", "reports", "parties", "masters", "orders")
# Request path prefix (after /api) -> module. Paths not listed are open to every signed-in member.
PATH_MODULES = (
    ("/billing", "billing"), ("/purchases", "purchases"), ("/inventory", "inventory"), ("/collections", "receivables"),
    ("/accounts", "accounts"), ("/settlements", "settlements"), ("/reports", "reports"), ("/parties", "parties"),
    ("/masters", "masters"), ("/checkout-admin", "orders"),
)


def is_super(identity: dict) -> bool:
    return identity.get("role") in SUPER_ROLES


def allowed_stores(identity: dict | None) -> list[str] | None:
    """None = every store; otherwise the store ids this member may work in."""
    if not identity or is_super(identity):
        return None
    stores = identity.get("store_ids")
    return [str(store) for store in stores] if stores is not None else None


def check_module(identity: dict, path: str) -> None:
    if is_super(identity) or identity.get("modules") is None:
        return
    for prefix, module in PATH_MODULES:
        if path == prefix or path.startswith(prefix + "/"):
            if module not in identity["modules"]:
                raise HTTPException(403, f"Your account does not include the {module} module")
            return


def check_store(identity: dict | None, store: dict) -> None:
    stores = allowed_stores(identity)
    if stores is not None and str(store["id"]) not in stores:
        raise HTTPException(403, f"Your account does not include store {store['code']}")
