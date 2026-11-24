import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Package } from "lucide-react";
import { ProductRail } from "../../components/ProductRail";
import { ProductCard } from "./components/ProductCard";
import { toAssetUrl } from "./utils";
import type { CatalogHomeResponse, StorefrontSection, StorefrontTemplate } from "../../types";
import { classicSections } from "./classicStorefront";
import { MARKETPLACE_IMAGES } from "./marketplaceImages";
import { BOUTIQUE_IMAGES } from "./boutiqueImages";
import { BrandCard } from "./components/BrandCard";
import { hasStorefrontLinkOverride, storefrontLink, storefrontSectionId as sectionId } from "./storefrontLinks";

type Theme = Exclude<StorefrontTemplate, "current">;

type StorefrontThemeHomeProps = {
  template: Theme;
  data: CatalogHomeResponse;
  phone: string;
  email: string;
  checkoutEnabled: boolean;
  checkoutError?: string;
  text: (key: string) => string;
  bulkNote: ReactNode;
};

function defaultSections(data: CatalogHomeResponse, text: (key: string) => string): StorefrontSection[] {
  const section = (
    section_key: string,
    section_type: StorefrontSection["section_type"],
    title: string,
    eyebrow: string,
    description: string,
    values: Partial<StorefrontSection> = {},
  ): StorefrontSection => ({
    section_key, section_type, title, eyebrow, description, sort_order: 0,
    is_enabled: true, configuration: {}, ...values,
  });
  return [
    section("theme-hero", "hero", `${text("hero_heading_first")} ${text("hero_heading_second")}`,
      text("hero_eyebrow"), text("hero_description")),
    section("theme-categories", "categories", `${text("categories_heading_first")} ${text("categories_heading_second")}`,
      text("categories_eyebrow"), text("categories_description"), { categories: data.categories }),
    section("theme-best-sellers", "products", `${text("best_sellers_heading_first")} ${text("best_sellers_heading_second")}`,
      text("best_sellers_eyebrow"), text("best_sellers_description"), { products: data.best_sellers }),
    section("theme-specials", "products", `${text("specials_heading_first")} ${text("specials_heading_second")}`,
      text("specials_eyebrow"), text("specials_description"), { products: data.sru_specials }),
    section("theme-brands", "brands", `${text("brands_heading_first")} ${text("brands_heading_second")}`,
      text("brands_eyebrow"), text("brands_description"), { brands: data.brands }),
  ];
}

function SectionImage({ src, alt }: { src?: string | null; alt: string }) {
  return <span className="theme-category-image">
    {src ? <img src={toAssetUrl(src)} alt={alt} loading="lazy" /> : <Package size={28} aria-hidden="true" />}
  </span>;
}

