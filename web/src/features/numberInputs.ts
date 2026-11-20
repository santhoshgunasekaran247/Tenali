/**
 * Number boxes drop redundant leading zeros as you type ("010" becomes "10", "0.5" stays).
 * React leaves a controlled number input untouched while its text parses to the same number,
 * so without this a field holding 0 keeps the 0 in front of whatever is typed next.
 */
export function withoutLeadingZeros(value: string): string {
  return value.replace(/^(-?)0+(?=\d)/, "$1");
}

function tidy(event: Event) {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== "number") return;
  const cleaned = withoutLeadingZeros(input.value);
  if (cleaned === input.value) return;
  // The prototype setter bypasses React's value tracker, so React still sees the change and
  // passes the cleaned text to the field's onChange handler.
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, cleaned);
}

/** A focused box that holds only 0 is selected, so typing replaces the 0. */
function selectZero(event: Event) {
  const input = event.target;
  if (input instanceof HTMLInputElement && input.type === "number" && Number(input.value) === 0 && input.value !== "") input.select();
}

export function installNumberInputs() {
  if (typeof document === "undefined") return;
  // Capture phase on the document runs before React's own listener on the app root.
  document.addEventListener("input", tidy, true);
  document.addEventListener("focusin", selectZero);
}
