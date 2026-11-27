import { useEffect, useRef, useState } from "react";
import { BulkPricingNote } from "../components/BulkPricingNote";
import { Link, useLocation } from "react-router-dom";
import { SiteFooter } from "../components/SiteFooter";
import { scrollToSection } from "../components/sectionScroll";
import { api } from "../api";
import type { CatalogHomeResponse, Company, StorefrontSection } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { ProductCard } from "../features/catalog/components/ProductCard";
import { BrandCard } from "../features/catalog/components/BrandCard";
import { ProductRail } from "../components/ProductRail";
import { storefrontDisplay } from "../features/catalog/storefrontDisplay";
import { StorefrontThemeHome } from "../features/catalog/StorefrontThemeHome";
import { toAssetUrl } from "../features/catalog/utils";
import { storefrontText } from "../features/catalog/storefrontText";
import { Package } from "lucide-react";
import { useAuth } from "../features/auth";
import { useCheckoutAvailability } from "../features/useCheckoutAvailability";
import { hasStorefrontLinkOverride, storefrontLink, storefrontSectionId } from "../features/catalog/storefrontLinks";
import { prioritizedItems, storefrontSectionStyle } from "../features/catalog/classicStorefront";

type StorefrontPreviewMessage = {
  type: "tenali-storefront-preview";
  companyId: string;
  company: Pick<Company, "storefront_template" | "site_theme" | "logo_url" | "storefront_content">;
  sections: StorefrontSection[];
};

function applyPreview(data: CatalogHomeResponse, draft: StorefrontPreviewMessage): CatalogHomeResponse {
  return {
    ...data,
    company: { ...data.company, ...draft.company },
    sections: draft.sections.filter(section => section.is_enabled),
    classic_sections_configured: draft.sections.length > 0,
  };
}

