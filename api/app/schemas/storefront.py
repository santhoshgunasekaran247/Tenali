import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.company import validate_image_source


SectionType = Literal["hero", "products", "categories", "brands"]


class StorefrontSectionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    section_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    section_type: SectionType
    title: str = Field(min_length=1, max_length=120)
    eyebrow: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=400)
    image_url: str | None = Field(default=None, max_length=1400000)
    sort_order: int = Field(ge=0, le=99999)
    is_enabled: bool = True
    configuration: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=30)
    product_ids: list[UUID] = Field(default_factory=list, max_length=100)
    category_ids: list[UUID] = Field(default_factory=list, max_length=100)
    brand_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_section_items(self):
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("A section cannot include the same product more than once")
        if len(set(self.category_ids)) != len(self.category_ids):
            raise ValueError("A section cannot include the same category more than once")
        if len(set(self.brand_ids)) != len(self.brand_ids):
            raise ValueError("A section cannot include the same brand more than once")
        expected = {
            "hero": ([], self.product_ids, self.category_ids, self.brand_ids),
            "products": (self.product_ids, self.category_ids, self.brand_ids),
            "categories": (self.category_ids, self.product_ids, self.brand_ids),
            "brands": (self.brand_ids, self.product_ids, self.category_ids),
        }[self.section_type]
        if self.section_type == "hero" and any(expected):
            raise ValueError("Hero sections cannot map catalog items")
        if self.section_type != "hero" and (expected[1] or expected[2]):
            raise ValueError(f"{self.section_type.title()} sections can only map matching catalog items")
        allowed_configuration = {
            "image_ratio", "image_fit", "font_family", "border_style",
            "background_color", "text_color", "accent_color",
            "classic_slot",
            "selected_only",
        }
        if self.configuration.keys() - allowed_configuration:
            raise ValueError("Section configuration contains unsupported style options")
        if "selected_only" in self.configuration and not isinstance(self.configuration["selected_only"], bool):
            raise ValueError("Selected-only display must be true or false")
        classic_slot = self.configuration.get("classic_slot")
        if classic_slot is not None:
            slot_types = {
                "hero": "hero", "categories": "categories", "best-sellers": "products",
                "specials": "products", "brands": "brands",
            }
            if not isinstance(classic_slot, str) or slot_types.get(classic_slot) != self.section_type:
                raise ValueError("Classic sections must use a matching built-in layout")
        for key in ("background_color", "text_color", "accent_color"):
            color = self.configuration.get(key)
            if color is not None and (not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
                raise ValueError(f"{key} must be a six-digit hex colour")
        if self.configuration.get("image_ratio", "square") not in {"square", "portrait", "landscape"}:
            raise ValueError("Image ratio must be square, portrait, or landscape")
        if self.configuration.get("image_fit", "cover") not in {"cover", "contain"}:
            raise ValueError("Image fit must be cover or contain")
        if self.configuration.get("font_family", "default") not in {"default", "serif", "sans"}:
            raise ValueError("Font family must be default, serif, or sans")
        if self.configuration.get("border_style", "theme") not in {"theme", "square", "rounded"}:
            raise ValueError("Border style must be theme, square, or rounded")
        validate_image_source(self.image_url)
        return self


class StorefrontSectionsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[StorefrontSectionInput] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_section_keys(self):
        keys = [section.section_key for section in self.sections]
        if len(set(keys)) != len(keys):
            raise ValueError("Section keys must be unique")
        return self


class ProductTagInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=80)
    product_ids: list[UUID] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def unique_products(self):
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("A tag cannot be assigned to the same product more than once")
        return self


class ProductTagsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[ProductTagInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_tag_codes(self):
        codes = [tag.code for tag in self.tags]
        if len(set(codes)) != len(codes):
            raise ValueError("Product tag codes must be unique")
        return self
