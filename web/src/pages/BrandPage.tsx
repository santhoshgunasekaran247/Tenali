import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import type { CatalogListResponse } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { ProductCard } from "../features/catalog/components/ProductCard";
import { toAssetUrl } from "../features/catalog/utils";
import { tenantBase } from "../features/tenantTransport";
import { storefrontText } from "../features/catalog/storefrontText";
import { useAuth } from "../features/auth";
import { Package } from "lucide-react";

export function BrandPage() {
  const {storefront}=useAuth();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<CatalogListResponse>();
  const [error, setError] = useState<string>();

  const brand = searchParams.get("brand") || undefined;
  const category = searchParams.get("category") || undefined;

  useEffect(() => {
    api
      .list({ brand, category })
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [brand, category]);

  const publicCompany=storefront||{company_name:"Tenali",nickname:undefined};
  const publicCopy=storefront?.storefront_content;
  if (error) {
    return <main className="loading">{storefrontText(publicCopy?.catalog.catalogue_unavailable||"Catalogue unavailable.",publicCompany)} {error}</main>;
  }

  if (!data) {
    return <main className="loading">{storefrontText(publicCopy?.catalog.catalogue_loading||"Loading catalogue...",publicCompany)}</main>;
  }

  const phone = (data.company.phone || FALLBACK_PHONE).replace(/\D/g, "");
  const email = data.company.email || FALLBACK_EMAIL;
  const homeCopy=data.company.storefront_content?.home||{};
  const catalogCopy=data.company.storefront_content?.catalog||{};
  const homeText=(key:string)=>storefrontText(homeCopy[key],data.company);
  const catalogText=(key:string,variables:Record<string,string|number>={})=>storefrontText(catalogCopy[key],data.company,variables);

  if (category === "all") {
    return (
      <>
        <main id="brand-page">
          <section className="catalog-hero category-index-hero">
            <div>
              <p className="eyebrow">{catalogText("all_categories_eyebrow")}</p>
              <h1>
                {catalogText("all_categories_heading_first")}
                <br />
                <span>{catalogText("all_categories_heading_second")}</span>
              </h1>
              <p className="lead">{catalogText("all_categories_description")}</p>
              <div className="actions">
                <a className="btn" href={`${tenantBase()}/#categories`}>{catalogText("back_home")}</a>
                {phone?<a className="link" href={`https://wa.me/${phone}`}>
                  {catalogText("whatsapp_us")}
                </a>:null}
              </div>
            </div>
          </section>
          <section className="product-section category-index-section">
            <div className="section-heading">
              <p className="eyebrow">{catalogText("all_categories")}</p>
              <h2>
                {catalogText("category_index_heading_first")}
                <br />
                <span>{catalogText("category_index_heading_second")}</span>
              </h2>
            </div>
            <div className="category-grid category-index-grid">
              {data.categories.map((item) => (
                <Link
                  className="category-card"
                  to={`/brand.html?category=${encodeURIComponent(item.category_slug)}`}
                  key={item.category_slug}
                >
                  <div className="category-image">
                    {item.image_url?<img src={toAssetUrl(item.image_url)} alt={item.category_title} loading="lazy" />:<Package size={36} aria-hidden="true"/>}
                  </div>
                  <div className="category-body">
                    <p className="eyebrow">{homeText("category_card_eyebrow")}</p>
                    <h3>{item.category_title}</h3>
                    <p>{item.category_description}</p>
                    <span>{homeText("category_action")}</span>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        </main>
        <SiteFooter />
      </>
    );
  }

  if (category && !data.selected_category) {
    return (
      <>
        <main className="empty">
          <h1>{catalogText("category_not_found")}</h1>
          <Link className="btn" to="/brand.html?category=all">
            {catalogText("back_to_categories")}
          </Link>
        </main>
        <SiteFooter />
      </>
    );
  }

  if (brand && !data.selected_brand) {
    return (
      <>
        <main className="empty">
          <h1>{catalogText("brand_not_found")}</h1>
          <a className="btn" href={`${tenantBase()}/#brands`}>
            {catalogText("back_to_brands")}
          </a>
        </main>
        <SiteFooter />
      </>
    );
  }

  if (!brand && !category) {
    return (
      <>
        <main className="empty">
          <h1>{catalogText("brand_not_found")}</h1>
          <a className="btn" href={`${tenantBase()}/#brands`}>
            {catalogText("back_to_brands")}
          </a>
        </main>
        <SiteFooter />
      </>
    );
  }

  const isCategoryView = Boolean(category && data.selected_category);
  const heading = isCategoryView ? data.selected_category!.category_title : data.selected_brand!.name;
  const lead = isCategoryView
    ? data.selected_category!.category_description
    : data.selected_brand!.description || catalogText("brand_description_fallback", { brand_name: data.selected_brand!.name });
  const eyebrow = catalogText(isCategoryView ? "category_page_eyebrow" : "products_page_eyebrow");
  const productRangeEyebrow = `${heading} · ${catalogText("product_range_suffix")}`;
  const backHref = tenantBase()+(isCategoryView ? "/brand.html?category=all" : "/#brands");
  const backLabel = catalogText(isCategoryView ? "all_categories_link" : "all_brands_link");
  const bestPricingMessage = encodeURIComponent(storefrontText(catalogCopy.whatsapp_prefilled_message,data.company,{brand_name:heading}));
  const heroImage = isCategoryView
    ? toAssetUrl(data.selected_category!.image_url)
    : toAssetUrl(`brand-logos/${data.selected_brand!.code}.png`);
  const heroAlt = isCategoryView ? heading : `${heading} logo`;

  return (
    <>
      <main id="brand-page">
        <section className="catalog-hero">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h1>{heading}</h1>
            <p className="lead">{lead}</p>
            <p className="catalog-note">{catalogText("product_count", { count: data.products.length })} · {catalogText("sample_price_note")}</p>
            <div className="actions">
              {phone?<a className="btn whatsapp-btn" href={`https://wa.me/${phone}`}>
                {catalogText("whatsapp_best_pricing")}
              </a>:null}
              {email?<a className="link" href={`mailto:${email}`}>
                {email} →
              </a>:null}
            </div>
          </div>
          <div className="catalog-brand-logo">
            {isCategoryView&&!data.selected_category!.image_url?<Package size={72} aria-label="Category"/>:<img src={heroImage} alt={heroAlt} loading="lazy" />}
          </div>
        </section>

        <div className="brand-page-nav">
          <a href={backHref}>{backLabel}</a>
          <span className="catalog-count">{catalogText("product_count", { count: data.products.length })}</span>
          {phone?<a href={`https://wa.me/${phone}?text=${bestPricingMessage}`}>{catalogText("get_best_pricing")}</a>:null}
        </div>

        <section className="product-section">
          <div className="section-heading">
            <p className="eyebrow">{productRangeEyebrow}</p>
            <h2>
              {catalogText("choose_heading_first")}
              <br />
              <span>{catalogText("choose_heading_second")}</span>
            </h2>
            <p>{catalogText("choose_description")}</p>
          </div>
          <div className="bulk-pricing">
            <strong>{catalogText("best_pricing_heading")}</strong>
            <span>{catalogText("best_pricing_description")}</span>
          </div>

          {data.products.length ? (
            <div className="product-grid">
              {data.products.map((product) => (
                <ProductCard key={product.id} product={product} phone={phone} />
              ))}
            </div>
          ) : (
            <div className="empty">{catalogText("no_products")}</div>
          )}
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
