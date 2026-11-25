import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronUp, Monitor, Plus, Save, Smartphone, Trash2, Upload } from "lucide-react";
import { api } from "../api";
import { FloatingAlert } from "../components/Notifications";
import { SITE_THEME_FIELDS, STOREFRONT_THEME_PALETTES, normalizeSiteTheme, storefrontSiteTheme } from "../features/siteTheme";
import { tenantBase } from "../features/tenantTransport";
import { toAssetUrl } from "../features/catalog/utils";
import { CLASSIC_COPY_FIELDS, classicSections } from "../features/catalog/classicStorefront";
import { storefrontPreviewSections } from "../features/catalog/storefrontPreview";
import { BOUTIQUE_IMAGES } from "../features/catalog/boutiqueImages";
import { HERITAGE_IMAGES, SUPERMARKET_IMAGES, JEWELLERY_IMAGES } from "../features/catalog/themeImages";
import { isStorefrontHref, MAX_STOREFRONT_MENU_ITEMS, storefrontHeaderMenu, storefrontLinkDefinitions, storefrontSectionTargets, type StorefrontLinkDefinition, type StorefrontLinkSetting } from "../features/catalog/storefrontLinks";
import type { CatalogStorefrontPreviewResponse, CompanySetup, CompanyUpdateInput, StorefrontMenuItem, StorefrontSection, StorefrontTemplate } from "../types";

type SectionOptions = {
  products: Array<{ id: string; name: string; brand_name?: string; is_active: boolean; catalog_visible: boolean }>;
  categories: Array<{ id: string; name: string; is_active: boolean }>;
  brands: Array<{ id: string; name: string; is_active: boolean }>;
};

const templates: Array<[StorefrontTemplate, string, string]> = [
  ["current", "Classic", "The current Tenali storefront"],
  ["marketplace", "Marketplace", "Dense, fast-shopping product discovery"],
  ["category_first", "Category First", "Amazon-style direct category browsing"],
  ["boutique", "Boutique", "Editorial, curated collections"],
  ["heritage", "Heritage India", "Craft, origin and cultural storytelling"],
  ["supermarket", "Supermarket", "Everyday value and quick category access"],
  ["jewellery", "Jewellery", "Premium product and occasion-led presentation"],
];

const storyImages = [
  ["heritage", "heritage_story", "Craft story image", HERITAGE_IMAGES.story],
  ["supermarket", "supermarket_story", "Fresh picks story image", SUPERMARKET_IMAGES.story],
  ["jewellery", "jewellery_story", "Atelier story image", JEWELLERY_IMAGES.story],
] as const;

type PreviewMessage = {
  type: "tenali-storefront-preview";
  companyId: string;
  company: Pick<CompanySetup, "storefront_template" | "site_theme" | "logo_url" | "storefront_content">;
  sections: StorefrontSection[];
};

function ActionField({ definition, value, targets, onChange, requireDestination = false }: {
  definition: StorefrontLinkDefinition;
  value?: StorefrontLinkSetting;
  targets: Array<{ href: string; label: string }>;
  onChange: (value: StorefrontLinkSetting) => void;
  requireDestination?: boolean;
}) {
  const [custom, setCustom] = useState(false);
  const pages = [
    { href: "/", label: "Homepage" }, { href: "/brand?category=all", label: "All categories / catalogue" },
    { href: "/brand?view=brands", label: "All brands" },
    { href: "/cart", label: "Cart" }, { href: "/account", label: "Shopper account" },
    { href: "/login", label: "Staff sign-in" }, { href: "/policies/tenant", label: "Store policies" },
  ];
  const href = value?.href || "";
  const customUrl = custom || (!!href && ![...targets, ...pages].some(target => target.href === href));
  const invalid = !!href && !isStorefrontHref(href);
  return <details className="storefront-design-section">
    <summary><strong>{definition.title}</strong></summary>
    <div className="storefront-design-section-fields">
      <label>Button / link text<input maxLength={120} value={value?.label ?? definition.label}
        onChange={event => onChange({ ...value, label: event.target.value })} /></label>
      <label>Destination<select value={customUrl ? "custom" : href} onChange={event => {
        setCustom(event.target.value === "custom");
        if (event.target.value !== "custom") onChange({ ...value, href: event.target.value });
      }}>
        {!requireDestination ? <option value="">Default destination{definition.href ? ` (${definition.href})` : " (selected catalogue item)"}</option> : null}
        <optgroup label="Homepage sections">{targets.map(target => <option key={target.href} value={target.href}>{target.label}</option>)}</optgroup>
        <optgroup label="Store pages">{pages.map(target => <option key={target.href} value={target.href}>{target.label}</option>)}</optgroup>
        <option value="custom">Custom URL, email or phone</option>
      </select></label>
      {customUrl ? <label>Custom destination<input maxLength={2048} value={href} placeholder="https://example.com, /brand?q=gift, mailto: or tel:"
        aria-invalid={invalid} onChange={event => onChange({ ...value, href: event.target.value })} /></label> : null}
      {invalid ? <p className="ops-error" role="alert">Use a store path, homepage section, HTTP(S), mailto or tel link without spaces.</p> : null}
      <p>{requireDestination ? "Choose a label and destination for this header menu item." : "Blank text or the default destination keeps the existing behaviour. Product and category names stay tied to your catalogue."}</p>
    </div>
  </details>;
}

