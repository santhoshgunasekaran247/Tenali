"""Schema-driven, private workflow preparation. Only ExecutionService posts records."""
import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, ValidationError
from sqlalchemy import text

from app.ai.actions import ACTIONS, ActionKey, DraftCreate, DraftProposal
from app.ai.capabilities import available_capabilities, current_identity, execute_lookup
from app.ai.drafts import DraftService, available_actions, bounded_payload, digest, reject_extra_fields
from app.ai.schemas import BusinessLookupArguments, CATALOGUE_KEYS, LookupArguments, ReadLookup, business_today
from app.services.feature_controls import lock_policy
from app.schemas.money import Money

# capability, exact-match labels, identifier, prerequisite action, seed field
REFERENCES = {
    "store_id": ("stores", ("name", "code"), "id", None, None),
    "account_id": ("accounts", ("account_name",), "account_id", "account_create", "nickname"),
    "party_id": ("parties", ("legal_name", "nickname"), "id", "party_create", "legal_name"),
    "product_id": ("products", ("name", "sku"), "id", "product_create", "name"),
    "variant_id": ("variants", ("variant_name", "sku"), "id", "variant_create", "variant_name"),
    "brand_id": ("brands", ("name", "code"), "id", "brand_create", "name"),
    "category_id": ("categories", ("name", "code"), "id", "category_create", "name"),
    "invoice_id": ("invoices", ("invoice_number",), "id", None, None),
    "hsn": ("hsn", ("code",), "code", None, None),
}
for alias in ("stock_store_id", "from_store_id", "to_store_id"):
    REFERENCES[alias] = REFERENCES["store_id"]
for alias in ("from_account_id", "to_account_id"):
    REFERENCES[alias] = REFERENCES["account_id"]
for alias in ("vendor_party_id", "customer_party_id", "vendor_id", "preferred_vendor_id", "related_party_id"):
    REFERENCES[alias] = REFERENCES["party_id"]
REFERENCES["target_product_id"] = REFERENCES["product_id"]
REFERENCES["target_variant_id"] = REFERENCES["variant_id"]
REFERENCES["hsn_code"] = REFERENCES["hsn"]

TARGETS = {
    "parties": REFERENCES["party_id"], "products": REFERENCES["product_id"],
    "accounts": REFERENCES["account_id"], "brands": REFERENCES["brand_id"],
    "product_categories": REFERENCES["category_id"], "product_variants": REFERENCES["variant_id"],
    "vendor_contributions": ("vendor_offers", ("product_name",), "id", None, None),
    "purchases": ("purchases", ("voucher_number", "bill_number"), "id", None, None),
    "invoices": REFERENCES["invoice_id"],
    "receivables": ("receivables", ("party_name",), "id", None, None),
    "account_transactions": ("transactions", ("from_account_name", "to_account_name"), "id", None, None),
    "refund_settlements": ("refunds", ("document_number",), "id", None, None),
    "stock_transfers": ("stock_transfers", ("reference",), "id", None, None),
    "stock_movements": ("stock_movements", ("product_name",), "id", None, None),
}
REPLACEMENTS = {"product_update", "variant_update", "offer_update", "brand_update", "category_update"}
EXPLICIT = {
    "purchase_create": ("store_id", "purchase_date", "received_now", "amount_paid", "lines"),
    "invoice_create": ("store_id", "invoice_date", "amount_received", "lines", "billing_address", "place_of_supply"),
    "stock_adjust": ("store_id",),
    "stock_transfer": ("transfer_date",),
    "purchase_payment": ("payment_date",),
    "collection_payment": ("payment_date",),
    "expense_create": ("transaction_date", "payment_mode", "create_borrowing"),
}
MANUAL = {"stores": "/portal/stores", "hsn": "/portal/masters", "products": "/portal/inventory"}
MAX_STEPS = 30
GST_STATES = (
    "01 - Jammu and Kashmir", "02 - Himachal Pradesh", "03 - Punjab", "04 - Chandigarh", "05 - Uttarakhand",
    "06 - Haryana", "07 - Delhi", "08 - Rajasthan", "09 - Uttar Pradesh", "10 - Bihar", "11 - Sikkim",
    "12 - Arunachal Pradesh", "13 - Nagaland", "14 - Manipur", "15 - Mizoram", "16 - Tripura", "17 - Meghalaya",
    "18 - Assam", "19 - West Bengal", "20 - Jharkhand", "21 - Odisha", "22 - Chhattisgarh", "23 - Madhya Pradesh",
    "24 - Gujarat", "26 - Dadra and Nagar Haveli and Daman and Diu", "27 - Maharashtra", "29 - Karnataka",
    "30 - Goa", "31 - Lakshadweep", "32 - Kerala", "33 - Tamil Nadu", "34 - Puducherry",
    "35 - Andaman and Nicobar Islands", "36 - Telangana", "37 - Andhra Pradesh", "38 - Ladakh",
)
# Workflow dropdowns: stored value -> label. Free text must resolve to one of these values.
CHOICES = {
    "receipt_type": {"PRODUCT": "Products", "STOCK": "Stock items", "SERVICE": "Service (no stock)"},
    "payment_mode": {"cash": "Cash", "bank": "Bank transfer", "upi": "UPI", "card": "Card", "cheque": "Cheque", "other": "Other"},
    "place_of_supply": {state: state for state in GST_STATES},
    # Same values/labels as the Parties page; PartiesService.ALLOWED_PARTY_TYPES remains the authority.
    "party_type": {"customer": "Customer", "vendor": "Vendor", "customer_vendor": "Customer + Vendor",
                   "employee": "Employee", "friend": "Friend", "other": "Other"},
}
# Plain-language labels for fields whose schema already restricts the values.
ENUM_LABELS = {
    ("borrowing_create", "direction"): {"borrow": "Borrowed from them (money in)", "repay": "Repaid to them (money out)",
                                         "lend": "Lent to them (money out)", "collect": "Collected back from them (money in)"},
}
CHOICE_ALIASES = {
    "party_type": {"supplier": "vendor", "seller": "vendor", "client": "customer", "buyer": "customer",
                   "both": "customer_vendor", "customer and vendor": "customer_vendor", "customer vendor": "customer_vendor",
                   "customer/vendor": "customer_vendor", "staff": "employee"},
    "receipt_type": {"goods": "PRODUCT", "product": "PRODUCT", "stock": "STOCK", "service": "SERVICE", "services": "SERVICE"},
    "payment_mode": {"bank": "bank", "neft": "bank", "imps": "bank", "rtgs": "bank", "transfer": "bank", "bank transfer": "bank",
                     "gpay": "upi", "google pay": "upi", "phonepe": "upi", "paytm": "upi", "credit card": "card",
                     "debit card": "card", "check": "cheque"},
}
BOOLEAN_WORDS = {"yes": True, "y": True, "true": True, "no": False, "n": False, "false": False}
DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %m %Y",
                "%b %d %Y", "%B %d %Y", "%m %d %Y")


def choice_value(field, value):
    text = " ".join(str(value).replace(",", " ").split()).casefold()
    if field == "place_of_supply":
        match = re.match(r"^(\d{1,2})(?:\b|$)", text)
        if match:
            code = match.group(1).zfill(2)
            return next((state for state in GST_STATES if state[:2] == code), None)
        return next((state for state in GST_STATES if state[5:].casefold() == text), None)
    for candidate in dict.fromkeys((text, text.replace("_", " "), text[:-1] if text.endswith("s") else text)):
        for key, label in CHOICES[field].items():
            if candidate in {key.casefold(), key.replace("_", " ").casefold(), label.casefold()}:
                return key
        alias = CHOICE_ALIASES.get(field, {}).get(candidate)
        if alias:
            return alias
    return None


