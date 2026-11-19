import { Minus, Plus } from "lucide-react";

type Props = {
  value: string;
  min: number;
  max: number;
  label: string;
  disabled?: boolean;
  /** When set, pressing minus at the minimum calls this instead (e.g. remove from cart). */
  onBelowMin?: () => void;
  onChange: (value: string) => void;
};

/** Whole-number quantity input with large minus/plus buttons; typing stays possible for bigger jumps. */
export function QuantityStepper({ value, min, max, label, disabled, onBelowMin, onChange }: Props) {
  const current = Number(value);
  const count = Number.isInteger(current) ? current : min;
  const atMin = count <= min;
  return <div className="quantity-stepper" role="group" aria-label={label} onClick={event => event.stopPropagation()}>
    <button type="button" aria-label={atMin && onBelowMin ? `Remove ${label.replace(/^Quantity for /, "")}` : `Decrease ${label.toLowerCase()}`}
      disabled={disabled || (atMin && !onBelowMin)}
      onClick={() => atMin ? onBelowMin?.() : onChange(String(Math.min(max, count - 1)))}><Minus size={16} aria-hidden="true" /></button>
    <input aria-label={label} type="number" inputMode="numeric" min={min} max={max} step={1} value={value} disabled={disabled}
      onChange={event => onChange(event.target.value)} onKeyDown={event => event.stopPropagation()} />
    <button type="button" aria-label={`Increase ${label.toLowerCase()}`} disabled={disabled || count >= max}
      onClick={() => onChange(String(Math.max(min, count + 1)))}><Plus size={16} aria-hidden="true" /></button>
  </div>;
}
