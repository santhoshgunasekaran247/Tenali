"""Bounded Excel templates and retryable import reports."""
from io import BytesIO
import re
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from defusedxml.common import DefusedXmlException
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
from app.services.product_images import background_name

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 40 * 1024 * 1024
MAX_ROWS = 2000
MAX_LOOKUPS = 5000
OFFER_FIELDS = ("vendor_mrp", "vendor_buying_price", "vendor_available_quantity", "vendor_availability",
                "vendor_lead_time_days", "vendor_sku", "vendor_reference", "vendor_product_url")

FIELDS = {
    "products": ("id", "name", "sku", "description", "brand", "brand_description", "categories",
                 "hsn_code", "hsn_description", "gst_rate", "vendor", "image_url", "image_file", "image_background",
                 "labels", "selling_price", "discount_percent", "pricing_mode", "is_active", "catalog_visible",
                 "brand_image_url", "brand_image_file", "category_image_url", "category_image_file",
                 "record_type", "parent_product_id", "parent_sku", "variant_name", "size", "colour", *OFFER_FIELDS),
    "variants": ("id", "product_id", "variant_name", "sku", "size", "colour", "selling_price",
                 "discount_percent", "pricing_mode", "image_url", "is_active", "vendor", *OFFER_FIELDS, "image_file"),
    "hsn": ("id", "code", "description", "gst_rate", "is_active"),
    "parties": ("id", "party_type", "legal_name", "nickname", "contact_person", "phone", "email",
                "address", "gst_number", "is_active"),
    "brands": ("id", "name", "description", "is_active", "image_url", "image_file"),
    "categories": ("id", "name", "description", "is_active", "image_url", "image_file"),
    "images": ("id", "entity", "image_url", "image_file", "image_background"),
}
SAMPLES = {
    "products": {"name": "Sample product", "brand": "Sample brand", "categories": "Home|Gifts",
                 "hsn_code": "1234", "hsn_description": "Sample goods", "gst_rate": 18,
                 "vendor": "Sample vendor", "labels": "Featured|New", "pricing_mode": "price"},
    "variants": {"product_id": "Paste a product ID", "variant_name": "Large", "size": "Large", "pricing_mode": "inherit"},
    "hsn": {"code": "1234", "description": "Sample goods", "gst_rate": 18, "is_active": True},
    "parties": {"party_type": "vendor", "legal_name": "Sample supplier", "phone": "9876543210", "is_active": True},
    "brands": {"name": "Sample brand", "description": "Example description", "is_active": True},
    "categories": {"name": "Home", "description": "Example category", "is_active": True},
    "images": {"id": "Paste a record ID", "entity": "product", "image_file": "photo.png", "image_background": "white"},
}
INSTRUCTIONS = {
    "products": (
        "Products: name is required for new products. SKU and description are optional.",
        "brand and categories accept existing names or new names. brand_description is used only for a newly created brand.",
        "categories and labels use | between names. Avoid | in names; first category is the primary one.",
        "For a new HSN, supply hsn_code, hsn_description and gst_rate. GST-registered workspaces require an HSN for new products.",
        "vendor maps an existing vendor by name or creates a new vendor contact. It becomes the preferred vendor.",
        "image_background uses English names: white, black, light blue, ivory. White is the default. Hex colours still work for existing files.",
        "brand_image_url / brand_image_file updates the named brand's logo; category_image_url / category_image_file updates the first category's image. Supply a matching name.",
        "For product image files, upload a ZIP containing manifest.xlsx and images/<filename>; set image_file to the filename.",
        "Product pricing_mode is price or discount; child rows may also inherit their parent's price. selling_price and discount_percent must meet inventory pricing rules.",
        "record_type is product (default) or child. A child is a size/colour variant, not a separate catalogue product.",
        "For child rows, set parent_product_id or parent_sku and variant_name (or name). Put parent rows first. Keep the exported child id when updating.",
        "Vendor offer columns describe the supplier's MRP, buying price, stock, availability, lead time and reference, not your selling price. Leave unknown values blank; an offer requires vendor.",
    ),
    "variants": (
        "Variants: product_id is the owning product's ID. variant_name is required for new variants.",
        "A variant ID can only be updated under its own product. pricing_mode can be inherit, price or discount.",
        "Variants are child records. Optional vendor and vendor_* columns create or update the supplier offer for this child, not the parent.",
        "For child image files, upload manifest.xlsx and images/<filename> in a ZIP and set image_file. Alternatively, use image_url; do not supply both.",
    ),
    "hsn": (
        "HSN: code must contain 4, 6 or 8 digits. Supply description and GST rate from 0 to 100.",
        "Existing HSN codes cannot be renamed. Create a different code instead.",
    ),
    "parties": (
        "Contacts: party_type is customer, vendor, customer_vendor, friend, employee or other.",
        "legal_name and party_type are required for new contacts. Telephone numbers should be stored as text.",
    ),
    "brands": ("Brands: name is required. Existing records use their exported id. Add image_url or image_file to include the logo in the same row.",),
    "categories": ("Categories: name is required. Existing records use their exported id. Add image_url or image_file to include a picture in the same row.",),
    "images": (
        "Images: choose entity product, brand or category and enter its existing ID.",
        "Specify either image_url or image_file, never both. Upload URLs as an XLSX workbook.",
        "For files, put this workbook in a ZIP as manifest.xlsx and photos in images/ (for example images/photo.png).",
        "Set image_file to the filename only. PNG, JPEG and WebP files must be at most 1 MiB each and 8 MiB total.",
        "A results ZIP with failure.xlsx and its image files can be uploaded directly after correction.",
        "image_background applies to product images only; a non-white background requires transparent photos or AI segmentation.",
    ),
}
LOOKUP_FIELDS = {
    "brand": "brands", "categories": "categories", "hsn_code": "hsn", "vendor": "vendors",
    "party_type": "party_types", "pricing_mode": "pricing_modes", "is_active": "booleans",
    "catalog_visible": "booleans",
    "entity": "image_entities",
    "record_type": "record_types", "vendor_availability": "vendor_availability",
}
AUTOFILL = {
    "brand_description": ("brand", "$A$2:$B$5001", 2),
    "hsn_description": ("hsn_code", "$D$2:$F$5001", 2),
    "gst_rate": ("hsn_code", "$D$2:$F$5001", 3),
}
REQUIRED_FIELDS = {
    "products": {"name"}, "variants": {"product_id", "variant_name"},
    "hsn": {"code", "description", "gst_rate"}, "parties": {"party_type", "legal_name"},
    "brands": {"name"}, "categories": {"name"}, "images": {"id", "entity"},
}
FIELD_HELP = {
    "id": "Leave blank to create. Keep an exported ID to update a record in this workspace.",
    "hsn_code": "Choose an existing HSN to fill description and GST. For a new code, overwrite both related cells with literal values.",
    "brand": "Choose an existing brand to fill its description, or type a new name.",
    "brand_description": "Auto-filled for an existing brand. For a new brand, replace the formula with its description.",
    "hsn_description": "Auto-filled from the selected HSN. For a new code, replace the formula with a description.",
    "gst_rate": "Auto-filled from the selected HSN. For a new code, replace the formula with a rate from 0 to 100 (for example 18, not 18%).",
    "categories": "Separate names with |. The first is primary. Existing names or new names are accepted.",
    "image_url": "Public HTTPS or an existing Tenali image URL. Leave image_file blank when using a URL.",
    "image_file": "Filename in the ZIP images/ folder. Leave image_url blank when using a file.",
    "image_background": "English colour name, for example white, ivory or light blue. Defaults to white for new products. Hex colours remain supported.",
    "brand_image_url": "Public HTTPS logo URL for the brand named in this row. Leave brand_image_file blank.",
    "brand_image_file": "Brand logo filename in images/. Set brand and leave brand_image_url blank.",
    "category_image_url": "Public HTTPS image URL for the first category in this row. Leave category_image_file blank.",
    "category_image_file": "Category image filename in images/. Set categories and leave category_image_url blank.",
    "failure_reason": "Correct the described error and re-upload only failed rows. This column is ignored during import.",
    "record_type": "product for a parent; child for a size/colour variant. Blank means product.",
    "parent_product_id": "For child rows: the existing parent product ID in this workspace.",
    "parent_sku": "For child rows: exact parent SKU, including a parent created in an earlier row. Do not use the child's SKU.",
    "variant_name": "Name of the child option, for example Large / Blue.",
    "vendor_mrp": "Supplier's MRP in INR. Not your selling price.",
    "vendor_buying_price": "Price you pay this vendor in INR. Never infer this from selling price.",
    "vendor_available_quantity": "Stock available from this vendor, not stock in your stores.",
}


