const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function harness(fetch, location = { pathname: "/products/bottle", search: "" }) {
  const nodes = [];
  const matches = (node, selector) => {
    const meta = /^meta\[(name|property)="([^"]+)"\]$/.exec(selector);
    if (meta) return node.tag === "meta" && node.attributes[meta[1]] === meta[2];
    if (selector === 'link[rel="canonical"]') return node.tag === "link" && node.rel === "canonical";
    return selector === "script[data-tenali-seo]" && node.tag === "script" && "tenaliSeo" in node.dataset;
  };
  const document = {
    title: "Previous page",
    documentElement: { dataset: {} },
    createElement: tag => {
      const node = { tag, attributes: {}, dataset: {}, setAttribute(key, value) { this.attributes[key] = value; },
        remove() { nodes.splice(nodes.indexOf(node), 1); } };
      return node;
    },
    head: {
      querySelector: selector => nodes.find(node => matches(node, selector)),
      querySelectorAll: selector => nodes.filter(node => matches(node, selector)),
      append: node => nodes.push(node),
    },
  };
  let effect;
  const exports = {};
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "components", "SeoMetadata.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(compiled, { exports, document, URLSearchParams, AbortController, console,
    require: name => ({
      react: { useEffect: callback => { effect = callback; } },
      "react-router-dom": { useLocation: () => location },
      "../features/tenantTransport": { tenantBase: () => "/c/shop", tenantFetch: fetch },
    })[name],
  });
  return { ...exports, document, nodes, start() { exports.SeoMetadata(); return effect(); } };
}

const product = {
  title: "Bottle | Shop", description: "Reusable steel bottle.", canonical: "https://shop.test/products/bottle",
  image: "https://shop.test/bottle.jpg", kind: "product", indexable: true,
  structured_data: [{ "@type": "Product", name: "Bottle" }],
};

test("initial server-rendered metadata is retained without fetching the same catalogue twice", () => {
  const h = harness(() => { throw new Error("Initial SEO should not be fetched again"); });
  h.applySeoMetadata(product);
  h.document.documentElement.dataset.tenaliSeoPath = "/c/shop/products/bottle";
  h.start();
  h.start();
  assert.equal(h.document.title, product.title);
  assert.equal(h.document.head.querySelector('meta[name="robots"]').content, "index,follow");
});

test("navigation replaces product metadata and removes public canonical and schema on private pages", () => {
  const h = harness();
  h.applySeoMetadata(product);
  h.applySeoMetadata({ ...product, title: "Kettle | Shop", canonical: "https://shop.test/products/kettle",
    image: "https://shop.test/kettle.jpg" });
  assert.equal(h.document.title, "Kettle | Shop");
  assert.equal(h.nodes.filter(node => node.tag === "link").length, 1);
  assert.equal(h.nodes.filter(node => node.tag === "script").length, 1);
  h.applySeoMetadata({ ...product, title: "Sign in", canonical: null, image: null, indexable: false, structured_data: [] });
  assert.equal(h.document.head.querySelector('meta[name="robots"]').content, "noindex,follow");
  assert.equal(h.document.head.querySelector('link[rel="canonical"]'), undefined);
  assert.equal(h.document.head.querySelector('meta[property="og:image"]'), undefined);
  assert.equal(h.nodes.filter(node => node.tag === "script").length, 0);
});

test("tenant navigation uses the full public path and ignores responses after leaving the page", async () => {
  let resolve;
  let requested;
  const h = harness((url, options) => {
    requested = { url, options };
    return new Promise(done => { resolve = done; });
  });
  const cleanup = h.start();
  assert.equal(new URL(requested.url, "https://platform.test").searchParams.get("path"), "/c/shop/products/bottle");
  cleanup();
  assert.equal(requested.options.signal.aborted, true);
  resolve({ ok: true, json: async () => product });
  await new Promise(done => setImmediate(done));
  assert.equal(h.document.title, "Previous page");
  assert.equal(h.document.head.querySelector('meta[name="robots"]').content, "noindex,follow");
});

test("a missing product receives noindex metadata rather than keeping the previous product", async () => {
  const h = harness(async () => ({ ok: false, status: 404,
    json: async () => ({ ...product, title: "Product not found", canonical: null, image: null, indexable: false, structured_data: [] }),
  }));
  h.applySeoMetadata(product);
  h.start();
  await new Promise(done => setImmediate(done));
  assert.equal(h.document.title, "Product not found");
  assert.equal(h.document.head.querySelector('link[rel="canonical"]'), undefined);
  assert.equal(h.nodes.filter(node => node.tag === "script").length, 0);
});
