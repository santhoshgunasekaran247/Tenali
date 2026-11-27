const assert = require("node:assert/strict");
const { readFileSync, statSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const read = file => readFileSync(path.join(root, "src", file), "utf8");
const tour = JSON.parse(read("content/product-tour.json"));

function track(file) {
  const content = readFileSync(path.join(root, "public", file), "utf8").replace(/\r\n/g, "\n");
  assert.ok(content.startsWith("WEBVTT\n"));
  const seconds = value => {
    const [minutes, seconds] = value.split(":").map(Number);
    return minutes * 60 + seconds;
  };
  return content.trim().split(/\n\n+/).slice(1).map(block => {
    const [timing, ...lines] = block.split("\n");
    const match = /^(\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}\.\d{3})$/.exec(timing);
    assert.ok(match, `Invalid cue: ${timing}`);
    return { start: seconds(match[1]), end: seconds(match[2]), text: lines.join(" ").replace(/\s+/g, " ").trim() };
  });
}

function marketingPlayer(video, muted = false) {
  const exports = {};
  const updates = [];
  let stateSlot = 0;
  const jsx = (type, props) => ({ type, props });
  const mocks = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect: () => {},
      useRef: () => ({ current: video }),
      useState: initial => [stateSlot++ === 5 ? muted : initial, value => updates.push(value)],
    },
    "react-router-dom": { Link: "Link" },
    "../content/product-tour.json": tour,
    "../features/useDismissOutside": { useDismissOutside() {} },
    "../features/policies": { policyPath: (scope, kind) => `/policies/${scope}/${kind}` },
  };
  const code = ts.transpileModule(read("pages/PlatformHomePage.tsx"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText;
  vm.runInNewContext(code, { exports, require: name => mocks[name] || {} });
  const nodes = [];
  const visit = node => {
    if (Array.isArray(node)) node.forEach(visit);
    else if (node && typeof node === "object") { nodes.push(node); visit(node.props?.children); }
  };
  visit(exports.PlatformHomePage());
  const chapterNav = nodes.find(node => node.props?.["aria-label"] === "Video chapters");
  const allNodes = nodes.slice();
  nodes.length = 0;
  visit(chapterNav);
  return {
    buttons: nodes.filter(node => node.type === "button"),
    video: allNodes.find(node => node.type === "video"),
    audio: allNodes.find(node => node.props?.className === "demo-audio-toggle"),
    updates,
  };
}

function renderRoot(auth, base = "", customApi = "") {
  const exports = {};
  const jsx = (type, props) => ({ type, props });
  const mocks = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: { createContext: () => ({}), useContext: () => auth },
    "react-router-dom": { Navigate: "Navigate" },
    "./tenantTransport": { tenantBase: () => base, tenantApiOrigin: () => customApi },
    "../pages/PlatformHomePage": { PlatformHomePage: "PlatformHomePage" },
  };
  const code = ts.transpileModule(read("features/auth.tsx"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { exports, require: name => mocks[name] || {} });
  return exports.StorefrontRoot({ children: "storefront" });
}

test("platform home is public for visitors and signed-in users", () => {
  for (const user of [null, { tenant_slug: "acme" }]) {
    assert.equal(renderRoot({ loading: false, storefront: null, user }).type, "PlatformHomePage");
  }
});

test("tenant storefronts and tenant redirects remain intact", () => {
  assert.equal(renderRoot({ loading: false, storefront: { id: "c" }, user: null }, "/c/acme").props.children, "storefront");
  const missing = renderRoot({ loading: false, storefront: null, user: { tenant_slug: "acme" } }, "/c/acme");
  assert.equal(missing.type, "Navigate");
  assert.equal(missing.props.to, "/portal");
  const custom = renderRoot({ loading: false, storefront: null, user: { tenant_slug: "acme" } }, "", "https://api.store.test");
  assert.notEqual(custom.type, "PlatformHomePage");
});

test("marketing page has real routes, an accessible demo and a local video", () => {
  const page = read("pages/PlatformHomePage.tsx");
  for (const section of ["what-we-do", "how-it-works", "demo", "about", "contact"]) assert.match(page, new RegExp(`id="${section}"`));
  assert.match(page, /to="\/register"/);
  assert.match(page, /to="\/login"/);
  assert.match(page, /policyPath\("platform", "contact"\)/);
  assert.match(page, /policyRequest<PublicPolicy>\("\/legal\/platform\/contact"\)/);
  assert.match(page, /<video controls preload="metadata" playsInline/);
  assert.doesNotMatch(page, /<video[^>]*autoPlay/);
  assert.match(page, /<track kind="captions" src="\/tenali-product-tour.vtt" srcLang="en" label="English"/);
  assert.match(page, /<track kind="chapters" src="\/tenali-product-tour-chapters.vtt"/);
  assert.match(page, /id="demo-transcript"/);
  assert.match(page, /Actual app screens use sample data/);
  assert.match(page, /no customer records or live AI replies/);
  assert.match(page, /Run your day-to-day operations, manage inventory/);
  assert.match(page, /Know who has paid/);
  assert.match(page, /Ask Tenali AI for help/);
  assert.match(page, /Read the instructions in the dark panel and follow the app in the light panel/);
  assert.doesNotMatch(page, /one-minute|1-minute/);
  assert.match(page, /setAttribute\("open", ""\)/);
  assert.match(page, /poster="\/tenali-product-tour-poster.jpg"/);
  assert.match(page, /src="\/tenali-product-tour.mp4" type="video\/mp4"/);
  assert.ok(statSync(path.join(root, "public", "tenali-workspace-preview.jpg")).size > 10000);
  assert.ok(statSync(path.join(root, "public", "tenali-product-tour-poster.jpg")).size > 10000);
});

test("local narrated guide is seekable with matching captions and chapters", () => {
  const video = readFileSync(path.join(root, "public", "tenali-product-tour.mp4"));
  assert.equal(video.toString("ascii", 4, 8), "ftyp");
  assert.ok(video.includes(Buffer.from("avc1")), "video must contain H.264 media");
  assert.ok(video.includes(Buffer.from("mp4a")), "video must include AAC narration and music");
  assert.ok(video.indexOf(Buffer.from("moov")) < video.indexOf(Buffer.from("mdat")), "metadata must precede media for progressive playback");
  const header = video.indexOf(Buffer.from("mvhd"));
  assert.ok(header > 0);
  assert.equal(video[header + 4], 0);
  const duration = video.readUInt32BE(header + 20) / video.readUInt32BE(header + 16);
  assert.ok(duration >= 300);
  assert.equal(duration, tour.duration);
  const cues = track("tenali-product-tour.vtt");
  assert.equal(cues.length, tour.steps.length);
  let end = 0;
  for (const [index, cue] of cues.entries()) {
    const step = tour.steps[index];
    assert.ok(cue.start >= end && cue.start - end <= 0.101);
    assert.ok(cue.end > cue.start && cue.end <= duration);
    const captionEnd = step.end === duration ? step.end : step.end - 0.1;
    assert.deepEqual(cue, { start: step.start, end: captionEnd, text: step.narration || step.instruction });
    end = cue.end;
  }
  assert.equal(end, duration);
  const chapters = track("tenali-product-tour-chapters.vtt");
  assert.equal(chapters.length, tour.chapters.length);
  for (const [index, chapter] of tour.chapters.entries()) {
    assert.deepEqual(chapters[index], {
      start: chapter.start,
      end: tour.chapters[index + 1]?.start ?? duration,
      text: chapter.title,
    });
  }
});

test("instructions allow reading time and each step belongs to its timed chapter", () => {
  assert.doesNotMatch(JSON.stringify(tour), /ask your accountant/i);
  for (const step of tour.steps) {
    const words = `${step.title} ${step.instruction}`.split(/\s+/).length;
    assert.ok(words / (step.end - step.start) <= 3.6, `Instruction too fast: ${step.title}`);
    const chapter = tour.chapters[step.chapter];
    assert.ok(step.start >= chapter.start);
    assert.ok(step.end <= (tour.chapters[step.chapter + 1]?.start ?? tour.duration));
  }
});

test("chapter buttons seek and play their actual start times without autoplay on load", async () => {
  let plays = 0;
  let focuses = 0;
  const video = { currentTime: 0, focus: () => focuses++, play: () => { plays++; return Promise.resolve(); } };
  const player = marketingPlayer(video);
  assert.equal(plays, 0);
  assert.equal(player.buttons.length, tour.chapters.length);
  for (const [index, button] of player.buttons.entries()) {
    button.props.onClick();
    assert.equal(video.currentTime, tour.chapters[index].start);
  }
  assert.equal(plays, tour.chapters.length);
  assert.equal(focuses, tour.chapters.length);
  video.currentTime = tour.chapters[6].start + 1;
  player.video.props.onTimeUpdate({ currentTarget: video });
  assert.equal(player.updates.at(-1), 6);
});

test("sound controls mute and unmute both narration and music without starting playback", () => {
  const video = { muted: false, volume: 1 };
  let player = marketingPlayer(video);
  player.audio.props.onClick();
  assert.equal(video.muted, true);
  video.volume = 0;
  player = marketingPlayer(video, true);
  player.audio.props.onClick();
  assert.equal(video.muted, false);
  assert.equal(video.volume, 1);
  player.video.props.onVolumeChange({ currentTarget: { muted: false, volume: 0 } });
  assert.equal(player.updates.at(-1), true);
});

test("playback failures give a readable alternative", async () => {
  const player = marketingPlayer({ currentTime: 0, focus() {}, play: () => Promise.reject(new Error("Playback blocked")) });
  player.buttons[1].props.onClick();
  await Promise.resolve();
  assert.match(player.updates.at(-1), /play button.*read the steps/);
  player.video.props.onError();
  assert.match(player.updates.at(-1), /could not be loaded.*read every step/);
});

test("marketing footer headings and links have explicit contrasting colors", () => {
  const css = read("pages/platform-home.css");
  assert.match(css, /\.marketing \.footer-grid strong \{ color: #172d4a;/);
  assert.match(css, /\.marketing \.footer-grid a, \.marketing \.footer-bottom a \{ color: #425f7d;/);
});