def _autofill_formula(field, number, fields):
    source, reference, index = AUTOFILL[field]
    cell = f"${get_column_letter(fields.index(source) + 1)}{number}"
    # Escape Excel lookup wildcards so brand names are matched literally.
    key = f'SUBSTITUTE(SUBSTITUTE(SUBSTITUTE({cell}&"","~","~~"),"*","~*"),"?","~?")'
    lookup = f"VLOOKUP({key},References!{reference},{index},FALSE)"
    if field != "gst_rate":
        lookup += '&""'
    return f'=IF({cell}="","",IFERROR({lookup},""))'


def _style_header(sheet, fields, kind):
    for column, field in enumerate(fields, 1):
        cell = _write_cell(sheet, 1, column, field)
        color = "147D78" if kind == "products" and field in AUTOFILL else (
            "9B3B30" if field == "failure_reason" else "193D67")
        cell.fill = PatternFill("solid", fgColor=color)
        cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        hint = FIELD_HELP.get(field, "Enter a value. Blank update cells leave this field unchanged.")
        if field in REQUIRED_FIELDS[kind]:
            hint = "Required for new records. " + hint
        cell.comment = Comment(hint, "Tenali")
        width = 42 if field in {"description", "hsn_description", "brand_description", "failure_reason", "image_url", "address"} else (
            38 if field in {"id", "product_id"} else max(20, len(field) + 4))
        dimension = sheet.column_dimensions[get_column_letter(column)]
        dimension.width = width
        if field in {"id", "product_id", "sku", "hsn_code", "code", "phone", "gst_number"}:
            dimension.number_format = "@"
    sheet.row_dimensions[1].height = 34


