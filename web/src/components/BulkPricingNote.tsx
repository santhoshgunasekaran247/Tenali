import { useEffect, useRef, useState } from "react";

/** One-line bulk-pricing note. When the text does not fit, a "More" toggle unfolds it (the full text is also the tooltip). */
export function BulkPricingNote({ heading, description }: { heading: string; description: string }) {
  const textRef = useRef<HTMLSpanElement>(null);
  const [clipped, setClipped] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const element = textRef.current;
    if (!element) return;
    const measure = () => { if (!open) setClipped(element.scrollWidth > element.clientWidth + 1); };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [open, heading, description]);

  return (
    <p className={`bulk-pricing${open ? " is-open" : ""}`} title={`${heading} ${description}`}>
      <strong>{heading}</strong>
      <span ref={textRef}>{description}</span>
      {clipped || open ? <button type="button" className="bulk-more" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {open ? "Less" : "More"}
      </button> : null}
    </p>
  );
}
