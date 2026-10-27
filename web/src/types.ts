export type Company = {
  id: string;
  company_name: string;
  nickname?: string;
  logo_url?: string;
  gst_number?: string;
  udyam_number?: string;
  phone?: string;
  email?: string;
  address?: string;
  website?: string;
  social_links?: Record<string, string>;
  is_active: boolean;
};

export type Brand = {
  code: string;
  name: string;
  description?: string;
};

export type CatalogCategory = {
  category_slug: string;
  name: string;
  category_title: string;
  category_description: string;
  image_url: string;
  home_order: number;
};

export type CatalogProduct = {
  id: string;
  portal_product_id: string;
  name: string;
  description: string;
  image_url: string;
  image_urls: string;
  mrp_display: string;
  selling_price_display: string;
  best_seller: boolean;
  sru_special: boolean;
  home_order: number;
  is_active: boolean;
  brand_code: string;
  brand_name: string;
  category_slug: string;
  category_title: string;
  category_description: string;
  stock_qty: number;
  gallery?: string[];
};

export type CatalogHomeResponse = {
  company: Company;
  brands: Brand[];
  categories: CatalogCategory[];
  best_sellers: CatalogProduct[];
  sru_specials: CatalogProduct[];
};

export type CatalogProductResponse = {
  product: CatalogProduct;
};

export interface CatalogListResponse {
  company: Company;
  brands: Brand[];
  categories: CatalogCategory[];
  products: CatalogProduct[];
  selected_brand: Brand | null;
  selected_category: CatalogCategory | null;
}
