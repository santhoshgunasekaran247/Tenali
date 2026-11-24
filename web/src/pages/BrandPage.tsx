import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { BulkPricingNote } from "../components/BulkPricingNote";
import { Link, useSearchParams } from "react-router-dom";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import type { CatalogListResponse, StorefrontTemplate } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { ProductCard } from "../features/catalog/components/ProductCard";
import { BrandCard } from "../features/catalog/components/BrandCard";
import { storefrontDisplay } from "../features/catalog/storefrontDisplay";
import { groupProducts } from "../features/catalog/productGroups";
import { toAssetUrl } from "../features/catalog/utils";
import { tenantBase } from "../features/tenantTransport";
import { storefrontText } from "../features/catalog/storefrontText";
import { useAuth } from "../features/auth";
import { MessageCircle, Package } from "lucide-react";
import { useCheckoutAvailability } from "../features/useCheckoutAvailability";

function CatalogThemeBanner({ template, eyebrow, heading, description, image, imageAlt, count, note, actions }: {
  template: StorefrontTemplate;
  eyebrow: string;
  heading: string;
  description?: string;
  image?: string;
  imageAlt?: string;
  count?: string;
  note?: string;
  actions?: ReactNode;
}) {
  const media = image ? <img src={image} alt={imageAlt || ""} loading="lazy" /> : <Package size={32} aria-hidden="true" />;
  if (template === "boutique") {
    return <section className="theme-catalog-banner theme-catalog-banner--boutique">
      <div><p className="eyebrow">{eyebrow}</p><h1>{heading}</h1>{description ? <p className="lead">{description}</p> : null}
        {note ? <p className="catalog-note">{note}</p> : null}{count ? <span className="catalog-count">{count}</span> : null}{actions}</div>
      <figure>{media}<figcaption>{imageAlt || heading}</figcaption></figure>
    </section>;
  }
  if (template === "heritage") {
    return <header className="theme-catalog-banner theme-catalog-banner--heritage">
      <span className="heritage-catalog-rule" aria-hidden="true" />
      <div><p className="eyebrow">{eyebrow}</p><h1>{heading}</h1>{description ? <p>{description}</p> : null}
        {note ? <p className="catalog-note">{note}</p> : null}{count ? <span className="catalog-count">{count}</span> : null}{actions}</div>
      {image ? <figure>{media}</figure> : null}
      <span className="heritage-catalog-rule" aria-hidden="true" />
    </header>;
  }
  if (template === "supermarket") {
    return <header className="theme-catalog-banner theme-catalog-banner--supermarket">
      <div><span className="supermarket-catalog-label">{eyebrow}</span><h1>{heading}</h1>{description ? <p>{description}</p> : null}
        {note ? <p className="catalog-note">{note}</p> : null}{actions}</div>
      <strong className="supermarket-catalog-count">{count || "Browse"}</strong>
      {image ? <div className="supermarket-catalog-image">{media}</div> : null}
    </header>;
  }
  if (template === "jewellery") {
    return <header className="theme-catalog-banner theme-catalog-banner--jewellery">
      {image ? <figure>{media}</figure> : null}
      <div><p className="eyebrow">{eyebrow}</p><span className="jewellery-divider" aria-hidden="true" />
        <h1>{heading}</h1>{description ? <p className="lead">{description}</p> : null}
        {note ? <p className="catalog-note">{note}</p> : null}{count ? <span className="catalog-count">{count}</span> : null}{actions}
      </div>
    </header>;
  }
  if (template === "marketplace") {
    return <header className="theme-catalog-banner theme-catalog-banner--marketplace">
      <div><p className="eyebrow">{eyebrow}</p><h1>{heading}</h1>{description ? <p>{description}</p> : null}
        {note ? <p className="catalog-note">{note}</p> : null}{actions}</div>
      <aside><strong>{count || "Explore"}</strong><span>{image ? media : null}</span></aside>
    </header>;
  }
  return <section className="catalog-hero catalog-hero-slim">
    {image ? <div className="catalog-brand-logo">{media}</div> : null}
    <div className="catalog-hero-copy"><p className="eyebrow">{eyebrow}</p><h1>{heading}</h1>
      {description ? <p className="lead">{description}</p> : null}{note ? <p className="catalog-note">{note}</p> : null}
      {count ? <span className="catalog-count">{count}</span> : null}
    </div>
    {actions}
  </section>;
}

