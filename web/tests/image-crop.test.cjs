const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const exportsObject = {};
vm.runInNewContext(ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "features", "imageCrop.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: exportsObject });
const { cropRectangle } = exportsObject;

test("crop respects the output ratio, centers by default and stays inside the source at each edge", () => {
  const center = cropRectangle(1600, 900, 1000, 1000, 1, 50, 50);
  assert.equal(center.x, 350);
  assert.equal(center.y, 0);
  assert.equal(center.width, 900);
  assert.equal(center.height, 900);
  for (const [width, height] of [[600, 600], [1600, 600], [800, 1000]]) {
    for (const position of [0, 50, 100]) {
      const crop = cropRectangle(900, 1600, width, height, 2, position, position);
      assert.ok(crop.x >= 0 && crop.y >= 0);
      assert.ok(crop.x + crop.width <= 900 && crop.y + crop.height <= 1600);
      assert.ok(Math.abs(crop.width / crop.height - width / height) < 0.000001);
    }
  }
});

test("invalid dimensions and positions are rejected before calculating a crop", () => {
  for (const args of [[0, 900, 1000, 1000, 1, 50, 50], [900, 900, 0, 1000, 1, 50, 50],
    [900, 900, 1000, 1000, 0.5, 50, 50], [900, 900, 1000, 1000, 1, -1, 50]]) {
    assert.throws(() => cropRectangle(...args), /valid image dimensions/);
  }
});

function cropEditor(sourceWidth, sourceHeight) {
  const states = [], refs = [];
  let stateIndex = 0, refIndex = 0, effect, first = true, applied;
  const exports = {};
  const element = (type, props) => ({ type, props });
  vm.runInNewContext(ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "components", "ImageCropEditor.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, require: name => ({
    react: {
      useId: () => "crop-test",
      useState: initial => { const index = stateIndex++; if (!(index in states)) states[index] = initial;
        return [states[index], value => { states[index] = typeof value === "function" ? value(states[index]) : value; }]; },
      useRef: initial => { const index = refIndex++; return refs[index] ||= { current: index === 0 ? { showModal() {} } : initial }; },
      useEffect: callback => { if (first) effect = callback; },
    },
    "react/jsx-runtime": { jsx: element, jsxs: element },
    "lucide-react": { X: "X" },
    "../features/imageCrop": exportsObject,
    "../features/catalog/utils": { toAssetUrl: value => value },
  })[name], Image: class {
    naturalWidth = sourceWidth; naturalHeight = sourceHeight;
    set src(value) { this.onload(); }
  }, document: { createElement: () => {
    const canvas = { getContext: () => ({ drawImage() {} }), toDataURL: () => {
      applied = { width: canvas.width, height: canvas.height }; return "data:image/png;base64,Y3JvcA==";
    } }; return canvas;
  } } });
  const render = () => {
    stateIndex = refIndex = 0;
    const tree = exports.ImageCropEditor({ source: "/saved-logo.png", label: "logo", width: 600, height: 600,
      presets: [{ label: "Wide logo", width: 1200, height: 300 }], onApply() {}, onClose() {} });
    if (first) { first = false; effect(); return render(); }
    return tree;
  };
  const find = (node, predicate) => {
    if (!node || typeof node !== "object") return undefined;
    if (Array.isArray(node)) return node.map(item => find(item, predicate)).find(Boolean);
    return predicate(node) ? node : find(node.props.children, predicate);
  };
  const text = node => typeof node === "object" && node ? Array.isArray(node) ? node.map(text).join("") : text(node.props.children) : String(node ?? "");
  return { render, find, text, applied: () => applied };
}

test("cropping starts with saved image pixels, offers square/wide choices and retains applied pixels when reopened", () => {
  const editor = cropEditor(1800, 300);
  const input = (tree, label) => editor.find(editor.find(tree, node => node.type === "label" && editor.text(node).startsWith(label)),
    node => node.type === "input");
  assert.equal(input(editor.render(), "Output width").props.value, 1800);
  assert.equal(input(editor.render(), "Output height").props.value, 300);
  editor.find(editor.render(), node => node.type === "button" && editor.text(node) === "Recommended 600 x 600").props.onClick();
  assert.equal(input(editor.render(), "Output height").props.value, 600);
  editor.find(editor.render(), node => node.type === "button" && editor.text(node) === "Wide logo 1200 x 300").props.onClick();
  assert.equal(input(editor.render(), "Output width").props.value, 1200);
  input(editor.render(), "Output width").props.onChange({ target: { value: "1800" } });
  editor.find(editor.render(), node => node.type === "button" && editor.text(node) === "Apply crop").props.onClick();
  assert.deepEqual(editor.applied(), { width: 1800, height: 300 });
  const reopened = cropEditor(editor.applied().width, editor.applied().height);
  assert.equal(reopened.find(reopened.render(), node => node.type === "input" && node.props.type === "number").props.value, 1800);
});
