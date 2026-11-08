import { useEffect, useState } from "react";
import { ai, type ActionDraft, type DraftAction, type AIExecution } from "../features/ai";
import { FloatingAlert } from "./Notifications";

type FieldSchema = { type?: string; title?: string; format?: string; enum?: unknown[]; const?: unknown;
  anyOf?: FieldSchema[]; $ref?: string; properties?: Record<string, FieldSchema>; items?: FieldSchema };
const friendly = (value: string) => value.replace(/_/g, " ");
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

function Fields({ values, schema, root, disabled, onChange }: {
  values: Record<string, unknown>; schema: FieldSchema; root: Record<string, unknown>; disabled: boolean;
  onChange: (values: Record<string, unknown>) => void;
}) {
  const resolve = (field: FieldSchema): FieldSchema => {
    if (field.$ref) return object(object(root.$defs)[field.$ref.split("/").pop() || ""]) as FieldSchema;
    return field.anyOf ? resolve(field.anyOf.find(item => item.type !== "null") || {}) : field;
  };
  return <div className="ai-field-grid">{Object.entries(schema.properties || {}).filter(([key]) =>
    !["idempotency_key", "attachments"].includes(key)).map(([key, raw]) => {
    const field = resolve(raw), value = values[key];
    const set = (next: unknown) => onChange({ ...values, [key]: next });
    if (field.type === "array") {
      const items = Array.isArray(value) ? value : [];
      const nested = resolve(field.items || {});
      return <fieldset key={key} className="ai-field-array" disabled={disabled}><legend>{friendly(key)}</legend>
        {items.map((item, index) => <div key={index}>
          {nested.type === "object" ? <Fields values={object(item)} schema={nested} root={root} disabled={disabled}
            onChange={updated => set(items.map((old, i) => i === index ? updated : old))} />
            : <label>{friendly(key)} {index + 1}<input value={String(item ?? "")}
              onChange={event => set(items.map((old, i) => i === index ? event.target.value : old))} /></label>}
          <button type="button" onClick={() => set(items.filter((_, i) => i !== index))}>Remove item {index + 1}</button>
        </div>)}
        <button type="button" onClick={() => set([...items, nested.type === "object" ? {} : ""])}>Add {key === "lines" ? "line" : "item"}</button>
      </fieldset>;
    }
    if (field.type === "object") return <fieldset key={key}><legend>{friendly(key)}</legend>
      <Fields values={object(value)} schema={field} root={root} disabled={disabled} onChange={set} /></fieldset>;
    const choices = field.enum || (field.const !== undefined ? [field.const] : null);
    if (field.type === "boolean") return <label key={key}>{friendly(key)}<select disabled={disabled}
      value={value === undefined || value === null ? "" : String(value)} onChange={event => set(event.target.value === "" ? null : event.target.value === "true")}>
      <option value="">Choose explicitly</option><option value="true">Yes</option><option value="false">No</option>
    </select></label>;
    return <label key={key}>{friendly(key)}{choices ? <select disabled={disabled} value={String(value ?? "")}
      onChange={event => set(event.target.value || null)}><option value="">Choose</option>
      {choices.map(choice => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}</select>
      : <input disabled={disabled} type={field.format === "date" ? "date" : "text"} value={String(value ?? "")}
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

function DraftCard({ draft, action, writable, busy, onRun }: {
  draft: ActionDraft; action?: DraftAction; writable: boolean; busy: boolean;
  onRun: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const original = JSON.stringify(draft.payload, null, 2);
  const [editing, setEditing] = useState(original);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [outcome, setOutcome] = useState<AIExecution | null>(null);
  useEffect(() => { setEditing(original); setError(""); setConfirmation(""); setOutcome(null); }, [original, draft.version]);
  const dirty = editing !== original, readonly = busy || !writable || draft.status === "executed";
  const save = async () => {
    try {
      const payload: unknown = JSON.parse(editing);
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("Enter a JSON object.");
      await onRun(() => ai.editDraft(draft, object(payload))); setError("");
    } catch (failure) { setError(String(failure)); }
  };
  const approve = async () => {
    if (!window.confirm("Approve these exact reviewed values? Approval alone does NOT post, pay, or change stock.")) return;
    await onRun(() => ai.approveDraft(draft));
  };
  const execute = async () => {
    if (!window.confirm("Submit this approved operation? This changes business records. A rejected business rule rolls everything back.")) return;
    await onRun(async () => { setOutcome(await ai.executeDraft(draft, confirmation || undefined)); });
  };
  let values: Record<string, unknown> | null = null;
  try { values = object(JSON.parse(editing)); } catch { /* Advanced editing may temporarily contain incomplete JSON. */ }
  return <details className="settings-card" open={draft.status !== "executed"} aria-label={`Draft ${draft.action_key}`}>
    <summary>{friendly(draft.action_key)} · {draft.status}</summary>
    {action?.high_impact ? <p className="ai-message-status">High impact: review all dependencies, refunds and stock effects.</p> : null}
    {values && action ? <Fields values={values} schema={action.schema} root={action.schema} disabled={readonly}
      onChange={updated => setEditing(JSON.stringify(updated, null, 2))} /> : null}
    <details><summary>Advanced fields and reference</summary><p>Target: {draft.target_id || "New record"} · Version {draft.version}</p>
      <label className="ai-draft-editor">Draft JSON<textarea rows={8} maxLength={16000} disabled={readonly}
        value={editing} onChange={event => setEditing(event.target.value)} /></label></details>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {draft.validation ? <section aria-label="Reviewed impact">
      <p>{draft.validation.warning}</p>
      <Impact value={draft.validation.preview} />
    </section> : null}
    {action?.high_impact && draft.status === "approved" ? <label>Type {String(draft.validation?.preview?.confirm_text || "")} to submit
      <input value={confirmation} disabled={readonly} onChange={event => setConfirmation(event.target.value)} /></label> : null}
    <div className="shop-actions">
      <button disabled={readonly || !dirty} onClick={() => void save()}>Save edits & invalidate approval</button>
      <button disabled={readonly || dirty} onClick={() => void onRun(() => ai.validateDraft(draft))}>Review calculated impact</button>
      <button disabled={readonly || dirty || draft.status !== "validated"} onClick={() => void approve()}>Approve reviewed values</button>
      <button disabled={readonly || dirty || draft.status !== "approved" || !action?.execution_enabled ||
        (action.high_impact && confirmation !== draft.validation?.preview?.confirm_text)} onClick={() => void execute()}>Submit operation</button>
      <button disabled={busy} onClick={() => void onRun(async () => setOutcome((await ai.execution(draft)).execution))}>Check saved outcome</button>
      <button disabled={readonly} onClick={() => {
        if (window.confirm("Discard this private draft? No business record is deleted.")) void onRun(() => ai.discardDraft(draft));
      }}>Discard</button>
    </div>
    {draft.status === "approved" && !action?.execution_enabled ? <p>Posting is disabled for this action. Contact the platform administrator.</p> : null}
    {outcome ? <div role="status"><p>{outcome.status === "succeeded" ? "Saved business outcome" : "Operation rejected; no business changes saved"}</p>
      <Impact value={outcome.result} />
      {outcome.validation_error ? <Impact value={outcome.validation_error} /> : null}
      {outcome.status === "failed" ? <p>Edit this draft, then review and approve a new version before another submission.</p> : null}</div> : null}
    {dirty ? <p>Save edits and review again before approval.</p> : null}
  </details>;
}

export function AIDrafts({ conversationId, refreshKey, writable, aiEnabled }: {
  conversationId: string; refreshKey: number; writable: boolean; aiEnabled: boolean;
}) {
  const [drafts, setDrafts] = useState<ActionDraft[]>([]), [actions, setActions] = useState<DraftAction[]>([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [offset, setOffset] = useState(0);
  const [destructive, setDestructive] = useState(false);
  useEffect(() => {
    let active = true;
    void Promise.all([ai.drafts(conversationId, offset), aiEnabled ? ai.actions() : Promise.resolve({ items: [] })])
      .then(([history, policies]) => { if (active) { setDrafts(history.items); setActions(policies.items); setError(""); } })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [conversationId, refreshKey, aiEnabled, offset]);
  const run = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await operation(); } catch (failure) { setError(String(failure)); }
    finally {
      try { setDrafts((await ai.drafts(conversationId, offset)).items); } catch (failure) { setError(String(failure)); }
      setBusy(false);
    }
  };
  const highImpact = (draft: ActionDraft) => ["invoice_cancel", "purchase_cancel", "product_delete", "transaction_delete"].includes(draft.action_key);
  return <section className="ai-drafts" aria-label="Private operational drafts">
    <div className="shop-actions"><button aria-pressed={!destructive} onClick={() => setDestructive(false)}>Add / update</button>
      <button aria-pressed={destructive} onClick={() => setDestructive(true)}>Cancel / delete</button></div>
    <p>{destructive ? "Separate high-impact operations require reviewed dependencies and exact typed confirmation." :
      "Ask in chat to prepare an operation. Review, approve, then explicitly submit. Chat replies never authorize changes."}</p>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {drafts.filter(draft => highImpact(draft) === destructive).map(draft => <DraftCard key={draft.id} draft={draft}
      action={actions.find(action => action.key === draft.action_key)} busy={busy}
      writable={writable && actions.some(action => action.key === draft.action_key)} onRun={run} />)}
    {!drafts.some(draft => highImpact(draft) === destructive) ? <p>No {destructive ? "cancellation / deletion" : "add / update"} drafts.</p> : null}
    {offset || drafts.length >= 30 ? <div className="shop-actions">
      <button disabled={busy || !offset} onClick={() => setOffset(Math.max(0, offset - 30))}>Newer drafts</button>
      <button disabled={busy || drafts.length < 30} onClick={() => setOffset(offset + 30)}>Older drafts</button>
    </div> : null}
  </section>;
}
