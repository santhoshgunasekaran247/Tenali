import { trackRequest } from "./busyIndicator";

export function tenantBase(): string {
  return window.location.pathname.match(/^\/c\/[a-z0-9-]+(?=\/|$)/)?.[0] || "";
}

export function tenantSlug(): string {
  return tenantBase().split("/")[2] || "";
}

export function tenantHeaders(): Record<string,string> {
  const headers:Record<string,string>={};
  const slug=tenantSlug();
  if(slug)headers['X-Tenant-Slug']=slug;
  const csrf=document.cookie.split('; ').find(value=>value.startsWith('tenali_csrf='))?.split('=').slice(1).join('=');
  if(csrf)headers['X-CSRF-Token']=decodeURIComponent(csrf);
  return headers;
}

export async function tenantFetch(input: RequestInfo|URL,options?:RequestInit) {
  const apiOrigin = tenantApiOrigin();
  const rawUrl = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(rawUrl, window.location.origin);
  const remote = !!apiOrigin && url.origin === window.location.origin && url.pathname.startsWith("/api/");
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  Object.entries(tenantHeaders()).forEach(([key, value]) => headers.set(key, value));
  new Headers(options?.headers).forEach((value, key) => headers.set(key, value));
  const realm = url.pathname.startsWith("/api/shop/") ? "shopper" : "staff";
  if (remote) {
    headers.delete("X-CSRF-Token");
    const token = remoteCsrf.get(realm);
    if (token) headers.set("X-CSRF-Token", token);
  }
  const target = remote ? apiOrigin + url.pathname + url.search : input;
  const request = remote && input instanceof Request ? new Request(target, input) : target;
  const response = await trackRequest(() => fetch(request, {
    ...options, credentials: remote ? "include" : "same-origin", headers,
  }));
  if (remote) {
    for (const kind of ["staff", "shopper"]) {
      const token = response.headers.get(`X-Tenali-${kind}-CSRF`);
      if (token) remoteCsrf.set(kind, token);
    }
  }
  return response;
}
declare const __TENALI_CUSTOM_DOMAINS__: boolean;
declare const __TENALI_PLATFORM_HOSTS__: string[];

const remoteCsrf = new Map<string, string>();

export function tenantApiOrigin(): string {
  if (typeof __TENALI_CUSTOM_DOMAINS__ === "undefined" || !__TENALI_CUSTOM_DOMAINS__) return "";
  const { hostname, protocol } = window.location;
  const platformHosts = typeof __TENALI_PLATFORM_HOSTS__ === "undefined" ? [] : __TENALI_PLATFORM_HOSTS__;
  if (protocol !== "https:" || ["localhost", "127.0.0.1"].includes(hostname) || platformHosts.includes(hostname)) return "";
  return `https://api.${hostname}`;
}