export function HomePage() {
  const {storefront}=useAuth();
  const { availability, error: checkoutError } = useCheckoutAvailability(storefront?.id);
  const location = useLocation();
  const [data, setData] = useState<CatalogHomeResponse>();
  const [error, setError] = useState<string>();
  const previewDraft = useRef<StorefrontPreviewMessage | null>(null);
  const previewId = new URLSearchParams(location.search).get("storefrontPreview");

  useEffect(() => {
    let active = true;
    previewDraft.current = null;
    (previewId ? api.storefrontPreview() : api.home())
      .then(result => {
        if (!active) return;
        const home: CatalogHomeResponse = result;
        setData(previewDraft.current ? applyPreview(home, previewDraft.current) : home);
      })
      .catch((e: Error) => { if (active) setError(e.message); });
    const receivePreview = (event: MessageEvent<unknown>) => {
      if (event.origin !== window.location.origin || event.source !== window.parent ||
          !event.data || typeof event.data !== "object") return;
      const message = event.data as StorefrontPreviewMessage;
      if (message.type !== "tenali-storefront-preview" || message.companyId !== previewId ||
          !message.company || !Array.isArray(message.sections)) return;
      previewDraft.current = message;
      setData(previous => previous ? applyPreview(previous, message) : previous);
    };
    if (previewId) {
      window.addEventListener("message", receivePreview);
      window.setTimeout(() => window.parent.postMessage({
        type: "tenali-storefront-preview-ready", companyId: previewId,
      }, window.location.origin), 0);
    }
    return () => {
      active = false;
      window.removeEventListener("message", receivePreview);
    };
  }, [previewId]);
  useEffect(() => {
    if (!data || !location.hash) return;
    let stop: (() => void) | undefined;
    const frame = requestAnimationFrame(() => {
      const target = document.getElementById(location.hash.slice(1));
      if (target) stop = scrollToSection(target);
    });
    return () => { cancelAnimationFrame(frame); stop?.(); };
  }, [data, location.key, location.hash]);

  const publicCompany=storefront||{company_name:"Tenali",nickname:undefined,storefront_content:undefined};
  const loadingCopy=publicCompany.storefront_content?.home||{};
  if (error) {
    return <main className="loading">{storefrontText(loadingCopy.catalogue_unavailable||"Catalogue unavailable.",publicCompany)} {error}</main>;
  }

  if (!data) {
    return <main className="loading">{storefrontText(loadingCopy.catalogue_loading||"Loading catalogue...",publicCompany)}</main>;
  }

  const display = storefrontDisplay(data.company);
  const contactPhone = data.company.phone || FALLBACK_PHONE;
  const phone = display.whatsapp_enquiry_enabled ? contactPhone : "";
  const email = data.company.email || FALLBACK_EMAIL;
  const copy = data.company.storefront_content?.home || {};
  const text = (key: string) => storefrontText(copy[key], data.company);
  const link = (key: string, href: string, label: string, sectionKey?: string) => storefrontLink(data.company, key, href, label, sectionKey);
  const bulkStrip = display.show_bulk_pricing ? (
    <BulkPricingNote heading={text("bulk_title")} description={text("bulk_description")} />
  ) : null;
  const configuredSections = data.sections || [];
  const template = data.company.storefront_template || "current";

  if (template !== "current") {
    return <>
      <StorefrontThemeHome
        template={template}
        data={data}
        phone={phone}
        email={email}
        checkoutEnabled={!!availability?.enabled}
        checkoutError={checkoutError}
        text={text}
        bulkNote={bulkStrip}
      />
      <SiteFooter company={data.company} />
    </>;
  }

  return (
    <>
      <main>
        {!data.classic_sections_configured && !data.sections?.some((section) => section.section_type === "hero") ? <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">{text("hero_eyebrow")}</p>
            <h1>
              {text("hero_heading_first")}<br /><span>{text("hero_heading_second")}</span>
            </h1>
            <p className="lead">{text("hero_description")}</p>
            <div className="actions">
              <Link className="btn" {...link("hero.primary", "/#collection-special", text("hero_primary_action"))} />
              <Link className="link" {...link("hero.secondary", "/#categories", text("hero_secondary_action"))} />
            </div>
          </div>
          <div className="hero-panel">
            <p>{text("hero_service_one")}</p>
            <i />
            <p>{text("hero_service_two")}</p>
            <i />
            <p>{text("hero_service_three")}</p>
          </div>
        </section> : null}

        {data.sections?.length || data.classic_sections_configured ? data.sections.map((section) => {
          const slot = section.configuration.classic_slot;
          const prefix = slot === "best-sellers" ? "best_sellers" : typeof slot === "string" ? slot : "";
          const nativeTitle = (heading: string) => <>
            {text(`${heading}_heading_first`)}<br /><span>{text(`${heading}_heading_second`)}</span>
          </>;
          const presentation = {
            "data-image-ratio": String(section.configuration.image_ratio || (section.section_type === "hero" ? "theme" : "square")),
            "data-image-fit": String(section.configuration.image_fit || "cover"),
            "data-font-family": String(section.configuration.font_family || "default"),
            "data-border-style": String(section.configuration.border_style || "theme"),
            style: storefrontSectionStyle(section.configuration),
          };
          if (slot === "hero") return <section key={section.section_key} id={`section-${section.section_key}`}
            className={`hero storefront-section storefront-section-hero${section.image_url ? " hero-configured" : ""}`} {...presentation}>
            <div className="hero-copy">
              <p className="eyebrow">{text("hero_eyebrow")}</p>
              <h1>{nativeTitle("hero")}</h1>
              <p className="lead">{text("hero_description")}</p>
              <div className="actions">
                <Link className="btn" {...link("hero.primary", "/#collection-special", text("hero_primary_action"), section.section_key)} />
                <Link className="link" {...link("hero.secondary", "/#categories", text("hero_secondary_action"), section.section_key)} />
              </div>
            </div>
            {section.image_url ? <div className="hero-panel hero-image-panel"><img src={toAssetUrl(section.image_url)} alt="" /></div>
              : <div className="hero-panel"><p>{text("hero_service_one")}</p><i /><p>{text("hero_service_two")}</p><i /><p>{text("hero_service_three")}</p></div>}
          </section>;
          return section.section_type === "hero" ? (
          <section key={section.id || section.section_key} id={`section-${section.section_key}`}
            className="hero hero-configured storefront-section storefront-section-hero"
            data-image-ratio={String(section.configuration.image_ratio || "theme")}
            data-image-fit={String(section.configuration.image_fit || "cover")}
            data-font-family={String(section.configuration.font_family || "default")}
            data-border-style={String(section.configuration.border_style || "theme")}
            style={storefrontSectionStyle(section.configuration)}>
            <div className="hero-copy">
              {section.eyebrow ? <p className="eyebrow">{section.eyebrow}</p> : null}
              <h1>{section.title}</h1>
              {section.description ? <p className="lead">{section.description}</p> : null}
              <div className="actions">
                <Link className="btn" {...link("hero.primary",
                  data.sections.find(candidate => candidate.section_type === "products")
                    ? `/#section-${data.sections.find(candidate => candidate.section_type === "products")?.section_key}` : "/brand?category=all",
                  "Shop collections", section.section_key)} />
                <Link className="link" {...link("hero.secondary", "/brand?category=all", "Browse catalogue", section.section_key)} />
              </div>
            </div>
            <div className="hero-panel hero-image-panel">
              {section.image_url ? <img src={toAssetUrl(section.image_url)} alt="" loading="lazy" /> : <p>{data.company.nickname || data.company.company_name}</p>}
            </div>
          </section>
        ) : (
          <section key={section.id || section.section_key}
            id={storefrontSectionId(section, configuredSections)}
            className={`${slot === "brands" ? "brands-section" : "home-section"} storefront-section storefront-section-${section.section_type}${slot === "categories" ? " categories-section" : slot === "best-sellers" ? " featured-section" : slot === "specials" ? " specials-section" : ""}`}
            data-image-ratio={String(section.configuration.image_ratio || "square")}
            data-image-fit={String(section.configuration.image_fit || "cover")}
            data-font-family={String(section.configuration.font_family || "default")}
            data-border-style={String(section.configuration.border_style || "theme")}
            style={{
              backgroundColor: typeof section.configuration.background_color === "string" ? section.configuration.background_color : undefined,
              color: typeof section.configuration.text_color === "string" ? section.configuration.text_color : undefined,
              borderColor: typeof section.configuration.accent_color === "string" ? section.configuration.accent_color : undefined,
            }}>
            {storefrontSectionId(section, configuredSections) !== `section-${section.section_key}` ?
              <span id={`section-${section.section_key}`} className="storefront-section-anchor" aria-hidden="true" /> : null}
            <div className="section-heading">
              {slot ? <p className="eyebrow">{text(`${prefix}_eyebrow`)}</p> : section.eyebrow ? <p className="eyebrow">{section.eyebrow}</p> : null}
              <h2>{slot ? nativeTitle(prefix) : section.title}</h2>
              {slot ? <p>{text(`${prefix}_description`)}</p> : section.description ? <p>{section.description}</p> : null}
              {section.image_url ? <img className="storefront-section-image" src={toAssetUrl(section.image_url)} alt="" loading="lazy" /> : null}
              {hasStorefrontLinkOverride(data.company, "section.view_all", section.section_key) ?
                <Link className="link" {...link("section.view_all", section.section_type === "brands" ? "/brand?view=brands" : "/brand?category=all", "View all", section.section_key)} /> : null}
            </div>
            {section.section_type === "products" ? (
              <>
                {checkoutError ? <p className="checkout-notice" role="alert">Online checkout unavailable: {checkoutError}</p> : null}
                {slot ? bulkStrip : null}
                <ProductRail label={slot ? text(`${prefix}_eyebrow`) : section.title}>
                  {(section.products || []).map((product) => (
                    <ProductCard key={product.id} product={product} phone={phone} checkoutEnabled={!!availability?.enabled} productCopy={data.company.storefront_content?.product} />
                  ))}
                </ProductRail>
              </>
            ) : section.section_type === "categories" ? (
              <><div className="category-grid">
                {(section.categories || []).map((category) => (
                  <Link className="category-card" to={link("category.card", `/brand?category=${encodeURIComponent(category.category_slug)}`, "").to} key={category.id}>
                    <div className="category-image">
                      {category.image_url ? <img src={toAssetUrl(category.image_url)} alt={category.category_title} loading="lazy" /> : <Package size={36} aria-hidden="true" />}
                    </div>
                    <div className="category-body">
                      {slot ? <p className="eyebrow">{text("category_card_eyebrow")}</p> : null}
                      <h3>{category.category_title}</h3>
                      <p>{category.category_description}</p>
                      {slot ? <span>{link("category.card", "", text("category_action")).children}</span> : null}
                    </div>
                  </Link>
                ))}
              </div>
              {slot ? <div className="category-more"><Link className="link" {...link("categories.more", "/brand?category=all", text("categories_more_action"))} /></div> : null}</>
            ) : (
              <ProductRail label={section.title} className="brand-rail">
                {(section.brands || []).map((brand) => (
                  <BrandCard key={brand.id} brand={brand} caption={slot ? text("brand_catalog_label") : brand.description}
                    href={link("brand.card", `/brand?brand=${encodeURIComponent(brand.code)}`, "").to} action={link("brand.card", "", text("brand_action")).children} />
                ))}
              </ProductRail>
            )}
          </section>
        ); }) : <>
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
            {data.categories.map((category) => (
              <Link
                className="category-card"
                to={link("category.card", `/brand?category=${encodeURIComponent(category.category_slug)}`, "").to}
                key={category.category_slug}
              >
                <div className="category-image">
                    {category.image_url?<img src={toAssetUrl(category.image_url)} alt={category.category_title} loading="lazy" />:<Package size={36} aria-hidden="true"/>}
                </div>
                <div className="category-body">
                  <p className="eyebrow">{text("category_card_eyebrow")}</p>
                  <h3>{category.category_title}</h3>
                  <p>{category.category_description}</p>
                  <span>{link("category.card", "", text("category_action")).children}</span>
                </div>
              </Link>
            ))}
          </div>
          <div className="category-more">
            <Link className="link" {...link("categories.more", "/brand?category=all", text("categories_more_action"))} />
          </div>
        </section>

        <section id="best-sellers" className="home-section featured-section">
          {checkoutError ? <p className="checkout-notice" role="alert">Online checkout unavailable: {checkoutError}</p> : null}
          <div className="section-heading">
            <p className="eyebrow">{text("best_sellers_eyebrow")}</p>
            <h2>
              {text("best_sellers_heading_first")}
              <br />
              <span>{text("best_sellers_heading_second")}</span>
            </h2>
            <p>{text("best_sellers_description")}</p>
          </div>
          {bulkStrip}
          <ProductRail label={text("best_sellers_eyebrow") || "Best sellers"}>
            {prioritizedItems(data.best_sellers, data.catalog_products || []).map((product) => (
              <ProductCard key={product.id} product={product} phone={phone} checkoutEnabled={!!availability?.enabled} productCopy={data.company.storefront_content?.product} />
            ))}
          </ProductRail>
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
          {bulkStrip}
          <ProductRail label={text("specials_eyebrow") || "Specials"}>
            {prioritizedItems(data.sru_specials, data.catalog_products || []).map((product) => (
              <ProductCard key={product.id} product={product} phone={phone} checkoutEnabled={!!availability?.enabled} productCopy={data.company.storefront_content?.product} />
            ))}
          </ProductRail>
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
          <ProductRail label={text("brands_eyebrow") || "Brands"} className="brand-rail">
            {data.brands.map((brand) => (
              <BrandCard key={brand.id} brand={brand} caption={text("brand_catalog_label")}
                href={link("brand.card", `/brand?brand=${encodeURIComponent(brand.code)}`, "").to} action={link("brand.card", "", text("brand_action")).children} />
            ))}
          </ProductRail>
        </section>
        </>}

        <section id="why" className="corporate">
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
            {phone || data.company.storefront_content?.links?.["why.contact"]?.href ?
              <Link className="btn light" {...link("why.contact", `https://wa.me/${phone.replace(/\D/g, "")}`, text("contact_whatsapp_label"))} /> : null}
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
            {phone || data.company.storefront_content?.links?.["contact.whatsapp"]?.href ?
              <Link className="btn whatsapp-btn" {...link("contact.whatsapp", `https://wa.me/${phone.replace(/\D/g, "")}`, `${text("contact_whatsapp_label")} ${phone}`)} /> : null}
            {!phone && contactPhone ? <Link className="btn light" {...link("contact.phone", `tel:${contactPhone.replace(/[^\d+]/g, "")}`, contactPhone)} /> : null}
            {email || data.company.storefront_content?.links?.["contact.email"]?.href ?
              <Link className="link" {...link("contact.email", `mailto:${email}`, email)} /> : null}
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
      <SiteFooter company={data.company} />
    </>
  );
}
