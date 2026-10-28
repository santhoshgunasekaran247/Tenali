import { API_BASE } from "../../api";

export function toAssetUrl(path?: string): string {
  if (!path) return "";
  if (/^data:image\/(png|jpeg|webp);base64,/i.test(path)) return path;
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

export function whatsappLink(phone: string, productName: string, brandName: string, template?: string): string {
  const digits = phone.replace(/\D/g, "");
  const message = (template || "Hello, I am interested in {product_name} from {brand_name}. Please share pricing, availability and bulk options.")
    .replace(/\{product_name\}/g, productName).replace(/\{brand_name\}/g, brandName);
  return `https://wa.me/${digits}?text=${encodeURIComponent(message)}`;
}