function ImageField({ label, value, onChange, onError }: {
  label: string;
  value?: string | null;
  onChange: (value: string | null) => void;
  onError: (message: string) => void;
}) {
  const upload = async (file?: File) => {
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 1024 * 1024) {
      onError("Choose a PNG, JPEG or WebP image under 1 MB.");
      return;
    }
    try {
      const source = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("Unable to read image."));
        reader.readAsDataURL(file);
      });
      onChange(source);
    } catch (failure) {
      onError(failure instanceof Error ? failure.message : "Unable to read image.");
    }
  };
  return <div className="storefront-design-image-field">
    {value ? <img src={toAssetUrl(value)} alt={`${label} preview`} /> : <div className="storefront-image-placeholder">Image preview</div>}
    <label>{label} URL<input value={value?.startsWith("data:") ? "" : value || ""} placeholder={value?.startsWith("data:") ? "Uploaded image — save to apply" : "Paste an image URL"} onChange={event => onChange(event.target.value || null)} /></label>
    <div className="storefront-design-image-actions">
      <label className="company-upload"><Upload size={15} aria-hidden="true" />Upload image
        <input type="file" accept="image/png,image/jpeg,image/webp" aria-label={`Upload ${label.toLowerCase()}`} onChange={event => { void upload(event.target.files?.[0]); event.target.value = ""; }} />
      </label>
      <button className="ops-link-btn" type="button" disabled={!value} onClick={() => onChange(null)}><Trash2 size={15} aria-hidden="true" />Remove</button>
    </div>
  </div>;
}

