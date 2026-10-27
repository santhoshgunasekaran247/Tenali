import type { SiteTheme } from "../types";

export const DEFAULT_SITE_THEME: SiteTheme = {
  primary_color: "#142b4a",
  accent_color: "#b88932",
  background_color: "#fbfaf7",
  surface_color: "#ffffff",
  text_color: "#142b4a",
  muted_text_color: "#59677a",
  border_color: "#ded9cf",
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

export function setSavedSiteTheme(theme?: Partial<SiteTheme> | null) {
  savedTheme = normalizeSiteTheme(theme);
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