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

test("assistant page renders text safely and requires explicit operation submission", () => {
  assert.match(src("App.tsx"), /path="\/portal\/ai"/);
  const page = src("pages/TenaliAIPage.tsx");
  assert.match(page, /Chat sends your messages/);
  assert.match(page, /permission-scoped business lookups/);
  assert.match(page, /Operations need separate review, approval and submission/);
  assert.match(page, /<p>\{message\.content\}<\/p>/);
  assert.doesNotMatch(page, /dangerouslySetInnerHTML/);
  assert.match(page, /crypto\.randomUUID\(\)/);
  assert.match(page, /token !== generation\.current/);
  assert.match(page, /viewer/);
});

test("draft editing, approval and submission bind exact version/hash", async () => {
  const calls = [];
  const { ai } = loadClient(async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ items: [] }) };
  });
  const draft = { id: "draft", version: 7, payload_hash: "approved-hash" };
  await ai.editDraft(draft, { amount: "25.50" });
  assert.deepEqual(JSON.parse(calls[0].options.body), { payload: { amount: "25.50" }, expected_version: 7 });
  await ai.validateDraft(draft);
  assert.equal(calls[1].path, "/api/ai/drafts/draft/validate?expected_version=7");
  await ai.approveDraft(draft);
  assert.deepEqual(JSON.parse(calls[2].options.body), { expected_version: 7, expected_hash: "approved-hash" });
  await ai.executeDraft(draft, "Exact label");
  assert.equal(calls[3].path, "/api/ai/drafts/draft/execute");
  assert.deepEqual(JSON.parse(calls[3].options.body), { expected_version: 7, expected_hash: "approved-hash", confirm_text: "Exact label" });
  const cards = src("components/AIDrafts.tsx");
  assert.match(cards, /window\.confirm/);
  assert.match(cards, /draft\.status !== "validated"/);
  assert.match(cards, /readonly \|\| dirty/);
  assert.match(cards, /does NOT post, pay, or change stock/);
  assert.match(cards, /Save edits & invalidate approval/);
  assert.doesNotMatch(cards, /dangerouslySetInnerHTML/);
});

test("platform posting controls are separate from draft preparation and reads", () => {
  const controls = src("components/PlatformAIActions.tsx");
  assert.match(controls, /\/ai\/actions/);
  assert.match(controls, /approve_contract/);
  assert.match(controls, /expected_version/);
  assert.match(controls, /enabling drafts alone never changes business records/);
  assert.match(controls, /execution_enabled: posting/);
  assert.match(controls, /Administrative settings and reset-all are excluded/);
});

test("private files are only processed on an explicitly sent stable message", async () => {
  const calls = [];
  const { ai } = loadClient(async (path, options) => {
    calls.push({ path, options }); return { ok: true, json: async () => ({ items: [] }) };
  });
  await ai.upload("chat", "bill.txt", "text/plain", "ZmlsZQ==");
  await ai.send("chat", "Read this", "stable-reference", ["file-id"]);
  assert.equal(calls[0].path, "/api/ai/conversations/chat/attachments");
  assert.deepEqual(JSON.parse(calls[1].options.body), { content: "Read this", client_key: "stable-reference", attachment_ids: ["file-id"] });
  assert.match(src("pages/TenaliAIPage.tsx"), /uploading does not make a paid call/);
});

test("assistant titles auto-save with version checks and visible failure recovery", () => {
  const page = src("pages/TenaliAIPage.tsx");
  assert.match(page, /window\.setTimeout\(\(\) => void saveTitle\(\), 600\)/);
  assert.match(page, /currentConversation\.current\?\.id === conversation\.id/);
  assert.match(page, /Title not saved/);
  assert.match(page, /Retry title save/);
  assert.doesNotMatch(page, />Rename<\/button>|<strong>\{message\.role/);
  assert.match(page, /aria-label=\{message\.role/);
  assert.match(src("styles.css"), /font-size: 16px/);
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
  assert.match(controls, /unrestricted store access/);
  assert.match(src("pages/TenaliAIPage.tsx"), /not complete catalogues or company financial totals/);
});
