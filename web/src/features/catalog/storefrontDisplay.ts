import type { StorefrontContent, StorefrontDisplay } from "../../types";

export const DEFAULT_STOREFRONT_DISPLAY: StorefrontDisplay = {
  show_bulk_pricing: true,
  whatsapp_enquiry_enabled: true,
  corner_style: "rounded",
  logo_shape: "original",
};

export function storefrontDisplay(company?: { storefront_content?: StorefrontContent | null } | null): StorefrontDisplay {
  const saved = company?.storefront_content?.display;
  return {
    show_bulk_pricing: saved?.show_bulk_pricing !== false,
    whatsapp_enquiry_enabled: saved?.whatsapp_enquiry_enabled !== false,
    corner_style: saved?.corner_style === "square" ? "square" : "rounded",
    logo_shape: saved?.logo_shape === "circle" ? "circle" : saved?.logo_shape === "square" ? "square" : "original",
  };
}

export function applyCornerStyle(style?: StorefrontDisplay["corner_style"]) {
  document.documentElement.dataset.corners = style === "square" ? "square" : "rounded";
}
