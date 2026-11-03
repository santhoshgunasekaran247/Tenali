import { tenantFetch } from "./tenantTransport";

export type PolicyScope = "platform" | "tenant";
export type PolicyKind = "privacy" | "terms" | "shipping" | "payment" | "returns" | "data-deletion" | "contact";
export const POLICY_TITLES: Record<PolicyKind, string> = {
  privacy: "Privacy Policy",
  terms: "Terms of Service",
  shipping: "Shipping and Delivery",
  payment: "Payment Policy",
  returns: "Cancellation, Refunds, Returns and Exchanges",
  "data-deletion": "Account and Data Deletion",
  contact: "Contact and Business Information",
};
export const PLATFORM_POLICY_KINDS: PolicyKind[] = ["privacy", "terms", "data-deletion", "contact"];
export const TENANT_POLICY_KINDS: PolicyKind[] = Object.keys(POLICY_TITLES) as PolicyKind[];
export type PolicyContent = {
  title: string; business_name: string; address: string; contact_email: string;
  jurisdiction: string; currency: "INR"; body: string;
};
export type PublicPolicy = {
  kind: PolicyKind; content: PolicyContent; published_at: string; published_revision: number;
};
export type PolicyDraft = {
  kind: PolicyKind; revision: number; content: PolicyContent; published: PolicyContent | null;
  published_at: string | null; published_revision: number | null; issues: string[];
};
export type PolicySummary = Pick<PublicPolicy, "kind" | "published_at" | "published_revision"> & { title: string };

export function policyPath(scope: PolicyScope, kind?: PolicyKind): string {
  return `/policies/${scope}${kind ? `/${kind}` : ""}`;
}

export function policyAdminPath(scope: PolicyScope): string {
  return scope === "platform" ? "/platform/policies" : "/company/policies";
}

export async function policyRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const platform = path.startsWith("/platform/");
  const cookie = platform ? "tenali_platform_csrf" : "tenali_csrf";
  const csrf = document.cookie.split("; ").find(entry => entry.startsWith(`${cookie}=`))?.slice(cookie.length + 1);
  const response = await tenantFetch(`/api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
      ...(platform ? { "X-Tenant-Slug": "" } : {}),
      ...options?.headers,
    },
  });
  const body = await response.json();
  if (!response.ok) {
    const message = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail)
      ? body.detail.map((entry: { msg?: string }) => entry.msg || "Invalid input").join(" ")
      : "Unable to load or update policies.";
    throw new Error(message);
  }
  return body as T;
}
