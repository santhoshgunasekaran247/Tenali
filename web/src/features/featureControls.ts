import type { FeatureStatus } from "../types";

export function platformLocked(status: FeatureStatus): boolean {
  return !status.platform_allowed || status.reason === "platform_ai_disabled";
}

export function featureExplanation(status: FeatureStatus): string {
  if (platformLocked(status)) return "Disabled by Tenali Platform. Contact the platform administrator.";
  if (status.reason === "ai_not_available") return "AI processing is not available yet. Your preference is saved for the assistant rollout.";
  if (status.reason === "provider_not_configured") return "The AI provider is not configured. Contact the platform administrator.";
  if (status.reason === "model_not_configured") return "An approved model and its pricing must be configured by the platform administrator.";
  if (status.reason === "workspace_disabled") return "This workspace is disabled.";
  return status.effective_enabled ? "Enabled." : "Disabled in company settings.";
}

export type AILimits = { daily_request_limit: number; monthly_token_limit: number; monthly_cost_limit: number };
export type AIOverrides = { [K in keyof AILimits]: number | null };
export type PlatformAIConfig = AILimits & {
  global_enabled: boolean;
  routine_model: string;
  document_model: string;
  max_output_tokens: number;
  timeout_seconds: number;
  retention_days: number;
  support_url: string;
  version: number;
  provider_configured: boolean;
  runtime_ready: boolean;
  model_ready: boolean;
  input_cost_per_million: number | string;
  output_cost_per_million: number | string;
};
export type TenantLimits = { overrides: AIOverrides; effective: AILimits; version: number };
export type PlatformWorkspace = { id: string; company_name: string; tenant_slug: string; is_active: boolean };

export const AI_LIMIT_FIELDS: [keyof AILimits, string, number][] = [
  ["daily_request_limit", "Requests per day", 10000],
  ["monthly_token_limit", "Tokens per month", 1000000000],
  ["monthly_cost_limit", "Estimated monthly cost limit (USD)", 10000],
];
