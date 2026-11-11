const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

const src = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");
const exportsObject = {};
vm.runInNewContext(ts.transpileModule(src("features/featureControls.ts"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { exports: exportsObject });
const { platformLocked, featureExplanation } = exportsObject;

test("platform denial always locks tenant controls; global AI off also locks", () => {
  for (const tenant_enabled of [false, true]) {
    assert.equal(platformLocked({ platform_allowed: false, tenant_enabled, reason: "platform_disabled" }), true);
  }
  assert.equal(platformLocked({ platform_allowed: true, reason: "platform_ai_disabled" }), true);
  assert.equal(platformLocked({ platform_allowed: true, reason: "tenant_disabled" }), false);
  assert.match(featureExplanation({ platform_allowed: false }), /Contact the platform administrator/);
});

test("AI rollout is not advertised as running", () => {
  assert.match(featureExplanation({ platform_allowed: true, reason: "ai_not_available" }), /not available yet/);
});

test("platform AI route, separate client controls and disabled tenant switches are wired", () => {
  assert.match(src("App.tsx"), /path="\/platform\/ai"/);
  assert.match(src("pages/PlatformAdminPage.tsx"), /<PlatformAISettings/);
  assert.match(src("pages/PlatformAdminPage.tsx"), /<PlatformWorkspaceFeatures/);
  const company = src("pages/CompanySetupPage.tsx");
  assert.match(company, /storefront_enabled: company\.features\?\.storefront\.platform_allowed \? company\.storefront_enabled !== false : undefined/);
  assert.match(company, /disabled=\{!company\.features\?\.storefront\.platform_allowed\}/);
  assert.match(company, /Contact platform/);
  assert.match(company, /<TenantAISettings/);
  assert.match(src("components/TenantAISettings.tsx"), /expected_version: features\.ai_settings_version/);
  assert.match(src("components/PlatformWorkspaceFeatures.tsx"), /expected_version: status\.version/);
});

test("platform AI separates navigation, preserves mounted edits and collapses detailed controls", () => {
  const settings = src("components/PlatformAISettings.tsx");
  for (const section of ["settings", "tools", "workspaces", "usage"]) {
    assert.match(settings, new RegExp(`id="platform-ai-${section}" hidden=\\{section !== "${section}"\\}`));
  }
  assert.match(settings, /aria-label="AI administration"/);
  assert.match(settings, /Documents & images/);
  assert.match(settings, /Advanced settings/);
  assert.match(settings, /disclosure\.open = true/);
  assert.match(settings, /expected_version: version/);
  assert.match(settings, /expected_version: limits\.version/);
  const reads = src("components/PlatformAICapabilities.tsx");
  assert.match(reads, /<details key=\{item\.key\} className="platform-ai-tool"/);
  assert.doesNotMatch(reads, /<PlatformAIActions/);
  const actions = src("components/PlatformAIActions.tsx");
  assert.match(actions, /Boolean\(item\.high_impact\) === highImpact/);
  assert.match(actions, />High impact<\/button>/);
  assert.match(src("styles.css"), /\.platform-ai-settings \[hidden\] \{ display: none !important; \}/);
});
