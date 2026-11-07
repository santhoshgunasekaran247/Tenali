import { tenantFetch } from "./tenantTransport";
import type { CompanyFeatures } from "../types";

export type Conversation = {
  id: string; title: string; status: "active" | "archived"; version: number;
  created_at: string; updated_at: string; expires_at: string;
};
export type ChatMessage = {
  id: string; client_key: string; role: "user" | "assistant"; content: string;
  status: "pending" | "completed" | "failed" | "unknown"; error_code: string | null; created_at: string;
};
export type Preference = { preference: "language" | "instructions"; value: string };
export type UsageTotals = { requests: number; tokens: number | string; cost: number | string; unconfirmed?: number };
export type AIUsage = { personal: UsageTotals; tenant: UsageTotals | null; period: string; currency: string; note: string };
export type ReadCapability = { key: string; description: string; version: number; tenant_version: number };

export async function aiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await tenantFetch("/api/ai" + path, {
    ...options, headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const body: unknown = await response.json();
  if (!response.ok) {
    let message = "Unable to complete the AI request.";
    if (body && typeof body === "object" && "detail" in body) {
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((entry: unknown) =>
        entry && typeof entry === "object" && "msg" in entry ? String(entry.msg) : "Invalid input").join("; ");
    }
    throw new Error(message);
  }
  return body as T;
}

export const ai = {
  settings: () => aiRequest<CompanyFeatures>("/settings"),
  capabilities: () => aiRequest<{ items: ReadCapability[] }>("/capabilities"),
  conversations: (search: string, archived: boolean, offset: number) =>
    aiRequest<{ items: Conversation[] }>(`/conversations?${new URLSearchParams({ search, archived: String(archived), offset: String(offset) })}`),
  create: () => aiRequest<Conversation>("/conversations", { method: "POST", body: JSON.stringify({ title: "New conversation" }) }),
  conversation: (id: string) => aiRequest<Conversation>(`/conversations/${id}`),
  update: (conversation: Conversation, changes: { title?: string; status?: "active" | "archived" }) =>
    aiRequest<Conversation>(`/conversations/${conversation.id}`, { method: "PATCH", body: JSON.stringify({ ...changes, expected_version: conversation.version }) }),
  remove: (conversation: Conversation) => aiRequest(`/conversations/${conversation.id}?expected_version=${conversation.version}`, { method: "DELETE" }),
  messages: (id: string, offset = 0) => aiRequest<{ items: ChatMessage[] }>(`/conversations/${id}/messages?offset=${offset}`),
  send: (id: string, content: string, client_key: string) =>
    aiRequest<{ items: ChatMessage[] }>(`/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ content, client_key }) }),
  preferences: () => aiRequest<{ items: Preference[] }>("/context"),
  preference: (key: Preference["preference"], value: string) =>
    aiRequest<{ items: Preference[] }>(`/context/preferences/${key}`, { method: "PUT", body: JSON.stringify({ value }) }),
  deletePreference: (key: Preference["preference"]) =>
    aiRequest<{ items: Preference[] }>(`/context/preferences/${key}`, { method: "DELETE" }),
  usage: () => aiRequest<AIUsage>("/usage"),
};

export function messageStatus(message: ChatMessage): string | null {
  if (message.role !== "user") return null;
  if (message.status === "pending") return "Reply processing. Refresh to recover the saved outcome.";
  if (message.status === "unknown") return "Provider outcome is unknown. The usage reservation remains counted; this request will not be automatically resent.";
  if (message.status === "failed") return `No usable reply (${message.error_code || "provider error"}). No business records changed.`;
  return null;
}
