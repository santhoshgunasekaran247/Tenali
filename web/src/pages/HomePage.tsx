import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import type { CatalogHomeResponse } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { ProductCard } from "../features/catalog/components/ProductCard";
import { toAssetUrl } from "../features/catalog/utils";
import { storefrontText } from "../features/catalog/storefrontText";
import { Package } from "lucide-react";
import { useAuth } from "../features/auth";

export function HomePage() {
  const {storefront}=useAuth();
  const location = useLocation();
  const [data, setData] = useState<CatalogHomeResponse>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    api.home().then(setData).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!data || !location.hash) return;
    const frame = requestAnimationFrame(() => document.getElementById(location.hash.slice(1))?.scrollIntoView());
    return () => cancelAnimationFrame(frame);
  }, [data, location.key, location.hash]);

  const publicCompany=storefront||{company_name:"Tenali",nickname:undefined,storefront_content:undefined};
  const loadingCopy=publicCompany.storefront_content?.home||{};
  if (error) {
    return <main className="loading">{storefrontText(loadingCopy.catalogue_unavailable||"Catalogue unavailable.",publicCompany)} {error}</main>;
  }

  if (!data) {
    return <main className="loading">{storefrontText(loadingCopy.catalogue_loading||"Loading catalogue...",publicCompany)}</main>;
  }

  const phone = data.company.phone || FALLBACK_PHONE;
  const email = data.company.email || FALLBACK_EMAIL;
  const copy = data.company.storefront_content?.home || {};
  const text = (key: string) => storefrontText(copy[key], data.company);

  return (
    <>
      <main>
        <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">{text("hero_eyebrow")}</p>
            <h1>
              {text("hero_heading_first")}<br /><span>{text("hero_heading_second")}</span>
            </h1>
            <p className="lead">{text("hero_description")}</p>
            <div className="actions">
              <a className="btn" href="#collection-special">{text("hero_primary_action")}</a>
              <a className="link" href="#categories">{text("hero_secondary_action")}</a>
            </div>
          </div>
          <div className="hero-panel">
            <p>{text("hero_service_one")}</p>
            <i />
            <p>{text("hero_service_two")}</p>
            <i />
            <p>{text("hero_service_three")}</p>
          </div>
        </section>

        <section id="categories" className="home-section categories-section">
          <div className="section-heading">
            <p className="eyebrow">{text("categories_eyebrow")}</p>
            <h2>
              {text("categories_heading_first")}
              <br />
              <span>{text("categories_heading_second")}</span>
            </h2>
            <p>{text("categories_description")}</p>
          </div>
          <div className="category-grid">
            {data.categories.slice(0, 4).map((category) => (
              <Link
                className="category-card"
                to={`/brand.html?category=${encodeURIComponent(category.category_slug)}`}
                key={category.category_slug}
              >
                <div className="category-image">
                    {category.image_url?<img src={toAssetUrl(category.image_url)} alt={category.category_title} loading="lazy" />:<Package size={36} aria-hidden="true"/>}
                </div>
                <div className="category-body">
                  <p className="eyebrow">{text("category_card_eyebrow")}</p>
                  <h3>{category.category_title}</h3>
                  <p>{category.category_description}</p>
                  <span>{text("category_action")}</span>
                </div>
              </Link>
            ))}
          </div>
          <div className="category-more">
            <Link className="link" to="/brand.html?category=all">
              {text("categories_more_action")}
            </Link>
          </div>
        </section>

        <section id="best-sellers" className="home-section featured-section">
          <div className="section-heading">
            <p className="eyebrow">{text("best_sellers_eyebrow")}</p>
            <h2>
              {text("best_sellers_heading_first")}
              <br />
              <span>{text("best_sellers_heading_second")}</span>
            </h2>
            <p>{text("best_sellers_description")}</p>
          </div>
          <div className="bulk-pricing">
            <strong>{text("bulk_title")}</strong>
            <span>{text("bulk_description")}</span>
          </div>
          <div className="product-grid home-product-grid">
            {data.best_sellers.map((product) => (
              <ProductCard key={product.id} product={product} phone={phone} />
            ))}
          </div>
        </section>

        <section id="sru-specials" className="home-section specials-section">
          <div className="section-heading">
            <p className="eyebrow">{text("specials_eyebrow")}</p>
            <h2>
              {text("specials_heading_first")}
              <br />
              <span>{text("specials_heading_second")}</span>
            </h2>
            <p>{text("specials_description")}</p>
          </div>
          <div className="bulk-pricing">
            <strong>{text("bulk_title")}</strong>
            <span>{text("bulk_description")}</span>
          </div>
          <div className="product-grid home-product-grid">
            {data.sru_specials.map((product) => (
              <ProductCard key={product.id} product={product} phone={phone} />
            ))}
          </div>
        </section>

        <section id="brands" className="brands-section">
          <div className="section-heading">
            <p className="eyebrow">{text("brands_eyebrow")}</p>
            <h2>
              {text("brands_heading_first")}
              <br />
              <span>{text("brands_heading_second")}</span>
            </h2>
            <p>{text("brands_description")}</p>
          </div>
          <div className="brand-grid">
            {data.brands.map((brand) => (
              <Link className="brand-card" to={`/brand.html?brand=${encodeURIComponent(brand.code)}`} key={brand.code}>
                <div className="logo-box">
                  <img src={toAssetUrl(`brand-logos/${brand.code}.png`)} alt={brand.name} loading="lazy" />
                </div>
                <strong>{brand.name}</strong>
                <span>{text("brand_catalog_label")}</span>
                <em>{text("brand_action")}</em>
              </Link>
            ))}
          </div>
        </section>

        <section className="corporate">
          <div>
            <p className="eyebrow">{text("why_eyebrow")}</p>
            <h2>
              {text("why_heading_first")}
              <br />
              <span>{text("why_heading_second")}</span>
            </h2>
          </div>
          <div>
            <p>{text("why_description")}</p>
            {phone?<a className="btn light" href={`https://wa.me/${phone.replace(/\D/g, "")}`}>
              {text("contact_whatsapp_label")}
            </a>:null}
          </div>
        </section>

        <section id="contact" className="contact">
          <p className="eyebrow">{text("contact_eyebrow")}</p>
          <h2>
            {text("contact_heading_first")}
            <br />
            {text("contact_heading_second")}
          </h2>
          <p>{text("contact_description")}</p>
          <div className="contact-actions">
            {phone?<a className="btn whatsapp-btn" href={`https://wa.me/${phone.replace(/\D/g, "")}`}>
              {text("contact_whatsapp_label")} {phone}
            </a>:null}
            {email?<a className="link" href={`mailto:${email}`}>
              {email}
            </a>:null}
          </div>
        </section>

        <section id="collection-special" className="statement collection-special">
          <p className="eyebrow">{text("collection_eyebrow")}</p>
          <h2>
            {text("collection_heading_first")}
            <br />
            <span>{text("collection_heading_second")}</span>
          </h2>
          <p>{text("collection_description")}</p>
          <div className="special-points">
            <div>
              <strong>{text("collection_point_one_title")}</strong>
              <span>{text("collection_point_one_body")}</span>
            </div>
            <div>
              <strong>{text("collection_point_two_title")}</strong>
              <span>{text("collection_point_two_body")}</span>
            </div>
            <div>
              <strong>{text("collection_point_three_title")}</strong>
              <span>{text("collection_point_three_body")}</span>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
