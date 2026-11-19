/**
 * Visible feedback for user-triggered requests: the pressed button gets a spinner (aria-busy),
 * the page shows a progress cursor and a thin top progress bar. Background polling stays silent
 * because only requests started shortly after a click or form submit are tracked.
 */
const INTERACTION_WINDOW_MS = 1500;
const SHOW_DELAY_MS = 120;

let lastInteraction = 0;
let lastControl: HTMLElement | null = null;
let pending = 0;
let showTimer: number | undefined;
const busyControls = new Map<HTMLElement, number>();

function remember(event: Event) {
  const target = event.target instanceof Element ? event.target : null;
  const control = event.type === "submit"
    ? (event as SubmitEvent).submitter || (target as HTMLFormElement | null)?.querySelector<HTMLElement>("button[type=submit], button:not([type])") || null
    : target?.closest<HTMLElement>("button, a.btn, [role=button]") || null;
  if (!control) return;
  lastInteraction = Date.now();
  lastControl = control;
}

export function installBusyIndicator() {
  if (typeof document === "undefined") return;
  document.addEventListener("click", remember, true);
  document.addEventListener("submit", remember, true);
}

function setBusy(on: boolean) {
  const root = document.documentElement;
  if (on) {
    if (showTimer === undefined && !root.hasAttribute("data-busy")) {
      showTimer = window.setTimeout(() => { showTimer = undefined; if (pending > 0) root.setAttribute("data-busy", ""); }, SHOW_DELAY_MS);
    }
  } else {
    if (showTimer !== undefined) { window.clearTimeout(showTimer); showTimer = undefined; }
    root.removeAttribute("data-busy");
  }
}

/** Wraps a request so a recently pressed control shows loading until the request settles. */
export async function trackRequest<T>(request: () => Promise<T>): Promise<T> {
  if (typeof document === "undefined" || Date.now() - lastInteraction > INTERACTION_WINDOW_MS) return request();
  const control = lastControl;
  pending += 1;
  setBusy(true);
  if (control) {
    busyControls.set(control, (busyControls.get(control) || 0) + 1);
    control.setAttribute("aria-busy", "true");
  }
  try {
    return await request();
  } finally {
    pending -= 1;
    if (pending <= 0) { pending = 0; setBusy(false); }
    if (control) {
      const left = (busyControls.get(control) || 1) - 1;
      if (left > 0) busyControls.set(control, left);
      else { busyControls.delete(control); control.removeAttribute("aria-busy"); }
    }
  }
}
