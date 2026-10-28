from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class CompanyOut(BaseModel):
    id: UUID
    company_name: str
    nickname: str | None = None
    logo_url: str | None = None
    phone: str | None = None
    email: str | None = None


class BrandOut(BaseModel):
    code: str
    name: str
    description: str = ""


class CategoryOut(BaseModel):
    category_slug: str
    name: str
    category_title: str
    category_description: str = ""
    image_url: str | None = None
    home_order: int | None = None


class CatalogVariantOut(BaseModel):
    id: UUID
    variant_name: str | None = None
    sku: str | None = None
    size: str | None = None
    colour: str | None = None
    item_name: str | None = None
    description: str | None = None
    weight: float | None = None
    height: float | None = None
    width: float | None = None
    length: float | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    mrp_display: str | None = None
    selling_price_display: str | None = None
    discount_percent: float | None = None
    stock_qty: float = 0


class ProductOut(BaseModel):
    id: UUID
    portal_product_id: str | None = None
    name: str
    description: str | None = None
    image_url: str | None = None
    image_urls: str | None = None
    mrp_display: str | None = None
    selling_price_display: str | None = None
    best_seller: bool = False
    sru_special: bool = False
    home_order: int | None = None
    is_active: bool = True
    brand_code: str | None = None
    brand_name: str | None = None
    category_slug: str | None = None
    category_title: str | None = None
    category_description: str | None = None
    stock_qty: float = 0
    gallery: list[str] = Field(default_factory=list)
    item_name: str | None = None
    size: str | None = None
    colour: str | None = None
    weight: float | None = None
    height: float | None = None
    width: float | None = None
    length: float | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    discount_percent: float | None = None
    variants: list[CatalogVariantOut] = Field(default_factory=list)


class CatalogHomeResponse(BaseModel):
    company: CompanyOut
    brands: list[BrandOut]
    categories: list[CategoryOut]
    best_sellers: list[ProductOut]
    sru_specials: list[ProductOut]


class CatalogListResponse(BaseModel):
    company: CompanyOut
    brands: list[BrandOut]
    categories: list[CategoryOut]
    products: list[ProductOut]
    selected_brand: BrandOut | None = None
    selected_category: CategoryOut | None = None


class CatalogProductResponse(BaseModel):
    product: ProductOut
    company: CompanyOut | None = None
