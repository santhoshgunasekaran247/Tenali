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


class CompanyUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    company_name: str = Field(min_length=1, max_length=200)
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

    _validate_logo = field_validator("logo_url")(validate_image_source)


class CompanySetupOut(CompanyUpdate):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    gst_number: str | None = None
    site_theme: SiteTheme = Field(default_factory=SiteTheme)
    id: UUID
    is_active: bool