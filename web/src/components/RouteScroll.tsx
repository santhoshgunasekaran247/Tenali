import { useEffect, useLayoutEffect } from "react";
import { useLocation } from "react-router-dom";
import { scrollToSection } from "./sectionScroll";

export function RouteScroll() {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    const previous = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    return () => { window.history.scrollRestoration = previous; };
  }, []);

  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    if (!hash) return;
    let stopSettling: (() => void) | undefined;
    const scrollToTarget = () => {
      const target = document.getElementById(hash.slice(1));
      if (!target) return false;
      stopSettling = scrollToSection(target);
      return true;
    };
    if (scrollToTarget()) return () => stopSettling?.();
    const observer = new MutationObserver(() => {
      if (scrollToTarget()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => { observer.disconnect(); stopSettling?.(); };
  }, [pathname, hash]);

  return null;
}
