import { useEffect, useRef, useState } from "react";
import { api, type BulkJob, type BulkKind } from "../api";

type Master = { id: string; name: string; is_active: boolean };

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function BulkWorkbookPanel({ selectedProducts, onImported }: { selectedProducts: string[]; onImported: () => void }) {
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
      setMessage(`Import complete: ${current.total} rows processed. Download results below.`);
      onImported();
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
        const ids = kind === "products" ? selectedProducts : kind === "brands" || kind === "categories"
          ? selected : manualIds.split(/[\s,]+/).filter(Boolean);
        if (!ids.length) throw new Error("Select at least one record to export.");
        const result = await api.bulkExport(kind, ids);
        save(result.blob, `tenali-${kind}-selected.xlsx`);
      } else {
        if (!file) throw new Error("Choose an Excel workbook first.");
        const limit = kind === "images" || (kind === "products" && file.name.toLowerCase().endsWith(".zip")) ? 20 : 10;
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

  return <section className="inventory-toolbar" aria-label="Bulk Excel workbooks">
    <h2>Bulk Excel workbooks</h2>
    <p>Download a fresh template, or export selected records. Uploads process rows separately; correct and re-upload failure.xlsx from the results ZIP.</p>
    <p>If interrupted, refresh saved imports and resume the existing job. Do not upload the original again; processed rows are already saved. Imports expire after seven days.</p>
    <div><button type="button" className="btn light" disabled={busy} onClick={() => {
      setBusy(true); void refreshJobs().catch(failure => setError(String(failure))).finally(() => setBusy(false));
    }}>Refresh saved imports</button></div>
    {jobs.map(job => <div key={job.id} className="shop-actions">
      <span>{job.kind}: {job.processed} / {job.total} rows {job.completed ? "complete" : "pending"} · expires {new Date(job.expires_at).toLocaleDateString()}</span>
      <button type="button" disabled={busy || job.completed} onClick={() => void jobAction(job, "resume")}>Resume</button>
      <button type="button" disabled={busy || !job.completed} onClick={() => void jobAction(job, "download")}>Download results</button>
      <button type="button" disabled={busy} onClick={() => { if (window.confirm("Remove this saved import and its results? Already saved records are not deleted.")) void jobAction(job, "delete"); }}>Remove</button>
    </div>)}
    <label>Record type<select value={kind} disabled={busy} onChange={event => { setKind(event.target.value as BulkKind); setFile(null); uploadKey.current = null; if (fileInput.current) fileInput.current.value = ""; }}>
      <option value="products">Products</option><option value="variants">Variants</option><option value="hsn">HSN / GST</option>
      <option value="parties">Customers, vendors & contacts</option><option value="brands">Brands</option><option value="categories">Categories</option>
      <option value="images">Product, brand & category images</option>
    </select></label>
    {kind === "products" ? <p>{selectedProducts.length} products selected in the product register below.</p> : null}
    {kind === "brands" || kind === "categories" ? <label>Select records<select multiple size={5} value={selected}
      onChange={event => setSelected(Array.from(event.currentTarget.selectedOptions, option => option.value))}>
      {masters.map(item => <option key={item.id} value={item.id}>{item.name}{item.is_active ? "" : " (inactive)"}</option>)}
    </select></label> : null}
    {kind === "hsn" || kind === "parties" || kind === "variants" ? <label>Record IDs for selected export<textarea
      value={manualIds} onChange={event => setManualIds(event.target.value)} placeholder="Paste IDs separated by commas or new lines" /></label> : null}
    {kind === "images" ? <p>For uploaded files, put the completed template in a ZIP as manifest.xlsx and add photos to an images folder. Enter each filename in the template. URL-only updates can use the workbook directly. See its README.</p> : null}
    {kind === "products" ? <p>For product images in the same import, upload a ZIP containing manifest.xlsx and an images folder. Enter the filenames in the image_file column.</p> : null}
    <div><button type="button" className="btn light" disabled={busy} onClick={() => void run("template")}>Download template</button>{" "}
      <button type="button" className="btn light" disabled={busy || kind === "images"} onClick={() => void run("export")}>Download selected</button></div>
    <label>Workbook or image ZIP to upload<input ref={fileInput} type="file" accept={kind === "images" || kind === "products" ? ".xlsx,.zip" : ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
      disabled={busy} onChange={event => { setFile(event.target.files?.[0] || null); uploadKey.current = null; }} /></label>
    <button type="button" className="btn" disabled={busy || !file} onClick={() => void run("import")}>{busy ? "Processing..." : "Upload workbook"}</button>
    {error ? <p role="alert">{error}</p> : null}{message ? <p role="status">{message}</p> : null}
  </section>;
}