function ThemeHero({ template, section, sections, companyName, company, text }: {
  template: Theme;
  section: StorefrontSection;
  sections: StorefrontSection[];
  companyName: string;
  company: CatalogHomeResponse["company"];
  text: (key: string) => string;
}) {
  const target = sections.find(item => item.section_type === "products");
  const primaryHref = target ? `#${sectionId(target, sections)}` : "/brand?category=all";
  const link = (key: string, href: string, label: string) => storefrontLink(company, key, href, label, section.section_key);
  const imageUrl = section.image_url || (template === "marketplace" ? MARKETPLACE_IMAGES.hero
    : template === "boutique" ? BOUTIQUE_IMAGES.hero : undefined);
  const image = imageUrl
    ? <img src={toAssetUrl(imageUrl)} alt="" loading="eager" />
    : <div className="theme-hero-art-placeholder" aria-hidden="true"><span>{companyName}</span></div>;
  const config = section.configuration;
  const presentation = {
    id: `section-${section.section_key}`,
    "data-image-ratio": String(config.image_ratio || "square"),
    "data-image-fit": String(config.image_fit || "cover"),
    "data-font-family": String(config.font_family || "default"),
    "data-border-style": String(config.border_style || "theme"),
    style: {
      backgroundColor: typeof config.background_color === "string" ? config.background_color : undefined,
      color: typeof config.text_color === "string" ? config.text_color : undefined,
      borderColor: typeof config.accent_color === "string" ? config.accent_color : undefined,
    },
  };
  const titleId = `storefront-hero-title-${section.section_key}`;
  const actions = <div className="actions theme-hero-actions">
    <Link className="btn" {...link("hero.primary", primaryHref, template === "marketplace" || template === "boutique" ? text("hero_primary_action") : "Shop collections")} />
    <Link className="link" {...link("hero.secondary", "/brand?category=all", template === "marketplace" || template === "boutique" ? text("hero_secondary_action") : "Browse catalogue")} />
  </div>;
  const eyebrow = section.eyebrow || text("hero_eyebrow");
  const description = section.description || text("hero_description");

  if (template === "boutique") {
    return <section {...presentation} className="storefront-section theme-hero theme-hero-boutique" aria-labelledby={titleId}>
      <div className="boutique-cover-grid">
        <div className="boutique-cover-copy">
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h1 id={titleId}>{section.title}</h1>
          {description ? <p className="lead">{description}</p> : null}
          {actions}
        </div>
        <figure className="boutique-cover-art">{image}<figcaption>{text("hero_service_one")}</figcaption></figure>
      </div>
      <div className="boutique-editorial">{["one", "two", "three"].map(key =>
        <span key={key}>{text(`hero_service_${key}`)}</span>)}</div>
    </section>;
  }

  if (template === "heritage") {
    return <section {...presentation} className="storefront-section theme-hero theme-hero-heritage" aria-labelledby={titleId}>
      <div className="heritage-story-frame">
        <div className="heritage-story-copy">
          <span className="heritage-ornament" aria-hidden="true">✦</span>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h1 id={titleId}>{section.title}</h1>
          {description ? <p className="lead">{description}</p> : null}
          {actions}
        </div>
        <figure className="heritage-story-art">{image}<figcaption>{companyName}</figcaption></figure>
        <div className="heritage-story-rule" aria-hidden="true" />
      </div>
      <div className="heritage-value-line"><span>{text("hero_service_one")}</span><i /><span>{text("hero_service_two")}</span><i /><span>{text("hero_service_three")}</span></div>
    </section>;
  }

  if (template === "supermarket") {
    return <section {...presentation} className="storefront-section theme-hero theme-hero-supermarket" aria-labelledby={titleId}>
      <div className="supermarket-promo-shell">
        <div className="supermarket-promo-copy">
          <p className="supermarket-offer-label">{eyebrow || "Shop local, shop smart"}</p>
          <h1 id={titleId}>{section.title}</h1>
          {description ? <p>{description}</p> : null}
          {actions}
        </div>
        <div className="supermarket-promo-art">{image}<span className="supermarket-promo-stamp">Good finds<br />all in one place</span></div>
      </div>
      <div className="supermarket-service-bar"><span>{text("hero_service_one")}</span><span>{text("hero_service_two")}</span><span>{text("hero_service_three")}</span></div>
    </section>;
  }

  if (template === "jewellery") {
    return <section {...presentation} className="storefront-section theme-hero theme-hero-jewellery" aria-labelledby={titleId}>
      <div className="jewellery-campaign-image">{image}<span>THE {companyName} COLLECTION</span></div>
      <div className="jewellery-campaign-copy">
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1 id={titleId}>{section.title}</h1>
        <span className="jewellery-divider" aria-hidden="true" />
        {description ? <p className="lead">{description}</p> : null}
        {actions}
        <p className="jewellery-craft-note">{text("hero_service_one")} · {text("hero_service_two")}</p>
      </div>
    </section>;
  }

  return <section {...presentation} className="storefront-section theme-hero theme-hero-marketplace" aria-labelledby={titleId}>
    <div className="marketplace-masthead">
      <div className="marketplace-hero-copy">
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1 id={titleId}>{section.title}</h1>
        {description ? <p className="lead">{description}</p> : null}
        {actions}
      </div>
      <div className="marketplace-promo-card">
        {image}
        <div className="marketplace-promo-caption"><strong>{companyName}</strong><span>Discover something you will love</span></div>
      </div>
      <aside className="marketplace-quick-links" aria-label="Explore the store">
        <Link to={link("quick.categories", "/#categories", "").to}><span className="eyebrow">{text("hero_service_one")}</span><strong>{link("quick.categories", "", text("hero_secondary_action")).children}</strong><span>{text("categories_eyebrow")}</span></Link>
        <Link to={link("quick.about", "/#collection-special", "").to}><span className="eyebrow">{text("hero_service_two")}</span><strong>{link("quick.about", "", text("hero_primary_action")).children}</strong><span>{text("hero_service_three")}</span></Link>
      </aside>
    </div>
    <div className="marketplace-service-bar">{["one", "two", "three"].map((key, index) =>
      <div key={key}><span className="marketplace-service-icon" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span><div><strong>{text(`collection_point_${key}_title`)}</strong><span>{text(`collection_point_${key}_body`)}</span></div></div>)}</div>
  </section>;
}

