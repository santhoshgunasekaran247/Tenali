import type { Company,StorefrontContent } from "../../types";

export type StorefrontGroup = keyof StorefrontContent;

export function storefrontText(
  value: string | undefined,
  company: Pick<Company, "company_name" | "nickname">,
  variables: Record<string, string | number> = {},
): string {
  const replacements: Record<string, string | number> = {
    nickname: company.nickname?.trim() || company.company_name,
    company_name: company.company_name,
    brand_name: company.company_name,
    ...variables,
  };
  return (value || "").replace(/\{([a-z_]+)\}/gi, (token, key: string) => String(replacements[key] ?? token));
}

export function storefrontCopy<G extends StorefrontGroup>(
  company: Pick<Company, "storefront_content">,
  group: G,
  key: string,
): string {
  return company.storefront_content?.[group]?.[key] || "";
}