def normalize_choices(payload, issues):
    def walk(values, prefix):
        if isinstance(values, list):
            for index, child in enumerate(values):
                walk(child, f"{prefix}{index}.")
            return
        if not isinstance(values, dict):
            return
        for key, value in list(values.items()):
            if key in CHOICES and isinstance(value, str) and value.strip():
                canonical = choice_value(key, value)
                if canonical:
                    values[key] = canonical
                else:
                    values.pop(key)
                    issues.append({"field": prefix + key, "message": f'"{value.strip()[:40]}" is not an option. Choose from the list.'})
            elif isinstance(value, (dict, list)):
                walk(value, f"{prefix}{key}.")
    walk(payload, "")


def coerce_scalar(value, kinds):
    text = value.strip()
    types = {kind.get("type") for kind in kinds}
    if "boolean" in types and "string" not in types:
        return BOOLEAN_WORDS.get(text.casefold(), value)
    if any(kind.get("format") == "date" for kind in kinds):
        words = " ".join(text.replace(",", " ").split())
        if words.casefold() in {"today", "yesterday"}:
            return (datetime.now().date() - timedelta(days=1 if words.casefold() == "yesterday" else 0)).isoformat()
        for pattern in DATE_FORMATS:
            try:
                return datetime.strptime(words, pattern).date().isoformat()
            except ValueError:
                continue
        return value
    if types & {"number", "integer"}:
        cleaned = re.sub(r"(?i)^(?:rs\.?|inr|₹)\s*|\s*(?:%|/-|rs\.?|rupees)$", "", text).replace(",", "").strip()
        try:
            number = Decimal(cleaned)
        except ArithmeticError:
            return value
        if not number.is_finite():
            return value
        if "integer" in types and number == number.to_integral_value():
            return int(number)
        return cleaned if "string" in types else float(number)
    return value


def coerce_payload(action, payload):
    """Convert chat-style answers ("5%", "yes", "11 Nov 2026") into the schema's scalar types."""
    schema = workflow_schema(action)
    definitions = schema.get("$defs", {})

    def variants(node):
        if "$ref" in node:
            node = definitions.get(node["$ref"].split("/")[-1], {})
        if "anyOf" in node:
            return [variant for child in node["anyOf"] for variant in variants(child)]
        return [node]

    def walk(values, node):
        objects = [variant for variant in variants(node) if variant.get("properties")]
        if not isinstance(values, dict) or not objects:
            return
        properties = objects[0]["properties"]
        for key, value in list(values.items()):
            if key not in properties or key in REFERENCES:
                continue
            kinds = variants(properties[key])
            if isinstance(value, dict):
                walk(value, properties[key])
            elif isinstance(value, list):
                item = next((kind.get("items") for kind in kinds if kind.get("type") == "array" and kind.get("items")), None)
                for child in value if item else ():
                    walk(child, item)
            elif isinstance(value, str) and key not in CHOICES:
                values[key] = coerce_scalar(value, kinds)

    walk(payload, schema)
    return payload


def workflow_schema(action):
    schema = deepcopy(ACTIONS[action].schema.model_json_schema())
    if action in {"purchase_create", "invoice_create"}:
        schema["properties"]["fully_paid"] = {"type": "boolean", "title": "Fully paid now"}
    if action == "purchase_create":
        schema["$defs"]["InvoiceLineCreate"]["properties"]["selling_price"] = {
            **TypeAdapter(Money | None).json_schema(), "title": "Selling price for a new product"}
    for definition in [schema, *schema.get("$defs", {}).values()]:
        for key, field in definition.get("properties", {}).items():
            if key in REFERENCES:
                field["x-workflow-reference"] = True
            elif key == "product_ids":
                field["items"]["x-workflow-reference"] = True
            elif key in CHOICES and "enum" not in field:
                definition["properties"][key] = {"type": "string", "title": field.get("title", key),
                                                 "enum": list(CHOICES[key]), "x-enum-labels": CHOICES[key]}
            elif (action, key) in ENUM_LABELS and "enum" in field:
                field["x-enum-labels"] = ENUM_LABELS[action, key]
    return schema


def search_reference(action, field):
    if field == "target":
        spec = TARGETS.get(ACTIONS[action].target)
        if spec:
            return spec
        raise HTTPException(422, "This operation does not have a searchable target.")
    schema = workflow_schema(action)
    current = schema
    for key in field.split("."):
        if "$ref" in current:
            current = schema.get("$defs", {}).get(current["$ref"].split("/")[-1], {})
        if "anyOf" in current:
            current = next((child for child in current["anyOf"] if child.get("type") != "null"), {})
        current = current.get("items", {}) if key.isdigit() else current.get("properties", {}).get(key, {})
    if not current.get("x-workflow-reference"):
        raise HTTPException(422, "This field is not a searchable record reference.")
    spec = REFERENCES["product_id"] if field.split(".")[-1].isdigit() else REFERENCES[field.split(".")[-1]]
    return reference_spec(action, spec)


def reference_spec(action, spec):
    if action == "invoice_create" and spec[0] == "products":
        return (*spec[:3], None, None)
    return spec


def record_options(rows, spec):
    return [{"value": str(row[spec[2]]), "label": " · ".join(str(row[key]) for key in dict.fromkeys(
        (*spec[1], "product_name", "party_name", "vendor_name", "purchase_date", "invoice_date",
         "transaction_date", "due_date", "transfer_date", "from_store_code", "to_store_code",
         "total", "amount", "amount_due", "balance_amount", "gst_number", "status",
         "variant_name", "sku", "vendor_reference", "buying_price")) if row.get(key) is not None)}
        for row in rows if row.get(spec[2])]


def normalize_purchase_proposal(payload):
    return normalize_document_proposal("purchase_create", payload)


def normalize_document_proposal(action, payload):
    bounded_payload(payload)
    normalized = deepcopy(payload)
    for key, field in ACTIONS[action].schema.model_fields.items():
        if (key not in {"idempotency_key", "attachments"} and key in normalized and normalized[key] is None
                and not field.is_required() and field.default is not None):
            normalized.pop(key)
    for line in normalized.get("lines") or []:
        if not isinstance(line, dict):
            continue
        for alias, field in (("item_name", "description"), ("unit_cost", "rate"),
                             ("unit_price", "rate"), ("gst_inclusive", "price_includes_gst")):
            if alias in line:
                if field in line and line[field] != line[alias]:
                    raise HTTPException(422, f"Conflicting document-line fields: {alias} and {field}.")
                line[field] = line.pop(alias)
        if line.get("new_product") is None:
            line.pop("new_product", None)
        if normalized.get("receipt_type", "PRODUCT") != "SERVICE" and not line.get("product_id") and line.get("description"):
            line["product_id"] = line["description"]
        if line.get("product_id") and line.get("new_product"):
            line["new_product"] = False
    return normalized


