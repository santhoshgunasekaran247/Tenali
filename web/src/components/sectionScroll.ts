const USER_SCROLL_EVENTS = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
const SETTLE_MS = 1500;

function stickyHeaderHeight() {
  const header = document.querySelector?.(".header");
  if (!header) return 0;
  const position = getComputedStyle(header).position;
  return position === "sticky" || position === "fixed" ? Math.ceil(header.getBoundingClientRect().height) : 0;
}

function align(target: Element) {
  const top = target.getBoundingClientRect().top + window.scrollY - stickyHeaderHeight();
  window.scrollTo({ top: Math.max(0, Math.round(top)), left: 0, behavior: "instant" });
}

// Places the section directly below the sticky header and keeps it there while images and fonts
// above it finish loading, until the shopper scrolls or the layout has had time to settle.
export function scrollToSection(target: Element): () => void {
  align(target);
  if (typeof ResizeObserver === "undefined") return () => undefined;
  let stopped = false;
  const observer = new ResizeObserver(() => { if (!stopped) align(target); });
  const stop = () => {
    if (stopped) return;
    stopped = true;
    observer.disconnect();
    clearTimeout(timer);
    USER_SCROLL_EVENTS.forEach(name => window.removeEventListener(name, stop));
  };
  const timer = setTimeout(stop, SETTLE_MS);
  USER_SCROLL_EVENTS.forEach(name => window.addEventListener(name, stop, { passive: true }));
  observer.observe(document.body);
  return stop;
}
