import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import type { CatalogHomeResponse } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { ProductCard } from "../features/catalog/components/ProductCard";
import { toAssetUrl } from "../features/catalog/utils";

export function HomePage() {
  const [data, setData] = useState<CatalogHomeResponse>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    api.home().then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return <main className="loading">Catalogue unavailable. {error}</main>;
  }

  if (!data) {
    return <main className="loading">Loading catalogue...</main>;
  }

  const phone = data.company.phone || FALLBACK_PHONE;
  const email = data.company.email || FALLBACK_EMAIL;

  return (
    <>
      <main>
        <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">THE SRU COLLECTION SPECIAL</p>
            <h1>
              Corporate gifting,
              <br />
              <span>curated the SRU way.</span>
            </h1>
            <p className="lead">
              A considered collection of premium, practical and memorable gifts, sourced from recognised brands and shaped around the occasion, audience and budget.
            </p>
            <div className="actions">
              <a className="btn" href="#collection-special">
                What makes it special
              </a>
              <a className="link" href="#categories">
                Explore categories
              </a>
            </div>
          </div>
          <div className="hero-panel">
            <p>CURATE</p>
            <i />
            <p>CUSTOMISE</p>
            <i />
            <p>DELIVER</p>
          </div>
        </section>

        <section id="categories" className="home-section categories-section">
          <div className="section-heading">
            <p className="eyebrow">CATEGORIES</p>
            <h2>
              Shop by gifting
              <br />
              <span>category.</span>
            </h2>
            <p>Browse the kinds of products SRU Global can curate for employee, client, leadership and milestone gifting.</p>
          </div>
          <div className="category-grid">
            {data.categories.slice(0, 4).map((category) => (
              <Link
                className="category-card"
                to={`/brand.html?category=${encodeURIComponent(category.category_slug)}`}
                key={category.category_slug}
              >
                <div className="category-image">
                  <img src={toAssetUrl(category.image_url)} alt={category.category_title} loading="lazy" />
                </div>
                <div className="category-body">
                  <p className="eyebrow">SRU COLLECTION</p>
                  <h3>{category.category_title}</h3>
                  <p>{category.category_description}</p>
                  <span>Explore category →</span>
                </div>
              </Link>
            ))}
          </div>
          <div className="category-more">
            <Link className="link" to="/brand.html?category=all">
              Explore more categories →
            </Link>
          </div>
        </section>

        <section id="best-sellers" className="home-section featured-section">
          <div className="section-heading">
            <p className="eyebrow">BEST SELLERS</p>
            <h2>
              Popular picks for
              <br />
              <span>corporate gifting.</span>
            </h2>
            <p>Sample pricing is shown for catalogue look and feel. Bulk quantities can be quoted separately.</p>
          </div>
          <div className="bulk-pricing">
            <strong>Better pricing on bulk orders.</strong>
            <span>WhatsApp us for best price and price matching with comparable offers.</span>
          </div>
          <div className="product-grid home-product-grid">
            {data.best_sellers.map((product) => (
              <ProductCard key={product.id} product={product} phone={phone} />
            ))}
          </div>
        </section>

        <section id="sru-specials" className="home-section specials-section">
          <div className="section-heading">
            <p className="eyebrow">SRU SPECIALS</p>
            <h2>
              Curated differently.
              <br />
              <span>Chosen by SRU.</span>
            </h2>
            <p>A hand-picked mix of premium, practical and conversation-worthy gifts for standout gifting moments.</p>
          </div>
          <div className="bulk-pricing">
            <strong>Better pricing on bulk orders.</strong>
            <span>WhatsApp us for best price and price matching with comparable offers.</span>
          </div>
          <div className="product-grid home-product-grid">
            {data.sru_specials.map((product) => (
              <ProductCard key={product.id} product={product} phone={phone} />
            ))}
          </div>
        </section>

        <section id="brands" className="brands-section">
          <div className="section-heading">
            <p className="eyebrow">BRANDS WE SUPPORT</p>
            <h2>
              Curated products from
              <br />
              <span>recognised brands.</span>
            </h2>
            <p>Explore available product ranges with sample MRP and our price for catalogue display.</p>
          </div>
          <div className="brand-grid">
            {data.brands.map((brand) => (
              <Link className="brand-card" to={`/brand.html?brand=${encodeURIComponent(brand.code)}`} key={brand.code}>
                <div className="logo-box">
                  <img src={toAssetUrl(`brand-logos/${brand.code}.png`)} alt={brand.name} loading="lazy" />
                </div>
                <strong>{brand.name}</strong>
                <span>Corporate catalogue</span>
                <em>View products →</em>
              </Link>
            ))}
          </div>
        </section>

        <section className="corporate">
          <div>
            <p className="eyebrow">WHY SRU GLOBAL</p>
            <h2>
              Thoughtful sourcing.
              <br />
              <span>Seamless execution.</span>
            </h2>
          </div>
          <div>
            <p>We understand the occasion, audience and requirement, then source, customise and coordinate the right gifting solution end-to-end.</p>
            <a className="btn light" href={`https://wa.me/${phone.replace(/\D/g, "")}`}>
              WhatsApp us
            </a>
          </div>
        </section>

        <section id="contact" className="contact">
          <p className="eyebrow">START A CONVERSATION</p>
          <h2>
            Let&apos;s create something
            <br />
            worth giving.
          </h2>
          <p>For corporate pricing, availability and bulk orders, contact SRU Global on WhatsApp or email.</p>
          <div className="contact-actions">
            <a className="btn whatsapp-btn" href={`https://wa.me/${phone.replace(/\D/g, "")}`}>
              WhatsApp {phone}
            </a>
            <a className="link" href={`mailto:${email}`}>
              {email}
            </a>
          </div>
        </section>

        <section id="collection-special" className="statement collection-special">
          <p className="eyebrow">WHAT IS THE SRU COLLECTION SPECIAL?</p>
          <h2>
            Not just a catalogue.
            <br />
            <span>A collection with a point of view.</span>
          </h2>
          <p>
            SRU Collection Special is our curated approach to corporate gifting: we bring together products worth giving,
            organise them by real gifting needs, and help businesses choose, customise and deliver the right gift at the right scale.
          </p>
          <div className="special-points">
            <div>
              <strong>CURATED</strong>
              <span>Products selected for corporate relevance, quality and gifting appeal.</span>
            </div>
            <div>
              <strong>FLEXIBLE</strong>
              <span>Options across categories, budgets, occasions and quantities.</span>
            </div>
            <div>
              <strong>COMMERCIAL</strong>
              <span>Transparent reference pricing with sharper quotes for bulk requirements.</span>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
