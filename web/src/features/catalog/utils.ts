import { API_BASE } from "../../api";

export function toAssetUrl(path?: string): string {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = path.replace(/^\/+/, "").replace(/^assets\//, "");
  return `${API_BASE}/catalog-assets/${normalized}`;
}

export function moneyLabel(value?: string): string {
  if (!value) return "";
  return value
    .split("-")
    .map((part) => {
      const n = Number(part.trim());
      return Number.isFinite(n) ? `INR ${n.toLocaleString("en-IN")}` : part.trim();
    })
    .join(" - ");
}

export function whatsappLink(phone: string, productName: string, brandName: string): string {
  const digits = phone.replace(/\D/g, "");
  const message = `Hi SRU Global, I am interested in ${productName} from ${brandName}. Please share the best corporate price, bulk pricing, availability and price matching options.`;
  return `https://wa.me/${digits}?text=${encodeURIComponent(message)}`;
}
