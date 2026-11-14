import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { ai, type OperationWorkflow, type WorkflowChoice, type WorkflowStep } from "../features/ai";

export function FieldCaption({ title, required = false }: { title: string; required?: boolean }) {
  return <span className="ai-field-caption">{title}{required ? <span className="ai-required-mark" aria-hidden="true"> *</span> : null}</span>;
}

export function WorkflowReference({ workflow, step, field, title, value, label, required = false, disabled, onChange, onChoose, onCreate }: {
  workflow: OperationWorkflow; step: WorkflowStep; field: string; title: string;
  value: unknown; label?: string | null; disabled: boolean;
  required?: boolean;
  onChange: (value: string) => void;
  onChoose: (value: string, query: string) => void;
  onCreate: (query: string) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false), [active, setActive] = useState(-1);
  const [result, setResult] = useState<WorkflowChoice | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const text = label || String(value ?? ""), query = text.trim();
  useEffect(() => {
    setResult(null); setActive(-1); setError(""); setLoading(false);
    if (!open || disabled || query.length < 2 || query.length > 80) return;
    let current = true;
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      void ai.searchWorkflow(workflow, step, field, query, controller.signal).then(result => {
        if (current) { setResult(result); setLoading(false); }
      }).catch(failure => {
        if (current) { setError(String(failure)); setLoading(false); }
      });
    }, 300);
    return () => { current = false; window.clearTimeout(timer); controller.abort(); };
  }, [open, disabled, query, workflow.id, workflow.version, step.id, field]);
  const choices = result?.query === query ? result : null;
  const select = (value: string) => { setOpen(false); onChoose(value, query); };
  return <div className="workflow-reference" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }}>
    <label htmlFor={id}><FieldCaption title={title} required={required} /></label>
    <input id={id} role="combobox" aria-autocomplete="list" aria-expanded={open}
      aria-controls={`${id}-options`} aria-activedescendant={open && active >= 0 ? `${id}-option-${active}` : undefined}
      autoComplete="off" aria-required={required} disabled={disabled} value={text} title={label || undefined} placeholder="Search records..."
      onFocus={() => setOpen(true)} onChange={event => { onChange(event.target.value); setOpen(true); setActive(-1); }}
      onKeyDown={event => {
        if (event.key === "Escape") { setOpen(false); return; }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault(); setOpen(true);
          const count = choices?.options.length || 0;
          if (count) setActive(index => event.key === "ArrowDown" ? (index + 1) % count : (index <= 0 ? count - 1 : index - 1));
        }
        if (event.key === "Enter") {
          event.preventDefault();
          if (open && active >= 0 && choices?.options[active]) select(choices.options[active].value);
        }
      }} />
    {open && !disabled ? <div className="workflow-reference-dropdown">
      {query.length < 2 ? <p role="status">Type at least 2 characters.</p> :
        query.length > 80 ? <p role="status">Use at most 80 characters.</p> :
        loading ? <p role="status">Searching...</p> : error ? <p role="alert">{error}</p> : null}
      <div id={`${id}-options`} role="listbox" aria-label={`${title} matches`}>
        {choices?.options.map((option, index) => <button key={option.value} id={`${id}-option-${index}`}
          type="button" role="option" aria-selected={active === index} tabIndex={-1}
          onMouseDown={event => event.preventDefault()} onClick={() => select(option.value)}>{option.label}</button>)}
      </div>
      {choices ? <>
        {!choices.options.length ? <p role="status">No matching records.</p> : null}
        {choices.more_matches ? <p role="status">More matches exist. Type a more specific name.</p> : null}
        {choices.can_create ? <button type="button" onClick={() => { setOpen(false); onCreate(query); }}>
          Create new {query}</button> : null}
        {choices.manual_path ? <Link to={choices.manual_path}>Manage {choices.capability}</Link> : null}
      </> : null}
    </div> : null}
  </div>;
}