function CategorySection({ template, section, text, company }: { template: Theme; section: StorefrontSection; text: (key: string) => string; company: CatalogHomeResponse["company"] }) {
  const categories = section.categories || [];
  const destination = (slug: string) => storefrontLink(company, "category.card", `/brand?category=${encodeURIComponent(slug)}`, "").to;
  if (template === "boutique") {
    return <div className="boutique-category-grid">{categories.map(category => (
      <Link className="boutique-category-card" to={destination(category.category_slug)} key={category.id}>
        <SectionImage src={category.image_url} alt={category.category_title} />
        <h3>{category.category_title}</h3>
        {category.category_description ? <p>{category.category_description}</p> : null}
        <span className="boutique-card-action">{storefrontLink(company, "category.card", "", text("category_action")).children}</span>
      </Link>
    ))}</div>;
  }
  if (template === "heritage") {
    return <div className="heritage-category-list">{categories.map((category, index) => (
      <Link className="heritage-category-item" to={destination(category.category_slug)} key={category.id}>
        <span className="heritage-category-index">{String(index + 1).padStart(2, "0")}</span>
        <div><p className="eyebrow">Explore the collection</p><h3>{category.category_title}</h3><span>{category.category_description}</span></div>
        <SectionImage src={category.image_url} alt={category.category_title} />
      </Link>
    ))}</div>;
  }
  if (template === "supermarket") {
    return <nav className="supermarket-aisle-grid" aria-label={section.title}>{categories.map(category => (
      <Link className="supermarket-aisle" to={destination(category.category_slug)} key={category.id}>
        <SectionImage src={category.image_url} alt="" /><strong>{category.category_title}</strong>
      </Link>
    ))}</nav>;
  }
  if (template === "jewellery") {
    return <div className="jewellery-collection-grid">{categories.map(category => (
      <Link className="jewellery-collection-card" to={destination(category.category_slug)} key={category.id}>
        <SectionImage src={category.image_url} alt={category.category_title} />
        <span>THE COLLECTION</span><h3>{category.category_title}</h3><p>{category.category_description}</p>
      </Link>
    ))}</div>;
  }
  return <nav className="marketplace-category-dock" aria-label={section.title}>{categories.map(category => (
    <Link className="marketplace-category-tile" to={destination(category.category_slug)} key={category.id}>
      <SectionImage src={category.image_url} alt="" /><strong>{category.category_title}</strong><span className="marketplace-category-action">{storefrontLink(company, "category.card", "", text("category_action") || "Shop now").children} →</span>
    </Link>
  ))}</nav>;
}

