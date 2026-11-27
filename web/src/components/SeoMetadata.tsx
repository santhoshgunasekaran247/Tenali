import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { tenantBase, tenantFetch } from "../features/tenantTransport";

type Metadata = {
  title: string;
  description: string;
  canonical: string | null;
  image: string | null;
  kind: string;
  indexable: boolean;
  structured_data: Record<string, unknown>[];
};

function meta(attribute: "name" | "property", key: string, value: string | null) {
  let node = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`);
  if (value === null) { node?.remove(); return; }
  if (!node) {
    node = document.createElement("meta");
    node.setAttribute(attribute, key);
    document.head.append(node);
  }
  node.content = value;
}

export function applySeoMetadata(data: Metadata) {
  document.title = data.title;
  meta("name", "description", data.description);
  meta("name", "robots", data.indexable ? "index,follow" : "noindex,follow");
  meta("property", "og:title", data.title);
  meta("property", "og:description", data.description);
  meta("property", "og:type", data.kind);
  meta("property", "og:url", data.canonical);
  meta("property", "og:image", data.image);
  meta("name", "twitter:card", "summary_large_image");
  meta("name", "twitter:title", data.title);
  meta("name", "twitter:description", data.description);
  meta("name", "twitter:image", data.image);
  let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!data.canonical) canonical?.remove();
  else {
    if (!canonical) { canonical = document.createElement("link"); canonical.rel = "canonical"; document.head.append(canonical); }
    canonical.href = data.canonical;
  }
  document.head.querySelectorAll("script[data-tenali-seo]").forEach(node => node.remove());
  for (const entry of data.structured_data) {
    const node = document.createElement("script");
    node.type = "application/ld+json";
    node.dataset.tenaliSeo = "";
    node.textContent = JSON.stringify(entry);
    document.head.append(node);
  }
}

export function SeoMetadata() {
  const { pathname, search } = useLocation();
  useEffect(() => {
    const controller = new AbortController();
    const path = tenantBase() + pathname + search;
    const renderedPath = document.documentElement.dataset.tenaliSeoPath;
    if (renderedPath === path) return;
    delete document.documentElement.dataset.tenaliSeoPath;
    meta("name", "robots", "noindex,follow");
    document.head.querySelector('link[rel="canonical"]')?.remove();
    document.head.querySelectorAll("script[data-tenali-seo]").forEach(node => node.remove());
    void tenantFetch("/api/seo/metadata?" + new URLSearchParams({ path }), { signal: controller.signal })
      .then(async response => {
        if (!response.ok && response.status !== 404) throw new Error(`Metadata request failed (HTTP ${response.status})`);
        const data: Metadata = await response.json();
        if (!controller.signal.aborted) applySeoMetadata(data);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) console.error("Unable to load page search metadata.", error);
      });
    return () => controller.abort();
  }, [pathname, search]);
  return null;
}
