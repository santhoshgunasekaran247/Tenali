const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

const src = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");

function loadUI(file) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(src(file) + (file.endsWith("AIDrafts.tsx") ? "\nexport { Fields, actionLabel, waitingForPrerequisites };" : ""), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, require: name =>
    name === "../features/ai" ? {} :
    name === "./WorkflowReference" ? loadUI("components/WorkflowReference.tsx") :
    name === "./Notifications" ? {} : require(name) });
  return exports;
}

test("forms mark filled and missing required fields without redundant selected captions", () => {
  const React = require("react"), { renderToStaticMarkup } = require("react-dom/server");
  const { Fields } = loadUI("components/AIDrafts.tsx");
  const { WorkflowReference } = loadUI("components/WorkflowReference.tsx");
  const schema = { type: "object", required: ["name"], properties: {
    name: { type: "string" }, optional: { type: "string" }, account_id: { type: "string", "x-workflow-reference": true },
    missing: { type: "string" }, lines: { type: "array", items: { type: "object", properties: {
      gst_rate: { type: "number" }, price_includes_gst: { type: "boolean" } } } },
  } };
  const html = renderToStaticMarkup(React.createElement(Fields, {
    schema, root: schema, values: { name: "Vendor", optional: "Note", account_id: "id",
      lines: [{ gst_rate: 0, price_includes_gst: false }] }, showAll: false, disabled: false,
    requiredFields: ["account_id", "missing", "lines.0.gst_rate", "lines.0.price_includes_gst"],
    labels: { account_id: { value: "id", label: "Main bank" } }, onChange() {},
    renderReference: (path, title, value, label, required) => React.createElement(WorkflowReference, {
      workflow: { id: "workflow", version: 1 }, step: { id: "step" }, field: path, title, value, label, required,
      disabled: false, onChange() {}, onChoose() {}, onCreate() {},
    }),
  }));
  assert.equal((html.match(/aria-required="true"/g) || []).length, 5);
  assert.match(html, /aria-required="false"[^>]*value="Note"/);
  assert.match(html, /role="combobox"[^>]*aria-required="true"[^>]*value="Main bank"/);
  assert.match(html, /<option value="false" selected="">No<\/option>/);
  assert.doesNotMatch(html, /Selected:|value="id"/);
  assert.doesNotMatch(src("components/AIDrafts.tsx"), /Selected:/);
});

test("sales retain their label and completed customer prerequisites no longer show waiting", () => {
  const { actionLabel, waitingForPrerequisites } = loadUI("components/AIDrafts.tsx");
  assert.equal(actionLabel("invoice_create"), "Sales billing");
  assert.equal(actionLabel("party_create", { party_type: "customer" }), "Customer");
  assert.equal(actionLabel("party_create", { party_type: "vendor" }), "Vendor");
  const parent = { bindings: { customer_party_id: { step_id: "customer" } } };
  assert.equal(waitingForPrerequisites(parent, [{ id: "customer", draft_status: "editing" }]), true);
  assert.equal(waitingForPrerequisites(parent, [{ id: "customer", draft_status: "executed" }]), false);
  assert.equal(waitingForPrerequisites(parent, []), true);
  assert.doesNotMatch(src("components/AIDrafts.tsx"), /Purchase rate per unit/);
});

function loadClient(fetch, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(src("features/ai.ts"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, { exports, require: () => ({ tenantFetch: fetch }), URLSearchParams, SyntaxError, ...globals });
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

test("workflow selection and creation use versioned private endpoints", async () => {
  const calls = [];
  const { ai } = loadClient(async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ items: [] }) };
  });
  const workflow = { id: "workflow", version: 3 }, step = { id: "step" };
  await ai.workflows("conversation");
  await ai.editWorkflow(workflow, step, null, { vendor_id: "selected" });
  await ai.editWorkflow(workflow, step, null, { vendor_id: "Tiger" }, "vendor_id");
  await ai.continueWorkflow(workflow);
  await ai.startWorkflow("conversation", "purchase_receive", "saved-purchase", {}, "stable-key");
  assert.equal(calls[0].path, "/api/ai/conversations/conversation/workflows?offset=0");
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    expected_version: 3, step_id: "step", target: null, payload: { vendor_id: "selected" },
  });
  assert.equal(JSON.parse(calls[2].options.body).create_field, "vendor_id");
  assert.equal(calls[3].path, "/api/ai/workflows/workflow/continue?expected_version=3");
  assert.equal(JSON.parse(calls[4].options.body).client_key, "stable-key");
});

