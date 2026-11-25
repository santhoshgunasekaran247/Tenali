import type { SiteTheme, StorefrontTemplate } from "../types";

export const DEFAULT_SITE_THEME: SiteTheme = {
  primary_color: "#142b4a",
  accent_color: "#b88932",
  background_color: "#fbfaf7",
  surface_color: "#ffffff",
  text_color: "#142b4a",
  muted_text_color: "#59677a",
  border_color: "#ded9cf",
};

export const STOREFRONT_THEME_PALETTES: Record<StorefrontTemplate, SiteTheme> = {
  current: DEFAULT_SITE_THEME,
  marketplace: {
    primary_color: "#173c59", accent_color: "#ffd15a", background_color: "#ffffff",
    surface_color: "#ffffff", text_color: "#1d2730", muted_text_color: "#707780", border_color: "#e5ebef",
  },
  category_first: {
    primary_color: "#131921", accent_color: "#febd69", background_color: "#f3f4f6",
    surface_color: "#ffffff", text_color: "#0f1111", muted_text_color: "#565959", border_color: "#d5d9d9",
  },
  boutique: {
    primary_color: "#7d4545", accent_color: "#d7ad94", background_color: "#fffdfb",
    surface_color: "#ffffff", text_color: "#3a302e", muted_text_color: "#887b75", border_color: "#eee5e0",
  },
  heritage: {
    primary_color: "#783c29", accent_color: "#d8b36c", background_color: "#f7f0e2",
    surface_color: "#fffdf7", text_color: "#372b20", muted_text_color: "#82715d", border_color: "#eee5d3",
  },
  supermarket: {
    primary_color: "#17613f", accent_color: "#f0a849", background_color: "#ffffff",
    surface_color: "#ffffff", text_color: "#263a30", muted_text_color: "#75837a", border_color: "#e4eee2",
  },
  jewellery: {
    primary_color: "#34221d", accent_color: "#b28a52", background_color: "#f7f2eb",
    surface_color: "#ffffff", text_color: "#302723", muted_text_color: "#8a7e75", border_color: "#e8dfd3",
  },
};

export const SITE_THEME_FIELDS = [
  ["primary_color", "Primary", "--site-primary"],
  ["accent_color", "Accent", "--site-accent"],
  ["background_color", "Page Background", "--site-background"],
  ["surface_color", "Surface", "--site-surface"],
  ["text_color", "Text", "--site-text"],
  ["muted_text_color", "Muted Text", "--site-muted"],
  ["border_color", "Borders", "--site-border"],
] as const;

export function normalizeSiteTheme(theme?: Partial<SiteTheme> | null): SiteTheme {
  const result = { ...DEFAULT_SITE_THEME };
  for (const [key] of SITE_THEME_FIELDS) {
    if (/^#[0-9a-f]{6}$/i.test(theme?.[key] || "")) result[key] = theme![key]!;
  }
  return result;
}

export function storefrontSiteTheme(theme?: Partial<SiteTheme> | null, template: StorefrontTemplate = "current"): SiteTheme {
  const normalized = normalizeSiteTheme(theme);
  const isPreset = Object.values(STOREFRONT_THEME_PALETTES).some(palette =>
    SITE_THEME_FIELDS.every(([key]) => normalized[key].toLowerCase() === palette[key].toLowerCase()));
  return isPreset ? { ...STOREFRONT_THEME_PALETTES[template] } : normalized;
}

export function contrastingText(color: string): string {
  const channels = [1, 3, 5].map((offset) => {
    const channel = parseInt(color.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  const luminance = channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  return 1.05 / (luminance + 0.05) >= (luminance + 0.05) / 0.05 ? "#ffffff" : "#000000";
}

let savedTheme = DEFAULT_SITE_THEME;
let previewTheme: SiteTheme | null = null;

function paintTheme(theme: SiteTheme) {
  for (const [key, , variable] of SITE_THEME_FIELDS) document.documentElement.style.setProperty(variable, theme[key]);
  document.documentElement.style.setProperty("--site-on-primary", contrastingText(theme.primary_color));
  document.documentElement.style.setProperty("--site-on-accent", contrastingText(theme.accent_color));
  document.documentElement.style.colorScheme = contrastingText(theme.surface_color) === "#ffffff" ? "dark" : "light";
}

export function setSavedSiteTheme(theme?: Partial<SiteTheme> | null, template?: StorefrontTemplate) {
  savedTheme = template ? storefrontSiteTheme(theme, template) : normalizeSiteTheme(theme);
  paintTheme(previewTheme || savedTheme);
}

export function previewSiteTheme(theme: SiteTheme) {
  previewTheme = normalizeSiteTheme(theme);
  paintTheme(previewTheme);
}

export function endSiteThemePreview() {
  previewTheme = null;
  paintTheme(savedTheme);
}