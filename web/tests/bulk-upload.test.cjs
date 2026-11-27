const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function load(file, overrides) {
  const exports = {};
  const code = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, {
    exports, URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} },
    document: { createElement: () => ({ click() {} }) }, setTimeout: fn => fn(),
    crypto: { randomUUID: () => "upload-reference" }, window: { confirm: () => true },
    require: name => overrides[name] || require(name),
  });
  return exports;
}

function hooks() {
  const states = [], effects = [];
  let index = 0, pending = [];
  return {
    react: {
      ...React,
      useState(initial) {
        const i = index++;
        if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
        return [states[i], value => { states[i] = typeof value === "function" ? value(states[i]) : value; }];
      },
      useRef(initial) {
        const i = index++;
        return states[i] || (states[i] = { current: initial });
      },
      useEffect(effect, deps) {
        const i = index++;
        if (!effects[i] || deps.some((value, j) => value !== effects[i].deps[j])) pending.push(() => {
          effects[i]?.cleanup?.();
          effects[i] = { deps, cleanup: effect() };
        });
      },
    },
    render(fn) { index = 0; const result = fn(); const queued = pending; pending = []; queued.forEach(fn => fn()); return result; },
  };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
function find(node, predicate) {
  if (!node || typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
}
const text = node => typeof node === "string" || typeof node === "number" ? String(node)
  : React.Children.toArray(node?.props?.children).map(text).join("");
const button = (tree, label) => find(tree, node => node.type === "button" && text(node).trim() === label);
const Link = ({ to, children }) => React.createElement("a", { href: to }, children);

test("dedicated bulk page retains inventory selection and denies non-admin users", () => {
  let role = "owner";
  const selections = [];
  const { BulkUploadPage } = load("pages/BulkUploadPage.tsx", {
    "react-router-dom": { Link, useLocation: () => ({ state: { selectedProducts: ["product-a", null, 2] } }) },
    "../features/auth": { useAuth: () => ({ user: { role } }) },
    "../components/BulkWorkbookPanel": { BulkWorkbookPanel: props => { selections.push(props.selectedProducts); return null; } },
  });
  const html = renderToStaticMarkup(React.createElement(BulkUploadPage));
  assert.match(html, /Back to inventory/);
  assert.deepEqual(Array.from(selections[0]), ["product-a"]);
  role = "staff";
  assert.match(renderToStaticMarkup(React.createElement(BulkUploadPage)), /Only workspace owners and administrators/);
  assert.equal(selections.length, 1);
});

test("changing record type clears the chosen file and keeps selected export scoped", async () => {
  const h = hooks(), exports = [];
  const { BulkWorkbookPanel } = load("components/BulkWorkbookPanel.tsx", {
    react: h.react, "react-router-dom": { Link },
    "../api": { api: {
      bulkJobs: async () => ({ items: [] }),
      bulkExport: async (...args) => { exports.push(args); return { blob: {} }; },
    } },
  });
  const render = () => h.render(() => BulkWorkbookPanel({ selectedProducts: ["product-a"] }));
  let tree = render();
  await settle();
  find(tree, node => node.type === "input" && node.props.type === "file").props.onChange({ target: { files: [{ name: "products.xlsx", size: 20 }] } });
  tree = render();
  assert.equal(button(tree, "Upload & process").props.disabled, false);
  button(tree, "Download selected (1)").props.onClick();
  await settle();
  assert.deepEqual(exports.map(([kind, ids]) => [kind, Array.from(ids)]), [["products", ["product-a"]]]);
  tree = render();
  find(tree, node => node.type === "button" && node.props["aria-pressed"] !== undefined && text(node).startsWith("Images")).props.onClick();
  tree = render();
  assert.equal(button(tree, "Upload & process").props.disabled, true);
  assert.equal(find(tree, node => node.type === "input" && node.props.type === "file").props.accept, ".xlsx,.zip");
  assert.equal(button(tree, "Download selected (1)"), undefined);
});

test("upload advances saved jobs to completion and exposes results, not a second upload", async () => {
  const h = hooks(), calls = [];
  const job = { id: "job-a", kind: "products", total: 4, processed: 0, success: 0, failures: 0, completed: false,
    created_at: "2026-11-26", expires_at: "2026-12-03" };
  const { BulkWorkbookPanel } = load("components/BulkWorkbookPanel.tsx", {
    react: h.react, "react-router-dom": { Link },
    "../api": { api: {
      bulkJobs: async () => ({ items: [] }),
      bulkStart: async (kind, file, key) => { calls.push(["start", kind, file.name, key]); return job; },
      bulkAdvance: async id => { calls.push(["advance", id]); const processed = calls.filter(call => call[0] === "advance").length === 1 ? 3 : 4; return { ...job, processed, success: processed - 1, failures: 1, completed: processed === 4 }; },
    } },
  });

  const render = () => h.render(() => BulkWorkbookPanel({ selectedProducts: [] }));
  let tree = render();
  await settle();
  find(tree, node => node.type === "input" && node.props.type === "file").props.onChange({ target: { files: [{ name: "products.xlsx", size: 20 }] } });
  tree = render();
  button(tree, "Upload & process").props.onClick();
  await settle();
  tree = render();
  assert.deepEqual(calls, [["start", "products", "products.xlsx", "upload-reference"], ["advance", "job-a"], ["advance", "job-a"]]);
  assert.match(text(find(tree, node => node.props.role === "status")), /Import complete: 4 rows processed/);
  assert.match(text(find(tree, node => node.props.role === "status")), /3 succeeded; 1 failed/);
  assert.match(text(tree), /3 succeeded.*1 failed.*0 remaining/);
  assert.ok(button(tree, "Download results"));
  assert.equal(button(tree, "Upload & process").props.disabled, true);
  assert.equal(button(tree, "Resume"), undefined);
});

test("older completed import responses recover real counts from result headers", async () => {
  const calls = [];
  const job = { id: "legacy", kind: "products", total: 2, processed: 2, completed: true };
  const { api } = load("api.ts", {
    "./features/tenantTransport": { tenantFetch: async url => {
      calls.push(url);
      return url.endsWith("/results") ? new Response("zip", { headers: { "X-Bulk-Success-Count": "1", "X-Bulk-Failure-Count": "1" } })
        : new Response(JSON.stringify({ items: [job] }));
    } },
  });
  const result = await api.bulkJobs();
  assert.equal(result.items[0].success, 1);
  assert.equal(result.items[0].failures, 1);
  assert.deepEqual(calls, ["/api/bulk/jobs", "/api/bulk/jobs/legacy/results"]);
});

test("missing or inconsistent import result counts fail explicitly rather than pretending zero failures", async () => {
  const { api } = load("api.ts", {
    "./features/tenantTransport": { tenantFetch: async url => url.endsWith("/results") ? new Response("zip")
      : new Response(JSON.stringify({ items: [{ id: "legacy", total: 2, processed: 2, completed: true }] })) },
  });
  await assert.rejects(api.bulkJobs(), /counts are unavailable/);
});
