import base64
import binascii
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_image_source(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("data:"):
        header, separator, encoded = value.partition(",")
        formats = {
            "data:image/png;base64": b"\x89PNG\r\n\x1a\n",
            "data:image/jpeg;base64": b"\xff\xd8\xff",
            "data:image/webp;base64": b"RIFF",
        }
        if not separator or header not in formats:
            raise ValueError("Use a PNG, JPEG or WebP image")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid image data") from exc
        if len(decoded) > 1024 * 1024 or not decoded.startswith(formats[header]):
            raise ValueError("Image must be a valid PNG, JPEG or WebP under 1 MB")
        if header == "data:image/webp;base64" and decoded[8:12] != b"WEBP":
            raise ValueError("Invalid WebP image")
    elif urlparse(value).scheme and urlparse(value).scheme not in {"http", "https"}:
        raise ValueError("Use an image upload, asset path, or HTTP(S) URL")
    return value


class InvoiceSettings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(default="TAX INVOICE", min_length=1, max_length=60)
    thank_you_note: str = Field(default="Thank you for letting us be a part of your celebration.", max_length=500)
    signatory_label: str = Field(default="Authorized Signatory", min_length=1, max_length=80)
    signatory_name: str = Field(default="", max_length=100)
    signatory_designation: str = Field(default="", max_length=100)
    signature_image: str | None = Field(default=None, max_length=1400000)
    footer_text: str = Field(default="SOURCED WITH INTEGRITY \u2022 DELIVERED GLOBALLY.", max_length=240)
    primary_color: str = Field(default="#142b4a", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color: str = Field(default="#b88932", pattern=r"^#[0-9a-fA-F]{6}$")
    footer_text_color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    bill_to_label: str = Field(default="BILL TO", min_length=1, max_length=60)
    ship_to_label: str = Field(default="SHIP TO", min_length=1, max_length=60)
    amount_in_words_label: str = Field(default="Total in Words", min_length=1, max_length=60)
    logo_width_mm: int = Field(default=65, ge=25, le=75)
    signature_width_mm: int = Field(default=34, ge=15, le=50)

    _validate_signature = field_validator("signature_image")(validate_image_source)


class SiteTheme(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    primary_color: str = Field(default="#142b4a", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color: str = Field(default="#b88932", pattern=r"^#[0-9a-fA-F]{6}$")
    background_color: str = Field(default="#fbfaf7", pattern=r"^#[0-9a-fA-F]{6}$")
    surface_color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    text_color: str = Field(default="#142b4a", pattern=r"^#[0-9a-fA-F]{6}$")
    muted_text_color: str = Field(default="#59677a", pattern=r"^#[0-9a-fA-F]{6}$")
    border_color: str = Field(default="#ded9cf", pattern=r"^#[0-9a-fA-F]{6}$")


class StorefrontNavigation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    collection: str = Field(default="Collection", max_length=80)
    categories: str = Field(default="Categories", max_length=80)
    best_sellers: str = Field(default="Best Sellers", max_length=80)
    specials: str = Field(default="Specials", max_length=80)
    brands: str = Field(default="Brands", max_length=80)
    contact: str = Field(default="Contact", max_length=80)
    sign_in: str = Field(default="Sign In", max_length=80)
    operations_portal: str = Field(default="Operations Portal", max_length=80)
    storefront: str = Field(default="Storefront", max_length=80)
    account_menu: str = Field(default="My Account", max_length=80)
    new_workspace: str = Field(default="New Workspace", max_length=80)
    account: str = Field(default="Account", max_length=80)
    sign_out: str = Field(default="Sign Out", max_length=80)


class StorefrontHomeCopy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    browser_title: str = Field(default="{nickname} | Catalogue & Workspace", max_length=140)
    hero_eyebrow: str = Field(default="THE {nickname} COLLECTION SPECIAL", max_length=140)
    hero_heading_first: str = Field(default="Corporate gifting,", max_length=140)
    hero_heading_second: str = Field(default="curated the {nickname} way.", max_length=140)
    hero_description: str = Field(default="A considered collection of premium, practical and memorable gifts, sourced from recognised brands and shaped around the occasion, audience and budget.", max_length=600)
    hero_primary_action: str = Field(default="What makes it special", max_length=100)
    hero_secondary_action: str = Field(default="Explore categories", max_length=100)
    hero_service_one: str = Field(default="CURATE", max_length=40)
    hero_service_two: str = Field(default="CUSTOMISE", max_length=40)
    hero_service_three: str = Field(default="DELIVER", max_length=40)
    categories_eyebrow: str = Field(default="CATEGORIES", max_length=80)
    categories_heading_first: str = Field(default="Shop by gifting", max_length=120)
    categories_heading_second: str = Field(default="category.", max_length=120)
    categories_description: str = Field(default="Browse products from {nickname}.", max_length=400)
    category_card_eyebrow: str = Field(default="{nickname} COLLECTION", max_length=120)
    category_action: str = Field(default="Explore category →", max_length=100)
    categories_more_action: str = Field(default="Explore more categories →", max_length=100)
    best_sellers_eyebrow: str = Field(default="BEST SELLERS", max_length=80)
    best_sellers_heading_first: str = Field(default="Popular picks for", max_length=120)
    best_sellers_heading_second: str = Field(default="corporate gifting.", max_length=120)
    best_sellers_description: str = Field(default="Sample pricing is shown for catalogue look and feel. Bulk quantities can be quoted separately.", max_length=500)
    bulk_title: str = Field(default="Better pricing on bulk orders.", max_length=140)
    bulk_description: str = Field(default="WhatsApp us for best price and price matching with comparable offers.", max_length=400)
    specials_eyebrow: str = Field(default="SPECIALS", max_length=80)
    specials_heading_first: str = Field(default="Curated differently.", max_length=120)
    specials_heading_second: str = Field(default="Chosen by {nickname}.", max_length=120)
    specials_description: str = Field(default="A hand-picked mix of premium, practical and conversation-worthy gifts for standout gifting moments.", max_length=500)
    brands_eyebrow: str = Field(default="BRANDS WE SUPPORT", max_length=80)
    brands_heading_first: str = Field(default="Curated products from", max_length=120)
    brands_heading_second: str = Field(default="recognised brands.", max_length=120)
    brands_description: str = Field(default="Explore available product ranges with sample MRP and our price for catalogue display.", max_length=500)
    brand_catalog_label: str = Field(default="Corporate catalogue", max_length=100)
    brand_action: str = Field(default="View products →", max_length=100)
    why_eyebrow: str = Field(default="WHY {nickname}", max_length=100)
    why_heading_first: str = Field(default="Thoughtful sourcing.", max_length=120)
    why_heading_second: str = Field(default="Seamless execution.", max_length=120)
    why_description: str = Field(default="We understand the occasion, audience and requirement, then source, customise and coordinate the right gifting solution end-to-end.", max_length=600)
    contact_eyebrow: str = Field(default="START A CONVERSATION", max_length=100)
    contact_heading_first: str = Field(default="Let's create something", max_length=120)
    contact_heading_second: str = Field(default="worth giving.", max_length=120)
    contact_description: str = Field(default="For pricing, availability and bulk orders, contact {nickname}.", max_length=400)
    contact_whatsapp_label: str = Field(default="WhatsApp", max_length=100)
    collection_eyebrow: str = Field(default="THE {nickname} COLLECTION", max_length=120)
    collection_heading_first: str = Field(default="Not just a catalogue.", max_length=120)
    collection_heading_second: str = Field(default="A collection with a point of view.", max_length=140)
    collection_description: str = Field(default="Our collection brings together products worth giving, organises them by real gifting needs, and helps businesses choose, customise and deliver the right gift at the right scale.", max_length=600)
    collection_point_one_title: str = Field(default="CURATED", max_length=60)
    collection_point_one_body: str = Field(default="Products selected for corporate relevance, quality and gifting appeal.", max_length=300)
    collection_point_two_title: str = Field(default="FLEXIBLE", max_length=60)
    collection_point_two_body: str = Field(default="Options across categories, budgets, occasions and quantities.", max_length=300)
    collection_point_three_title: str = Field(default="COMMERCIAL", max_length=60)
    collection_point_three_body: str = Field(default="Transparent reference pricing with sharper quotes for bulk requirements.", max_length=300)
    catalogue_unavailable: str = Field(default="Catalogue unavailable.", max_length=120)
    catalogue_loading: str = Field(default="Loading catalogue...", max_length=120)


class StorefrontCatalogCopy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    all_categories_eyebrow: str = Field(default="{nickname} · CATEGORIES", max_length=120)
    category_page_eyebrow: str = Field(default="{nickname} · CATEGORY", max_length=120)
    products_page_eyebrow: str = Field(default="{nickname} · PRODUCTS", max_length=120)
    all_categories_heading_first: str = Field(default="Shop by gifting", max_length=120)
    all_categories_heading_second: str = Field(default="category.", max_length=120)
    all_categories_description: str = Field(default="Explore the categories from {nickname}.", max_length=400)
    catalogue_unavailable: str = Field(default="Catalogue unavailable.", max_length=120)
    catalogue_loading: str = Field(default="Loading catalogue...", max_length=120)
    back_home: str = Field(default="Back to home", max_length=100)
    whatsapp_us: str = Field(default="WhatsApp us →", max_length=100)
    all_categories: str = Field(default="ALL CATEGORIES", max_length=100)
    category_index_heading_first: str = Field(default="Find the right", max_length=120)
    category_index_heading_second: str = Field(default="kind of gift.", max_length=120)
    category_not_found: str = Field(default="Category not found", max_length=120)
    brand_not_found: str = Field(default="Brand not found", max_length=120)
    back_to_categories: str = Field(default="Back to categories", max_length=100)
    back_to_brands: str = Field(default="Back to brands", max_length=100)
    brand_description_fallback: str = Field(default="Corporate gifting catalogue from {brand_name}.", max_length=300)
    all_categories_link: str = Field(default="← All categories", max_length=100)
    all_brands_link: str = Field(default="← All brands", max_length=100)
    product_count: str = Field(default="{count} products", max_length=100)
    sample_price_note: str = Field(default="Sample corporate pricing shown below", max_length=200)
    whatsapp_best_pricing: str = Field(default="WhatsApp for best pricing", max_length=100)
    get_best_pricing: str = Field(default="Get best pricing →", max_length=100)
    whatsapp_prefilled_message: str = Field(default="Hello, I need help selecting products. Please share pricing and availability.", max_length=400)
    product_range_suffix: str = Field(default="PRODUCT RANGE", max_length=100)
    choose_heading_first: str = Field(default="Choose a product.", max_length=120)
    choose_heading_second: str = Field(default="Then enquire.", max_length=120)
    choose_description: str = Field(default="MRP is shown for reference. Our listed price is a sample individual requirement price; bulk orders can be priced better.", max_length=500)
    no_products: str = Field(default="No products found for this filter.", max_length=200)
    best_pricing_heading: str = Field(default="Better pricing on bulk orders.", max_length=140)
    best_pricing_description: str = Field(default="WhatsApp us for the best price and price matching with comparable offers.", max_length=400)


class StorefrontProductCopy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    home_breadcrumb: str = Field(default="Home", max_length=80)
    fallback_brand: str = Field(default="{nickname}", max_length=80)
    variant_label: str = Field(default="Size / Colour", max_length=80)
    base_product: str = Field(default="Base product", max_length=80)
    mrp_label: str = Field(default="MRP", max_length=60)
    our_price_label: str = Field(default="Our Price", max_length=60)
    request_quote: str = Field(default="Request a quote", max_length=100)
    discount_suffix: str = Field(default="% off MRP", max_length=60)
    item_name_label: str = Field(default="Item name", max_length=80)
    size_label: str = Field(default="Size", max_length=60)
    colour_label: str = Field(default="Colour", max_length=60)
    weight_label: str = Field(default="Weight (kg)", max_length=80)
    height_label: str = Field(default="Height (cm)", max_length=80)
    width_label: str = Field(default="Width (cm)", max_length=80)
    length_label: str = Field(default="Length (cm)", max_length=80)
    bulk_heading: str = Field(default="Better pricing on bulk orders.", max_length=140)
    bulk_description: str = Field(default="WhatsApp us for best price and price matching with comparable offers.", max_length=400)
    price_note: str = Field(default="Our listed price is for individual requirements. Bulk orders will have better pricing. WhatsApp us for best quote.", max_length=400)
    whatsapp_action: str = Field(default="WhatsApp for best price", max_length=100)
    product_unavailable: str = Field(default="Product unavailable.", max_length=120)
    product_loading: str = Field(default="Loading product...", max_length=120)
    view_photo: str = Field(default="View photo {number}", max_length=100)
    best_seller_badge: str = Field(default="Best Seller", max_length=60)
    special_badge: str = Field(default="Special", max_length=60)
    photos_count: str = Field(default="{count} photos", max_length=100)
    in_stock: str = Field(default="In stock", max_length=60)
    out_of_stock: str = Field(default="Out of stock", max_length=60)
    whatsapp_enquiry: str = Field(default="WhatsApp enquiry", max_length=100)
    whatsapp_message: str = Field(default="Hello, I am interested in {product_name} from {brand_name}. Please share pricing, availability and bulk options.", max_length=400)


class StorefrontFooterCopy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    catalogue_label: str = Field(default="Product Catalogue", max_length=120)


class StorefrontContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    navigation: StorefrontNavigation = Field(default_factory=StorefrontNavigation)
    home: StorefrontHomeCopy = Field(default_factory=StorefrontHomeCopy)
    catalog: StorefrontCatalogCopy = Field(default_factory=StorefrontCatalogCopy)
    product: StorefrontProductCopy = Field(default_factory=StorefrontProductCopy)
    footer: StorefrontFooterCopy = Field(default_factory=StorefrontFooterCopy)


class CompanyUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    company_name: str = Field(min_length=1, max_length=200)
    tenant_slug: str | None = Field(default=None, min_length=3, max_length=48, pattern=r"^[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])$")
    nickname: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=2000)
    gst_number: str | None = Field(default=None, pattern=r"^\d{2}[A-Z0-9]{13}$")
    udyam_number: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=300)
    logo_url: str | None = Field(default=None, max_length=1400000)
    social_links: dict[str, str] = Field(default_factory=dict, max_length=20)
    invoice_settings: InvoiceSettings = Field(default_factory=InvoiceSettings)
    site_theme: SiteTheme | None = None
    storefront_content: StorefrontContent = Field(default_factory=StorefrontContent)

    _validate_logo = field_validator("logo_url")(validate_image_source)

    @field_validator("tenant_slug")
    @classmethod
    def valid_tenant_slug(cls, value: str | None) -> str | None:
        if value is not None and value in {"app", "api", "www", "admin", "login", "register", "portal", "support", "assets", "static", "auth"}:
            raise ValueError("Workspace address is reserved")
        return value


class CompanySetupOut(CompanyUpdate):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    gst_number: str | None = None
    site_theme: SiteTheme = Field(default_factory=SiteTheme)
    tenant_slug: str | None = None
    id: UUID
    is_active: bool