export function StorefrontDesignPage() {
  const [company, setCompany] = useState<CompanySetup>();
  const [sections, setSections] = useState<StorefrontSection[]>([]);
  const [previewData, setPreviewData] = useState<CatalogStorefrontPreviewResponse>();
  const [options, setOptions] = useState<SectionOptions>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [previewScaleMode, setPreviewScaleMode] = useState<"fit" | "actual">("fit");
  const [useSamples, setUseSamples] = useState(false);
  const [previewSize, setPreviewSize] = useState({ width: 0, height: 0 });
  const previewCanvas = useRef<HTMLDivElement>(null);
  const iframe = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (!previewCanvas.current) return;
    const observer = new ResizeObserver(([entry]) => {
      setPreviewSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(previewCanvas.current);
    return () => observer.disconnect();
  }, [loading, company?.id]);

  useEffect(() => {
    let active = true;
    Promise.all([
      api.company(),
      api.storefrontSections(),
      api.storefrontPreview(),
      api.inventoryProducts(),
      api.inventoryMasterEntries("categories"),
      api.inventoryMasterEntries("brands"),
    ]).then(([savedCompany, savedSections, preview, products, categories, brands]) => {
      if (!active) return;
      setCompany({ ...savedCompany, site_theme: storefrontSiteTheme(savedCompany.site_theme, savedCompany.storefront_template) });
      setSections(savedSections.length ? savedSections : classicSections(preview));
      setPreviewData(preview);
      const mappedProducts = new Set(savedSections.flatMap(section => section.product_ids || []));
      const mappedCategories = new Set(savedSections.flatMap(section => section.category_ids || []));
      const mappedBrands = new Set(savedSections.flatMap(section => section.brand_ids || []));
      setOptions({
        products: products.items
          .filter(product => (product.is_active && product.catalog_visible && !product.is_draft) || mappedProducts.has(product.id))
          .map(({ id, name, brand_name, is_active, catalog_visible }) => ({ id, name, brand_name, is_active, catalog_visible })),
        categories: categories.items.filter(item => item.is_active || mappedCategories.has(item.id)),
        brands: brands.items.filter(item => item.is_active || mappedBrands.has(item.id)),
      });
    }).catch(failure => {
      if (active) setError(failure instanceof Error ? failure.message : "Unable to load Storefront Design.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const sendPreview = useCallback(() => {
    if (!company || !previewData) return;
    const message: PreviewMessage = {
      type: "tenali-storefront-preview",
      companyId: company.id,
      company: {
        storefront_template: company.storefront_template,
        site_theme: company.site_theme,
        logo_url: company.logo_url,
        storefront_content: company.storefront_content,
      },
      sections: storefrontPreviewSections(sections, previewData, company.storefront_template || "current", useSamples),
    };
    iframe.current?.contentWindow?.postMessage(message, window.location.origin);
  }, [company, sections, previewData, useSamples]);

  useEffect(() => { sendPreview(); }, [sendPreview]);

  useEffect(() => {
    const receiveReady = (event: MessageEvent<unknown>) => {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") return;
      const message = event.data as { type?: string; companyId?: string };
      if (message.type === "tenali-storefront-preview-ready" && message.companyId === company?.id) sendPreview();
    };
    window.addEventListener("message", receiveReady);
    return () => window.removeEventListener("message", receiveReady);
  }, [company?.id, sendPreview]);

  const previewBase = tenantBase() || (company ? `/c/${company.tenant_slug}` : "");
  const previewUrl = company ? `${previewBase}/?storefrontPreview=${encodeURIComponent(company.id)}` : "";
  const previewWidth = device === "desktop" ? 1440 : 390;
  const fitScale = previewSize.width > 0 ? Math.min(1, previewSize.width / previewWidth) : 1;
  const previewScale = previewScaleMode === "actual" ? 1 : fitScale;
  const previewHeight = previewSize.height || 570;
  const enabledCount = sections.filter(section => section.is_enabled).length;
  const productCount = useMemo(() => options?.products.length || 0, [options]);
  const linkDefinitions = company ? storefrontLinkDefinitions(company, sections) : [];
  const linkTargets = storefrontSectionTargets(sections, company?.storefront_template || "current");
  const headerMenu = company ? storefrontHeaderMenu(company) : [];

  const updateCompany = (patch: Partial<CompanyUpdateInput>) => {
    setCompany(previous => previous ? { ...previous, ...patch } : previous);
    setMessage("");
  };
  const updateHeaderMenu = (items: StorefrontMenuItem[]) => {
    if (company) updateCompany({ storefront_content: { ...company.storefront_content, header_menu: items } });
  };
  const addHeaderMenuItem = () => {
    let index = 1;
    while (headerMenu.some(item => item.key === `menu-${index}`)) index++;
    updateHeaderMenu([...headerMenu, { key: `menu-${index}`, label: "New menu item", href: "/", is_enabled: true }]);
  };
  const moveHeaderMenuItem = (index: number, direction: -1 | 1) => {
    const next = [...headerMenu];
    const target = index + direction;
    [next[index], next[target]] = [next[target], next[index]];
    updateHeaderMenu(next);
  };
  const actionField = (definition: StorefrontLinkDefinition) => <ActionField key={definition.key}
    definition={definition} value={company?.storefront_content.links?.[definition.key]} targets={linkTargets}
    onChange={value => {
      if (company) updateCompany({ storefront_content: { ...company.storefront_content,
        links: { ...company.storefront_content.links, [definition.key]: value } } });
    }} />;
  const updateHomeCopy = (key: string, value: string) => {
    if (!company) return;
    updateCompany({
      storefront_content: {
        ...company.storefront_content,
        home: { ...company.storefront_content.home, [key]: value },
      },
    });
  };
  const copyFields = (slot: string) => (CLASSIC_COPY_FIELDS[slot] || [])
    .filter(([key]) => !["hero_primary_action", "hero_secondary_action", "category_action", "categories_more_action", "brand_action", "contact_whatsapp_label"].includes(key))
    .map(([key, label, maxLength]) =>
    <label key={key}>{label}
      {maxLength > 200 ? <textarea rows={3} maxLength={maxLength} value={company?.storefront_content.home[key] || ""}
        onChange={event => updateHomeCopy(key, event.target.value)} />
        : <input maxLength={maxLength} value={company?.storefront_content.home[key] || ""}
          onChange={event => updateHomeCopy(key, event.target.value)} />}
    </label>);
  const updateSection = (sectionKey: string, patch: Partial<StorefrontSection>) => {
    if (patch.product_ids) setUseSamples(false);
    setSections(previous => previous.map(section => section.section_key === sectionKey ? { ...section, ...patch } : section));
    setMessage("");
  };
  const addSection = (sectionType: StorefrontSection["section_type"]) => {
    const sectionKey = `custom-${Date.now()}`;
    setSections(previous => [...previous, {
      section_key: sectionKey,
      section_type: sectionType,
      title: sectionType === "hero" ? "Welcome to our store" : sectionType === "products" ? "New collection" : sectionType === "categories" ? "Shop categories" : "Featured brands",
      eyebrow: "",
      description: "",
      sort_order: previous.length,
      is_enabled: true,
      configuration: { image_ratio: "square" },
      product_ids: [],
      category_ids: [],
      brand_ids: [],
    }]);
  };
  const moveSection = (index: number, direction: -1 | 1) => {
    setSections(previous => {
      const target = index + direction;
      if (target < 0 || target >= previous.length) return previous;
      const next = [...previous];
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((section, sort_order) => ({ ...section, sort_order }));
    });
  };
  const save = async () => {
    if (!company) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      if (headerMenu.length > MAX_STOREFRONT_MENU_ITEMS || headerMenu.some(item => !item.label.trim() || !item.href || !isStorefrontHref(item.href))) {
        throw new Error("Header supports up to 9 menu items. Give each item a label and a valid destination.");
      }
      if (Object.values(company.storefront_content.links || {}).some(link => link.href && !isStorefrontHref(link.href))) {
        throw new Error("Fix the invalid destination in its homepage section before saving.");
      }
      const payload: CompanyUpdateInput = {
        company_name: company.company_name,
        nickname: company.nickname || undefined,
        address: company.address || undefined,
        gst_number: company.gst_number || undefined,
        gst_registered: company.gst_registered !== false,
        whatsapp_number: company.whatsapp_number || undefined,
        udyam_number: company.udyam_number || undefined,
        tenant_slug: company.tenant_slug,
        phone: company.phone || undefined,
        email: company.email || undefined,
        website: company.website || undefined,
        logo_url: company.logo_url || undefined,
        social_links: company.social_links || {},
        invoice_settings: company.invoice_settings,
        site_theme: company.site_theme,
        storefront_template: company.storefront_template || "current",
        storefront_content: company.storefront_content,
        storefront_enabled: company.features?.storefront.platform_allowed ? company.storefront_enabled !== false : undefined,
        workflow_guidance_enabled: company.workflow_guidance_enabled !== false,
      };
      const savedCompany = await api.updateCompany(payload);
      setCompany({ ...savedCompany, site_theme: storefrontSiteTheme(savedCompany.site_theme, savedCompany.storefront_template) });
      try {
        const result = await api.saveStorefrontSections(sections.map((section, sort_order) => ({ ...section, sort_order })));
        setSections(result.sections);
      } catch (failure) {
        throw new Error(`Theme and brand settings were saved, but homepage sections were not: ${failure instanceof Error ? failure.message : String(failure)}`);
      }
      setMessage("Storefront design saved. Your product catalogue, cart, checkout and WhatsApp settings are unchanged.");
      window.dispatchEvent(new Event("company-updated"));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to save Storefront Design.");
    } finally { setSaving(false); }
  };

  return <main className="storefront-design-page">
    <header className="storefront-design-toolbar">
      <div className="storefront-design-title">
        <div><p className="storefront-design-eyebrow">Storefront</p><h1>Design editor</h1></div>
      </div>
      <div className="storefront-design-toolbar-actions">
        <span className="storefront-design-save-status">{saving ? "Saving…" : "Draft preview"}</span>
        <Link className="btn light" to="/" target="_blank">Open live store</Link>
        <button className="btn" type="button" disabled={!company || loading || saving} onClick={() => void save()}><Save size={16} aria-hidden="true" />Save design</button>
      </div>
    </header>
    <div className="storefront-design-notices">
      {error ? <FloatingAlert>{error}</FloatingAlert> : null}
      {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    </div>
    {loading ? <p className="loading">Loading storefront editor…</p> : null}
    {company ? <div className="storefront-design-workspace">
      <aside className="storefront-design-controls" aria-label="Storefront design controls">
        <div className="storefront-design-panel-heading"><h2>Design</h2><span>{enabledCount + 5} active sections</span></div>
        <section className="storefront-design-control-group">
          <h3>Store theme</h3>
          <label>Choose a storefront
            <select value={company.storefront_template || "current"} onChange={event => {
              const template = event.target.value as StorefrontTemplate;
              updateCompany({ storefront_template: template, site_theme: storefrontSiteTheme(company.site_theme, template) });
            }}>
              {templates.map(([value, name, description]) => <option value={value} key={value}>{name} — {description}</option>)}
            </select>
          </label>
          <p>Changing themes only changes presentation. Your products, categories, brands, tags, orders and checkout stay the same.</p>
        </section>
        <section className="storefront-design-control-group">
          <h3>Colours</h3>
          <div className="storefront-design-colours">
            {SITE_THEME_FIELDS.map(([key, label]) => <label key={key}>
              <span>{label}</span>
              <input aria-label={`${label} colour`} type="color" value={normalizeSiteTheme(company.site_theme)[key]}
                onChange={event => updateCompany({ site_theme: { ...company.site_theme, [key]: event.target.value } })} />
            </label>)}
          </div>
          <button className="ops-link-btn" type="button" onClick={() => updateCompany({ site_theme: { ...STOREFRONT_THEME_PALETTES[company.storefront_template || "current"] } })}>Reset colours</button>
          <p>Reset restores this design&apos;s sample palette. Custom colours apply to every storefront page.</p>
          <label>Card and button corners
            <select value={company.storefront_content.display?.corner_style === "square" ? "square" : "rounded"} onChange={event => updateCompany({
              storefront_content: {
                ...company.storefront_content,
                display: { show_bulk_pricing: company.storefront_content.display?.show_bulk_pricing !== false,
                  whatsapp_enquiry_enabled: company.storefront_content.display?.whatsapp_enquiry_enabled !== false,
                  corner_style: event.target.value === "square" ? "square" : "rounded" },
              },
            })}>
              <option value="rounded">Rounded</option><option value="square">Square</option>
            </select>
          </label>
        </section>
        <section className="storefront-design-control-group">
          <div className="storefront-design-section-heading"><h3>Homepage sections</h3><span>{sections.length + 5}</span></div>
          <p>Reorder, hide or edit any section. Select products, categories and brands manually; these choices are separate from product tags.</p>
          <p>Each section contains its own links and buttons. Destinations can be enabled homepage sections, store pages or custom URLs.</p>
          <details className="storefront-design-section">
            <summary><strong>Header</strong><span>Fixed at top</span></summary>
            <div className="storefront-design-section-fields">
              <p>The header always stays above the homepage sections.</p>
              <ImageField label="Store logo" value={company.logo_url} onChange={value => updateCompany({ logo_url: value || undefined })} onError={setError} />
              <label>Browser title<input maxLength={140} value={company.storefront_content.home.browser_title || ""}
                onChange={event => updateHomeCopy("browser_title", event.target.value)} /></label>
              <h4>Header menu ({headerMenu.length}/{MAX_STOREFRONT_MENU_ITEMS})</h4>
              <p>Add, reorder, hide or remove up to 9 primary menu items. Cart and account controls remain separate.</p>
              {headerMenu.map((item, index) => <div key={item.key}>
                <ActionField requireDestination definition={{ key: item.key, title: `Menu ${index + 1}: ${item.label}`,
                  label: item.label, href: item.href, group: "Header menu" }} value={item} targets={linkTargets}
                  onChange={value => updateHeaderMenu(headerMenu.map((entry, position) => position === index
                    ? { ...entry, label: value.label ?? entry.label, href: value.href ?? entry.href } : entry))} />
                <label className="storefront-design-checkbox"><input type="checkbox" checked={item.is_enabled}
                  onChange={event => updateHeaderMenu(headerMenu.map((entry, position) => position === index
                    ? { ...entry, is_enabled: event.target.checked } : entry))} />Show {item.label || `menu ${index + 1}`}</label>
                <button type="button" className="ops-link-btn" disabled={index === 0} aria-label={`Move menu ${index + 1} up`}
                  onClick={() => moveHeaderMenuItem(index, -1)}><ChevronUp size={15} aria-hidden="true" />Move up</button>
                <button type="button" className="ops-link-btn" disabled={index === headerMenu.length - 1} aria-label={`Move menu ${index + 1} down`}
                  onClick={() => moveHeaderMenuItem(index, 1)}><ChevronDown size={15} aria-hidden="true" />Move down</button>
                <button type="button" className="ops-link-btn" onClick={() => updateHeaderMenu(headerMenu.filter((_, position) => position !== index))}>
                  <Trash2 size={15} aria-hidden="true" />Remove menu {index + 1}</button>
              </div>)}
              <button type="button" className="ops-link-btn" disabled={headerMenu.length >= MAX_STOREFRONT_MENU_ITEMS}
                onClick={addHeaderMenuItem}>
                <Plus size={15} aria-hidden="true" />Add menu item</button>
              <h4>Account, cart and header links</h4>
              {linkDefinitions.filter(definition => definition.group === "Header").map(actionField)}
              <label>My Account menu text<input maxLength={80} value={company.storefront_content.navigation.account_menu || "My Account"}
                onChange={event => updateCompany({ storefront_content: { ...company.storefront_content,
                  navigation: { ...company.storefront_content.navigation, account_menu: event.target.value } } })} /></label>
            </div>
          </details>
          {sections.map((section, index) => {
            const classicSlot = typeof section.configuration.classic_slot === "string" ? section.configuration.classic_slot : undefined;
            const selectedIds = section.section_type === "products" ? section.product_ids || []
              : section.section_type === "categories" ? section.category_ids || []
                : section.section_type === "brands" ? section.brand_ids || [] : [];
            const choices = section.section_type === "products"
              ? (options?.products || []).map(item => [item.id, `${item.name}${item.brand_name ? ` · ${item.brand_name}` : ""}${item.is_active && item.catalog_visible ? "" : " (not visible)"}`] as const)
              : section.section_type === "categories"
                ? (options?.categories || []).map(item => [item.id, `${item.name}${item.is_active ? "" : " (inactive)"}`] as const)
                : (options?.brands || []).map(item => [item.id, `${item.name}${item.is_active ? "" : " (inactive)"}`] as const);
            return <details className="storefront-design-section" key={section.section_key} open={index === 0}>
              <summary><span className="storefront-design-drag-mark" aria-hidden="true">::</span><strong>{section.title || `Section ${index + 1}`}</strong><span>{section.section_type}</span></summary>
              <div className="storefront-design-section-fields">
                {classicSlot ? copyFields(classicSlot) : <>
                <label>Section title<input maxLength={120} required value={section.title} onChange={event => updateSection(section.section_key, { title: event.target.value })} /></label>
                <label>Type<select value={section.section_type} onChange={event => {
                  const sectionType = event.target.value as StorefrontSection["section_type"];
                  updateSection(section.section_key, { section_type: sectionType, product_ids: [], category_ids: [], brand_ids: [] });
                }}>
                  <option value="hero">Hero / banner</option><option value="products">Products</option><option value="categories">Categories</option><option value="brands">Brands</option>
                </select></label>
                <label>Eyebrow<input maxLength={80} value={section.eyebrow} onChange={event => updateSection(section.section_key, { eyebrow: event.target.value })} /></label>
                <label>Description<textarea rows={2} maxLength={400} value={section.description} onChange={event => updateSection(section.section_key, { description: event.target.value })} /></label>
                </>}
                {linkDefinitions.filter(definition => definition.group === "Individual sections" &&
                  definition.key.startsWith(`section.${section.section_key}.`)).map(actionField)}
                {section.section_type === "categories" || section.section_type === "brands" ? <>
                  <p>Card action settings are shared across {section.section_type} sections. The default destination opens the selected catalogue item.</p>
                  {linkDefinitions.filter(definition => definition.key === (section.section_type === "categories" ? "category.card" : "brand.card") ||
                    (section.section_type === "categories" && classicSlot && (company.storefront_template || "current") === "current" && definition.key === "categories.more")).map(actionField)}
                </> : null}
                {section.section_type === "products" ? <details className="storefront-design-section">
                  <summary><strong>Product button labels</strong></summary>
                  <div className="storefront-design-section-fields">
                    <p>These labels are shared across product sections and product pages. Purchase controls retain their original shopping actions.</p>
                    {[
                      ["add_to_cart", "Add to Cart"], ["add_to_enquiry", "Add to enquiry"], ["choose_options", "Choose options"],
                      ["view_cart", "View cart"], ["view_enquiry_list", "View list"], ["whatsapp_enquiry", "WhatsApp enquiry"],
                    ].map(([key, fallback]) => <label key={key}>{fallback}<input maxLength={100}
                      value={company.storefront_content.product?.[key] ?? fallback} onChange={event => updateCompany({
                        storefront_content: { ...company.storefront_content, product: { ...company.storefront_content.product, [key]: event.target.value } },
                      })} /></label>)}
                  </div>
                </details> : null}
                <ImageField label="Section image" value={section.image_url} onChange={value => updateSection(section.section_key, { image_url: value })} onError={setError} />
                <label>Image size<select value={String(section.configuration.image_ratio || (section.section_type === "hero" ? "theme" : "square"))} onChange={event => {
                  const { image_ratio, ...configuration } = section.configuration;
                  updateSection(section.section_key, { configuration: event.target.value === "theme" ? configuration
                    : { ...configuration, image_ratio: event.target.value } });
                }}>
                  {section.section_type === "hero" ? <option value="theme">Theme default</option> : null}
                  <option value="square">Square</option><option value="portrait">Portrait</option><option value="landscape">Landscape</option>
                </select></label>
                <label>Image fit<select value={String(section.configuration.image_fit || "cover")} onChange={event => updateSection(section.section_key, { configuration: { ...section.configuration, image_fit: event.target.value } })}>
                  <option value="cover">Fill frame</option><option value="contain">Show full image</option>
                </select></label>
                <label>Font<select value={String(section.configuration.font_family || "default")} onChange={event => updateSection(section.section_key, { configuration: { ...section.configuration, font_family: event.target.value } })}>
                  <option value="default">Theme default</option><option value="serif">Serif</option><option value="sans">Sans serif</option>
                </select></label>
                <label>Border<select value={String(section.configuration.border_style || "theme")} onChange={event => updateSection(section.section_key, { configuration: { ...section.configuration, border_style: event.target.value } })}>
                  <option value="theme">Theme default</option><option value="square">Square</option><option value="rounded">Rounded</option>
                </select></label>
                {(["background_color", "text_color", "accent_color"] as const).map(key => <label className="storefront-design-inline-color" key={key}>
                  {key === "background_color" ? "Section background" : key === "text_color" ? "Section text" : "Section accent"}
                  <input type="color" value={String(section.configuration[key] || (key === "background_color" ? "#ffffff" : key === "text_color" ? "#142b4a" : "#b88932"))}
                    onChange={event => updateSection(section.section_key, { configuration: { ...section.configuration, [key]: event.target.value } })} />
                </label>)}
                <label className="storefront-design-checkbox"><input type="checkbox" checked={section.is_enabled} onChange={event => updateSection(section.section_key, { is_enabled: event.target.checked })} />Show section</label>
                {section.section_type !== "hero" ? <label>Select {section.section_type}
                  <select multiple size={Math.min(7, Math.max(3, choices.length))} value={selectedIds}
                    onChange={event => {
                      const ids = Array.from(event.currentTarget.selectedOptions, option => option.value);
                      updateSection(section.section_key, section.section_type === "products" ? { product_ids: ids }
                        : section.section_type === "categories" ? { category_ids: ids } : { brand_ids: ids });
                    }}>
                    {choices.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                  </select>
                  {section.section_type === "products" ? <span>{productCount} catalogue products available</span> : null}
                </label> : null}
                <div className="storefront-design-section-actions">
                  <button type="button" className="ops-link-btn" aria-label="Move section up" disabled={index === 0} onClick={() => moveSection(index, -1)}><ChevronUp size={15} />Move up</button>
                  <button type="button" className="ops-link-btn" aria-label="Move section down" disabled={index === sections.length - 1} onClick={() => moveSection(index, 1)}><ChevronDown size={15} />Move down</button>
                  <button type="button" className="ops-link-btn" onClick={() => setSections(previous => previous.filter(item => item.section_key !== section.section_key))}><Trash2 size={15} />Remove</button>
                </div>
              </div>
            </details>;
          })}
          <div className="storefront-design-add-section">
            <button type="button" onClick={() => addSection("hero")}><Plus size={15} />Hero</button>
            <button type="button" onClick={() => addSection("products")}><Plus size={15} />Products</button>
            <button type="button" onClick={() => addSection("categories")}><Plus size={15} />Categories</button>
            <button type="button" onClick={() => addSection("brands")}><Plus size={15} />Brands</button>
          </div>
          {(["why", "contact", "about"] as const).map(slot => <details className="storefront-design-section" key={slot}>
            <summary><strong>{slot === "why" ? "Why" : slot === "contact" ? "Contact" : "About / collection story"}</strong><span>Shared content</span></summary>
            <div className="storefront-design-section-fields">
              {copyFields(slot)}
              {slot === "why" && company.storefront_template === "boutique" ? <>
                <p>Boutique journal photographs are decorative. Category, brand and product images still come from your selected catalogue entries.</p>
                {(["why_left", "why_right"] as const).map((key, index) => <ImageField key={key}
                  label={`Journal image ${index + 1}`} value={company.storefront_content.images?.[key] === undefined
                    ? BOUTIQUE_IMAGES[key] : company.storefront_content.images[key]}
                  onChange={value => updateCompany({ storefront_content: { ...company.storefront_content,
                    images: { ...company.storefront_content.images, [key]: value } } })} onError={setError} />)}
              </> : null}
              {slot === "why" ? storyImages.filter(([template]) => template === company.storefront_template).map(([, key, label, fallback]) =>
                <ImageField key={key} label={label} value={company.storefront_content.images?.[key] === undefined
                  ? fallback : company.storefront_content.images[key]}
                  onChange={value => updateCompany({ storefront_content: { ...company.storefront_content,
                    images: { ...company.storefront_content.images, [key]: value } } })} onError={setError} />) : null}
              {linkDefinitions.filter(definition => slot === "why" ? definition.key === "why.contact"
                : slot === "contact" ? definition.key.startsWith("contact.") : false).map(actionField)}
            </div>
          </details>)}
          <details className="storefront-design-section">
            <summary><strong>Footer</strong><span>Fixed at bottom</span></summary>
            <div className="storefront-design-section-fields">
              <p>The footer always stays below the homepage sections. Store policies remain available below it.</p>
              <label>Footer text<input maxLength={240} value={company.storefront_content.footer.contact_text ?? company.email ?? company.storefront_content.footer.catalogue_label ?? ""}
                onChange={event => updateCompany({ storefront_content: { ...company.storefront_content,
                  footer: { ...company.storefront_content.footer, contact_text: event.target.value } } })} /></label>
              {linkDefinitions.filter(definition => definition.group === "Footer").map(actionField)}
              <p>The fallback catalogue link appears at the end of themed homepages when no product section is shown.</p>
              {linkDefinitions.filter(definition => definition.key === "catalog.explore").map(actionField)}
            </div>
          </details>
        </section>
      </aside>
      <section className="storefront-design-preview" aria-label="Live storefront preview">
        <div className="storefront-preview-toolbar">
          <div><strong>Live preview</strong><span>{previewWidth}px {device} · {Math.round(previewScale * 100)}% · {previewScaleMode === "fit" ? "Fit to panel" : "Actual size"}</span></div>
          <div className="storefront-preview-controls">
            <div className="storefront-preview-zoom-switch" role="group" aria-label="Preview zoom">
              <button type="button" aria-pressed={previewScaleMode === "fit"} className={previewScaleMode === "fit" ? "active" : ""} onClick={() => setPreviewScaleMode("fit")}>Fit</button>
              <button type="button" aria-pressed={previewScaleMode === "actual"} className={previewScaleMode === "actual" ? "active" : ""} onClick={() => setPreviewScaleMode("actual")}>100%</button>
            </div>
            <div className="storefront-preview-device-switch" role="group" aria-label="Preview device">
              <button type="button" aria-pressed={device === "desktop"} className={device === "desktop" ? "active" : ""} onClick={() => setDevice("desktop")}><Monitor size={16} />Desktop</button>
              <button type="button" aria-pressed={device === "mobile"} className={device === "mobile" ? "active" : ""} onClick={() => setDevice("mobile")}><Smartphone size={16} />Mobile</button>
            </div>
          </div>
        </div>
        <div className="storefront-preview-notice">
          <label><input type="checkbox" checked={useSamples} onChange={event => setUseSamples(event.target.checked)} />Use sample products for all product sections</label>
          <p>Unmapped sections always show samples here. Selecting products returns to your actual selections.
            Samples and this preview switch are never saved or shown on the live store. Shopping actions are disabled.</p>
        </div>
        <div ref={previewCanvas} className={`storefront-preview-canvas${device === "mobile" ? " mobile" : ""}${previewScaleMode === "actual" ? " actual-size" : ""}`}>
          <div className="storefront-preview-frame" style={{ width: previewWidth * previewScale, height: previewHeight }}>
            {previewUrl ? <iframe ref={iframe} title="Live storefront preview" src={previewUrl} onLoad={sendPreview}
              style={{ width: previewWidth, height: previewHeight / previewScale, transform: `scale(${previewScale})` }} /> : null}
          </div>
        </div>
      </section>
    </div> : null}
  </main>;
}
