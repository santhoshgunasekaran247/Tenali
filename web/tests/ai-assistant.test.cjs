const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

const src = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");

function loadClient(fetch) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(src("features/ai.ts"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, { exports, require: () => ({ tenantFetch: fetch }), URLSearchParams });
  return exports;
}

test("AI calls use tenant transport and preserve the exact client message reference", async () => {
  const calls = [];
  const { ai } = loadClient(async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ items: [] }) };
  });
  await ai.send("conversation", "twenty lamps", "stable-reference");
  assert.equal(calls[0].path, "/api/ai/conversations/conversation/messages");
  assert.deepEqual(JSON.parse(calls[0].options.body), { content: "twenty lamps", client_key: "stable-reference" });
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
});

test("quota failures are visible and never automatically retried", async () => {
  let attempts = 0;
  const { ai } = loadClient(async () => {
    attempts++;
    return { ok: false, json: async () => ({ detail: "Tenant AI usage limit reached" }) };
  });
  await assert.rejects(ai.send("conversation", "hello", "key"), /usage limit reached/);
  assert.equal(attempts, 1);
});

test("history searches are encoded, edits use versions, and unknown calls remain explicit", async () => {
  const calls = [];
  const { ai, messageStatus } = loadClient(async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ items: [] }) };
  });
  await ai.conversations("lamps & brass", true, 30);
  assert.match(calls[0].path, /search=lamps\+%26\+brass&archived=true&offset=30/);
  await ai.update({ id: "one", version: 4 }, { title: "Renamed" });
  assert.equal(JSON.parse(calls[1].options.body).expected_version, 4);
  assert.match(messageStatus({ role: "user", status: "unknown" }), /will not be automatically resent/);
  assert.equal(messageStatus({ role: "assistant", status: "completed" }), null);
});

test("assistant page is routed, renders text safely and explains scoped reads without business writes", () => {
  assert.match(src("App.tsx"), /path="\/portal\/ai"/);
  const page = src("pages/TenaliAIPage.tsx");
  assert.match(page, /Chat sends your messages/);
  assert.match(page, /permission-scoped business lookups/);
  assert.match(page, /No transaction drafts, document uploads or business execution/);
  assert.match(page, /<p>\{message\.content\}<\/p>/);
  assert.doesNotMatch(page, /dangerouslySetInnerHTML/);
  assert.match(page, /crypto\.randomUUID\(\)/);
  assert.match(page, /token !== generation\.current/);
  assert.match(page, /viewer/);
});

test("capability discovery uses tenant transport and platform approval uses versioned policies", async () => {
  const calls = [];
  const { ai } = loadClient(async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ items: [] }) };
  });
  await ai.capabilities();
  assert.equal(calls[0].path, "/api/ai/capabilities");
  const controls = src("components/PlatformAICapabilities.tsx");
  assert.match(controls, /approve_contract/);
  assert.match(controls, /expected_version/);
  assert.match(controls, /window\.confirm/);
  assert.match(controls, /No financial writes/);
});