def _readme(book, kind, notes):
    sheet = book.create_sheet("README")
    sheet.sheet_view.showGridLines = False
    for column in range(1, 9):
        sheet.column_dimensions[get_column_letter(column)].width = 15
    lines = [
        ("TENALI | BULK WORKBOOK", "title"),
        (f"{kind.upper()} - Quick start", "section"),
        ("1. Fill in Data. Leave id blank for new records; keep exported IDs to update.", ""),
        ("2. Use dropdowns for existing records, or type new names. Suggestions belong to this workspace at download time.", ""),
        ("3. Upload your completed workbook on Bulk upload. Each row saves independently.", ""),
        ("4. Download the results ZIP. Correct failure.xlsx and upload only failed rows again.", ""),
        ("Working with your data", "section"),
        ("Blank update cells keep existing values. Use <clear> to clear an optional field.", ""),
        ("Dark blue headers are inputs; teal headers auto-fill related values. Hover over headers for field guidance.", ""),
        ("Purple text on pale lavender cells is AI-generated content. Review it against your source before uploading; colour is guidance, not verification.", ""),
        ("Products: selecting an HSN fills its description and GST; selecting a brand fills its description.", "") if kind == "products" else
        ("Only the Data sheet is imported. This guide and the example below are not imported.", ""),
        ("For a new HSN or brand, replace its auto-filled cells with your own values. Existing HSN/GST values are verified from the live master on upload.", "") if kind == "products" else
        ("Do not remove or rename the Data sheet or its column headers.", ""),
        ("Use text for HSN codes, SKUs and phone numbers to preserve leading zeroes.", ""),
        ("Keep the built-in lookup formulas, or replace them with literal values. Other formulas are rejected.", ""),
        (f"Limits: {MAX_ROWS:,} data rows; XLSX 10 MiB; image ZIP 20 MiB.", ""),
        ("Record-specific guidance", "section"),
        *((line, "") for line in INSTRUCTIONS[kind]),
        ("Image sizes: products 1000 x 1000 px; brand logos 600 x 600 px; category pictures 800 x 800 px. Use square PNG, JPEG or WebP under 1 MiB. Keep the whole subject inside the image; Tenali fits it without stretching.", "") if kind in {"products", "brands", "categories", "images", "variants"} else
        ("Check your entries before upload.", ""),
        ("Example only - copy values into Data if needed", "section"),
    ]
    for number, (line, style) in enumerate(lines, 1):
        sheet.merge_cells(start_row=number, start_column=1, end_row=number, end_column=8)
        cell = _write_cell(sheet, number, 1, line)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.font = Font(name="Calibri", size=11, color="172D4A")
        sheet.row_dimensions[number].height = 34 if len(line) > 115 else 28
        if style:
            cell.fill = PatternFill("solid", fgColor="193D67" if style == "title" else "E5EFF8")
            cell.font = Font(name="Calibri", size=16 if style == "title" else 12, bold=True,
                             color="FFFFFF" if style == "title" else "193D67")
    number = len(lines)
    for field, value in SAMPLES[kind].items():
        number += 1
        sheet.merge_cells(start_row=number, start_column=1, end_row=number, end_column=2)
        sheet.merge_cells(start_row=number, start_column=3, end_row=number, end_column=8)
        _write_cell(sheet, number, 1, field).font = Font(bold=True, color="193D67")
        _write_cell(sheet, number, 3, value).alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[number].height = 25
    if notes:
        for line in ("AI catalog notes (review against the source):", notes):
            number += 1
            sheet.merge_cells(start_row=number, start_column=1, end_row=number, end_column=8)
            _write_cell(sheet, number, 1, line).alignment = Alignment(wrap_text=True, vertical="top")
            sheet.row_dimensions[number].height = 90 if line == notes else 28
    sheet.freeze_panes = "A3"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True


