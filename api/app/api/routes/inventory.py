from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.inventory import BulkVendorMapping, InventoryLookupCreate, ProductInput, ReorderReminder, StockAdjustment, VariantInput, VendorOfferInput
from app.services.inventory_service import InventoryService

router = APIRouter()


def inventory_service(company_id: UUID | None = None, db: Session = Depends(get_db)) -> InventoryService:
    return InventoryService(db, str(company_id) if company_id else None)


@router.get("/lookups")
def lookups(service: InventoryService = Depends(inventory_service)):
    return service.lookups()


@router.post("/lookups/{kind}", status_code=201)
def create_lookup(kind: str, payload: InventoryLookupCreate, service: InventoryService = Depends(inventory_service)):
    return service.create_lookup(kind, payload.name,payload.description,payload.is_active)


@router.get("/lookups/{kind}")
def master_entries(kind:str,service:InventoryService=Depends(inventory_service)):
    return service.master_entries(kind)


@router.put("/lookups/{kind}/{record_id}")
def update_lookup(kind:str,record_id:UUID,payload:InventoryLookupCreate,service:InventoryService=Depends(inventory_service)):
    return service.update_lookup(kind,str(record_id),payload)


@router.get("/products")
def products(service: InventoryService = Depends(inventory_service)):
    return service.list_products()


@router.post("/products", status_code=201)
def create_product(payload: ProductInput, service: InventoryService = Depends(inventory_service)):
    return service.save_product(payload)


@router.get("/products/{product_id}")
def product(product_id: UUID, service: InventoryService = Depends(inventory_service)):
    return service.detail(str(product_id))


@router.put("/products/{product_id}")
def update_product(product_id: UUID, payload: ProductInput, service: InventoryService = Depends(inventory_service)):
    return service.save_product(payload, str(product_id))


@router.post("/products/{product_id}/variants", status_code=201)
def create_variant(product_id: UUID, payload: VariantInput, service: InventoryService = Depends(inventory_service)):
    return service.save_variant(str(product_id), payload)


@router.put("/products/{product_id}/variants/{variant_id}")
def update_variant(product_id: UUID, variant_id: UUID, payload: VariantInput, service: InventoryService = Depends(inventory_service)):
    return service.save_variant(str(product_id), payload, str(variant_id))


@router.post("/products/{product_id}/offers", status_code=201)
def create_offer(product_id: UUID, payload: VendorOfferInput, service: InventoryService = Depends(inventory_service)):
    return service.save_offer(str(product_id), payload)


@router.put("/products/{product_id}/offers/{offer_id}")
def update_offer(product_id: UUID, offer_id: UUID, payload: VendorOfferInput, service: InventoryService = Depends(inventory_service)):
    return service.save_offer(str(product_id), payload, str(offer_id))


@router.post("/products/vendor-mappings")
def bulk_mapping(payload: BulkVendorMapping, service: InventoryService = Depends(inventory_service)):
    return service.bulk_map(payload)


@router.post("/products/{product_id}/stock")
def adjust_stock(product_id: UUID, payload: StockAdjustment, service: InventoryService = Depends(inventory_service)):
    return service.adjust_stock(str(product_id), payload)


@router.get("/products/{product_id}/movements")
def movements(product_id: UUID, service: InventoryService = Depends(inventory_service)):
    return service.movements(str(product_id))


@router.get("/alerts")
def alerts(service: InventoryService = Depends(inventory_service)):
    return service.alerts()


@router.put("/products/{product_id}/reminder")
def remind(product_id: UUID, payload: ReorderReminder, service: InventoryService = Depends(inventory_service)):
    return service.remind(str(product_id), payload)