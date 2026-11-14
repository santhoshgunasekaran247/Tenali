// Older assistant replies stored verified lookups as raw JSON; show them in the same plain form as new replies.
const LEGACY_MARKER = "Verified Tenali lookup (read only):";
const MARKER = "From your Tenali records";
const TITLE_FIELDS = ["name", "legal_name", "product_name", "account_name", "invoice_number", "voucher_number", "bill_number",
  "party_name", "customer_name", "vendor_name", "code", "store_code", "nickname", "reference"];
const FIRST_FIELDS = ["current_balance", "stock_qty", "balance_quantity", "quantity", "total", "balance_amount", "amount",
  "outstanding", "collection_status", "payment_status", "status"];
const HIDDEN_FIELDS = new Set(["id", "period_key", "is_draft", "movement_quantity", "movement_count", "difference",
  "missing_document_references"]);
const MONEY_WORDS = ["amount", "balance", "total", "price", "cost", "inflow", "outflow", "value", "outstanding", "mrp"];
const COUNT_WORDS = ["qty", "quantity", "stock", "count", "difference", "references"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const NO_DRAFT = "No draft was saved in this reply.";
const TITLES: Record<string, string> = { reconciliation: "Stock by store", reorder: "Low stock",
  account_journal: "Account entries", hsn: "HSN codes", parties: "Customers & vendors" };

type Row = Record<string, unknown>;

const isMoney = (key: string) => MONEY_WORDS.some(word => key.includes(word)) && !COUNT_WORDS.some(word => key.includes(word));
const label = (key: string) => key.replace(/^is_/, "").replace(/_/g, " ");

export function rupees(value: number): string {
  const [whole, fraction] = Math.abs(value).toFixed(2).split(".");
  let head = whole.slice(0, -3), tail = whole.slice(-3);
  while (head.length > 2) { tail = `${head.slice(-2)},${tail}`; head = head.slice(0, -2); }
  return `${value < 0 ? "-" : ""}₹${head ? `${head},` : ""}${tail}.${fraction}`;
}

function display(key: string, value: unknown): string {
  if (typeof value === "boolean") return value ? "yes" : "no";
  const text = String(value);
  const date = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T ])/.exec(text);
  if (date) return `${Number(date[3])} ${MONTHS[Number(date[2]) - 1]} ${date[1]}`;
  if (/^-?\d+(\.\d+)?$/.test(text)) return isMoney(key) ? rupees(Number(text)) : String(Number(text));
  return key.endsWith("status") || key === "direction" ? text.replace(/_/g, " ").toLowerCase() : text;
}

function row(item: Row): string {
  const title = TITLE_FIELDS.map(key => item[key]).find(value => value !== null && value !== undefined && value !== "");
  const keys = [...FIRST_FIELDS.filter(key => key in item), ...Object.keys(item).filter(key => !FIRST_FIELDS.includes(key))];
  const details = keys.flatMap(key => {
    const value = item[key];
    if (value === null || value === undefined || value === "" || value === false || HIDDEN_FIELDS.has(key)
      || key.endsWith("_id") || String(value) === String(title)) return [];
    return [value === true ? label(key) : `${label(key)} ${display(key, value)}`];
  });
  return `• ${[title === undefined ? "" : String(title), details.join(" · ")].filter(Boolean).join(": ")}`;
}

function legacyBlock(json: string): string | null {
  try {
    const result = JSON.parse(json) as { capability?: string; items?: Row[]; more_matches?: boolean };
    if (!result.capability || !Array.isArray(result.items)) return null;
    const name = TITLES[result.capability] ?? result.capability.replace(/_/g, " ");
    const heading = `${MARKER} — ${name.charAt(0).toUpperCase()}${name.slice(1)} (${result.items.length}${result.more_matches ? "+" : ""})`;
    const lines = result.items.length ? result.items.map(row) : ["• No matching records."];
    return [heading, ...lines, ...(result.more_matches ? ["More records match; ask with a narrower name, store or date."] : [])].join("\n");
  } catch {
    return null;
  }
}

/** Plain-language display of an assistant reply; never changes the stored message. */
export function readableMessage(content: string): string {
  if (!content.includes(LEGACY_MARKER) && !content.includes(`${MARKER} — `)) return content;
  const parts = content.split(LEGACY_MARKER);
  const rendered = parts.slice(1).map(part => {
    const body = part.replace(/^\s+/, "");
    if (!body.startsWith("{")) return `${MARKER} — ${body}`;
    const end = body.lastIndexOf("}");
    const readable = end > 0 ? legacyBlock(body.slice(0, end + 1)) : null;
    return readable === null ? `${MARKER}: details from this older reply could not be shown.` : readable + body.slice(end + 1);
  });
  // Text written before the data was read ("I can look that up…") is dropped once the data is shown.
  return [parts.length > 1 ? "" : parts[0], ...rendered].join("\n\n")
    .split(NO_DRAFT).join("").replace(/\n{3,}/g, "\n\n").trim();
}
