const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

const src = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");

function loadClient(fetch, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(src("features/ai.ts"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, { exports, require: () => ({ tenantFetch: fetch }), URLSearchParams, ...globals });
  return exports;
}

test("private report download uses tenant execution identity and releases the local URL", async () => {
  const calls = [], cleanup = [];
  const link = { click: () => cleanup.push("click"), remove: () => cleanup.push("remove") };
  const callbacks = [];
  const { ai } = loadClient(async path => {
    calls.push(path);
    return { ok: true, blob: async () => ({ private: true }) };
  }, {
    URL: { createObjectURL: blob => { assert.equal(blob.private, true); return "blob:private"; },
      revokeObjectURL: url => cleanup.push(url) },
    document: { createElement: tag => { assert.equal(tag, "a"); return link; }, body: { appendChild: node => assert.equal(node, link) } },
    window: { setTimeout: callback => callbacks.push(callback) },
  });
  await ai.downloadReport("saved-execution");
  assert.deepEqual(calls, ["/api/ai/executions/saved-execution/report"]);
  assert.equal(link.href, "blob:private");
  assert.equal(link.download, "tenali-report.csv");
  assert.deepEqual(cleanup, ["click", "remove"]);
  callbacks[0]();
  assert.deepEqual(cleanup, ["click", "remove", "blob:private"]);
  const denied = loadClient(async () => ({ ok: false, json: async () => ({ detail: "Private report expired" }) }));
  await assert.rejects(denied.ai.downloadReport("expired"), /expired/);
  assert.match(src("components/AIDrafts.tsx"), /draft\.high_impact/);
  assert.match(src("components/AIDrafts.tsx"), /Generate private report/);
  assert.match(src("components/AIDrafts.tsx"), /No business records will change/);
  assert.match(src("components/AIDrafts.tsx"), /Private report generated/);
  assert.match(src("components/PlatformAIActions.tsx"), /All modules/);
  assert.match(src("components/PlatformAICapabilities.tsx"), /All modules/);
});

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

test("draft summaries distinguish items and flag exact duplicates", () => {
  const { draftDescription, hasDuplicateDraft } = loadClient(async () => ({}));
  const first = { id: "one", action_key: "purchase_create", target_id: null, payload_hash: "same",
    payload: { lines: [{ description: "Copper Tumbler", quantity: 10 }] } };
  const second = { ...first, id: "two" };
  assert.equal(draftDescription(first), "Copper Tumbler · Qty 10");
  assert.equal(draftDescription({ ...first, action_key: "party_create", payload: { legal_name: "Tiger Copper" } }), "Tiger Copper");
  assert.equal(draftDescription({ ...first, payload: {} }), "Item not specified");
  assert.equal(hasDuplicateDraft(first, [first, second]), true);
  assert.equal(hasDuplicateDraft(first, [first, { ...second, payload_hash: "different" }]), true);
  assert.equal(hasDuplicateDraft(first, [first, { ...second, payload_hash: "different", payload: { lines: [{ description: "Copper Tumbler", quantity: 20 }] } }]), false);
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

test("unnamed conversations display their date without changing custom titles", () => {
  const { conversationLabel } = loadClient(async () => ({}));
  assert.match(conversationLabel({ title: "New conversation", created_at: "2026-11-08T10:00:00Z" }), /^New conversation · /);
  assert.equal(conversationLabel({ title: "Copper purchase", created_at: "2026-11-08T10:00:00Z" }), "Copper purchase");
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
  assert.match(page, /<section className="ai-operations" aria-label="Operations to review">/);
  assert.match(page, /className="ai-conversation-layout"/);
  assert.match(page, /className="ai-compose-actions"/);
  assert.match(page, /event\.key === "Enter" && !event\.shiftKey/);
  assert.match(page, /aria-label=\{submission \? "Retry message" : "Send message"\}/);
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
  assert.match(cards, /Show essential fields/);
  assert.match(cards, /Show all fields/);
  assert.match(cards, /"store_id", "purchase_date", "received_now", "lines"/);
  assert.match(cards, /draft\.status === "approved" \|\| draft\.status === "executed"/);
  assert.doesNotMatch(cards, /ai-draft-filters/);
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
  assert.match(page, /currentTitle\.current\.trim\(\) === selected\.title/);
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
