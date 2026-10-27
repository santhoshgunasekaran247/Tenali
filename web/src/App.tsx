import { useEffect, useMemo, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { API_BASE, api } from "./api";
import type { CatalogHomeResponse, CatalogListResponse, CatalogProduct } from "./types";

const FALLBACK_PHONE = "+919361748842";
const FALLBACK_EMAIL = "sourcedbysru@gmail.com";

function toAssetUrl(path?: string): string {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = path.replace(/^\/+/, "").replace(/^assets\//, "");
  return `${API_BASE}/catalog-assets/${normalized}`;
}

function moneyLabel(value?: string): string {
  if (!value) return "";
  return value
    .split("-")
    .map((part) => {
      const n = Number(part.trim());
      return Number.isFinite(n) ? `INR ${n.toLocaleString("en-IN")}` : part.trim();
    })
    .join(" - ");
}

function whatsappLink(phone: string, productName: string, brandName: string): string {
  const digits = phone.replace(/\D/g, "");
  const message = `Hi SRU Global, I am interested in ${productName} from ${brandName}. Please share the best corporate price, bulk pricing, availability and price matching options.`;
  return `https://wa.me/${digits}?text=${encodeURIComponent(message)}`;
}

function Header({ menuOpen, onMenuToggle }: { menuOpen: boolean; onMenuToggle: () => void }) {
  return (
    <header className="header">
      <Link className="brand" to="/">
        <img src={toAssetUrl("sru-global-logo.png")} alt="SRU Global" />
      </Link>
      <nav className={menuOpen ? "open" : ""}>
        <a href="/#collection-special">SRU Collection Special</a>
        <a href="/#categories">Categories</a>
        <a href="/#best-sellers">Best Sellers</a>
        <a href="/#sru-specials">SRU Specials</a>
        <a href="/#brands">Brands</a>
        <a href="/#contact">Contact</a>
      </nav>
      <button className="menu" aria-label="Open menu" onClick={onMenuToggle}>
        ☰
      </button>
    </header>
  );
}

function ProductCard({ product, phone }: { product: CatalogProduct; phone: string }) {
  const navigate = useNavigate();
  const gallery = (product.image_urls || "").split("|").map((img) => img.trim()).filter(Boolean);
  const image = gallery[0] || product.image_url;

  return (
    <article
      className="product-card dynamic-card"
      role="link"
      tabIndex={0}
      onClick={() => navigate(`/products/${product.id}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter") navigate(`/products/${product.id}`);
      }}
    >
      <div className="product-image">
        <img src={toAssetUrl(image)} alt={product.name} loading="lazy" />
        <div className="product-tags">
          {product.best_seller && <span className="badge-best">Best Seller</span>}
          {product.sru_special && <span className="badge-special">SRU Special</span>}
        </div>
        {gallery.length > 1 && <span className="photo-count">{gallery.length} photos</span>}
        {!!product.stock_qty && (
          <span className={product.stock_qty > 0 ? "stock-badge stock-in" : "stock-badge stock-out"}>
            {product.stock_qty > 0 ? "In stock" : "Out of stock"}
          </span>
        )}
      </div>
      <div className="product-body">
        <div className="product-type">{product.brand_name || product.category_title}</div>
        <h3 title={product.name}>{product.name}</h3>
        <div className="price-block">
          <div className="mrp">
            <span>MRP</span>
            <s>{moneyLabel(product.mrp_display)}</s>
          </div>
          <div className="our-price">
            <span>Our Price</span>
            <strong>{moneyLabel(product.selling_price_display)}</strong>
          </div>
        </div>
        <p title={product.description}>{product.description}</p>
        <a
          className="btn whatsapp-btn"
          href={whatsappLink(phone, product.name, product.brand_name || "SRU Collection")}
          onClick={(e) => e.stopPropagation()}
        >
          WhatsApp enquiry
        </a>
      </div>
    </article>
  );
}

function HomePage() {
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
      <footer>
        <strong>SRU GLOBAL</strong>
        <span>Corporate gifting and curated catalogues</span>
      </footer>
    </>
  );
}

function BrandPage() {
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
        <footer>
          <strong>SRU GLOBAL</strong>
          <span>Corporate gifting and curated catalogues</span>
        </footer>
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
        <footer>
          <strong>SRU GLOBAL</strong>
          <span>Corporate gifting and curated catalogues</span>
        </footer>
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
        <footer>
          <strong>SRU GLOBAL</strong>
          <span>Corporate gifting and curated catalogues</span>
        </footer>
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
        <footer>
          <strong>SRU GLOBAL</strong>
          <span>Corporate gifting and curated catalogues</span>
        </footer>
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
      <footer>
        <strong>SRU GLOBAL</strong>
        <span>Corporate gifting and curated catalogues</span>
      </footer>
    </>
  );
}

function ProductPage() {
  const { productId } = useParams();
  const [product, setProduct] = useState<CatalogProduct>();
  const [error, setError] = useState<string>();
  const [photoIndex, setPhotoIndex] = useState(0);

  useEffect(() => {
    if (!productId) return;
    api
      .product(productId)
      .then((r) => setProduct(r.product))
      .catch((e: Error) => setError(e.message));
  }, [productId]);

  const gallery = useMemo(() => {
    if (!product) return [];
    const photos = product.gallery || [];
    if (photos.length) return photos;
    if (product.image_url) return [product.image_url];
    return [];
  }, [product]);

  if (error) return <main className="loading">Product unavailable. {error}</main>;
  if (!product) return <main className="loading">Loading product...</main>;

  const mainPhoto = gallery[photoIndex] || product.image_url;

  return (
    <>
      <main id="product-page">
        <div className="product-detail-crumb">
          <Link to="/">Home</Link>
          <span>/</span>
          <span>{product.brand_name || "SRU"}</span>
          <span>/</span>
          <span>{product.name}</span>
        </div>
        <section className="product-detail">
          <div className="detail-gallery">
            <div className="detail-image-wrap">
              <img src={toAssetUrl(mainPhoto)} alt={product.name} />
            </div>
            {gallery.length > 1 && (
              <div className="product-thumbs">
                {gallery.map((image, index) => (
                  <button
                    className={index === photoIndex ? "product-thumb active" : "product-thumb"}
                    type="button"
                    key={`${image}-${index}`}
                    onClick={() => setPhotoIndex(index)}
                    aria-label={`View photo ${index + 1}`}
                  >
                    <img src={toAssetUrl(image)} alt={`${product.name} photo ${index + 1}`} />
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="detail-copy">
            <p className="eyebrow">
              {product.brand_name || "SRU"} · {product.category_title}
            </p>
            <h1>{product.name}</h1>
            <div className="price-block">
              <div className="mrp">
                <span>MRP</span>
                <s>{moneyLabel(product.mrp_display)}</s>
              </div>
              <div className="our-price">
                <span>Our Price</span>
                <strong>{moneyLabel(product.selling_price_display)}</strong>
              </div>
            </div>
            <p className="sample-price-note">Sample pricing shown for layout and catalogue demonstration.</p>
            <p className="detail-desc">{product.description}</p>
            <div className="bulk-pricing">
              <strong>Better pricing on bulk orders.</strong>
              <span>WhatsApp us for best price and price matching with comparable offers.</span>
            </div>
            <div className="detail-note">
              Our listed price is for individual requirements. Bulk orders will have better pricing. WhatsApp us for best quote.
            </div>
            <div className="detail-actions">
              <a
                className="btn whatsapp-btn"
                href={whatsappLink(FALLBACK_PHONE, product.name, product.brand_name || "SRU Collection")}
              >
                WhatsApp for best price
              </a>
              <a className="link" href={`mailto:${FALLBACK_EMAIL}`}>
                {FALLBACK_EMAIL}
              </a>
            </div>
          </div>
        </section>
      </main>
      <footer>
        <strong>SRU GLOBAL</strong>
        <span>Corporate gifting and curated catalogues</span>
      </footer>
    </>
  );
}

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div>
      <Header menuOpen={menuOpen} onMenuToggle={() => setMenuOpen((prev) => !prev)} />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/brand" element={<BrandPage />} />
        <Route path="/brand.html" element={<BrandPage />} />
        <Route path="/products/:productId" element={<ProductPage />} />
      </Routes>
    </div>
  );
}