export function BrandPage() {
  const {storefront}=useAuth();
  const { availability, error: checkoutError } = useCheckoutAvailability(storefront?.id);
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<CatalogListResponse>();
  const [error, setError] = useState<string>();

  const brand = searchParams.get("brand") || undefined;
  const category = searchParams.get("category") || undefined;
  const search = searchParams.get("q") || undefined;

  useEffect(() => {
    api
      .list({ brand, category, search })
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [brand, category, search]);

  const publicCompany=storefront||{company_name:"Tenali",nickname:undefined};
  const publicCopy=storefront?.storefront_content;
  if (error) {
    return <main className="loading">{storefrontText(publicCopy?.catalog.catalogue_unavailable||"Catalogue unavailable.",publicCompany)} {error}</main>;
  }

  if (!data) {
    return <main className="loading">{storefrontText(publicCopy?.catalog.catalogue_loading||"Loading catalogue...",publicCompany)}</main>;
  }

  const display = storefrontDisplay(data.company);
  const template = data.company.storefront_template || "current";
  const phone = display.whatsapp_enquiry_enabled ? (data.company.phone || FALLBACK_PHONE).replace(/\D/g, "") : "";
  const email = data.company.email || FALLBACK_EMAIL;
  const homeCopy=data.company.storefront_content?.home||{};
  const catalogCopy=data.company.storefront_content?.catalog||{};
  const homeText=(key:string)=>storefrontText(homeCopy[key],data.company);
  const catalogText=(key:string,variables:Record<string,string|number>={})=>storefrontText(catalogCopy[key],data.company,variables);
  // "{count} products" reads "1 product" for a single item; custom wording without "products" is left as written.
  const productCount=(count:number)=>{const label=catalogText("product_count",{count});return count===1?label.replace(/\b(products)\b/i,word=>word.slice(0,-1)):label;};
  const categoryFilters = <nav className="storefront-catalog-filters" aria-label="Browse categories">
    <Link to="/brand?category=all">All categories</Link>
    {data.categories.map(item => <Link key={item.id} to={`/brand?category=${encodeURIComponent(item.category_slug)}`}
      aria-current={category === item.category_slug ? "page" : undefined}>{item.category_title}</Link>)}
  </nav>;

  if (searchParams.get("view") === "brands" && !brand && !category && !search) {
    return <>
      <main id="brand-page" className={`storefront-catalog storefront-commerce-page storefront-catalog--${template}`}>
        <CatalogThemeBanner template={template} eyebrow={homeText("brands_eyebrow")} heading="All brands"
          description={homeText("brands_description")} count={`${data.brands.length} brands`}
          actions={<div className="actions"><Link className="btn" to="/">{catalogText("back_home")}</Link></div>} />
        <section className="product-section brand-index-section" aria-label="All brands">
          {data.brands.length ? <div className="brand-grid">{data.brands.map(item =>
            <BrandCard key={item.id} brand={item} template={template} action={homeText("brand_action") || "View products"} />)}
          </div> : <p className="empty">No brands available yet.</p>}
        </section>
      </main>
      <SiteFooter company={data.company} />
    </>;
  }

  if (category === "all") {
    return (
      <>
        <main id="brand-page" className={`storefront-catalog storefront-commerce-page storefront-catalog--${template}`}>
          <CatalogThemeBanner template={template}
            eyebrow={catalogText("all_categories_eyebrow")}
            heading={`${catalogText("all_categories_heading_first")} ${catalogText("all_categories_heading_second")}`}
            description={catalogText("all_categories_description")}
            count={`${data.categories.length} categories`}
            actions={<div className="actions">
                <a className="btn" href={`${tenantBase()}/#categories`}>{catalogText("back_home")}</a>
                {phone?<a className="link" href={`https://wa.me/${phone}`}>
                  {catalogText("whatsapp_us")}
                </a>:null}
              </div>} />
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
                  to={`/brand?category=${encodeURIComponent(item.category_slug)}`}
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
        <SiteFooter company={data.company} />
      </>
    );
  }

  if (category && !data.selected_category) {
    return (
      <>
        <main className="empty">
          <h1>{catalogText("category_not_found")}</h1>
          <Link className="btn" to="/brand?category=all">
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
          <Link className="btn" to="/brand?view=brands">
            {catalogText("back_to_brands")}
          </Link>
        </main>
        <SiteFooter />
      </>
    );
  }

  if (!brand && !category && search) {
    return (
      <>
        <main id="brand-page" className={`storefront-catalog storefront-commerce-page storefront-catalog--${template}`}>
          <CatalogThemeBanner template={template} eyebrow="PRODUCT SEARCH" heading={`Results for “${search}”`}
            description={productCount(data.products.length)} count={productCount(data.products.length)} />
          {categoryFilters}
          {checkoutError ? <p className="checkout-notice" role="alert">Online checkout unavailable: {checkoutError}</p> : null}
          <section className="product-section catalog-products">
            {data.products.length ? <div className="product-grid compact-product-grid" role="region" aria-label={`Search results for ${search}`}>
              {data.products.map((product) => <ProductCard key={product.id} product={product} phone={phone} checkoutEnabled={!!availability?.enabled} template={template} />)}
            </div> : <div className="empty">No products found for “{search}”.</div>}
          </section>
        </main>
        <SiteFooter company={data.company} />
      </>
    );
  }

  if (!brand && !category) {
    return (
      <>
        <main className="empty">
          <h1>{catalogText("brand_not_found")}</h1>
          <Link className="btn" to="/brand?view=brands">
            {catalogText("back_to_brands")}
          </Link>
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
  const backHref = tenantBase()+(isCategoryView ? "/brand?category=all" : "/brand?view=brands");
  const backLabel = catalogText(isCategoryView ? "all_categories_link" : "all_brands_link");
  const bestPricingMessage = encodeURIComponent(storefrontText(catalogCopy.whatsapp_prefilled_message,data.company,{brand_name:heading}));
  const firstProductImage = isCategoryView ? data.products.map((item) => item.image_urls?.split("|").map((image) => image.trim()).find(Boolean) || item.image_url).find(Boolean) : undefined;
  const heroImage = isCategoryView
    ? toAssetUrl(firstProductImage || data.selected_category!.image_url)
    : toAssetUrl(`brand-logos/${data.selected_brand!.code}.png`);
  const heroAlt = isCategoryView ? heading : `${heading} logo`;
  const productGroups = groupProducts(data.products, (product) => (isCategoryView ? product.brand_name : product.category_title) || heading);

  return (
    <>
      <main id="brand-page" className={`storefront-catalog storefront-commerce-page storefront-catalog--${template}`}>
        <CatalogThemeBanner template={template} eyebrow={eyebrow} heading={heading} description={lead}
          image={heroImage} imageAlt={heroAlt} note={catalogText("sample_price_note")}
          count={productCount(data.products.length)}
          actions={<div className="actions catalog-hero-actions">
            {phone?<a className="btn whatsapp-btn hero-whatsapp" href={`https://wa.me/${phone}?text=${bestPricingMessage}`}>
              <MessageCircle size={15} aria-hidden="true" /><span>{catalogText("whatsapp_best_pricing")}</span>
            </a>:null}
            {email?<a className="catalog-hero-email" href={`mailto:${email}`}>{email}</a>:null}
          </div>} />
        {categoryFilters}

        <div className="brand-page-nav catalog-toolbar">
          <a href={backHref}>{backLabel}</a>
          <span className="catalog-count">{productCount(data.products.length)}</span>
        </div>

        <section className="product-section catalog-products">
          <div className="catalog-choose">
            <h2>
              {catalogText("choose_heading_first")}{" "}
              <span>{catalogText("choose_heading_second")}</span>
            </h2>
            <p>{catalogText("choose_description")}</p>
            {display.show_bulk_pricing ? <BulkPricingNote heading={catalogText("best_pricing_heading")} description={catalogText("best_pricing_description")} /> : null}
          </div>
          {checkoutError ? <p className="checkout-notice" role="alert">Online checkout unavailable: {checkoutError}</p> : null}
          {data.products.length ? productGroups.map((group) => (
            <div className="product-rail-group" key={group.name}>
              {productGroups.length > 1 ? <h3 className="product-rail-heading">{group.name} <span>{group.products.length}</span></h3> : null}
              <div className="product-grid compact-product-grid" role="region" aria-label={productGroups.length > 1 ? `${heading}: ${group.name}` : heading}>
                {group.products.map((product) => (
                  <ProductCard key={product.id} product={product} phone={phone} checkoutEnabled={!!availability?.enabled} template={template} />
                ))}
              </div>
            </div>
          )) : (
            <div className="empty">{catalogText("no_products")}</div>
          )}
        </section>
      </main>
      <SiteFooter company={data.company} />
    </>
  );
}
