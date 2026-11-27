from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.company import SiteTheme, StorefrontContent


class CompanyOut(BaseModel):
    id: UUID
    company_name: str
    nickname: str | None = None
    logo_url: str | None = None
    phone: str | None = None
    email: str | None = None
    site_theme: SiteTheme = Field(default_factory=SiteTheme)
    storefront_template: str = "current"
    tenant_slug: str | None = None
    storefront_content: StorefrontContent = Field(default_factory=StorefrontContent)
    storefront_enabled: bool = True
    storefront_platform_allowed: bool = True


class BrandOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: str = ""
    image_url: str | None = None


class CategoryOut(BaseModel):
    id: UUID
    category_slug: str
    name: str
    category_title: str
    category_description: str = ""
    image_url: str | None = None
    home_order: int | None = None


class CatalogVariantOut(BaseModel):
    id: UUID
    variant_name: str | None = None
    image_url: str | None = None
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
    minimum_order_quantity: int = Field(ge=1, le=100)
    portal_product_id: str | None = None
    name: str
    description: str | None = None
    image_url: str | None = None
    image_urls: str | None = None
    image_background: str = "#ffffff"
    mrp_display: str | None = None
    selling_price_display: str | None = None
    best_seller: bool = False
    sru_special: bool = False
    tags: list[str] = Field(default_factory=list)
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


class StorefrontSectionOut(BaseModel):
    id: UUID
    section_key: str
    section_type: str
    title: str
    eyebrow: str = ""
    description: str = ""
    image_url: str | None = None
    sort_order: int
    is_enabled: bool
    configuration: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    products: list[ProductOut] = Field(default_factory=list)
    categories: list[CategoryOut] = Field(default_factory=list)
    brands: list[BrandOut] = Field(default_factory=list)


class CatalogHomeResponse(BaseModel):
    company: CompanyOut
    brands: list[BrandOut]
    categories: list[CategoryOut]
    best_sellers: list[ProductOut]
    sru_specials: list[ProductOut]
    catalog_products: list[ProductOut] = Field(default_factory=list)
    sections: list[StorefrontSectionOut] = Field(default_factory=list)
    classic_sections_configured: bool = False


class CatalogStorefrontPreviewResponse(CatalogHomeResponse):
    pass


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
