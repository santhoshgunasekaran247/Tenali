import { FormEvent, useEffect, useState } from "react";
import { Download, RotateCcw, Save, Trash2, Upload } from "lucide-react";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { api } from "../api";
import { toAssetUrl } from "../features/catalog/utils";
import { DEFAULT_INVOICE_SETTINGS } from "../features/invoiceSettings";
import { DEFAULT_SITE_THEME, SITE_THEME_FIELDS, endSiteThemePreview, normalizeSiteTheme, previewSiteTheme, setSavedSiteTheme } from "../features/siteTheme";
import { STOREFRONT_COPY_FIELDS, STOREFRONT_COPY_GROUP_LABELS, type StorefrontCopyGroup } from "../features/catalog/storefrontCopyFields";
import { tenantBase } from "../features/tenantTransport";
import type { CompanySetup, CompanyUpdateInput, Invoice, InvoiceSettings } from "../types";

type AssetInputProps = {
  label: string;
  value?: string | null;
  disabled: boolean;
  onChange: (value: string | null) => void;
  onError: (message: string) => void;
};

function AssetInput({ label, value, disabled, onChange, onError }: AssetInputProps) {
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
    } catch (error) {
      onError(error instanceof Error ? error.message : "Unable to read image.");
    }
  };

  return (
    <div className="company-asset">
      <h3>{label}</h3>
      {value ? <img className="company-asset-preview" src={toAssetUrl(value)} alt={`${label} preview`}
        onError={() => onError(`${label} could not be loaded.`)} /> : null}
      <label>
        {label} URL or Asset Path
        <input disabled={disabled} value={value?.startsWith("data:") ? "" : value || ""}
          placeholder={value?.startsWith("data:") ? "Uploaded image" : ""}
          onChange={(event) => onChange(event.target.value || null)} />
      </label>
      <div className="company-asset-actions">
        <label className="company-upload">
          <Upload size={16} aria-hidden="true" /> Upload
          <input type="file" accept="image/png,image/jpeg,image/webp" disabled={disabled}
            aria-label={`Upload ${label.toLowerCase()}`}
            onChange={(event) => { void upload(event.target.files?.[0]); event.target.value = ""; }} />
        </label>
        <button className="ops-link-btn" type="button" title={`Remove ${label.toLowerCase()}`}
          aria-label={`Remove ${label.toLowerCase()}`} disabled={disabled || !value} onClick={() => onChange(null)}>
          <Trash2 size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

export function CompanySetupPage() {
  const [company, setCompany] = useState<CompanySetup | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [socialLinks, setSocialLinks] = useState("");

  useEffect(() => {
    let active = true;
    api.company().then((result) => {
      if (!active) return;
      setSavedSiteTheme(result.site_theme);
      setCompany({ ...result, invoice_settings: { ...DEFAULT_INVOICE_SETTINGS, ...result.invoice_settings }, site_theme: normalizeSiteTheme(result.site_theme) });
      setSocialLinks(JSON.stringify(result.social_links || {}, null, 2));
    }).catch((failure) => {
      if (active) setError(failure instanceof Error ? failure.message : "Unable to load company.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => { if (company) previewSiteTheme(company.site_theme); }, [company?.site_theme]);
  useEffect(() => () => endSiteThemePreview(), []);

  const update = (patch: Partial<CompanyUpdateInput>) => {
    setCompany((previous) => previous ? { ...previous, ...patch } : previous);
    setMessage("");
  };
  const updateInvoice = (patch: Partial<InvoiceSettings>) => {
    setCompany((previous) => previous ? { ...previous, invoice_settings: { ...previous.invoice_settings, ...patch } } : previous);
    setMessage("");
  };
  const updateStorefrontCopy = (group: StorefrontCopyGroup, key: string, value: string) => {
    setCompany((previous) => previous ? {
      ...previous,
      storefront_content: {
        ...previous.storefront_content,
        [group]: { ...previous.storefront_content[group], [key]: value },
      },
    } : previous);
    setMessage("");
  };
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!company) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const links: unknown = JSON.parse(socialLinks || "{}");
      if (!links || typeof links !== "object" || Array.isArray(links) || Object.values(links).some((value) => typeof value !== "string")) {
        throw new Error("Social links must be a JSON object with text values.");
      }
      const result = await api.updateCompany({
        company_name: company.company_name,
        nickname: company.nickname || undefined,
        address: company.address || undefined,
        gst_number: company.gst_number || undefined,
        udyam_number: company.udyam_number || undefined,
        tenant_slug: company.tenant_slug,
        phone: company.phone || undefined,
        email: company.email || undefined,
        website: company.website || undefined,
        logo_url: company.logo_url || undefined,
        social_links: links as Record<string, string>,
        invoice_settings: company.invoice_settings,
        site_theme: company.site_theme,
        storefront_content: company.storefront_content,
      });
      setSavedSiteTheme(result.site_theme);
      setCompany(result);
      setMessage("Company settings saved.");
      window.dispatchEvent(new Event("company-updated"));
      if (tenantBase() && result.tenant_slug !== company.tenant_slug) {
        window.location.assign(`/c/${result.tenant_slug}/portal/company`);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to save company.");
    } finally { setSaving(false); }
  };
  const saveTheme = async () => {
    if (!company) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      if (!SITE_THEME_FIELDS.every(([key]) => /^#[0-9a-f]{6}$/i.test(company.site_theme[key]))) {
        throw new Error("Site colours must use six-digit hex values, such as #142b4a.");
      }
      const result = await api.updateSiteTheme(company.site_theme);
      setSavedSiteTheme(result.site_theme);
      update({ site_theme: result.site_theme });
      setMessage("Site colours saved.");
      window.dispatchEvent(new Event("company-updated"));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to save site colours."); }
    finally { setSaving(false); }
  };
  const preview = async () => {
    if (!company) return;
    setPreviewing(true);
    setError("");
    try {
      const { downloadInvoicePdf } = await import("../features/invoicePdf");
      const { items: masters } = await api.hsnMasters();
      const master = masters[0];
      if (!master) throw new Error("Add an active HSN / SAC code in Master Data before generating a sample invoice.");
      const gstRate = Number(master.gst_rate);
      const gstCents = Math.round(1000 * gstRate);
      const cgstCents = Math.round(gstCents / 2);
      const sampleTotal = 1000 + gstCents / 100;
      const sample: Invoice = {
        id: "preview", company_id: company.id, invoice_number: "SAMPLE-NOT-FOR-ISSUE",
        invoice_date: new Date().toLocaleDateString("en-CA"), customer_party_id: "preview",
        customer_name: "Sample Customer", subtotal: 1000, gst_total: gstCents / 100, total: sampleTotal,
        status: "SAMPLE", collection_status: "UNPAID", amount_received: 0, created_at: "",
        document_data: {
          seller: company,
          bill_to: { name: "Sample Customer", address: "Sample billing address" },
          ship_to: { name: "Sample Customer", address: "Sample shipping address" },
          place_of_supply: company.gst_number?.slice(0, 2) || "Sample", interstate: false,
          subtotal: "1000.00", gst_total: (gstCents / 100).toFixed(2), total: sampleTotal.toFixed(2),
          lines: [{ description: master.description, hsn: master.code, quantity: "1", rate: "1000.00", gst_rate: String(gstRate), taxable: "1000.00", cgst: (cgstCents / 100).toFixed(2), sgst: ((gstCents - cgstCents) / 100).toFixed(2), igst: "0", total: sampleTotal.toFixed(2) }],
        },
      };
      await downloadInvoicePdf(sample);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to preview invoice.");
    } finally { setPreviewing(false); }
  };

  return (
    <main className="ops-page company-setup-page">
      <section className="company-setup-heading">
        <PortalHomeLink />
        <h1>Company Setup</h1>
      </section>
      {loading ? <p className="company-setup-status">Loading...</p> : null}
      {error ? <p className="company-setup-status ops-error" role="alert">{error}</p> : null}
      {message ? <p className="company-setup-status" role="status">{message}</p> : null}
      {company ? <form className="company-setup-form ops-form" onSubmit={save}>
        <fieldset disabled={saving} className="company-setup-section">
          <legend>Company Details</legend>
          <div className="company-fields">
            <label>Company Name<input required maxLength={200} value={company.company_name} onChange={(event) => update({ company_name: event.target.value })} /></label>
            <label>Display Name<input maxLength={100} value={company.nickname || ""} onChange={(event) => update({ nickname: event.target.value })} /></label>
            <label>Storefront Address<input required minLength={3} maxLength={48} pattern="[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])" value={company.tenant_slug} onChange={(event) => update({ tenant_slug: event.target.value.toLowerCase() })} /><span className="access-workspace-url">/c/{company.tenant_slug}</span></label>
            <label className="company-field-wide">Registered Address<textarea rows={4} maxLength={2000} value={company.address || ""} onChange={(event) => update({ address: event.target.value })} /></label>
            <label>GSTIN<input pattern="[0-9]{2}[A-Z0-9]{13}" maxLength={15} value={company.gst_number || ""} onChange={(event) => update({ gst_number: event.target.value.toUpperCase() })} /></label>
            <label>Udyam Number<input maxLength={50} value={company.udyam_number || ""} onChange={(event) => update({ udyam_number: event.target.value })} /></label>
            <label>Phone<input type="tel" maxLength={60} value={company.phone || ""} onChange={(event) => update({ phone: event.target.value })} /></label>
            <label>Email<input type="email" maxLength={254} value={company.email || ""} onChange={(event) => update({ email: event.target.value })} /></label>
            <label>Website<input inputMode="url" maxLength={300} value={company.website || ""} onChange={(event) => update({ website: event.target.value })} /></label>
            <label>Social Links (JSON)<textarea rows={3} value={socialLinks} onChange={(event) => setSocialLinks(event.target.value)} /></label>
          </div>
        </fieldset>
        <section className="company-storefront-copy">
          <h2>Storefront Copy</h2>
          <p>Update the customer-facing wording without changing products or company records.</p>
          {(Object.keys(STOREFRONT_COPY_FIELDS) as StorefrontCopyGroup[]).map((group) => (
            <details className="company-copy-group" key={group}>
              <summary>{STOREFRONT_COPY_GROUP_LABELS[group]}</summary>
              <div className="company-fields">
                {STOREFRONT_COPY_FIELDS[group].map(([key, label]) => {
                  const value = company.storefront_content[group][key] || "";
                  const longText = /description|body|note/i.test(key);
                  return <label key={key}>{label}
                    {longText
                      ? <textarea rows={3} maxLength={600} value={value} onChange={(event) => updateStorefrontCopy(group, key, event.target.value)} />
                      : <input maxLength={600} value={value} onChange={(event) => updateStorefrontCopy(group, key, event.target.value)} />}
                  </label>;
                })}
              </div>
            </details>
          ))}
        </section>
        <fieldset disabled={saving} className="company-setup-section">
          <legend>Site Colours</legend>
          <div className="site-theme-grid">
            {SITE_THEME_FIELDS.map(([key, label]) => <div className="site-theme-field" key={key}>
              <label htmlFor={`site-color-${key}`}>{label}</label>
              <div className="site-theme-inputs">
                <input id={`site-color-${key}`} type="color" aria-label={`Site ${label} colour`}
                  value={normalizeSiteTheme(company.site_theme)[key]} onChange={(event) => update({ site_theme: { ...company.site_theme, [key]: event.target.value } })} />
                <input aria-label={`Site ${label} hex colour`} required pattern="#[0-9a-fA-F]{6}" maxLength={7}
                  value={company.site_theme[key]} onChange={(event) => update({ site_theme: { ...company.site_theme, [key]: event.target.value } })} />
              </div>
            </div>)}
          </div>
          <div className="company-setup-actions site-theme-actions">
            <button className="btn" type="button" disabled={saving || previewing} onClick={() => void saveTheme()}><Save size={16} aria-hidden="true" />{saving ? "Saving..." : "Save Site Colours"}</button>
            <button className="btn light" type="button" disabled={saving} onClick={() => update({ site_theme: { ...DEFAULT_SITE_THEME } })}><RotateCcw size={16} aria-hidden="true" />Reset Site Colours</button>
          </div>
        </fieldset>
        <fieldset disabled={saving} className="company-setup-section">
          <legend>Logo & Signature</legend>
          <div className="company-fields">
            <AssetInput label="Company Logo" value={company.logo_url} disabled={saving} onChange={(value) => update({ logo_url: value || undefined })} onError={setError} />
            <AssetInput label="Signature Image" value={company.invoice_settings.signature_image} disabled={saving} onChange={(value) => updateInvoice({ signature_image: value })} onError={setError} />
            <label>Logo Width (mm)<input type="number" min={25} max={75} required value={company.invoice_settings.logo_width_mm} onChange={(event) => updateInvoice({ logo_width_mm: Number(event.target.value) })} /></label>
            <label>Signature Width (mm)<input type="number" min={15} max={50} required value={company.invoice_settings.signature_width_mm} onChange={(event) => updateInvoice({ signature_width_mm: Number(event.target.value) })} /></label>
          </div>
        </fieldset>
        <fieldset disabled={saving} className="company-setup-section">
          <legend>Invoice Wording</legend>
          <div className="company-fields">
            {([
              ["title", "Invoice Title", 60], ["bill_to_label", "Bill To Label", 60],
              ["ship_to_label", "Ship To Label", 60], ["amount_in_words_label", "Amount in Words Label", 60],
              ["signatory_label", "Signatory Label", 80], ["signatory_name", "Signatory Name", 100],
              ["signatory_designation", "Signatory Designation", 100],
            ] as const).map(([key, label, maxLength]) => (
              <label key={key}>{label}<input maxLength={maxLength} required={!["signatory_name", "signatory_designation"].includes(key)} value={company.invoice_settings[key]}
                onChange={(event) => updateInvoice({ [key]: event.target.value })} /></label>
            ))}
            <label className="company-field-wide">Thank-you Note<textarea rows={3} maxLength={500} value={company.invoice_settings.thank_you_note} onChange={(event) => updateInvoice({ thank_you_note: event.target.value })} /></label>
            <label className="company-field-wide">Footer Text<textarea rows={2} maxLength={240} value={company.invoice_settings.footer_text} onChange={(event) => updateInvoice({ footer_text: event.target.value })} /></label>
          </div>
        </fieldset>
        <fieldset disabled={saving} className="company-setup-section">
          <legend>Invoice Colours</legend>
          <div className="company-colors">
            {([["primary_color", "Primary / Footer"], ["accent_color", "Separator"], ["footer_text_color", "Footer Text"]] as const).map(([key, label]) => (
              <label key={key}>{label}<input type="color" value={company.invoice_settings[key]} onChange={(event) => updateInvoice({ [key]: event.target.value })} /></label>
            ))}
          </div>
        </fieldset>
        <div className="company-setup-actions">
          <button className="btn" type="submit" disabled={saving || previewing}><Save size={16} aria-hidden="true" /> {saving ? "Saving..." : "Save Changes"}</button>
          <button className="btn light" type="button" disabled={saving || previewing} onClick={() => void preview()}><Download size={16} aria-hidden="true" /> {previewing ? "Generating..." : "Sample Invoice PDF"}</button>
        </div>
      </form> : null}
    </main>
  );
}