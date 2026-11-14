import { useEffect, useRef, useState } from "react";
import { ChevronDown, Plus, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { ai, draftDescription, hasDuplicateDraft, type ActionDraft, type DraftAction, type AIExecution,
  type OperationWorkflow, type WorkflowEstimate, type WorkflowStep } from "../features/ai";
import { FloatingAlert } from "./Notifications";
import { FieldCaption, WorkflowReference } from "./WorkflowReference";

type FieldSchema = { type?: string; title?: string; format?: string; enum?: unknown[]; const?: unknown;
  anyOf?: FieldSchema[]; $ref?: string; properties?: Record<string, FieldSchema>; items?: FieldSchema; maxLength?: number; required?: string[];
  "x-workflow-reference"?: boolean; "x-enum-labels"?: Record<string, string> };
type ReferenceRenderer = (path: string, title: string, value: unknown, label: string | null, required: boolean) => React.ReactNode;
const friendly = (value: string) => value.replace(/_/g, " ");
const fieldLabel = (key: string) => ({
  vendor_name: "Vendor name", create_vendor_if_missing: "Create vendor if not found", product_name: "Product name",
  quantity: "Quantity", rate: "Rate per unit", hsn: "HSN / SAC", gst_rate: "GST rate",
  price_includes_gst: "Unit rate includes GST", selling_price: "Selling price per unit",
  store_name: "Receiving store", purchase_date: "Purchase date", payment_mode: "Payment mode",
  account_name: "Payment account", fully_paid: "Fully paid now", received_now: "Goods received now",
  vendor_party_id: "Vendor", customer_party_id: "Customer", related_party_id: "Related party",
} as Record<string, string>)[key] || friendly(key.replace(/_id$/, ""));
const actionLabel = (key: string, payload: Record<string, unknown> = {}) => (
  key === "party_create" || key === "party_update" ? ({
    customer: "Customer", vendor: "Vendor", customer_vendor: "Customer & vendor",
  } as Record<string, string>)[String(payload.party_type)] : null) || ({ purchase_create: "Purchase", invoice_create: "Sales billing",
  purchase_bundle_create: "Purchase · Vendor · Product · Stock", party_create: "Vendor or customer",
  product_create: "Product", stock_adjust: "Stock adjustment" } as Record<string, string>)[key] || friendly(key);
const statusLabel = (status: ActionDraft["status"]) => ({ editing: "Needs review", validated: "Ready to save",
  approved: "Ready to save", executed: "Saved" })[status];
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const waitingForPrerequisites = (step: WorkflowStep, steps: WorkflowStep[]) =>
  [...Object.values(step.bindings).map(binding => binding.step_id), ...Object.values(step.offer_steps || {})]
    .some(id => steps.find(child => child.id === id)?.draft_status !== "executed");

function Fields({ values, schema, root, disabled, showAll, requiredFields = [], visibleFields = requiredFields, hiddenFields = [], labels = {}, prefix = "", renderReference, onChange }: {
  values: Record<string, unknown>; schema: FieldSchema; root: Record<string, unknown>; disabled: boolean;
  showAll: boolean; requiredFields?: string[]; visibleFields?: string[]; hiddenFields?: string[];
  labels?: WorkflowStep["labels"]; prefix?: string;
  renderReference?: ReferenceRenderer;
  onChange: (values: Record<string, unknown>) => void;
}) {
  const resolve = (field: FieldSchema): FieldSchema => {
    if (field.$ref) return object(object(root.$defs)[field.$ref.split("/").pop() || ""]) as FieldSchema;
    return field.anyOf ? resolve(field.anyOf.find(item => item.type !== "null") || {}) : field;
  };
  return <div className="ai-field-grid">{Object.entries(schema.properties || {}).filter(([key]) =>
    !["idempotency_key", "attachments"].includes(key) && !hiddenFields.includes(key) &&
    (showAll || (key in values && values[key] != null && values[key] !== "") || schema.required?.includes(key) ||
      visibleFields.some(required => required === key || required.startsWith(`${key}.`)))).map(([key, raw]) => {
    const field = resolve(raw), value = values[key];
    const path = prefix ? `${prefix}.${key}` : key;
    const required = !!schema.required?.includes(key) || requiredFields.includes(key);
    const caption = <FieldCaption title={fieldLabel(key)} required={required} />;
    const set = (next: unknown) => onChange({ ...values, [key]: next });
    if (field.type === "array") {
      const items = Array.isArray(value) ? value : [];
      const nested = resolve(field.items || {});
      return <fieldset key={key} className="ai-field-array" disabled={disabled}><legend>{caption}</legend>
        {items.map((item, index) => <div key={index}>
          {nested.type === "object" ? <Fields values={object(item)} schema={nested} root={root} disabled={disabled} showAll={showAll} hiddenFields={hiddenFields}
            labels={labels} prefix={`${path}.${index}`} renderReference={renderReference}
            requiredFields={requiredFields.filter(name => name.startsWith(`${key}.${index}.`)).map(name => name.slice(`${key}.${index}.`.length))}
            visibleFields={visibleFields.filter(name => name.startsWith(`${key}.${index}.`)).map(name => name.slice(`${key}.${index}.`.length))}
            onChange={updated => set(items.map((old, i) => i === index ? updated : old))} />
            : field.items?.["x-workflow-reference"] && renderReference
              ? renderReference(`${path}.${index}`, `${fieldLabel(key)} ${index + 1}`, item,
                labels[`${path}.${index}`]?.value === item ? labels[`${path}.${index}`].label : null, required)
            : <label><FieldCaption title={`${friendly(key)} ${index + 1}`} required={required} /><input aria-required={required} value={labels[`${path}.${index}`] && labels[`${path}.${index}`].value === item
              ? labels[`${path}.${index}`].label : String(item ?? "")}
              onChange={event => set(items.map((old, i) => i === index ? event.target.value : old))} /></label>}
          <button className="ai-icon-button" type="button" title={`Remove item ${index + 1}`} aria-label={`Remove item ${index + 1}`} onClick={() => set(items.filter((_, i) => i !== index))}><Trash2 size={16} /></button>
        </div>)}
        <button className="ai-add-item" type="button" onClick={() => set([...items, nested.type === "object" ? {} : ""])}><Plus size={16} /> Add {key === "lines" ? "line" : "item"}</button>
      </fieldset>;
    }
    if (field.type === "object") return <fieldset key={key}><legend>{caption}</legend>
      <Fields values={object(value)} schema={field} root={root} disabled={disabled} showAll={showAll} hiddenFields={hiddenFields}
        labels={labels} prefix={path} renderReference={renderReference}
        visibleFields={visibleFields.filter(name => name.startsWith(`${key}.`)).map(name => name.slice(key.length + 1))}
        requiredFields={requiredFields.filter(name => name.startsWith(`${key}.`)).map(name => name.slice(key.length + 1))} onChange={set} /></fieldset>;
    const label = labels[path] && labels[path].value === value ? labels[path].label : null;
    if (raw["x-workflow-reference"] && renderReference) return <div key={key}>
      {renderReference(path, fieldLabel(key), value, label, required)}</div>;
    const choices = field.enum || (field.const !== undefined ? [field.const] : null);
    if (field.type === "boolean") return <label key={key}>{caption}<select aria-required={required} disabled={disabled}
      value={value === undefined || value === null ? "" : String(value)} onChange={event => set(event.target.value === "" ? null : event.target.value === "true")}>
      <option value="">Choose explicitly</option><option value="true">Yes</option><option value="false">No</option>
    </select></label>;
    return <label key={key}>{caption}{choices ? <select aria-required={required} disabled={disabled} value={String(value ?? "")}
      onChange={event => set(event.target.value || null)}><option value="">Choose</option>
      {choices.map(choice => <option key={String(choice)} value={String(choice)}>{field["x-enum-labels"]?.[String(choice)] || String(choice)}</option>)}</select>
      : (field.maxLength || 0) >= 1000 ? <textarea aria-required={required} disabled={disabled} rows={2} value={String(value ?? "")}
        maxLength={field.maxLength} onChange={event => set(event.target.value)} />
      : <input aria-required={required} disabled={disabled} title={label || undefined} type={field.format === "date" ? "date" : "text"} value={String(label || value || (value === 0 ? 0 : ""))}
        placeholder={field.format === "uuid" ? "Search by name, not an internal ID" : undefined}
        inputMode={field.type === "number" || field.type === "integer" ? "decimal" : undefined}
        onChange={event => set(event.target.value === "" && raw.anyOf?.some(item => item.type === "null") ? null :
          field.type === "integer" && event.target.value !== "" ? Number(event.target.value) : event.target.value)} />}</label>;
  })}</div>;
}

function Impact({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>None</span>;
  if (Array.isArray(value)) return value.length ? <ol className="ai-impact-list">{value.map((item, index) =>
    <li key={index}><Impact value={item} /></li>)}</ol> : <span>None</span>;
  if (typeof value === "object") return <dl className="ai-impact">{Object.entries(object(value)).map(([key, item]) =>
    <div key={key}><dt>{friendly(key)}</dt><dd><Impact value={item} /></dd></div>)}</dl>;
  return <span>{typeof value === "boolean" ? value ? "Yes" : "No" : String(value)}</span>;
}

function ReviewPreview({ draft, labels }: { draft: ActionDraft; labels: WorkflowStep["labels"] }) {
  const preview = draft.validation?.preview;
  if (!preview) return null;
  const money = (value: unknown) => Number.isFinite(Number(value))
    ? new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(Number(value)) : String(value);
  const totals = [["subtotal", "Before tax"], ["gst_total", "GST"], ["total", "Total"],
    ["paid_or_received", draft.action_key === "purchase_create" ? "Paid now" : "Paid / received"]] as const;
  const lines = Array.isArray(preview.lines) ? preview.lines.map(object) : [];
  const stock = Array.isArray(preview.stock_changes) ? preview.stock_changes.map(object) : [];
  const context = ["vendor_party_id", "customer_party_id", "store_id", "purchase_date", "invoice_date",
    "account_id", "payment_mode", "payment_date", "transaction_date"];
  const details = Object.fromEntries(Object.entries(preview).filter(([key]) =>
    !["purchase_payload", "fields", "operation", "target", "warning"].includes(key)));
  return <section className="ai-review-preview" aria-label="Review before saving">
    <h4>Review before saving</h4>
    <p>These are the checked values. Nothing is saved until you confirm.</p>
    {!preview.fields ? <dl className="ai-review-fields">{context.filter(key => draft.payload[key] != null && draft.payload[key] !== "")
      .map(key => <div key={key}><dt>{fieldLabel(key)}</dt>
        <dd>{String(labels[key]?.value === draft.payload[key] ? labels[key].label : draft.payload[key])}</dd></div>)}</dl> : null}
    {preview.fields ? <dl className="ai-review-fields">{Object.entries(object(preview.fields))
      .filter(([, value]) => value != null && value !== "").map(([key, value]) => <div key={key}>
        <dt>{fieldLabel(key)}</dt><dd><Impact value={labels[key]?.value === value ? labels[key].label : value} /></dd>
      </div>)}</dl> : null}
    {totals.some(([key]) => preview[key] != null) ? <dl className="ai-review-totals">
      {totals.filter(([key]) => preview[key] != null).map(([key, title]) =>
        <div key={key}><dt>{title}</dt><dd>{money(preview[key])}</dd></div>)}
    </dl> : null}
    {lines.length ? <div className="ai-review-table"><table><thead><tr>
      <th>Item</th><th>Qty</th><th>Rate</th><th>GST</th><th>Total</th>
    </tr></thead><tbody>{lines.map((line, index) => <tr key={index}><td>{String(line.description || `Line ${index + 1}`)}</td>
      <td>{String(line.quantity ?? "")}</td><td>{money(line.rate)}</td><td>{String(line.gst_rate ?? "")}%</td>
      <td>{line.total != null ? money(line.total) : "See total above"}</td></tr>)}</tbody></table></div> : null}
    {stock.length ? <ul className="ai-stock-summary" aria-label="Stock before and after">{stock.map((change, index) => {
      const line = lines.find(line => line.product_id === change.product_id && line.variant_id === change.variant_id);
      const product = change.product_name || line?.description || "Stock";
      return <li key={index}><strong>{String(product)}</strong>{change.store_name ? ` @ ${String(change.store_name)}` : ""}: {String(change.current)} → {String(change.after)}
        {" "}({Number(change.change) >= 0 ? "+" : ""}{String(change.change)})</li>;
    })}</ul> : null}
    {stock.length ? <p className="ai-draft-note">Source: {draft.action_key === "invoice_create" ? "this sales invoice (stock out)" :
      draft.action_key === "purchase_create" ? "this purchase receipt (stock in)" : "this operation"}</p> : null}
    {preview.goods_received !== undefined ? <p>{preview.goods_received ? "Goods are received into stock when saved." : "Goods are not received into stock yet."}</p> : null}
    {draft.high_impact ? <Impact value={details} /> :
      Object.keys(details).length ? <details><summary>All checked details</summary><Impact value={details} /></details> : null}
  </section>;
}

function DraftCard({ draft, action, writable, busy, duplicate, workflowStep = false, referenceLabels = {}, requiredFields = [], onEdit, onRun }: {
  draft: ActionDraft; action?: DraftAction; writable: boolean; busy: boolean;
  duplicate: boolean;
  workflowStep?: boolean;
  referenceLabels?: WorkflowStep["labels"];
  requiredFields?: string[];
  onEdit?: (payload: Record<string, unknown>) => Promise<unknown>;
  onRun: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const original = JSON.stringify(draft.payload, null, 2);
  const [editing, setEditing] = useState(original);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [outcome, setOutcome] = useState<AIExecution | null>(null);
  useEffect(() => { setEditing(original); setError(""); setConfirmation(""); setOutcome(null); }, [original, draft.version]);
  const dirty = editing !== original, readonly = busy || !writable || draft.status === "executed";
  const save = async () => {
    try {
      const payload: unknown = JSON.parse(editing);
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("Enter a JSON object.");
      await onRun(() => onEdit ? onEdit(object(payload)) : ai.editDraft(draft, object(payload))); setError("");
    } catch (failure) { setError(String(failure)); }
  };
  const execute = async () => {
    const report = draft.action_key === "report_export" || draft.action_key === "gst_reconcile";
    if (!window.confirm(report ? "Approve these reviewed values and generate this private report? No business records will change. The download expires in one hour." :
      "Confirm and save these reviewed values? This records your approval and changes business records. Business rules are checked again before saving.")) return;
    await onRun(async () => { setOutcome(await ai.submitReviewedDraft(draft, confirmation || undefined)); });
  };
  let values: Record<string, unknown> | null = null;
  try { values = object(JSON.parse(editing)); } catch { /* Advanced editing may temporarily contain incomplete JSON. */ }
  return <details className="settings-card ai-draft-card" aria-label={`Draft ${draft.action_key}`} open={workflowStep || undefined}>
    <summary><ChevronDown className="ai-draft-chevron" size={17} aria-hidden="true" /><span className="ai-draft-summary">    <span className="ai-draft-title"><strong>{actionLabel(draft.action_key, draft.payload)}</strong>
      <span>{draftDescription(draft)}</span></span><span className="ai-draft-meta">
      {draft.created_at && !Number.isNaN(Date.parse(draft.created_at)) ? <time className="ai-draft-date" dateTime={draft.created_at}>
        {new Date(draft.created_at).toLocaleString()}</time> : null}
      <span className="ai-draft-state">{statusLabel(draft.status)}</span>
      {draft.high_impact ? <span className="ai-draft-duplicate">High impact</span> : null}
      {duplicate ? <span className="ai-draft-duplicate">Possible duplicate</span> : null}</span></span></summary>
    {duplicate ? <p role="status">Another draft may describe the same operation. Review both before submitting to avoid a duplicate.</p> : null}
    {draft.action_key === "purchase_bundle_create" ? <p className="ai-draft-note">Vendor → product → purchase → payment and stock receipt are reviewed and submitted together. The new product remains a draft until confirmed for sale.</p> : null}
    {draft.high_impact ? <p className="ai-message-status">High impact: review all dependencies, refunds and stock effects.</p> : null}
    <details className="ai-entry-details" open={draft.status === "editing" || dirty || undefined}>
    <summary>{draft.status === "editing" ? "Entry details" : "View or edit entry details"}</summary>
    <p className="ai-required-help"><span aria-hidden="true">*</span> Required fields</p>
    {values && action ? <><Fields values={values} schema={workflowStep && action.workflow_schema ? action.workflow_schema : action.schema}
      root={workflowStep && action.workflow_schema ? action.workflow_schema : action.schema} disabled={readonly} showAll={showAll}
      labels={referenceLabels}
      requiredFields={[...requiredFields, ...(draft.action_key === "purchase_create" ? ["store_id", "purchase_date", "received_now", "lines"] :
        draft.action_key === "purchase_bundle_create" ? ["vendor_name", "create_vendor_if_missing", "product_name", "quantity", "rate", "hsn", "store_name", "purchase_date", "price_includes_gst", "fully_paid", "received_now", ...(values?.fully_paid === true ? ["payment_mode", "account_name"] : [])] :
        draft.action_key === "invoice_create" ? ["store_id", "invoice_date", "lines"] : [])]}
      hiddenFields={draft.action_key === "purchase_bundle_create" ? ["vendor_party_id", "store_id", "account_id"] : []}
      onChange={updated => setEditing(JSON.stringify(updated, null, 2))} />
      <button type="button" aria-pressed={showAll} onClick={() => setShowAll(!showAll)}>{showAll ? "Show essential fields" : "Show all fields"}</button></> : null}
    <details className="ai-advanced"><summary>Advanced fields and reference</summary><p>Target: {draft.target_id || "New record"} · Version {draft.version}</p>
      <label className="ai-draft-editor">Draft JSON<textarea rows={8} maxLength={16000} disabled={readonly}
        value={editing} onChange={event => setEditing(event.target.value)} /></label></details>
    </details>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {draft.validation && !dirty && draft.status !== "executed" ? <ReviewPreview draft={draft} labels={referenceLabels} /> : null}
    {action?.high_impact && (draft.status === "validated" || draft.status === "approved") ? <label>Type {String(draft.validation?.preview?.confirm_text || "")} to save
      <input value={confirmation} disabled={readonly} onChange={event => setConfirmation(event.target.value)} /></label> : null}
    <div className="shop-actions ai-step-actions">
      {dirty ? <button className="ai-primary-button" disabled={readonly} onClick={() => void save()}>Save changes for review</button> : null}
      {!dirty && draft.status === "editing" ? <button className="ai-primary-button" disabled={readonly || dirty} onClick={() => void onRun(() => ai.validateDraft(draft))}>Review & check</button> : null}
      {!dirty && (draft.status === "validated" || draft.status === "approved") ? <button className="ai-primary-button" disabled={readonly || dirty || !action?.execution_enabled ||
        (action.high_impact && confirmation !== draft.validation?.preview?.confirm_text)} onClick={() => void execute()}>
          {draft.action_key === "report_export" || draft.action_key === "gst_reconcile" ? "Generate private report" : "Confirm & save"}</button> : null}
      {draft.status === "approved" || draft.status === "executed" ? <button disabled={busy} onClick={() => void onRun(async () => setOutcome((await ai.execution(draft)).execution))}>Check saved outcome</button> : null}
      {!workflowStep ? <button className="ai-icon-button" title="Discard draft" aria-label="Discard draft" disabled={readonly} onClick={() => {
        if (window.confirm("Discard this private draft? No business record is deleted.")) void onRun(() => ai.discardDraft(draft));
      }}><Trash2 size={17} /></button> : null}
    </div>
    {(draft.status === "validated" || draft.status === "approved") && !action?.execution_enabled ? <p>Posting is disabled for this action. Contact the platform administrator.</p> : null}
    {outcome ? <div role="status"><p>{outcome.status === "succeeded" ? outcome.result.report_id ? "Private report generated" : "Saved business outcome" : "Operation rejected; no business changes saved"}</p>
      <Impact value={outcome.result} />
      {outcome.status === "succeeded" && typeof outcome.result.report_id === "string" ?
        <button disabled={busy} onClick={() => void onRun(() => ai.downloadReport(outcome.id))}>Download private CSV (expires in one hour)</button> : null}
      {outcome.validation_error ? <Impact value={outcome.validation_error} /> : null}
      {outcome.status === "failed" ? <p>Edit this draft, then review and approve a new version before another submission.</p> : null}</div> : null}
    {dirty ? <p>Save edits and review again before approval.</p> : null}
  </details>;
}

function Estimate({ estimate }: { estimate: WorkflowEstimate }) {
  const money = (value: string) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(Number(value));
  return <section className="ai-review-preview" aria-label="Calculated so far">
    <h4>Calculated so far</h4>
    <dl className="ai-review-totals">
      <div><dt>Before tax</dt><dd>{money(estimate.subtotal)}</dd></div>
      <div><dt>GST</dt><dd>{money(estimate.gst_total)}</dd></div>
      <div><dt>Total</dt><dd>{money(estimate.total)}</dd></div>
    </dl>
    <div className="ai-review-table"><table><thead><tr><th>Item</th><th>Qty</th><th>Rate</th><th>GST</th><th>Total</th></tr></thead>
      <tbody>{estimate.lines.map((line, index) => <tr key={index}><td>{line.description}</td><td>{line.quantity}</td>
        <td>{money(line.rate)}{line.price_includes_gst ? " incl." : ""}</td><td>{line.gst_rate}% · {money(line.gst)}</td><td>{money(line.total)}</td></tr>)}</tbody></table></div>
    {estimate.stock?.length ? <ul className="ai-stock-summary" aria-label="Stock before and after">{estimate.stock.map((row, index) =>
      <li key={index}><strong>{row.product}</strong> @ {row.store}: {row.current} → {row.after} ({Number(row.change) >= 0 ? "+" : ""}{row.change})</li>)}</ul> : null}
    {estimate.stock_source && estimate.stock?.length ? <p className="ai-draft-note">Source: {estimate.stock_source}</p> : null}
    {estimate.stock_note ? <p className="ai-draft-note">{estimate.stock_note}</p> : null}
    <p className="ai-draft-note">Use this total for the amount paid or received, or choose Fully paid now. Review &amp; check confirms the final values.</p>
  </section>;
}

function changePath(payload: Record<string, unknown>, path: string, value: string): Record<string, unknown> {
  const updated: Record<string, unknown> = JSON.parse(JSON.stringify(payload));
  const keys = path.split(".");
  let current: Record<string, unknown> | unknown[] = updated;
  for (const key of keys.slice(0, -1)) {
    const next: unknown = Array.isArray(current) ? current[Number(key)] : current[key];
    if (!next || typeof next !== "object") throw new Error("Save the document lines before selecting a reference.");
    current = Array.isArray(next) ? next : object(next);
  }
  const key = keys[keys.length - 1];
  if (Array.isArray(current)) current[Number(key)] = value;
  else current[key] = value;
  return updated;
}

function WorkflowFields({ workflow, step, action, disabled, onRun }: {
  workflow: OperationWorkflow; step: WorkflowStep; action: DraftAction; disabled: boolean;
  onRun: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const [values, setValues] = useState(step.payload), [target, setTarget] = useState(step.target || "");
  const [showAll, setShowAll] = useState(["party_update", "account_update"].includes(step.action)), [error, setError] = useState("");
  useEffect(() => { setValues(step.payload); setTarget(step.target || ""); setError(""); }, [workflow.version, step.id]);
  const required = [...new Set([...(step.required_fields || []), ...step.issues
    .filter(issue => issue.message.startsWith("Required:") || issue.message === "Field required").map(issue => issue.field)])];
  const visible = [...new Set([...required, ...step.issues.map(issue => issue.field)])];
  const choose = (path: string, value: string, query?: string) => {
    try {
      const next = path === "target" ? values : changePath(values, path, value);
      if (path === "target") setTarget(value); else setValues(next);
      void onRun(() => ai.editWorkflow(workflow, step, path === "target" ? value : target || null, next,
        undefined, undefined, query ? { field: path, query } : undefined));
    }
    catch (failure) { setError(String(failure)); }
  };
  const targetLabel = step.labels.target?.value === target ? step.labels.target.label : null;
  const schema = action.workflow_schema || action.schema;
  const renderReference: ReferenceRenderer = (path, title, value, label, required) => <WorkflowReference
    workflow={workflow} step={step} field={path} title={title} value={value} label={label} required={required} disabled={disabled}
    onChange={value => {
      if (path === "target") setTarget(value);
      else setValues(current => changePath(current, path, value));
    }}
    onChoose={(value, query) => choose(path, value, query)}
    onCreate={query => {
      const next = changePath(values, path, query);
      setValues(next);
      void onRun(() => ai.editWorkflow(workflow, step, target || null, next, path));
    }} />;
  return <section className="settings-card" aria-label={`Workflow step ${step.action}`}>
    <h4>{actionLabel(step.action, values)}</h4>
    <p className="ai-required-help"><span aria-hidden="true">*</span> Required fields</p>
    {action.target_required ? renderReference("target", "Find the existing record", target, targetLabel, true) : null}
    <Fields values={values} schema={schema} root={schema} disabled={disabled} showAll={showAll}
      requiredFields={required} visibleFields={visible} labels={step.labels} renderReference={renderReference} onChange={setValues} />
    {(!action.workflow_schema ? step.choices : []).map(choice => <div key={choice.field}>
      <label>{fieldLabel(choice.field)}: search results
        <select disabled={disabled} value="" onChange={event => { if (event.target.value) choose(choice.field, event.target.value); }}>
          <option value="">Select a record</option>
          {choice.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      {choice.more_matches ? <p>More matches exist. Enter a more specific name.</p> : null}
      {choice.can_create ? <button disabled={disabled}
        onClick={() => void onRun(() => ai.editWorkflow(workflow, step, target || null, values, choice.field))}>
        Create new {String(choice.query)}</button> : null}
      {choice.manual_path ? <Link to={choice.manual_path}>Manage {choice.capability}</Link> : null}
    </div>)}
    {step.estimate ? <Estimate estimate={step.estimate} /> : null}
    {step.issues.length ? <ul role="status">{step.issues.map((issue, index) =>
      <li key={index}>{fieldLabel(issue.field)}: {issue.message}
        {issue.links?.map(link => <Link key={link.path} className="ai-issue-link" to={link.path}>{link.label}</Link>)}</li>)}</ul> : null}
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    <div className="shop-actions">
      <button className="ai-primary-button" disabled={disabled} onClick={() => void onRun(() => ai.editWorkflow(workflow, step, target || null, values))}>
        Continue with these details</button>
      <button disabled={disabled} aria-pressed={showAll} onClick={() => setShowAll(!showAll)}>
        {showAll ? "Show essential fields" : "Show all fields"}</button>
    </div>
  </section>;
}

export function AIDrafts({ conversationId, refreshKey, writable, aiEnabled }: {
  conversationId: string; refreshKey: number; writable: boolean; aiEnabled: boolean;
}) {
  const [drafts, setDrafts] = useState<ActionDraft[]>([]), [actions, setActions] = useState<DraftAction[]>([]);
  const [workflows, setWorkflows] = useState<OperationWorkflow[]>([]);
  const startRequest = useRef<{ signature: string; key: string } | null>(null);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [offset, setOffset] = useState(0);
  const history = async () => {
    const [draftHistory, workflowHistory] = await Promise.all([ai.drafts(conversationId, offset), ai.workflows(conversationId, offset)]);
    const ids = [...new Set(workflowHistory.items.filter(workflow => workflow.status === "active")
      .flatMap(workflow => workflow.plan.steps.flatMap(step => step.draft_id ? [step.draft_id] : [])))];
    const missing = await Promise.all(ids.filter(id => !draftHistory.items.some(draft => draft.id === id)).map(id => ai.draft(id)));
    return { drafts: [...draftHistory.items, ...missing], workflows: workflowHistory.items };
  };
  useEffect(() => {
    let active = true;
    setDrafts([]); setWorkflows([]);
    void Promise.all([history(), aiEnabled ? ai.actions() : Promise.resolve({ items: [] })])
      .then(([loaded, policies]) => { if (active) { setDrafts(loaded.drafts); setWorkflows(loaded.workflows); setActions(policies.items); setError(""); } })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [conversationId, refreshKey, aiEnabled, offset]);
  const run = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try {
      await operation();
      const current = (await ai.workflows(conversationId, offset)).items;
      for (const workflow of current.filter(workflow => workflow.status === "active")) {
        await ai.continueWorkflow(workflow);
      }
    } catch (failure) { setError(String(failure)); }
    finally {
      try { const loaded = await history(); setDrafts(loaded.drafts); setWorkflows(loaded.workflows); }
      catch (failure) { setError(String(failure)); }
      setBusy(false);
    }
  };
  const start = (action: string, target: string | null = null, payload: Record<string, unknown> = {}) => run(async () => {
    const signature = JSON.stringify([conversationId, action, target, payload]);
    if (startRequest.current && startRequest.current.signature !== signature) {
      throw new Error("Check the previous workflow request before starting a different one.");
    }
    startRequest.current ||= { signature, key: crypto.randomUUID() };
    await ai.startWorkflow(conversationId, action, target, payload, startRequest.current.key);
    startRequest.current = null;
  });
  const owned = new Set(workflows.flatMap(workflow => workflow.plan.steps.flatMap(step => step.draft_id ? [step.draft_id] : [])));
  return <section className="ai-drafts" aria-label="Private operational drafts">
    {workflows.map(workflow => <details className="settings-card" key={workflow.id} open>
      <summary><strong>{actionLabel(workflow.action_key, workflow.plan.steps[0]?.payload)} workflow</strong> · {workflow.status === "completed" ? "Completed" : "In progress"}</summary>
      <p className="ai-draft-note">Complete the details, review, then confirm &amp; save. Each saved prerequisite advances the next step automatically.</p>
      {workflow.operation_summary ? <p className="ai-draft-note" aria-label="Connected operations">{workflow.operation_summary}</p> : null}
      <ol className="ai-workflow-progress" aria-label="Workflow progress">{[...workflow.plan.steps].reverse().map(step =>
        <li key={step.id} data-completed={step.draft_status === "executed"}>{actionLabel(step.action, step.payload)} · {step.draft_status === "executed" ? "Done" :
          step.draft_id ? "Ready for review" : waitingForPrerequisites(step, workflow.plan.steps) ? "Waiting for prerequisites" : "Needs details"}</li>)}</ol>
      {[...workflow.plan.steps].reverse().map(step => {
        const pending = [...workflow.plan.steps].reverse().find(item => item.draft_status !== "executed" &&
          !waitingForPrerequisites(item, workflow.plan.steps));
        if (workflow.status === "active" && pending && step.id !== pending.id) return null;
        const action = actions.find(item => item.key === step.action), draft = drafts.find(item => item.id === step.draft_id);
        if (draft) return <DraftCard key={step.id} draft={draft} action={action} writable={writable && !!action}
          busy={busy} duplicate={hasDuplicateDraft(draft, drafts)} workflowStep referenceLabels={step.labels}
          requiredFields={step.required_fields}
          onEdit={payload => ai.editWorkflow(workflow, step, step.target, payload, undefined, draft.version)} onRun={run} />;
        if (step.draft_status === "executed") return <p key={step.id}>{actionLabel(step.action)}: submitted</p>;
        return action ? <WorkflowFields key={step.id} workflow={workflow} step={step} action={action}
          disabled={busy || !writable || workflow.status !== "active"} onRun={run} /> :
          <p key={step.id}>{actionLabel(step.action)}: action unavailable. Check permissions and platform settings.</p>;
      })}
      <div className="shop-actions ai-workflow-actions">
      {workflow.status === "active" ? <button disabled={busy || !writable || !aiEnabled} onClick={() => void run(() => ai.continueWorkflow(workflow))}>
        Refresh workflow</button> : <div role="status"><p>Completed. Would you like to make the next entry?</p>
        {workflow.plan.next.map((next, index) => next.path ? <p key={index}><Link to={next.path}>{next.label}</Link></p> :
          <button key={index} disabled={busy || !writable || !actions.some(action => action.key === next.action)}
            onClick={() => void start(next.action, next.target, next.payload)}>{next.label}</button>)}
      </div>}
      <button className="ai-danger-button" disabled={busy || !writable} onClick={() => {
        if (window.confirm("Discard this workflow and its unposted drafts? Already submitted records are not undone.")) {
          void run(() => ai.discardWorkflow(workflow));
        }
      }}>Discard workflow</button>
      </div>
    </details>)}
    {drafts.length ? <p className="ai-draft-note">Nothing is posted until you confirm &amp; save the reviewed step.</p> : null}
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {drafts.filter(draft => !owned.has(draft.id)).map(draft => <DraftCard key={draft.id} draft={draft} duplicate={hasDuplicateDraft(draft, drafts)}
      action={actions.find(action => action.key === draft.action_key)} busy={busy}
      writable={writable && actions.some(action => action.key === draft.action_key)} onRun={run} />)}
    {!drafts.length && !workflows.length ? <p>No workflows or drafts to review.</p> : null}
    {offset || drafts.length >= 30 || workflows.length >= 30 ? <div className="shop-actions">
      <button disabled={busy || !offset} onClick={() => setOffset(Math.max(0, offset - 30))}>Newer drafts</button>
      <button disabled={busy || drafts.length < 30} onClick={() => setOffset(offset + 30)}>Older drafts</button>
    </div> : null}
  </section>;
}
