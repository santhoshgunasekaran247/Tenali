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

export function tenantFetch(input: RequestInfo|URL,options?:RequestInit) {
  return fetch(input,{...options,credentials:'same-origin',headers:{...tenantHeaders(),...options?.headers}});
}