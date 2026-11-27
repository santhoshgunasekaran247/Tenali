import { useEffect, useRef, useState } from "react";
import { Download, FileSpreadsheet, Image, RefreshCw, UploadCloud } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type BulkJob, type BulkKind } from "../api";

type Master = { id: string; name: string; is_active: boolean };
const RECORD_TYPES: { kind: BulkKind; label: string; help: string }[] = [
  { kind: "products", label: "Products", help: "Products, pricing, categories, HSN and preferred vendors." },
  { kind: "variants", label: "Variants", help: "Sizes, colours and variant pricing for existing products." },
  { kind: "hsn", label: "HSN / GST", help: "Tax codes, descriptions and GST rates." },
  { kind: "parties", label: "Contacts", help: "Customers, vendors and other business contacts." },
  { kind: "brands", label: "Brands", help: "Brand names, descriptions and logo URLs or files." },
  { kind: "categories", label: "Categories", help: "Category names, descriptions and image URLs or files." },
  { kind: "images", label: "Images", help: "Photos for existing products, brands and categories." },
];

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function BulkWorkbookPanel({ selectedProducts }: { selectedProducts: string[] }) {
  const [kind, setKind] = useState<BulkKind>("products");
  const [masters, setMasters] = useState<Master[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [manualIds, setManualIds] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadKey = useRef<string | null>(null);
  const mounted = useRef(true);
  const [jobs, setJobs] = useState<BulkJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refreshJobs = async () => setJobs((await api.bulkJobs()).items);
  useEffect(() => {
    mounted.current = true;
    void api.bulkJobs().then(result => { if (mounted.current) setJobs(result.items); })
      .catch(failure => { if (mounted.current) setError(String(failure)); });
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setSelected([]); setMasters([]); setManualIds(""); setError("");
    if (kind === "brands" || kind === "categories") {
      api.inventoryMasterEntries(kind).then(result => { if (active) setMasters(result.items); })
        .catch(failure => { if (active) setError(failure instanceof Error ? failure.message : "Unable to load records."); });
    }
    return () => { active = false; };
  }, [kind]);

  const resume = async (job: BulkJob) => {
    let current = job;
    setJobs(previous => [current, ...previous.filter(item => item.id !== current.id)]);
    while (!current.completed && mounted.current) {
      current = await api.bulkAdvance(current.id);
      setJobs(previous => previous.map(item => item.id === current.id ? current : item));
    }
    if (current.completed && mounted.current) {
      setMessage(`Import complete: ${current.total} rows processed. ${current.success} succeeded; ${current.failures} failed. Download results below.`);
    }
  };

  const jobAction = async (job: BulkJob, action: "resume" | "download" | "delete") => {
    setBusy(true); setError(""); setMessage("");
    try {
      if (action === "resume") await resume(job);
      else if (action === "delete") { await api.bulkDelete(job.id); await refreshJobs(); }
      else {
        const result = await api.bulkResults(job.id);
        save(result.blob, `tenali-${job.kind}-results.zip`);
        setMessage(`${result.success} succeeded; ${result.failures} failed. Open the ZIP for separate workbooks.`);
      }
    } catch (failure) {
      setError((failure instanceof Error ? failure.message : "Bulk operation failed.") +
        " Refresh the saved imports and resume the existing job rather than uploading the original again.");
      try { await refreshJobs(); } catch (refreshFailure) { setError(String(failure) + " Refresh failed: " + String(refreshFailure)); }
    } finally { setBusy(false); }
  };

  const run = async (operation: "template" | "export" | "import") => {
    setBusy(true); setError(""); setMessage("");
    try {
      if (operation === "template") {
        const result = await api.bulkTemplate(kind);
        save(result.blob, `tenali-${kind}-template.xlsx`);
      } else if (operation === "export") {
        const ids = kind === "products" && selectedProducts.length ? selectedProducts : kind === "brands" || kind === "categories"
          ? selected : manualIds.split(/[\s,]+/).filter(Boolean);
        if (!ids.length) throw new Error("Select at least one record to export.");
        const result = await api.bulkExport(kind, ids);
        save(result.blob, `tenali-${kind}-selected.xlsx`);
      } else {
        if (!file) throw new Error("Choose an Excel workbook first.");
        const limit = supportsFiles && file.name.toLowerCase().endsWith(".zip") ? 20 : 10;
        if (file.size > limit * 1024 * 1024) throw new Error(`The upload must be at most ${limit} MiB.`);
        const job = await api.bulkStart(kind, file, uploadKey.current || (uploadKey.current = crypto.randomUUID()));
        setFile(null);
        if (fileInput.current) fileInput.current.value = "";
        uploadKey.current = null;
        await resume(job);
      }
    } catch (failure) {
      setError((failure instanceof Error ? failure.message : "Bulk operation failed.") +
        (operation === "import" ? " Refresh saved imports before retrying; resume an existing job if available." : ""));
      if (operation === "import") {
        try { await refreshJobs(); } catch (refreshFailure) { setError(String(failure) + " Refresh failed: " + String(refreshFailure)); }
      }
    }
    finally { setBusy(false); }
  };

  const supportsFiles = ["products", "images", "brands", "categories"].includes(kind);
  const exportCount = kind === "products" && selectedProducts.length ? selectedProducts.length
    : kind === "brands" || kind === "categories" ? selected.length : manualIds.split(/[\s,]+/).filter(Boolean).length;
  return <div className="bulk-content" aria-label="Bulk Excel workbooks" aria-busy={busy}>
    {error ? <p className="bulk-feedback bulk-error" role="alert">{error}</p> : null}
    {message ? <p className="bulk-feedback" role="status">{message}</p> : null}
    <section className="bulk-type-section" aria-labelledby="bulk-type-title">
      <h2 id="bulk-type-title">What would you like to upload?</h2>
      <p>Choose a record type to get the right template and instructions.</p>
      <div className="bulk-types">
        {RECORD_TYPES.map(item => <button key={item.kind} type="button" disabled={busy} aria-pressed={kind === item.kind}
          onClick={() => { setKind(item.kind); setFile(null); setMessage(""); uploadKey.current = null; if (fileInput.current) fileInput.current.value = ""; }}>
          {item.kind === "images" ? <Image size={20} aria-hidden="true" /> : <FileSpreadsheet size={20} aria-hidden="true" />}
          <strong>{item.label}</strong><span>{item.help}</span>
        </button>)}
      </div>
    </section>
    <div className="bulk-workspace">
      <section className="bulk-card" aria-labelledby="bulk-prepare-title">
        <div className="bulk-step-heading"><span className="bulk-step">1</span><div><h2 id="bulk-prepare-title">Prepare your workbook</h2><p>Start fresh or edit existing records.</p></div></div>
        <button type="button" className="btn" disabled={busy} onClick={() => void run("template")}><Download size={16} aria-hidden="true" /> Download {RECORD_TYPES.find(item => item.kind === kind)?.label.toLowerCase()} template</button>
        <ul className="bulk-tips">
          <li>Fill in the <strong>Data</strong> sheet. The README explains every step and includes an example.</li>
          <li>Leave <strong>id</strong> blank for new records; keep exported IDs to update.</li>
          {kind === "products" ? <li>Select an existing HSN to fill its description and GST rate; select a brand to fill its description. For new entries, replace those cells with your own values.</li> : null}
          {kind === "products" ? <li>Use English background colours such as <strong>white</strong> or <strong>light blue</strong>. Brand and primary-category photos can use their own image URL or file columns.</li> : null}
          {kind === "variants" ? <li>Use an existing product ID for each variant. Keep the variant ID when updating.</li> : null}
          {kind === "hsn" ? <li>Use 4, 6 or 8 digit codes. Enter a description and a GST rate between 0 and 100.</li> : null}
          {kind === "parties" ? <li>New contacts need a legal name and party type. Format phone numbers as text.</li> : null}
          {kind === "images" ? <li>Enter the existing record ID and choose product, brand or category. Use one image source per row.</li> : null}
          <li>Up to <strong>2,000 rows</strong> per upload. Blank update cells keep existing values; <strong>&lt;clear&gt;</strong> clears optional fields.</li>
        </ul>
        {kind !== "images" ? <details className="bulk-export">
          <summary>Export existing records to edit</summary>
          {kind === "products" && selectedProducts.length ? <p>{selectedProducts.length} products selected from inventory.</p> : null}
          {kind === "products" ? <p><Link to="/portal/inventory">Select products in inventory</Link> and open Bulk Excel, or paste IDs below.</p> : null}
          {kind === "brands" || kind === "categories" ? <label>Select records (Ctrl / Cmd to select more than one)<select multiple size={5} value={selected} disabled={busy}
            onChange={event => setSelected(Array.from(event.currentTarget.selectedOptions, option => option.value))}>
            {masters.map(item => <option key={item.id} value={item.id}>{item.name}{item.is_active ? "" : " (inactive)"}</option>)}
          </select>{!masters.length ? <small>No records available to export.</small> : null}</label> : null}
          {kind === "hsn" || kind === "parties" || kind === "variants" || (kind === "products" && !selectedProducts.length) ? <label>Record IDs<textarea
            value={manualIds} disabled={busy} onChange={event => setManualIds(event.target.value)} placeholder="Paste IDs separated by commas or new lines" /></label> : null}
          <button type="button" className="btn light" disabled={busy || !exportCount || exportCount > 2000} onClick={() => void run("export")}><Download size={16} aria-hidden="true" /> Download selected ({exportCount})</button>
          {exportCount > 2000 ? <p role="alert">Select at most 2,000 records per export.</p> : null}
        </details> : null}
      </section>
      <section className="bulk-card" aria-labelledby="bulk-upload-title">
        <div className="bulk-step-heading"><span className="bulk-step">2</span><div><h2 id="bulk-upload-title">Upload & process</h2><p>Review your data, then choose the file.</p></div></div>
        <div className="bulk-file-picker"><UploadCloud size={32} aria-hidden="true" />
          <label htmlFor="bulk-file">Choose your {supportsFiles ? "workbook or image ZIP" : "Excel workbook"}</label>
          <span>{supportsFiles ? ".xlsx up to 10 MiB / .zip up to 20 MiB" : ".xlsx up to 10 MiB"}</span>
          <input id="bulk-file" ref={fileInput} type="file" accept={supportsFiles ? ".xlsx,.zip" : ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            disabled={busy} onChange={event => { setFile(event.target.files?.[0] || null); uploadKey.current = null; }} />
          {file ? <strong>{file.name} ({(file.size / 1024).toFixed(0)} KiB)</strong> : null}
        </div>
        {supportsFiles ? <div className="bulk-image-guide"><h3><Image size={17} aria-hidden="true" /> Including photos?</h3>
          <p><strong>Image URLs:</strong> enter a public HTTPS URL in <code>image_url</code> and upload the workbook.</p>
          <p><strong>Image files:</strong> ZIP the workbook as <code>manifest.xlsx</code> alongside an <code>images/</code> folder. Put each filename in <code>image_file</code>, leaving its URL blank.</p>
          <pre aria-label="Image ZIP structure">{"upload.zip\n  manifest.xlsx\n  images/\n    photo.png"}</pre>
          <p>Recommended: products <strong>1000 x 1000 px</strong>, brand logos <strong>600 x 600 px</strong>, categories <strong>800 x 800 px</strong>. Square PNG, JPEG or WebP; up to 1 MiB per photo and 8 MiB total. Images fit without stretching.</p>
        </div> : null}
        <button type="button" className="btn bulk-upload-button" disabled={busy || !file} onClick={() => void run("import")}><UploadCloud size={17} aria-hidden="true" />{busy ? "Processing..." : "Upload & process"}</button>
        <p className="bulk-muted">Rows save independently. A failed row will not undo successful rows.</p>
      </section>
    </div>
    <section className="bulk-card bulk-history" aria-labelledby="bulk-history-title">
      <div className="bulk-history-heading"><div className="bulk-step-heading"><span className="bulk-step">3</span><div><h2 id="bulk-history-title">Saved imports & results</h2><p>Download results or pick up where you left off.</p></div></div>
        <button type="button" className="btn light" disabled={busy} onClick={() => {
          setBusy(true); void refreshJobs().catch(failure => setError(String(failure))).finally(() => setBusy(false));
        }}><RefreshCw size={15} aria-hidden="true" /> Refresh saved imports</button>
      </div>
      <p className="bulk-resume-note">Interrupted? Resume the saved import, not the original file: processed rows are already saved. Imports are private to your account and expire after seven days.</p>
      {!jobs.length ? <div className="bulk-empty"><FileSpreadsheet size={28} aria-hidden="true" /><p>No saved imports yet. Your uploads and results will appear here.</p></div> : null}
      {jobs.map(job => <article key={job.id} className="bulk-job">
        <div><strong>{RECORD_TYPES.find(item => item.kind === job.kind)?.label || job.kind}</strong><span className={`bulk-job-status${job.completed ? " is-complete" : ""}`}>{job.completed ? "Processed" : "Ready to resume"}</span>
          <p>{job.processed} / {job.total} rows processed</p>
          <p role="status">{job.success} succeeded · {job.failures} failed · {job.total - job.processed} remaining</p>
          <progress aria-label={`${job.kind} import progress`} value={job.processed} max={Math.max(1, job.total)} />
          <small>Uploaded {new Date(job.created_at).toLocaleString()} · Expires {new Date(job.expires_at).toLocaleDateString()}</small>
        </div>
        <div className="bulk-job-actions">
          {!job.completed ? <button type="button" className="btn" disabled={busy} onClick={() => void jobAction(job, "resume")}>Resume</button> : <button type="button" className="btn" disabled={busy} onClick={() => void jobAction(job, "download")}><Download size={15} aria-hidden="true" /> Download results</button>}
          <button type="button" className="bulk-remove" disabled={busy} onClick={() => { if (window.confirm("Remove this saved import and its results? Already saved records are not deleted.")) void jobAction(job, "delete"); }}>Remove</button>
        </div>
      </article>)}
      <p className="bulk-muted">Results ZIP: <strong>success.xlsx</strong> contains saved rows; <strong>failure.xlsx</strong> explains errors. Correct only failed rows and upload again. Image failure ZIPs retain their files and can be re-uploaded directly.</p>
    </section>
  </div>;
}