def business_payload(action, payload):
    values = deepcopy(payload)
    if action in {"purchase_create", "invoice_create"}:
        values.pop("fully_paid", None)
    if action == "purchase_create":
        for line in values.get("lines") or []:
            if isinstance(line, dict):
                line.pop("selling_price", None)
    return values


def validate_workflow_payload(action, payload):
    bounded_payload(payload)
    reject_extra_fields(ACTIONS[action].schema, business_payload(action, payload))
    if action in {"purchase_create", "invoice_create"}:
        try:
            if payload.get("fully_paid") is not None:
                TypeAdapter(StrictBool).validate_python(payload["fully_paid"])
            for line in payload.get("lines") or []:
                if isinstance(line, dict) and line.get("selling_price") is not None:
                    TypeAdapter(Money).validate_python(line["selling_price"])
        except ValidationError as error:
            raise HTTPException(422, "Document workflow needs a boolean fully_paid and a non-negative, finite selling price with at most two decimals.") from error


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: ActionKey
    target: str | None = Field(default=None, max_length=200)
    payload: dict = Field(default_factory=dict)
    client_key: UUID


class WorkflowEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    step_id: UUID
    target: str | None = Field(default=None, max_length=200)
    payload: dict
    create_field: str | None = Field(default=None, max_length=200)
    draft_version: int | None = Field(default=None, ge=1)
    selection_field: str | None = Field(default=None, max_length=160)
    selection_query: str | None = Field(default=None, min_length=2, max_length=80)


