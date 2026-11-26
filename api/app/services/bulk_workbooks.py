"""Bounded Excel templates and retryable import reports."""
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from defusedxml.common import DefusedXmlException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 40 * 1024 * 1024
MAX_ROWS = 2000
MAX_LOOKUPS = 5000

FIELDS = {
    "products": ("id", "name", "sku", "description", "brand", "brand_description", "categories",
                 "hsn_code", "hsn_description", "gst_rate", "vendor", "image_url", "image_file", "image_background",
                 "labels", "selling_price", "discount_percent", "pricing_mode", "is_active", "catalog_visible"),
    "variants": ("id", "product_id", "variant_name", "sku", "size", "colour", "selling_price",
                 "discount_percent", "pricing_mode", "image_url", "is_active"),
    "hsn": ("id", "code", "description", "gst_rate", "is_active"),
    "parties": ("id", "party_type", "legal_name", "nickname", "contact_person", "phone", "email",
                "address", "gst_number", "is_active"),
    "brands": ("id", "name", "description", "is_active"),
    "categories": ("id", "name", "description", "is_active"),
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
    "images": {"id": "Paste a record ID", "entity": "product", "image_file": "photo.png", "image_background": "#ffffff"},
}
INSTRUCTIONS = {
    "products": (
        "Products: name is required for new products. SKU and description are optional.",
        "brand and categories accept existing names or new names. brand_description is used only for a newly created brand.",
        "categories and labels use | between names. Avoid | in names; first category is the primary one.",
        "For a new HSN, supply hsn_code, hsn_description and gst_rate. GST-registered workspaces require an HSN for new products.",
        "vendor maps an existing vendor by name or creates a new vendor contact. It becomes the preferred vendor.",
        "image_background is a hex color such as #ffffff. Non-white requires a transparent image or AI segmentation.",
        "For product image files, upload a ZIP containing manifest.xlsx and images/<filename>; set image_file to the filename.",
        "pricing_mode is price or discount. selling_price and discount_percent must meet inventory pricing rules.",
    ),
    "variants": (
        "Variants: product_id is the owning product's ID. variant_name is required for new variants.",
        "A variant ID can only be updated under its own product. pricing_mode can be inherit, price or discount.",
    ),
    "hsn": (
        "HSN: code must contain 4, 6 or 8 digits. Supply description and GST rate from 0 to 100.",
        "Existing HSN codes cannot be renamed. Create a different code instead.",
    ),
    "parties": (
        "Contacts: party_type is customer, vendor, customer_vendor, friend, employee or other.",
        "legal_name and party_type are required for new contacts. Telephone numbers should be stored as text.",
    ),
    "brands": ("Brands: name is required. Existing records use their exported id.",),
    "categories": ("Categories: name is required. Existing records use their exported id.",),
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
}


def _write_cell(sheet, row, column, value):
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell


def workbook(kind: str, rows=(), lookups=None, *, reasons=False, notes=None) -> bytes:
    if kind not in FIELDS:
        raise HTTPException(422, "Unknown bulk workbook type.")
    lookups = lookups or {}
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    fields = (*FIELDS[kind], "failure_reason") if reasons else FIELDS[kind]
    for column, field in enumerate(fields, 1):
        _write_cell(sheet, 1, column, field).font = Font(bold=True)
    for number, row in enumerate(rows, 2):
        for column, field in enumerate(fields, 1):
            _write_cell(sheet, number, column, row.get(field))
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(fields))}{max(1, sheet.max_row)}"
    for column in range(1, len(fields) + 1):
        sheet.column_dimensions[get_column_letter(column)].width = 22

    readme = book.create_sheet("README")
    instructions = (
        "Tenali bulk workbook",
        f"Record type: {kind}. Only rows on the Data sheet are imported.",
        "Leave id empty to create; retain an exported id to update that record in this workspace.",
        "Downloaded existing rows are full records. Edit them and upload the workbook again.",
        "Blank cells on an existing row leave that field unchanged. Use <clear> to clear an optional field.",
        "Categories and labels are separated with |. The first category is the primary category.",
        "Type new brand, category or vendor names directly; new HSN codes require a description and GST rate.",
        "Use text for HSN codes and phone numbers to preserve leading zeroes.",
        "Image URLs must be public HTTPS links or existing Tenali image URLs. File images use the separate image workflow.",
        "After upload, successes and failures are separate workbooks. Correct failure_reason rows and upload again.",
        "Dropdown suggestions are refreshed whenever a workbook is downloaded; free text is allowed.",
        f"Maximum {MAX_ROWS} data rows per upload; maximum upload size is 10 MiB.",
        *INSTRUCTIONS[kind],
        "Each row is committed independently; a failure does not undo successful rows.",
        "Do not upload formulas. Use literal values; do not remove or rename the Data sheet.",
        "The sample below is illustrative and is not imported automatically.",
        "Sample row (copy values to Data to use):",
    )
    for number, line in enumerate(instructions, 1):
        _write_cell(readme, number, 1, line)
    if notes:
        _write_cell(readme, len(instructions) + 3, 1, "AI catalog notes (review against the source):")
        _write_cell(readme, len(instructions) + 4, 1, notes)
    readme.column_dimensions["A"].width = 110
    header_row = len(instructions) + 1
    for column, field in enumerate(FIELDS[kind], 1):
        _write_cell(readme, header_row, column, field).font = Font(bold=True)
        _write_cell(readme, header_row + 1, column, SAMPLES[kind].get(field))

    lists = book.create_sheet("Suggestions")
    lists.sheet_state = "hidden"
    for column, (key, values) in enumerate(lookups.items(), 1):
        if len(values) > MAX_LOOKUPS:
            raise HTTPException(422, f"Too many {key} suggestions to generate a workbook.")
        _write_cell(lists, 1, column, key)
        for row, value in enumerate(values, 2):
            _write_cell(lists, row, column, str(value))
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
            if any(cell.data_type == "f" for cell in cells):
                raise HTTPException(422, "Formulas are not supported in bulk workbooks; paste values instead.")
            values = {name: cell.value for name, cell in zip(names, cells) if name != "failure_reason"}
            if any(value is not None and value != "" for value in values.values()):
                rows.append(values)
        return rows
    except DefusedXmlException as error:
        raise HTTPException(422, "Workbook contains unsafe XML.") from error
    finally:
        book.close()
