import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

type ProductRailProps = {
  label: string;
  children: ReactNode;
  className?: string;
};

/** A single horizontally scrolling row of cards with previous/next controls and edge fades. */
export function ProductRail({ label, children, className }: ProductRailProps) {
  const track = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ previous: false, next: false });
  useEffect(() => {
    const element = track.current;
    if (!element) return;
    const update = () => setEdges({
      previous: element.scrollLeft > 4,
      next: element.scrollLeft + element.clientWidth < element.scrollWidth - 4,
    });
    update();
    element.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(element);
    return () => { element.removeEventListener("scroll", update); observer?.disconnect(); };
  }, [children]);
  const move = (direction: number) => {
    const element = track.current;
    if (element) element.scrollBy({ left: direction * Math.max(160, element.clientWidth * 0.85), behavior: "smooth" });
  };
  return (
    <div
      className={className ? `product-rail ${className}` : "product-rail"}
      data-more-previous={edges.previous ? "true" : undefined}
      data-more-next={edges.next ? "true" : undefined}
    >
      <button type="button" className="product-rail-arrow previous" aria-label={`Scroll ${label} back`} hidden={!edges.previous} onClick={() => move(-1)}>
        <ChevronLeft size={20} aria-hidden="true" />
      </button>
      <div className="product-rail-track" ref={track} role="region" aria-label={label} tabIndex={0}>
        {children}
      </div>
      <button type="button" className="product-rail-arrow next" aria-label={`Scroll ${label} forward`} hidden={!edges.next} onClick={() => move(1)}>
        <ChevronRight size={20} aria-hidden="true" />
      </button>
    </div>
  );
}