def uuid_value(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def normalize(value):
    return " ".join(str(value or "").split()).casefold()


def step(action, payload, target=None, **extra):
    return {"id": str(uuid4()), "action": action, "target": str(target) if target and ACTIONS[action].target else None,
            "payload": payload, "bindings": {}, "labels": {}, "draft_id": None, "issues": [], "choices": [], **extra}


def reset_review(item, steps):
    previous = item["id"]
    item["id"], item["draft_id"], item["draft_status"] = str(uuid4()), None, None
    for parent in steps:
        for binding in parent["bindings"].values():
            if binding["step_id"] == previous:
                binding["step_id"] = item["id"]
        for key, step_id in parent.get("offer_steps", {}).items():
            if step_id == previous:
                parent["offer_steps"][key] = item["id"]


def reference_fields(payload, prefix=()):
    for key, value in payload.items():
        path = (*prefix, key)
        if key in REFERENCES and value not in (None, ""):
            yield path, value, REFERENCES[key]
        elif key == "product_ids" and isinstance(value, list):
            for index, item in enumerate(value):
                yield (*path, index), item, REFERENCES["product_id"]
        elif isinstance(value, dict):
            yield from reference_fields(value, path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    yield from reference_fields(item, (*path, index))


def set_path(payload, path, value):
    current = payload
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


def preserve_bindings(item, payload):
    if item.get("offer_steps"):
        vendor = uuid_value(payload.get("vendor_party_id"))
        keys = {f"{uuid_value(line.get('product_id'))}:{uuid_value(line.get('variant_id')) or ''}:{vendor}"
                for line in payload.get("lines") or [] if isinstance(line, dict)}
        if not set(item["offer_steps"]) <= keys:
            raise HTTPException(409, "A vendor offer is already linked. Discard this workflow before replacing its vendor or products.")
    for location, binding in item["bindings"].items():
        old, new = item["payload"], payload
        try:
            for key in binding["path"]:
                old, new = old[key], new[key]
        except (KeyError, IndexError, TypeError):
            raise HTTPException(409, "Keep prerequisite fields and document lines until their steps are complete.") from None
        label = item["labels"].get(location, {}).get("label")
        if new != old and (not label or normalize(new) != normalize(label)):
            raise HTTPException(409, "A prerequisite is already linked. Discard this workflow before replacing that prerequisite.")
        set_path(payload, binding["path"], old)


def required_fields(action, payload):
    required = list(EXPLICIT.get(action, ()))
    if action in {"purchase_create", "invoice_create"} and payload.get("fully_paid") is True:
        required = [key for key in required if key != ("amount_paid" if action == "purchase_create" else "amount_received")]
        required += ["account_id", "payment_mode"]
    if action in {"product_create", "product_update"} and payload.get("pricing_mode", "price") == "price":
        required += ["selling_price"]
    if action == "borrowing_create" and payload.get("create_account_transaction"):
        required += ["account_id"]
    if action in {"expense_create", "business_payment_create"} and payload.get("purpose") in {"purchase", "billing"}:
        required += ["related_party_id"]
    if action == "account_transaction_create" and not payload.get("from_account_id") and not payload.get("to_account_id"):
        required += ["from_account_id", "to_account_id"]
    if action == "receivable_status" and payload.get("status") == "BAD_DEBT":
        required += ["bad_debt_reason"]
    if action == "report_export":
        required += ["as_of"] if payload.get("kind") in {"ar_aging", "ap_aging"} else ["from_date", "to_date"]
    if action == "purchase_bundle_create":
        required += ["vendor_name", "product_name", "quantity", "rate", "hsn", "gst_rate",
                     "price_includes_gst", "purchase_date", "fully_paid", "received_now"]
        required += ["store_name"] if not payload.get("store_id") else []
        if payload.get("fully_paid"):
            required += ["payment_mode"]
            required += ["account_name"] if not payload.get("account_id") else []
    if action in {"purchase_create", "invoice_create"}:
        amount = payload.get("amount_paid" if action == "purchase_create" else "amount_received")
        try:
            paid = amount is not None and Decimal(str(amount)) > 0
        except ArithmeticError:
            paid = False
        if paid:
            required += ["account_id", "payment_mode"]
        for index, line in enumerate(payload.get("lines") or []):
            if isinstance(line, dict):
                required += [f"lines.{index}.{key}" for key in ("gst_rate", "price_includes_gst")]
    return list(dict.fromkeys(required))


def workflow_view(row):
    row = dict(row)
    row["plan"] = deepcopy(row["plan"])
    for item in row["plan"].get("steps", []):
        item["required_fields"] = required_fields(item["action"], item["payload"])
    root = next(iter(row["plan"].get("steps", [])), None)
    if root:
        row["operation_summary"] = ACTIONS[root["action"]].description
    return row


def missing_fields(action, payload):
    issues = []
    if action in {"party_update", "account_update"} and not payload:
        issues.append({"field": "", "message": "Enter at least one changed field."})
    for key in required_fields(action, payload):
        value = payload
        try:
            for part in key.split("."):
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError):
            value = None
        if value not in (None, "", []):
            continue
        issues.append({"field": key, "message": "Required: choose or enter this value."})
    supplied = business_payload(action, payload)
    schema = ACTIONS[action].schema
    if "idempotency_key" in schema.model_fields:
        supplied["idempotency_key"] = "workflow-validation"
    try:
        schema.model_validate(supplied)
    except ValidationError as error:
        issues += [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                   for item in error.errors(include_context=False, include_input=False)]
    unique = {}
    for item in issues:
        unique.setdefault(item["field"] or item["message"], item)
    return list(unique.values())


def keep_line_products(current, incoming):
    """A follow-up line description is text, not a new product, once the workflow line already names one."""
    for old, new in zip(current.get("lines") or [], incoming.get("lines") or []):
        if (isinstance(old, dict) and isinstance(new, dict) and old.get("product_id")
                and new.get("product_id") and new.get("product_id") == new.get("description")):
            new.pop("product_id")


def merge_known(current, incoming):
    merged = deepcopy(current)
    for key, value in incoming.items():
        if value is None or value == "":
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_known(merged[key], value)
        elif isinstance(value, list) and isinstance(merged.get(key), list) and len(value) == len(merged[key]):
            merged[key] = [merge_known(old, new) if isinstance(old, dict) and isinstance(new, dict) else new
                           for old, new in zip(merged[key], value)]
        else:
            merged[key] = value
    return merged


def next_entries(action, payload, result):
    entries = []
    record_id = str(result["id"]) if result.get("id") else None
    if action in {"purchase_create", "purchase_bundle_create"} and record_id:
        received = payload.get("received_now")
        if not received:
            entries.append({"action": "purchase_receive", "target": record_id, "payload": {},
                            "label": "Record goods receipt?"})
        paid = payload.get("fully_paid") if action == "purchase_bundle_create" else (
            Decimal(str(payload.get("amount_paid", 0))) >= Decimal(str(result.get("total", 0))))
        if not paid:
            entries.append({"action": "purchase_payment", "target": record_id, "payload": {},
                            "label": "Record vendor payment?"})
    if action == "invoice_create" and record_id and (
            Decimal(str(result.get("amount_received", 0))) < Decimal(str(result.get("total", 0)))):
        entries.append({"action": "collection_payment", "target": None, "payload": {},
                        "label": "Review collections?", "path": "/portal/receivables"})
    if action in {"product_create", "product_update", "product_confirm", "purchase_receive"}:
        entries.append({"action": "offer_create", "target": None,
                        "payload": {"product_id": record_id} if action.startswith("product_") and record_id else {},
                        "label": "Add a vendor offer?"})
    entries.append({"action": action, "target": None, "payload": {},
                    "label": "Start another " + action.replace("_", " ") + "?"})
    return entries


class WorkflowService:
    def __init__(self, assistant):
        self.assistant = assistant
        self.db = assistant.db
        self.scope = assistant.scope
        self.drafts = DraftService(assistant)

    def policies(self):
        lock_policy(self.db)
        self.assistant.require_enabled()
        self.assistant.identity = current_identity(self.db, self.assistant.identity)
        self.actions = {item["key"] for item in available_actions(self.db, self.assistant.identity)}
        self.capabilities = {item["key"] for item in available_capabilities(self.db, self.assistant.identity)}
        self.cache = {}

    def get(self, workflow_id):
        row = self.db.execute(text("""select * from ai_operation_workflows where id=:id
            and company_id=:company and user_id=:user and status<>'discarded' and expires_at>now()"""),
            {**self.scope, "id": str(workflow_id)}).mappings().first()
        if not row:
            raise HTTPException(404, "Workflow not found")
        self.assistant.conversation(row["conversation_id"])
        return workflow_view(row)

    def list(self, conversation_id, offset=0):
        self.assistant.conversation(conversation_id)
        rows = self.db.execute(text("""select * from ai_operation_workflows where conversation_id=:id
            and company_id=:company and user_id=:user and status<>'discarded' and expires_at>now()
            order by created_at desc,id limit 30 offset :offset"""),
            {**self.scope, "id": str(conversation_id), "offset": offset}).mappings()
        return {"items": [workflow_view(row) for row in rows]}

    def search(self, workflow_id, step_id, field, query):
        row = self.get(workflow_id)
        if row["status"] != "active":
            raise HTTPException(409, "This workflow is completed.")
        item = next((item for item in row["plan"]["steps"] if item["id"] == str(step_id)), None)
        if not item:
            raise HTTPException(404, "Workflow step not found")
        self.policies()
        if item["action"] not in self.actions:
            raise HTTPException(403, "This Operations workflow is not permitted.")
        return self.search_choices(item["action"], field, query)

    def search_choices(self, action, field, query):
        spec = search_reference(action, field)
        result = self.lookup(spec, query.strip())
        return {"field": field, "query": query.strip(), "capability": spec[0],
                "options": record_options(result["items"], spec), "more_matches": result["more_matches"],
                "can_create": field != "target" and not result["more_matches"] and spec[3] in self.actions,
                "manual_path": MANUAL.get(spec[0])}

    def save(self, row):
        encoded = json.dumps(jsonable_encoder(row["plan"]))
        if len(encoded.encode()) > 180000:
            raise HTTPException(422, "Workflow is too large. Split this operation into smaller entries.")
        changed = self.db.execute(text("""update ai_operation_workflows set plan=cast(:plan as jsonb),
            status=:status,version=version+1,updated_at=now() where id=:id and company_id=:company
            and user_id=:user and version=:version returning *"""),
            {**self.scope, "id": str(row["id"]), "plan": encoded, "status": row["status"],
             "version": row["version"]}).mappings().first()
        if not changed:
            raise HTTPException(409, "Workflow changed. Refresh before continuing.")
        return workflow_view(changed)

    def create(self, conversation_id, payload: WorkflowCreate, *, commit=True):
        self.assistant.lock_conversation(conversation_id)
        conversation = self.assistant.conversation(conversation_id)
        if conversation["status"] != "active":
            raise HTTPException(409, "Restore the conversation before starting a workflow.")
        self.policies()
        if payload.action not in self.actions:
            raise HTTPException(403, "This Operations workflow is not permitted.")
        if payload.action in {"purchase_create", "invoice_create"}:
            payload = payload.model_copy(update={"payload": normalize_document_proposal(payload.action, payload.payload)})
        validate_workflow_payload(payload.action, payload.payload)
        old = self.db.execute(text("""select * from ai_operation_workflows where company_id=:company
            and user_id=:user and conversation_id=:id and client_key=:key"""),
            {**self.scope, "id": str(conversation_id), "key": payload.client_key}).mappings().first()
        request_hash = digest({"action": payload.action, "target": payload.target, "payload": payload.payload})
        if old:
            if old["request_hash"] != request_hash:
                raise HTTPException(409, "Workflow reference was already used with different values.")
            return self.get(old["id"])
        plan = {"steps": [step(payload.action, payload.payload, payload.target)], "next": []}
        row = self.db.execute(text("""insert into ai_operation_workflows(company_id,user_id,conversation_id,
            client_key,action_key,request_hash,plan,expires_at) values(:company,:user,:conversation,:key,:action,
            :hash,cast(:plan as jsonb),:expires) returning *"""),
            {**self.scope, "conversation": str(conversation_id), "key": payload.client_key,
             "action": payload.action, "hash": request_hash, "plan": json.dumps(plan),
             "expires": min(conversation["expires_at"], datetime.now(timezone.utc) + timedelta(days=7))}).mappings().one()
        prepared = self.prepare(dict(row))
        saved = self.save(prepared)
        self.assistant.audit(conversation_id, "OPERATION_WORKFLOW_CREATED", payload.client_key)
        if commit:
            self.db.commit()
        return saved

    def from_proposal(self, conversation_id, proposal: DraftProposal, client_key):
        self.assistant.lock_conversation(conversation_id)
        values = json.loads(proposal.payload_json)
        if not isinstance(values, dict):
            raise HTTPException(422, "The workflow proposal must be a JSON object.")
        if proposal.action in {"purchase_create", "invoice_create"}:
            values = normalize_document_proposal(proposal.action, values)
        coerce_payload(proposal.action, values)
        if "workflow_id" in proposal.model_fields_set:
            if proposal.workflow_id is None:
                return self.create(conversation_id, WorkflowCreate(action=proposal.action,
                    target=str(proposal.target_id) if proposal.target_id else None,
                    payload=values, client_key=client_key), commit=False)
            existing = self.get(proposal.workflow_id)
            if (str(existing["conversation_id"]) != str(conversation_id) or
                    not any(item["action"] == proposal.action for item in existing["plan"]["steps"])):
                raise HTTPException(404, "Workflow not found for this conversation and action.")
            if existing["status"] != "active":
                raise HTTPException(409, "This workflow is completed. Explicitly start a new entry instead.")
            active = [existing]
        else:
            # Older clients omit workflow_id; resume only an unambiguous active action.
            active = self.db.execute(text("""select * from ai_operation_workflows where company_id=:company
                and user_id=:user and conversation_id=:id and action_key=:action
                and status='active' and expires_at>now() order by created_at desc limit 30"""),
                {**self.scope, "id": str(conversation_id), "action": proposal.action}).mappings().all()
        matches = [dict(row) for row in active if
                   (proposal.workflow_id is not None or not proposal.target_id or not row["plan"]["steps"][0]["target"] or
                    normalize(row["plan"]["steps"][0]["target"]) == normalize(proposal.target_id))]
        if len(matches) == 1:
            row = matches[0]
            row["plan"] = deepcopy(row["plan"])
            candidates = [item for item in row["plan"]["steps"] if item["action"] == proposal.action
                          and item.get("draft_status") != "executed"]
            if len(candidates) != 1:
                raise HTTPException(409, "Select the intended prerequisite in Operations; this action has multiple or completed steps.")
            root = candidates[0]
            if (proposal.target_id and root["target"] and
                    normalize(proposal.target_id) not in {normalize(root["target"]), normalize(root["labels"].get("target", {}).get("label"))}):
                raise HTTPException(409, "Start a new workflow to change a different target record.")
            self.policies()
            if proposal.action not in self.actions:
                raise HTTPException(403, "This Operations workflow is not permitted.")
            keep_line_products(root["payload"], values)
            if root.get("draft_id"):
                draft = self.drafts.get(root["draft_id"])
                if draft["status"] == "executed":
                    return self.save(self.prepare(row))
                merged = merge_known(merge_known(root["payload"], draft["payload"]), values)
                preserve_bindings(root, merged)
                validate_workflow_payload(proposal.action, merged)
                if merged != draft["payload"]:
                    # Return to workflow preparation when new text introduces names or missing prerequisites.
                    draft = self.drafts.lock(draft["id"], draft["version"])
                    self.db.execute(text("""update ai_action_drafts set status='discarded',payload='{}',validation=null,
                        approved_at=null,approved_version=null,version=version+1 where id=:id
                        and company_id=:company and user_id=:user"""), {**self.scope, "id": draft["id"]})
                    root["payload"] = merged
                    reset_review(root, row["plan"]["steps"])
                    self.assistant.audit(conversation_id, "WORKFLOW_REVIEW_INVALIDATED", client_key)
                return self.save(self.prepare(row))
            merged = merge_known(root["payload"], values)
            preserve_bindings(root, merged)
            root["payload"] = merged
            if proposal.target_id and not root["target"]:
                root["target"] = str(proposal.target_id)
            validate_workflow_payload(proposal.action, root["payload"])
            return self.save(self.prepare(row))
        if matches:
            raise HTTPException(409, "Multiple workflows are waiting. Continue the intended workflow in Operations.")
        return self.create(conversation_id, WorkflowCreate(action=proposal.action,
            target=str(proposal.target_id) if proposal.target_id else None,
            payload=values, client_key=client_key), commit=False)

    def lookup(self, spec, query):
        capability = spec[0]
        if capability not in self.capabilities:
            raise HTTPException(403, "Search is unavailable for " + capability + ". Ask an administrator to enable it.")
        key = (capability, normalize(query))
        if key not in self.cache:
            if not 2 <= len(query) <= 80:
                raise HTTPException(422, "Search needs 2 to 80 characters; narrow this name.")
            if len(self.cache) >= 24:
                raise HTTPException(422, "Search limit reached for this pass. Continue to resolve the remaining references.")
            args = {"query": query, "store_id": None, "limit": 10}
            arguments = LookupArguments(**args) if capability in CATALOGUE_KEYS else BusinessLookupArguments(
                **args, from_date=None, to_date=None, as_of=None, status=None)
            self.cache[key] = execute_lookup(self.db, self.assistant.identity,
                                            ReadLookup(capability=capability, arguments=arguments))
        return self.cache[key]

    def resolve(self, item, path, value, spec, steps, *, target=False, force_create=False):
        spec = reference_spec(item["action"], spec)
        if uuid_value(value) and spec[0] != "hsn":
            return uuid_value(value)
        location = ".".join(map(str, path))
        try:
            result = self.lookup(spec, str(value).strip())
        except HTTPException as error:
            if error.status_code not in {403, 422}:
                raise
            item["issues"].append({"field": location, "message": str(error.detail)})
            return value
        rows = result["items"]
        # A vendor/customer mismatch must never silently select or create another party.
        exact = [row for row in rows if any(normalize(row.get(key)) == normalize(value) for key in spec[1])]
        identifiers = {str(row[spec[2]]) for row in exact if row.get(spec[2])}
        if len(identifiers) == 1 and not result["more_matches"]:
            identifier = identifiers.pop()
            if spec[0] == "parties":
                expected = "vendor" if path[-1] in {"vendor_party_id", "vendor_id", "preferred_vendor_id"} else (
                    "customer" if path[-1] == "customer_party_id" else None)
                if expected and exact[0].get("party_type") not in {expected, "customer_vendor"}:
                    item["issues"].append({"field": location,
                        "message": f"The existing party is not a {expected}. Update its type in Parties, then continue."})
                    return value
            if spec[0] == "hsn" and item["action"] in {"purchase_create", "invoice_create"} and path[0] == "lines":
                line = item["payload"]["lines"][path[1]]
                if line.get("gst_rate") is None and exact[0].get("gst_rate") is not None:
                    line["gst_rate"] = exact[0]["gst_rate"]
            item["labels"][location] = {"value": identifier, "label": str(value)}
            return identifier
        if (not rows or force_create) and not result["more_matches"] and not target and spec[3] in self.actions:
            if len(steps) >= MAX_STEPS:
                item["issues"].append({"field": location, "message": "Too many prerequisites; split this entry."})
                return value
            seed = {spec[4]: value}
            container = item["payload"]
            for key in path[:-1]:
                container = container[key]
            if spec[0] == "products" and isinstance(container, dict) and container.get("hsn"):
                seed["hsn_code"] = container["hsn"]
            if spec[0] == "products" and isinstance(container, dict) and container.get("selling_price") is not None:
                seed["selling_price"] = container["selling_price"]
            if spec[0] == "variants" and isinstance(container, dict) and container.get("product_id"):
                seed["product_id"] = container["product_id"]
            if spec[0] == "parties":
                if path[-1] in {"vendor_party_id", "vendor_id", "preferred_vendor_id"}:
                    seed["party_type"] = "vendor"
                elif path[-1] == "customer_party_id":
                    seed["party_type"] = "customer"
            shared = next((child for child in steps if child["action"] == spec[3] and
                           normalize(child["payload"].get(spec[4])) == normalize(value) and
                           (spec[0] != "variants" or child["payload"].get("product_id") == seed.get("product_id"))), None)
            child = shared or step(spec[3], seed)
            if not shared:
                steps.append(child)
            item["bindings"][location] = {"step_id": child["id"], "path": list(path)}
            return value
        item["choices"].append({"field": location, "query": value, "capability": spec[0],
            "options": record_options(rows, spec), "more_matches": result["more_matches"],
            "can_create": not target and not result["more_matches"] and spec[3] in self.actions,
            "manual_path": MANUAL.get(spec[0])})
        item["issues"].append({"field": location, "message":
            "Select a match or narrow the search." if rows else
            "No match. Create this prerequisite in its module, or enable its AI create action, then search again."})
        return value

    def document_products(self, item):
        if "product_details" not in self.capabilities:
            return
        for index, line in enumerate(item["payload"].get("lines") or []):
            if not isinstance(line, dict) or not uuid_value(line.get("product_id")):
                continue
            if line.get("description") and line.get("hsn"):
                continue
            try:
                result = self.lookup(("product_details", (), "id", None, None), str(line["product_id"]))
            except HTTPException as error:
                if error.status_code not in {403, 422}:
                    raise
                item["issues"].append({"field": f"lines.{index}.product_id", "message": str(error.detail)})
                continue
            product = next((product for product in result["items"] if uuid_value(product.get("id")) == uuid_value(line["product_id"])), None)
            if product:
                for field, source in (("description", "name"), ("hsn", "hsn_code")):
                    if not line.get(field) and product.get(source):
                        line[field] = product[source]

    def document_estimate(self, item):
        """Show totals and stock effects as soon as lines are priced; review recomputes them authoritatively."""
        from app.services.financial_amounts import line_amounts
        action, payload = item["action"], item["payload"]
        company = self.db.execute(text("select gst_registered,prices_include_gst from companies where id=:company"),
                                  self.scope).mappings().one()
        lines, subtotal, gst_total = [], Decimal("0"), Decimal("0")
        for index, line in enumerate(payload.get("lines") or []):
            if not isinstance(line, dict):
                return None
            inclusive = line.get("price_includes_gst")
            if inclusive is None and action == "invoice_create":
                inclusive = bool(company["prices_include_gst"])
            try:
                quantity, rate = Decimal(str(line["quantity"])), Decimal(str(line["rate"]))
                gst_rate = Decimal(str(line["gst_rate"])) if action == "purchase_create" or company["gst_registered"] else Decimal("0")
            except (KeyError, ArithmeticError, TypeError):
                return None
            if inclusive is None or not all(value.is_finite() for value in (quantity, rate, gst_rate)):
                return None
            taxable, gst = line_amounts(quantity, rate, gst_rate, bool(inclusive))
            subtotal, gst_total = subtotal + taxable, gst_total + gst
            label = item["labels"].get(f"lines.{index}.product_id", {}).get("label") or line.get("description")
            lines.append({"description": label or f"Line {index + 1}", "quantity": str(quantity), "rate": str(rate),
                          "gst_rate": str(gst_rate), "price_includes_gst": bool(inclusive),
                          "taxable": str(taxable), "gst": str(gst), "total": str(taxable + gst)})
        if not lines:
            return None
        estimate = {"subtotal": str(subtotal), "gst_total": str(gst_total), "total": str(subtotal + gst_total), "lines": lines}
        store = uuid_value(payload.get("stock_store_id")) or uuid_value(payload.get("store_id"))
        books_stock = action == "invoice_create" or (payload.get("received_now") is True and payload.get("receipt_type", "PRODUCT") != "SERVICE")
        if store and books_stock:
            row = self.db.execute(text("select name,fulfilment_store_id from stores where id=:id and company_id=:company"),
                                  {**self.scope, "id": store}).mappings().first()
            if row and action == "invoice_create" and not payload.get("stock_store_id") and row["fulfilment_store_id"]:
                store = str(row["fulfilment_store_id"])
                row = self.db.execute(text("select name,fulfilment_store_id from stores where id=:id and company_id=:company"),
                                      {**self.scope, "id": store}).mappings().first()
            stock = []
            for index, line in enumerate(payload.get("lines") or []):
                product = uuid_value(line.get("product_id"))
                if not product or not row:
                    continue
                current = self.db.execute(text("""select coalesce(sum(quantity),0) from stock_balances where company_id=:company
                    and store_id=:store and product_id=:product and variant_id is not distinct from cast(:variant as uuid)"""),
                    {**self.scope, "store": store, "product": product, "variant": uuid_value(line.get("variant_id"))}).scalar_one()
                change = Decimal(str(line["quantity"])) * (-1 if action == "invoice_create" else 1)
                stock.append({"product": lines[index]["description"], "store": row["name"], "current": str(current),
                              "change": str(change), "after": str(current + change)})
            estimate["stock"] = stock
            estimate["stock_source"] = "Sales invoice (stock out)" if action == "invoice_create" else "Purchase receipt (stock in)"
        elif action == "purchase_create" and payload.get("received_now") is False:
            estimate["stock_note"] = "Stock is not changed until goods are received."
        return estimate

    def loan_direction(self, item):
        """Wording like "X gave back" is ambiguous; the party's balances decide repay versus collect."""
        payload = item["payload"]
        direction, party = payload.get("direction"), payload.get("party_id")
        if direction not in {"repay", "collect"} or not uuid_value(party):
            return
        try:
            amount = Decimal(str(payload.get("amount")))
            when = date.fromisoformat(str(payload.get("transaction_date") or business_today()))
        except (InvalidOperation, ValueError):
            return
        from app.services.borrowing_ledger import available_repayment
        company = self.scope["company"]
        own = available_repayment(self.db, company, str(party), when, direction)
        if amount <= own or own != 0:
            return
        other = "collect" if direction == "repay" else "repay"
        balance = available_repayment(self.db, company, str(party), when, other)
        if amount <= balance:
            payload["direction"] = other
            owner = "they owe you" if other == "collect" else "you owe them"
            item["labels"]["direction"] = {"value": other,
                "label": f"{ENUM_LABELS['borrowing_create', 'direction'][other]} - {owner} ₹{balance:,.2f}"}

    def invoice_context(self, item):
        payload = item["payload"]
        customer = uuid_value(payload.get("customer_party_id"))
        party = {}
        if customer and "parties" in self.capabilities and not (payload.get("billing_address") and payload.get("place_of_supply")):
            party = self.drafts.reference("parties", customer)
        if party.get("address") and not payload.get("billing_address"):
            payload["billing_address"] = party["address"]
        store_id = uuid_value(payload.get("store_id"))
        if store_id:
            store = self.drafts.reference("stores", store_id)
            company = self.db.execute(text("select address,gst_number,gst_registered from companies where id=:company"),
                                      self.scope).mappings().one()
            gst = (store.get("gst_number") or company["gst_number"] or "").strip()
            missing = ([] if store.get("address") or company["address"] else ["seller address"]) + (
                ["15-character GSTIN"] if company["gst_registered"] and len(gst) != 15 else [])
            if missing:
                item["issues"].append({"field": "store_id", "message":
                    f"Billing needs {' and '.join(missing)} for {store.get('name') or 'this store'}. "
                    "Add it in Company Setup (all stores) or Stores (this store only), then choose Refresh workflow.",
                    "links": [{"label": "Open Company Setup", "path": "/portal/company"},
                              {"label": "Open Stores", "path": "/portal/stores"}]})
            if not payload.get("place_of_supply"):
                # Default to the customer's GST state, else the seller's state (intra-state sale); editable before review.
                customer_gst = str(party.get("gst_number") or "")
                state = str(store.get("state_code") or "")
                code = next((value[:2] for value in (customer_gst, state, gst) if re.match(r"^\d{2}", value)), None)
                supply = choice_value("place_of_supply", code) if code else None
                if supply:
                    payload["place_of_supply"] = supply

    def purchase_offers(self, item, steps):
        vendor = uuid_value(item["payload"].get("vendor_party_id"))
        if not vendor or item["payload"].get("receipt_type") == "SERVICE":
            return
        links = item.setdefault("offer_steps", {})
        for index, line in enumerate(item["payload"].get("lines") or []):
            if not isinstance(line, dict) or not uuid_value(line.get("product_id")):
                continue
            product, variant = uuid_value(line["product_id"]), uuid_value(line.get("variant_id"))
            key = f"{product}:{variant or ''}:{vendor}"
            if key in links:
                child = next(child for child in steps if child["id"] == links[key])
                if child.get("draft_status") != "executed":
                    item["issues"].append({"field": f"lines.{index}.product_id",
                                           "message": "Complete the vendor offer prerequisite first."})
                continue
            try:
                result = self.lookup(("vendor_offers", (), "id", None, None), product)
            except HTTPException as error:
                if error.status_code not in {403, 422}:
                    raise
                item["issues"].append({"field": f"lines.{index}.product_id", "message": str(error.detail)})
                continue
            if any(uuid_value(offer.get("product_id")) == product and uuid_value(offer.get("vendor_id")) == vendor
                   and uuid_value(offer.get("variant_id")) == variant
                   and offer.get("is_active") is not False for offer in result["items"]):
                continue
            if result["more_matches"] or "offer_create" not in self.actions or len(steps) >= MAX_STEPS:
                item["issues"].append({"field": f"lines.{index}.product_id",
                    "message": "Map this vendor to the selected product in Inventory, then continue."})
                continue
            child = step("offer_create", {"product_id": product, "variant_id": variant, "vendor_id": vendor})
            product_label = item["labels"].get(f"lines.{index}.product_id", {}).get("label") or line.get("description")
            vendor_label = item["labels"].get("vendor_party_id", {}).get("label")
            for field, identifier, label in (("product_id", product, product_label), ("vendor_id", vendor, vendor_label)):
                if label:
                    child["labels"][field] = {"value": identifier, "label": label}
            steps.append(child)
            links[key] = child["id"]
            item["issues"].append({"field": f"lines.{index}.product_id",
                                   "message": "Complete the vendor offer prerequisite first."})

    def prepare(self, row, create_request=None):
        steps = row["plan"]["steps"]
        by_id = {item["id"]: item for item in steps}
        # Recover every posted prerequisite before evaluating any dependent step.
        for item in steps:
            if item.get("draft_id"):
                draft = self.drafts.get(item["draft_id"])
                item["draft_status"] = draft["status"]
                if draft["status"] == "executed":
                    execution = self.db.execute(text("""select result from ai_executions where draft_id=:id
                        and draft_version=:version and company_id=:company and user_id=:user and status='succeeded'"""),
                        {**self.scope, "id": draft["id"], "version": draft["version"]}).mappings().one()
                    item["result"] = execution["result"]
                    item["payload"] = draft["payload"]
        for item in steps:
            item["issues"], item["choices"] = [], []
            if item.get("draft_id"):
                continue
            if item["action"] not in self.actions:
                item["issues"].append({"field": "", "message": "This prerequisite action is no longer permitted."})
                continue
            if item["action"] in {"purchase_create", "invoice_create"}:
                item["payload"] = normalize_document_proposal(item["action"], item["payload"])
            coerce_payload(item["action"], item["payload"])
            normalize_choices(item["payload"], item["issues"])
            for binding in item["bindings"].values():
                child = by_id.get(binding["step_id"])
                if child and child.get("result", {}).get("id"):
                    set_path(item["payload"], binding["path"], str(child["result"]["id"]))
                    name = child["payload"].get("name") or child["payload"].get("legal_name") or child["payload"].get("nickname") or child["payload"].get("variant_name")
                    item["labels"][".".join(map(str, binding["path"]))] = {
                        "value": str(child["result"]["id"]), "label": str(name or "Selected record")}
                else:
                    item["issues"].append({"field": ".".join(map(str, binding["path"])),
                                           "message": "Complete the prerequisite step first."})
            action = ACTIONS[item["action"]]
            if not action.target:
                # Older model proposals sometimes put a vendor name in a create action's target.
                item["target"] = None
            if action.target:
                if not item["target"]:
                    item["issues"].append({"field": "target", "message": "Search for the existing record to change."})
                else:
                    if action.key in REPLACEMENTS and action.target == "products":
                        spec = ("product_details", ("name", "sku"), "id", None, None)
                    else:
                        spec = TARGETS[action.target]
                    item["target"] = self.resolve(item, ("target",), item["target"], spec, steps, target=True)
                    if uuid_value(item["target"]):
                        current = self.drafts.reference(action.target, item["target"], allow_inactive=action.key in REPLACEMENTS | {"account_update"})
                        if action.key in REPLACEMENTS and not item.get("hydrated"):
                            preserved = jsonable_encoder({key: current[key] for key in action.schema.model_fields
                                                          if key in current and key not in {"idempotency_key", "attachments"}})
                            if action.key == "product_update":
                                preserved["image_urls"] = [source for source in (current.get("image_urls") or "").split("|") if source]
                            item["requested_fields"] = deepcopy(item["payload"])
                            item["payload"] = {**preserved, **item["payload"]}
                            item["hydrated"] = True
            if action.key == "purchase_bundle_create":
                for name, identifier in (("vendor_name", "vendor_party_id"), ("store_name", "store_id"),
                                         ("account_name", "account_id")):
                    if item["payload"].get(name) and not item["payload"].get(identifier):
                        item["payload"][identifier] = item["payload"][name]
            if action.key in {"purchase_create", "invoice_create"}:
                self.document_products(item)
            references = list(reference_fields(item["payload"]))
            for path, value, spec in references:
                location = ".".join(map(str, path))
                if location not in item["bindings"] or uuid_value(value):
                    set_path(item["payload"], path, self.resolve(item, path, value, spec, steps,
                        force_create=create_request == (item["id"], location)))
            if action.key in {"purchase_create", "invoice_create"}:
                # A name may have resolved to a product in this pass.
                self.document_products(item)
                for index, line in enumerate(item["payload"].get("lines") or []):
                    if (isinstance(line, dict) and line.get("hsn") and
                            not any(path == ("lines", index, "hsn") for path, _, _ in references)):
                        self.resolve(item, ("lines", index, "hsn"), line["hsn"], REFERENCES["hsn"], steps)
            if action.key == "invoice_create":
                self.invoice_context(item)
            if action.key == "borrowing_create":
                self.loan_direction(item)
            if action.key == "purchase_create":
                self.purchase_offers(item, steps)
            if action.key in {"purchase_create", "invoice_create"}:
                item["estimate"] = self.document_estimate(item)
            # One clear message per field; linked fields wait on their prerequisite step instead of showing UUID errors.
            noted = {issue["field"] for issue in item["issues"]} | set(item["bindings"])
            item["issues"] += [issue for issue in missing_fields(action.key, item["payload"])
                               if not issue["field"] or issue["field"] not in noted]
            if not item["issues"] and not item["choices"]:
                values = business_payload(action.key, item["payload"])
                if action.key in {"purchase_create", "invoice_create"} and item["payload"].get("fully_paid") is True:
                    from app.ai.business_writes import document_preview
                    amount_field = "amount_paid" if action.key == "purchase_create" else "amount_received"
                    try:
                        values, _ = document_preview(self.db, self.scope["company"], action.key,
                                                     {**values, amount_field: "0"})
                    except HTTPException as error:
                        if error.status_code not in {403, 409, 422}:
                            raise
                        item["issues"].append({"field": "", "message": str(error.detail)})
                        continue
                    if (item["payload"].get(amount_field) is not None and
                            Decimal(str(item["payload"][amount_field])) != Decimal(str(values["total"]))):
                        item["issues"].append({"field": amount_field,
                            "message": "The entered payment differs from the computed total. Correct it or choose Fully paid now: No."})
                        continue
                    values[amount_field] = values["total"]
                created = self.drafts.create(row["conversation_id"], DraftCreate(action=action.key,
                    target_id=item["target"], payload=values, client_key=UUID(item["id"])), commit=False)
                item["draft_id"], item["draft_status"] = str(created["id"]), created["status"]
            by_id.update({child["id"]: child for child in steps})
        if all(item.get("draft_status") == "executed" for item in steps):
            root = steps[0]
            row["status"] = "completed"
            row["plan"]["next"] = next_entries(root["action"], root["payload"], root["result"])
        return row

    def advance(self, workflow_id, version, edit=None):
        row = self.get(workflow_id)
        self.assistant.lock_conversation(row["conversation_id"])
        row = self.get(workflow_id)
        if row["version"] != version or row["status"] != "active":
            raise HTTPException(409, "Workflow changed or completed. Refresh before continuing.")
        if self.assistant.conversation(row["conversation_id"])["status"] != "active":
            raise HTTPException(409, "Restore the conversation before continuing.")
        self.policies()
        row["plan"] = deepcopy(row["plan"])
        if edit:
            item = next((item for item in row["plan"]["steps"] if item["id"] == str(edit.step_id)), None)
            if not item:
                raise HTTPException(404, "Workflow step not found")
            if item["action"] not in self.actions:
                raise HTTPException(403, "This Operations workflow is not permitted.")
            if edit.selection_field:
                if not edit.selection_query:
                    raise HTTPException(422, "Include the search query when selecting a record.")
                choice = self.search_choices(item["action"], edit.selection_field, edit.selection_query)
                selected = edit.target if edit.selection_field == "target" else edit.payload
                try:
                    if edit.selection_field != "target":
                        for key in edit.selection_field.split("."):
                            selected = selected[int(key)] if isinstance(selected, list) else selected[key]
                except (KeyError, IndexError, TypeError, ValueError):
                    raise HTTPException(422, "Select a record for the searched field.") from None
                option = next((option for option in choice["options"] if option["value"] == selected), None)
                if not option:
                    raise HTTPException(409, "Search results changed. Search again and select an available record.")
                item["labels"][edit.selection_field] = {"value": option["value"], "label": option["label"]}
            if item.get("draft_id"):
                draft = self.drafts.get(item["draft_id"])
                if draft["version"] != edit.draft_version:
                    raise HTTPException(409, "Review draft changed. Refresh before editing.")
                self.drafts.lock(draft["id"], edit.draft_version)
                self.db.execute(text("""update ai_action_drafts set status='discarded',payload='{}',validation=null,
                    approved_at=null,approved_version=null,version=version+1 where id=:id
                    and company_id=:company and user_id=:user"""), {**self.scope, "id": draft["id"]})
                reset_review(item, row["plan"]["steps"])
            if edit.create_field:
                query = edit.payload
                try:
                    for key in edit.create_field.split("."):
                        query = query[int(key)] if isinstance(query, list) else query[key]
                except (KeyError, IndexError, TypeError, ValueError):
                    raise HTTPException(422, "Enter the name for this new prerequisite.") from None
                if not isinstance(query, str) or not self.search_choices(item["action"], edit.create_field, query)["can_create"]:
                    raise HTTPException(409, "Creation is unavailable for this reference. Select a match or narrow the search.")
            for choice in item["choices"]:
                selected = edit.target if choice["field"] == "target" else edit.payload
                if choice["field"] != "target":
                    try:
                        for key in choice["field"].split("."):
                            selected = selected[int(key)] if isinstance(selected, list) else selected[key]
                    except (KeyError, IndexError, TypeError):
                        continue
                option = next((option for option in choice["options"] if option["value"] == selected), None)
                if option:
                    item["labels"][choice["field"]] = {"value": option["value"], "label": option["label"]}
            if item["action"] in {"purchase_create", "invoice_create"}:
                edit.payload = normalize_document_proposal(item["action"], edit.payload)
            validate_workflow_payload(item["action"], edit.payload)
            preserve_bindings(item, edit.payload)
            if any(item["id"] in parent.get("offer_steps", {}).values() for parent in row["plan"]["steps"]):
                for field in ("product_id", "variant_id", "vendor_id"):
                    old, new = item["payload"].get(field), edit.payload.get(field)
                    label = item["labels"].get(field, {}).get("label")
                    if new != old and (not label or normalize(new) != normalize(label)):
                        raise HTTPException(409, "Keep the linked vendor and product on this offer prerequisite.")
                    edit.payload[field] = old
            if item["target"] != edit.target:
                if item.get("hydrated"):
                    edit.payload = {**item.get("requested_fields", {}),
                                    **{key: value for key, value in edit.payload.items()
                                       if key not in item["payload"] or item["payload"][key] != value}}
                item.pop("hydrated", None)
            item["payload"], item["target"] = edit.payload, edit.target
        create_request = (str(edit.step_id), edit.create_field) if edit and edit.create_field else None
        saved = self.save(self.prepare(row, create_request))
        self.assistant.audit(row["conversation_id"], "OPERATION_WORKFLOW_PREPARED", uuid4())
        self.db.commit()
        return saved

    def discard(self, workflow_id, version):
        row = self.get(workflow_id)
        self.assistant.lock_conversation(row["conversation_id"])
        row = self.get(workflow_id)
        if row["version"] != version:
            raise HTTPException(409, "Workflow changed. Refresh before discarding.")
        if self.assistant.conversation(row["conversation_id"])["status"] != "active":
            raise HTTPException(409, "Restore the conversation before discarding.")
        for item in row["plan"]["steps"]:
            if item.get("draft_id"):
                self.db.execute(text("""update ai_action_drafts set status='discarded',payload='{}',validation=null,
                    approved_version=null,approved_at=null,version=version+1 where id=:id
                    and company_id=:company and user_id=:user and status<>'executed'"""),
                    {**self.scope, "id": item["draft_id"]})
        row["plan"], row["status"] = {}, "discarded"
        self.save(row)
        self.assistant.audit(row["conversation_id"], "OPERATION_WORKFLOW_DISCARDED", uuid4())
        self.db.commit()
        return {"discarded": True}