test("workflow dropdown searches are read-only, encoded and cancellable", async () => {
  const calls = [], signal = {};
  const { ai } = loadClient(async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ options: [] }) };
  });
  const workflow = { id: "workflow", version: 3 }, step = { id: "step" };
  await ai.searchWorkflow(workflow, step, "lines.0.product_id", "brass & bottle", signal);
  assert.equal(calls[0].path, "/api/ai/workflows/workflow/search?step_id=step&field=lines.0.product_id&query=brass+%26+bottle");
  assert.equal(calls[0].options.signal, signal);
  assert.equal(calls[0].options.body, undefined);
  await ai.editWorkflow(workflow, step, null, { store_id: "selected" }, undefined, undefined,
    { field: "store_id", query: "main" });
  const payload = JSON.parse(calls[1].options.body);
  assert.equal(payload.selection_field, "store_id");
  assert.equal(payload.selection_query, "main");
  const source = src("components/WorkflowReference.tsx");
  assert.match(source, /role="combobox"/);
  assert.match(source, /role="listbox"/);
  assert.match(source, /controller\.abort\(\)/);
  assert.match(source, /if \(current\)/);
  assert.match(source, /ArrowDown/);
  assert.match(source, /Create new/);
});

test("workflows are text-triggered and record selection advances without an operation menu", () => {
  const source = src("components/AIDrafts.tsx");
  assert.doesNotMatch(source, /Start an Operations workflow|Choose an operation|setNewAction/);
  assert.match(source, /Create new \{String\(choice\.query\)\}/);
  assert.match(source, /const choose =[\s\S]*?void onRun\(\(\) => ai\.editWorkflow/);
  assert.match(source, /await ai\.continueWorkflow\(workflow\)/);
  assert.match(source, /action\.workflow_schema \|\| action\.schema/);
  assert.match(source, /Object\.values\(step\.offer_steps \|\| \{\}\)/);
  assert.match(source, /Completed\. Would you like to make the next entry/);
  assert.match(source, /Already submitted records are not undone/);
});

test("draft summaries distinguish items and flag exact duplicates", () => {
  const { draftDescription, hasDuplicateDraft } = loadClient(async () => ({}));
  const first = { id: "one", action_key: "purchase_create", target_id: null, payload_hash: "same",
    payload: { lines: [{ description: "Copper Tumbler", quantity: 10 }] } };
  const second = { ...first, id: "two" };
  assert.equal(draftDescription(first), "Copper Tumbler · Qty 10");
  assert.equal(draftDescription({ ...first, action_key: "purchase_bundle_create",
    payload: { vendor_name: "Tiger Glass", product_name: "Glass Tumbler", quantity: 100 } }),
    "Tiger Glass · Glass Tumbler x 100");
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

test("non-JSON submission errors explain recovery without retrying the write", async () => {
  let attempts = 0;
  const { ai } = loadClient(async () => {
    attempts++;
    return { ok: false, status: 500, json: async () => { throw new SyntaxError("Unexpected token I"); } };
  });
  await assert.rejects(ai.executeDraft({ id: "vendor", version: 3, payload_hash: "approved" }),
    /server error.*Check saved outcome/i);
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
  assert.match(messageStatus({ role: "user", status: "failed", error_code: "lookup_capability_changed" }), /lookup permission changed or is unavailable/);
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
  assert.match(page, /Confirm &amp; save records your approval and submits the reviewed values/);
  assert.match(page, /<p>\{message\.role === "assistant" \? readableMessage\(message\.content\) : message\.content\}<\/p>/);
  assert.doesNotMatch(page, /dangerouslySetInnerHTML/);
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
  assert.match(cards, /draft\.status === "validated" \|\| draft\.status === "approved"/);
  assert.match(cards, /readonly \|\| dirty/);
  assert.match(cards, /Confirm and save these reviewed values/);
  assert.match(cards, /Save changes for review/);
  assert.match(cards, /Review & check/);
  assert.match(cards, /Confirm & save/);
  assert.doesNotMatch(cards, /Review calculated impact|Approve reviewed values/);
  assert.match(cards, /Show essential fields/);
  assert.match(cards, /Show all fields/);
  assert.match(cards, /"store_id", "purchase_date", "received_now", "lines"/);
  assert.match(cards, /"fully_paid", "received_now"/);
  assert.match(cards, /hiddenFields=\{draft\.action_key === "purchase_bundle_create"/);
  assert.match(cards, /draft\.status === "approved" \|\| draft\.status === "executed"/);
  assert.doesNotMatch(cards, /ai-draft-filters/);
  assert.doesNotMatch(cards, /dangerouslySetInnerHTML/);
});

test("confirm and save approves the exact reviewed version before posting once", async () => {
  const calls = [];
  const draft = { id: "draft", version: 7, payload_hash: "reviewed-hash", status: "validated" };
  const { ai } = loadClient(async (path, options) => {
    calls.push({ path, payload: JSON.parse(options.body) });
    return { ok: true, json: async () => path.endsWith("/approve") ? { ...draft, status: "approved" } : { status: "succeeded" } };
  });
  const result = await ai.submitReviewedDraft(draft, "Exact confirmation");
  assert.equal(result.status, "succeeded");
  assert.deepEqual(calls.map(call => call.path), ["/api/ai/drafts/draft/approve", "/api/ai/drafts/draft/execute"]);
  assert.deepEqual(calls[0].payload, { expected_version: 7, expected_hash: "reviewed-hash" });
  assert.deepEqual(calls[1].payload, { expected_version: 7, expected_hash: "reviewed-hash", confirm_text: "Exact confirmation" });
  calls.length = 0;
  await ai.submitReviewedDraft({ ...draft, status: "approved" });
  assert.deepEqual(calls.map(call => call.path), ["/api/ai/drafts/draft/execute"]);
  calls.length = 0;
  await assert.rejects(ai.submitReviewedDraft({ ...draft, status: "editing" }), /Review the current values/);
  assert.equal(calls.length, 0);
});

test("confirm and save never posts after rejected or changed approval", async () => {
  const draft = { id: "draft", version: 7, payload_hash: "reviewed", status: "validated" };
  for (const body of [{ ...draft, status: "approved", id: "other-draft" }, { ...draft, status: "approved", version: 8 },
      { ...draft, status: "approved", payload_hash: "changed" }, { ...draft, status: "editing" }]) {
    const calls = [];
    const { ai } = loadClient(async path => {
      calls.push(path);
      return { ok: true, json: async () => body };
    });
    await assert.rejects(ai.submitReviewedDraft(draft), /Reviewed values changed/);
    assert.deepEqual(calls, ["/api/ai/drafts/draft/approve"]);
  }
  const calls = [];
  const { ai } = loadClient(async path => {
    calls.push(path);
    return { ok: false, json: async () => ({ detail: "References changed" }) };
  });
  await assert.rejects(ai.submitReviewedDraft(draft), /References changed/);
  assert.deepEqual(calls, ["/api/ai/drafts/draft/approve"]);
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

test("older JSON lookup replies are shown as plain, readable records", () => {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(src("features/aiMessages.ts"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, { exports });
  const { readableMessage, rupees } = exports;
  const stored = 'I can look up your account balances. If you want, I can also narrow it.\n\nVerified Tenali lookup (read only):\n' +
    '{"capability": "accounts", "items": [{"account_id": "50ac5aa6", "account_name": "Main Account", "account_type": "bank", ' +
    '"is_company_account": false, "opening_balance": "1000.00", "current_balance": "4000.00", "transaction_count": 5, ' +
    '"last_transaction_date": "2026-11-14"}], "more_matches": false, "note": "Balances as of 2026-11-14"}\n\nNo draft was saved in this reply.';
  assert.equal(readableMessage(stored), "From your Tenali records — Accounts (1)\n• Main Account: current balance ₹4,000.00 · " +
    "account type bank · opening balance ₹1,000.00 · transaction count 5 · last transaction date 14 Nov 2026");
  assert.equal(readableMessage("Verified Tenali lookup (read only): Products matching “x”\n• X"),
    "From your Tenali records — Products matching “x”\n• X");
  assert.match(readableMessage('Checking.\n\nVerified Tenali lookup (read only):\n{"capability": "accounts", "items": [{"acc'),
    /could not be shown/);
  assert.equal(readableMessage("Hello there."), "Hello there.");
  assert.equal(rupees(1234567.5), "₹12,34,567.50");
});