function BrandSection({ template, section, text, company }: {
  template: Theme;
  section: StorefrontSection;
  text: (key: string) => string;
  company: CatalogHomeResponse["company"];
}) {
  const brands = section.brands || [];
  const destination = (code: string) => storefrontLink(company, "brand.card", `/brand?brand=${encodeURIComponent(code)}`, "").to;
  if (template === "boutique") {
    return <div className="boutique-brand-list">{brands.map(brand => (
      <BrandCard key={brand.id} brand={brand} template={template} caption={text("brand_catalog_label")}
        href={destination(brand.code)} action={storefrontLink(company, "brand.card", "", text("brand_action")).children} />
    ))}</div>;
  }
  if (template === "heritage") {
    return <div className="heritage-brand-seals">{brands.map(brand => (
      <Link to={destination(brand.code)} key={brand.code}>
        <span className="heritage-brand-monogram">{brand.name.slice(0, 1)}</span><strong>{brand.name}</strong><span>{brand.description || text("brand_catalog_label")}</span>
      </Link>
    ))}</div>;
  }
  if (template === "supermarket") {
    return <div className="supermarket-brand-shelf">{brands.map(brand => (
      <Link to={destination(brand.code)} key={brand.code}>
        <img src={toAssetUrl(`brand-logos/${brand.code}.png`)} alt={brand.name} loading="lazy" /><strong>{brand.name}</strong>
      </Link>
    ))}</div>;
  }
  if (template === "jewellery") {
    return <div className="jewellery-brand-row">{brands.map(brand => (
      <Link to={destination(brand.code)} key={brand.code}>
        <span>{brand.name.slice(0, 1)}</span><strong>{brand.name}</strong>
      </Link>
    ))}</div>;
  }
  return <div className="marketplace-brand-grid">{brands.map(brand => (
    <BrandCard key={brand.id} brand={brand} template={template} caption={text("brand_catalog_label")}
      href={destination(brand.code)} action={storefrontLink(company, "brand.card", "", text("brand_action")).children} />
  ))}</div>;
}

function ProductSection({ template, section, phone, checkoutEnabled, checkoutError, bulkNote, productCopy }: {
  template: Theme;
  section: StorefrontSection;
  phone: string;
  checkoutEnabled: boolean;
  checkoutError?: string;
  bulkNote: ReactNode;
  productCopy?: Record<string, string>;
}) {
  const products = section.products || [];
  const cards = products.map(product => <ProductCard key={product.id} product={product} phone={phone} checkoutEnabled={checkoutEnabled} template={template} productCopy={productCopy} />);
  const alert = checkoutError ? <p className="checkout-notice" role="alert">Online checkout unavailable: {checkoutError}</p> : null;
  if (template === "marketplace" || template === "supermarket") {
    return <>{alert}{bulkNote}<div className={`${template}-product-grid`} role="region" aria-label={section.title}>{cards}</div></>;
  }
  const railClass = template === "boutique" ? "boutique-product-rail"
    : template === "heritage" ? "heritage-product-rail" : "jewellery-product-rail";
  return <>{alert}{bulkNote}<ProductRail label={section.title} className={railClass}>{cards}</ProductRail></>;
}