def _write_cell(sheet, row, column, value):
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell


def workbook(kind: str, rows=(), lookups=None, *, reasons=False, notes=None, ai_generated=False) -> bytes:
    if kind not in FIELDS:
        raise HTTPException(422, "Unknown bulk workbook type.")
    lookups = lookups or {}
    book = Workbook()
    book.calculation = CalcProperties(calcMode="auto")
    sheet = book.active
    sheet.title = "Data"
    fields = (*FIELDS[kind], "failure_reason") if reasons else FIELDS[kind]
    _style_header(sheet, fields, kind)
    for number, row in enumerate(rows, 2):
        for column, field in enumerate(fields, 1):
            value = row.get(field)
            if field == "image_background" and isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                value = background_name(value)
            cell = _write_cell(sheet, number, column, value)
            if ai_generated and value is not None:
                cell.font = Font(name="Calibri", color="7135A5", size=11)
                cell.fill = PatternFill("solid", fgColor="F3EAFB")
    sheet.freeze_panes = "B2"
    last_row = max(2, sheet.max_row)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(fields))}{last_row}"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 85
    sheet.sheet_properties.tabColor = "193D67"
    sheet.print_title_rows = "1:1"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.conditional_formatting.add(f"A2:{get_column_letter(len(fields))}{MAX_ROWS + 1}",
        FormulaRule(formula=["MOD(ROW(),2)=0"], fill=PatternFill("solid", fgColor="F0F5FA")))
    _readme(book, kind, notes)

    references = book.create_sheet("References")
    references.sheet_state = "hidden"
    for column, key in enumerate(("brands", "brand_descriptions", None, "hsn", "hsn_descriptions", "hsn_gst_rates"), 1):
        if key:
            _write_cell(references, 1, column, key)
            for number, value in enumerate(lookups.get(key, []), 2):
                _write_cell(references, number, column, value)
    if kind == "products":
        for field in AUTOFILL:
            column = fields.index(field) + 1
            source = AUTOFILL[field][0]
            source_column = fields.index(source) + 1
            names = lookups.get("brands" if source == "brand" else "hsn", [])
            for number in range(2, MAX_ROWS + 2):
                cell = sheet.cell(number, column)
                if cell.value is None or (not ai_generated and str(sheet.cell(number, source_column).value) in names):
                    cell.value = _autofill_formula(field, number, fields)
                    cell.font = Font(name="Calibri", color="147D78")
                    cell.number_format = "0.##" if field == "gst_rate" else "General"
        # Column formatting alone is not honored by every spreadsheet editor.
        for number in range(2, MAX_ROWS + 2):
            sheet.cell(number, fields.index("hsn_code") + 1).number_format = "@"

    lists = book.create_sheet("Suggestions")
    lists.sheet_state = "hidden"
    for column, (key, values) in enumerate(lookups.items(), 1):
        if len(values) > MAX_LOOKUPS:
            raise HTTPException(422, f"Too many {key} suggestions to generate a workbook.")
        _write_cell(lists, 1, column, key)
        for row, value in enumerate(values, 2):
            _write_cell(lists, row, column, value)
        if not values:
            continue
        letter = get_column_letter(column)
        for index, field in enumerate(fields, 1):
            if LOOKUP_FIELDS.get(field) != key:
                continue
            validation = DataValidation(type="list", formula1=f"INDIRECT(\"'Suggestions'!${letter}$2:${letter}${len(values) + 1}\")",
                                        allow_blank=True, showErrorMessage=False)
            sheet.add_data_validation(validation)
            validation.add(f"{get_column_letter(index)}2:{get_column_letter(index)}{MAX_ROWS + 1}")
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def read_workbook(kind: str, content: bytes) -> list[dict]:
    if kind not in FIELDS:
        raise HTTPException(422, "Unknown bulk workbook type.")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Workbook must be nonempty and at most 10 MiB.")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
                raise HTTPException(413, "Workbook expands beyond the permitted size.")
            if any(entry.flag_bits & 1 for entry in entries):
                raise HTTPException(422, "Encrypted workbooks are not supported.")
        book = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, OSError, ValueError, KeyError, DefusedXmlException) as error:
        raise HTTPException(422, "Upload a valid unencrypted .xlsx workbook.") from error
    try:
        if "Data" not in book.sheetnames:
            raise HTTPException(422, "Workbook must contain a Data sheet.")
        sheet = book["Data"]
        if (sheet.max_column or 0) > len(FIELDS[kind]) + 1 or (sheet.max_row or 0) > MAX_ROWS + 1:
            raise HTTPException(422, f"Workbook exceeds {MAX_ROWS} rows or has too many columns.")
        sheet.reset_dimensions()
        iterator = sheet.iter_rows()
        header = next(iterator, ())
        if len(header) > len(FIELDS[kind]) + 1:
            raise HTTPException(422, "Data sheet has too many columns.")
        names = [cell.value for cell in header]
        if any(not isinstance(name, str) or name not in (*FIELDS[kind], "failure_reason") for name in names):
            raise HTTPException(422, "Data sheet contains an unknown or blank column name.")
        if len(set(names)) != len(names) or "id" not in names:
            raise HTTPException(422, "Data sheet must include one id column and no duplicate headers.")
        rows = []
        for number, cells in enumerate(iterator, 1):
            if number > MAX_ROWS or len(cells) > len(names):
                raise HTTPException(422, "Workbook has too many rows or cells outside the header.")
            values = {}
            for name, cell in zip(names, cells):
                if cell.data_type == "f":
                    if (kind != "products" or name not in AUTOFILL or AUTOFILL[name][0] not in names
                            or cell.value.replace("'References'!", "References!") != _autofill_formula(name, number + 1, names)):
                        raise HTTPException(422, "Formulas other than built-in dependent-field lookups are not supported; paste values instead.")
                    # Do not execute uploaded formulas or trust their cached values/snapshot.
                    # Existing dependencies are resolved against this tenant's live masters.
                    value = None
                else:
                    value = cell.value
                if name != "failure_reason":
                    values[name] = value
            if any(value is not None and value != "" for value in values.values()):
                rows.append(values)
        return rows
    except DefusedXmlException as error:
        raise HTTPException(422, "Workbook contains unsafe XML.") from error
    finally:
        book.close()
