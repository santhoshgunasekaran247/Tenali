import { useEffect, useState } from "react";
import { Download, FileText, Paperclip, RefreshCw, Trash2, Upload, X } from "lucide-react";
import { api } from "../api";
import type { Attachment, AttachmentEntity, AttachmentInput } from "../types";

const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 5;
const TYPES: Record<string, AttachmentInput["mime_type"]> = {
  pdf: "application/pdf", jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp",
};
const fileBytes = (file: AttachmentInput) => Math.floor(file.data_base64.length * 3 / 4) - (file.data_base64.endsWith("==") ? 2 : file.data_base64.endsWith("=") ? 1 : 0);
const sizeLabel = (size: number) => size >= 1024 * 1024 ? `${(size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.ceil(size / 1024))} KB`;

export function AttachmentPicker({ value, onChange, disabled = false, onBusyChange, existingCount = 0, existingBytes = 0 }: {
  value: AttachmentInput[];
  onChange: (items: AttachmentInput[]) => void;
  disabled?: boolean;
  onBusyChange?: (busy: boolean) => void;
  existingCount?: number;
  existingBytes?: number;
}) {
  const [reading, setReading] = useState(false);
  const [error, setError] = useState("");
  const choose = async (files: File[]) => {
    if (!files.length) return;
    setError("");
    setReading(true);
    onBusyChange?.(true);
    try {
      if (files.length + value.length + existingCount > MAX_FILES) throw new Error("Maximum 5 attachments per record.");
      if (existingBytes + value.reduce((sum, item) => sum + fileBytes(item), 0) + files.reduce((sum, file) => sum + file.size, 0) > MAX_TOTAL_BYTES) {
        throw new Error("Total attachments cannot exceed 20 MB.");
      }
      for (const file of files) {
        const extension = file.name.split(".").pop()?.toLowerCase() || "";
        if (!TYPES[extension] || (file.type && file.type !== TYPES[extension])) throw new Error("Choose PDF, JPEG, PNG or WebP files.");
        if (!file.size || file.size > MAX_FILE_BYTES) throw new Error("Each attachment must be non-empty and no larger than 5 MB.");
      }
      const selected = await Promise.all(files.map(async (file): Promise<AttachmentInput> => {
        const data = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(",")[1]);
          reader.onerror = () => reject(new Error(`Unable to read ${file.name}.`));
          reader.readAsDataURL(file);
        });
        return { file_name: file.name, mime_type: TYPES[file.name.split(".").pop()!.toLowerCase()], data_base64: data };
      }));
      onChange([...value, ...selected]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to read attachments."); }
    finally { setReading(false); onBusyChange?.(false); }
  };
  return <div className="attachment-picker">
    <label className="attachment-upload-label">
      <Paperclip size={16} aria-hidden="true" /> Receipts / Bills
      <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp" aria-label="Choose receipts or bills"
        disabled={disabled || reading || value.length + existingCount >= MAX_FILES}
        onChange={(event) => { const files = Array.from(event.target.files || []); event.target.value = ""; void choose(files); }} />
    </label>
    {reading ? <span role="status">Reading files...</span> : null}
    {error ? <p className="ops-error" role="alert">{error}</p> : null}
    {value.length ? <ul className="attachment-list">
      {value.map((file, index) => <li key={`${file.file_name}-${index}`}>
        <FileText size={16} aria-hidden="true" /><span className="attachment-name">{file.file_name}</span><small>{sizeLabel(fileBytes(file))}</small>
        <button className="ops-link-btn" type="button" title={`Remove ${file.file_name}`} aria-label={`Remove ${file.file_name}`}
          disabled={disabled || reading} onClick={() => onChange(value.filter((_, position) => position !== index))}><Trash2 size={16} aria-hidden="true" /></button>
      </li>)}
    </ul> : null}
  </div>;
}

export function AttachmentManager({ entity, recordId, title, onClose }: {
  entity: AttachmentEntity; recordId: string; title: string; onClose: () => void;
}) {
  const [items, setItems] = useState<Attachment[]>([]);
  const [pending, setPending] = useState<AttachmentInput[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reading, setReading] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = async () => {
    setLoading(true);
    setError("");
    try { setItems((await api.attachments(entity, recordId)).items); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to load attachments."); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [entity, recordId]);
  const upload = async () => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const result = await api.uploadAttachments(entity, recordId, pending);
      setItems((previous) => [...previous, ...result.items]);
      setPending([]);
      setMessage("Attachments uploaded.");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to upload attachments."); }
    finally { setSaving(false); }
  };
  const download = async (file: Attachment) => {
    setDownloading(file.id);
    setError("");
    try {
      const blob = await api.downloadAttachment(file.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.file_name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to download attachment."); }
    finally { setDownloading(null); }
  };
  return <section className="attachment-manager" aria-label={`Attachments for ${title}`}>
    <div className="attachment-heading"><h3>Receipts / Bills: {title}</h3>
      <div className="attachment-actions">
        <button className="ops-link-btn" type="button" title="Refresh attachments" aria-label="Refresh attachments" disabled={saving || loading} onClick={() => void load()}><RefreshCw size={16} aria-hidden="true" /></button>
        <button className="ops-link-btn" type="button" title="Close attachments" aria-label="Close attachments" disabled={saving || reading} onClick={onClose}><X size={18} aria-hidden="true" /></button>
      </div>
    </div>
    {error ? <p className="ops-error" role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    {loading ? <p role="status">Loading attachments...</p> : null}
    {!loading && !items.length ? <p>No attachments.</p> : null}
    <ul className="attachment-list">{items.map((file) => <li key={file.id}>
      <FileText size={16} aria-hidden="true" /><span className="attachment-name">{file.file_name}</span><small>{sizeLabel(file.file_size)}</small>
      <button className="ops-link-btn" type="button" title={`Download ${file.file_name}`} aria-label={`Download ${file.file_name}`}
        disabled={!!downloading} onClick={() => void download(file)}><Download size={16} aria-hidden="true" /></button>
    </li>)}</ul>
    <AttachmentPicker value={pending} onChange={setPending} disabled={loading || saving} onBusyChange={setReading}
      existingCount={items.length} existingBytes={items.reduce((sum, item) => sum + item.file_size, 0)} />
    <button className="btn attachment-save" type="button" disabled={!pending.length || loading || saving || reading} onClick={() => void upload()}>
      <Upload size={16} aria-hidden="true" />{saving ? "Uploading..." : "Upload Attachments"}
    </button>
  </section>;
}