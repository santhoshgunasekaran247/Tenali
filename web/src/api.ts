import type {
  CatalogHomeResponse,
  CatalogListResponse,
  CatalogProductResponse,
} from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return response.json();
}

export const api = {
  home: () => request<CatalogHomeResponse>("/catalog/home"),
  async list(filters?: { brand?: string; category?: string }) {
    const params = new URLSearchParams();
    if (filters?.brand) params.set("brand", filters.brand);
    if (filters?.category) params.set("category", filters.category);
    const qs = params.toString();
    return request<CatalogListResponse>(`/catalog/list${qs ? `?${qs}` : ""}`);
  },
  product: (productId: string) =>
    request<CatalogProductResponse>(`/catalog/products/${encodeURIComponent(productId)}`),
};