export function StorefrontThemeHome({
  template, data, phone, email, checkoutEnabled, checkoutError, text, bulkNote,
}: StorefrontThemeHomeProps) {
  const usesClassicSections = template === "marketplace" || template === "boutique";
  const sourceSections = usesClassicSections && !data.sections?.length && !data.classic_sections_configured
    ? classicSections(data) : data.sections || [];
  const configured = sourceSections.filter(section => section.is_enabled).map(section => {
    const slot = section.configuration.classic_slot;
    if (typeof slot !== "string") return section;
    const prefix = slot === "best-sellers" ? "best_sellers" : slot;
    return {
      ...section,
      eyebrow: text(`${prefix}_eyebrow`),
      title: `${text(`${prefix}_heading_first`)} ${text(`${prefix}_heading_second`)}`.trim(),
      description: text(`${prefix}_description`),
    };
  });
  const hasClassicSections = data.classic_sections_configured || sourceSections.some(section => !!section.configuration.classic_slot);
  const hasConfiguredSections = hasClassicSections || (template === "boutique" && sourceSections.length > 0);
  const sections = configured.length || (usesClassicSections && hasConfiguredSections) ? configured : defaultSections(data, text);
  if (!sections.some(section => section.section_type === "hero") && !(usesClassicSections && hasConfiguredSections)) {
    sections.unshift(defaultSections(data, text)[0]);
  }
  const companyName = data.company.nickname || data.company.company_name;
  const firstProductSection = sections.find(section => section.section_type === "products");
  const storyHeading = `${text("why_heading_first")} ${text("why_heading_second")}`;
  const link = (key: string, href: string, label: string, sectionKey?: string) => storefrontLink(data.company, key, href, label, sectionKey);

  return <main className={`storefront-theme-home storefront-theme-home--${template}`}>
    {sections.map(section => {
      if (section.section_type === "hero") {
        return <ThemeHero key={section.section_key} template={template} section={section} sections={sections} companyName={companyName} company={data.company} text={text} />;
      }
      const style = {
        backgroundColor: typeof section.configuration.background_color === "string" ? section.configuration.background_color : undefined,
        color: typeof section.configuration.text_color === "string" ? section.configuration.text_color : undefined,
        borderColor: typeof section.configuration.accent_color === "string" ? section.configuration.accent_color : undefined,
      };
      return <section key={section.section_key} id={sectionId(section, sections)}
        className={`storefront-section template-section template-section--${template} template-section--${section.section_type}`}
        data-image-ratio={String(section.configuration.image_ratio || "square")}
        data-image-fit={String(section.configuration.image_fit || "cover")}
        data-font-family={String(section.configuration.font_family || "default")}
        data-border-style={String(section.configuration.border_style || "theme")}
        style={style}>
        {sectionId(section, sections) !== `section-${section.section_key}` ?
          <span id={`section-${section.section_key}`} className="storefront-section-anchor" aria-hidden="true" /> : null}
        <header className={`template-section-heading template-section-heading--${template}`}>
          <div className="template-section-copy">
          {section.eyebrow ? <p className="eyebrow">{section.eyebrow}</p> : null}
          <h2>{section.title}</h2>
          {section.description ? <p>{section.description}</p> : null}
          {section.image_url ? <img className="storefront-section-image" src={toAssetUrl(section.image_url)} alt="" loading="lazy" /> : null}
          </div>
          {template === "marketplace" || template === "boutique" || template === "supermarket" || hasStorefrontLinkOverride(data.company, "section.view_all", section.section_key) ?
            <Link {...link("section.view_all", section.section_type === "brands" ? "/brand?view=brands" : "/brand?category=all", "View all →", section.section_key)} /> : null}
        </header>
        {section.section_type === "products" ? (
          <ProductSection template={template} section={section} phone={phone}
            checkoutEnabled={checkoutEnabled} checkoutError={checkoutError} bulkNote={bulkNote} productCopy={data.company.storefront_content?.product} />
        ) : section.section_type === "categories" ? <CategorySection template={template} section={section} text={text} company={data.company} />
          : <BrandSection template={template} section={section} text={text} company={data.company} />}
      </section>;
    })}
    {template === "marketplace" ? <section id="why" className="marketplace-story marketplace-why">
      <img className="marketplace-story-image" src={MARKETPLACE_IMAGES.story} alt="" loading="lazy" />
      <div><p className="eyebrow">{text("why_eyebrow")}</p><h2>{storyHeading}</h2></div>
      <p>{text("why_description")}</p>
      {hasStorefrontLinkOverride(data.company, "why.contact") ?
        <Link className="btn" {...link("why.contact", phone ? `https://wa.me/${phone.replace(/\D/g, "")}` : "/#contact", text("contact_whatsapp_label"))} /> : null}
    </section> : null}
    {template === "boutique" ? <section id="why" className="boutique-journal">
      {(["why_left", "why_right"] as const).map(key => {
        const saved = data.company.storefront_content?.images?.[key];
        const src = saved === undefined ? BOUTIQUE_IMAGES[key] : saved;
        return src ? <img key={key} src={toAssetUrl(src)} alt="" loading="lazy" className={`boutique-journal-${key}`} /> : null;
      })}
      <div className="boutique-journal-copy"><p className="eyebrow">{text("why_eyebrow")}</p>
        <h2>{storyHeading}</h2><p>{text("why_description")}</p>
        {hasStorefrontLinkOverride(data.company, "why.contact") ?
          <Link className="link" {...link("why.contact", phone ? `https://wa.me/${phone.replace(/\D/g, "")}` : "/#contact", text("contact_whatsapp_label"))} /> : null}
      </div>
    </section> : null}
    {template === "heritage" ? <section id="collection-special" className="heritage-closing-note">
      <p className="eyebrow">{text("collection_eyebrow")}</p><h2>{storyHeading}</h2><p>{text("why_description")}</p>
    </section> : template === "jewellery" ? <section id="collection-special" className="jewellery-closing-note">
      <span className="jewellery-divider" aria-hidden="true" /><p className="eyebrow">{text("collection_eyebrow")}</p>
      <h2>{storyHeading}</h2><p>{text("collection_description")}</p>
    </section> : template === "boutique" ? <section id="collection-special" className="boutique-closing-note">
      <p className="eyebrow">{text("collection_eyebrow")}</p>
      <h2>{text("collection_heading_first")} {text("collection_heading_second")}</h2><p>{text("collection_description")}</p>
      <div className="boutique-about-points">{["one", "two", "three"].map(key =>
        <div key={key}><h3>{text(`collection_point_${key}_title`)}</h3><p>{text(`collection_point_${key}_body`)}</p></div>)}</div>
    </section> : <section id="contact" className={`template-contact template-contact--${template}`}>
      <div><p className="eyebrow">{text("contact_eyebrow")}</p><h2>{text("contact_heading_first")} {text("contact_heading_second")}</h2></div>
      <div><p>{text("contact_description")}</p>
        {phone || data.company.storefront_content?.links?.["contact.whatsapp"]?.href ?
          <Link className="btn whatsapp-btn" {...link("contact.whatsapp", `https://wa.me/${phone.replace(/\D/g, "")}`, text("contact_whatsapp_label"))} /> : null}
        {email || data.company.storefront_content?.links?.["contact.email"]?.href ?
          <Link className="link" {...link("contact.email", `mailto:${email}`, email)} /> : null}
      </div>
    </section>}
    {template === "boutique" || template === "heritage" || template === "jewellery" ? <section id="contact" className={`template-contact template-contact--${template}`}>
      <p className="eyebrow">{text("contact_eyebrow")}</p><h2>{text("contact_heading_first")} {text("contact_heading_second")}</h2>
      <p>{text("contact_description")}</p>
      <div className="contact-actions">
        {phone || data.company.storefront_content?.links?.["contact.whatsapp"]?.href ?
          <Link className="btn whatsapp-btn" {...link("contact.whatsapp", `https://wa.me/${phone.replace(/\D/g, "")}`, `${text("contact_whatsapp_label")} ${phone}`)} /> : null}
        {email || data.company.storefront_content?.links?.["contact.email"]?.href ?
          <Link className="link" {...link("contact.email", `mailto:${email}`, email)} /> : null}
        {template === "boutique" && (data.company.phone || data.company.storefront_content?.links?.["contact.phone"]?.href) ?
          <Link className="link" {...link("contact.phone", `tel:${(data.company.phone || "").replace(/[^\d+]/g, "")}`, data.company.phone || "Phone")} /> : null}
      </div>
    </section> : null}
    {template === "marketplace" ? <section id="collection-special" className="marketplace-story marketplace-about">
      <img className="marketplace-story-image" src={MARKETPLACE_IMAGES.collection} alt="" loading="lazy" />
      <div><p className="eyebrow">{text("collection_eyebrow")}</p><h2>{text("collection_heading_first")} {text("collection_heading_second")}</h2><p>{text("collection_description")}</p></div>
      <div className="marketplace-about-points">{["one", "two", "three"].map(key =>
        <div key={key}><strong>{text(`collection_point_${key}_title`)}</strong><p>{text(`collection_point_${key}_body`)}</p></div>)}</div>
    </section> : null}
    {!firstProductSection ? <Link className="storefront-theme-catalog-link" {...link("catalog.explore", "/brand?category=all", "Explore the catalogue")} /> : null}
  </main>;
}
