import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import type { CatalogListResponse } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { ProductCard } from "../features/catalog/components/ProductCard";
import { toAssetUrl } from "../features/catalog/utils";

export function BrandPage() {
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

  if (error) {
    return <main className="loading">Catalogue unavailable. {error}</main>;
  }

  if (!data) {
    return <main className="loading">Loading catalogue...</main>;
  }

  const phone = (data.company.phone || FALLBACK_PHONE).replace(/\D/g, "");
  const email = data.company.email || FALLBACK_EMAIL;

  if (category === "all") {
    return (
      <>
        <main id="brand-page">
          <section className="catalog-hero category-index-hero">
            <div>
              <p className="eyebrow">SRU COLLECTION · CATEGORIES</p>
              <h1>
                Shop by gifting
                <br />
                <span>category.</span>
              </h1>
              <p className="lead">Explore all the product categories SRU Global can curate for corporate gifting.</p>
              <div className="actions">
                <a className="btn" href="/#categories">
                  Back to home
                </a>
                <a className="link" href={`https://wa.me/${phone}`}>
                  WhatsApp us →
                </a>
              </div>
            </div>
          </section>
          <section className="product-section category-index-section">
            <div className="section-heading">
              <p className="eyebrow">ALL CATEGORIES</p>
              <h2>
                Find the right
                <br />
                <span>kind of gift.</span>
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
                    <img src={toAssetUrl(item.image_url)} alt={item.category_title} loading="lazy" />
                  </div>
                  <div className="category-body">
                    <p className="eyebrow">SRU COLLECTION</p>
                    <h3>{item.category_title}</h3>
                    <p>{item.category_description}</p>
                    <span>Explore category →</span>
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
          <h1>Category not found</h1>
          <Link className="btn" to="/brand.html?category=all">
            Back to categories
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
          <h1>Brand not found</h1>
          <a className="btn" href="/#brands">
            Back to brands
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
          <h1>Brand not found</h1>
          <a className="btn" href="/#brands">
            Back to brands
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
    : data.selected_brand!.description || `Corporate gifting catalogue from ${data.selected_brand!.name}.`;
  const eyebrow = isCategoryView ? "SRU COLLECTION · CATEGORY" : "SRU GLOBAL · CORPORATE GIFTING";
  const productRangeEyebrow = `${heading} · PRODUCT RANGE`;
  const backHref = isCategoryView ? "/brand.html?category=all" : "/#brands";
  const backLabel = isCategoryView ? "← All categories" : "← All brands";
  const bestPricingMessage = encodeURIComponent(
    "Hi SRU Global, I need help selecting products for a corporate gifting requirement. Please share the best bulk pricing.",
  );
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
            <p className="catalog-note">{data.products.length} products · Sample corporate pricing shown below</p>
            <div className="actions">
              <a className="btn whatsapp-btn" href={`https://wa.me/${phone}`}>
                WhatsApp for best pricing
              </a>
              <a className="link" href={`mailto:${email}`}>
                {email} →
              </a>
            </div>
          </div>
          <div className="catalog-brand-logo">
            <img src={heroImage} alt={heroAlt} loading="lazy" />
          </div>
        </section>

        <div className="brand-page-nav">
          <a href={backHref}>{backLabel}</a>
          <span className="catalog-count">{data.products.length} products</span>
          <a href={`https://wa.me/${phone}?text=${bestPricingMessage}`}>Get best pricing →</a>
        </div>

        <section className="product-section">
          <div className="section-heading">
            <p className="eyebrow">{productRangeEyebrow}</p>
            <h2>
              Choose a product.
              <br />
              <span>Then enquire.</span>
            </h2>
            <p>MRP is shown for reference. Our listed price is a sample individual requirement price; bulk orders can be priced better.</p>
          </div>
          <div className="bulk-pricing">
            <strong>Better pricing on bulk orders.</strong>
            <span>WhatsApp us for the best price and price matching with comparable offers.</span>
          </div>

          {data.products.length ? (
            <div className="product-grid">
              {data.products.map((product) => (
                <ProductCard key={product.id} product={product} phone={phone} />
              ))}
            </div>
          ) : (
            <div className="empty">No products found for this filter.</div>
          )}
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
