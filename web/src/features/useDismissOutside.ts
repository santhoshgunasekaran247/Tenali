import { useEffect, useRef, type RefObject } from "react";

export function useDismissOutside(container: RefObject<HTMLElement | null>, dismiss: () => void, enabled = true,
  trigger?: RefObject<HTMLElement | null>) {
  const callback = useRef(dismiss);
  callback.current = dismiss;
  useEffect(() => {
    if (!enabled) return;
    const outside = (event: Event) => {
      if (event.target instanceof Node && container.current && !container.current.contains(event.target) &&
        !trigger?.current?.contains(event.target)) callback.current();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
    };
  }, [container, enabled, trigger]);
}
