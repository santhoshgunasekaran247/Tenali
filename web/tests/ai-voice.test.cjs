const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

const src = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");

function recordingHelpers() {
  const exports = {};
  const code = src("features/voiceRecording.ts").replace(/import\.meta\.url/g, '"http://localhost/voiceRecording.ts"');
  vm.runInNewContext(ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, { exports, Blob, ArrayBuffer, DataView, Float32Array });
  return exports;
}

test("microphone WAV encoding measures duration and clamps PCM samples", async () => {
  const { encodeVoiceWav } = recordingHelpers();
  const samples = new Float32Array(16000); samples[0] = -2; samples[1] = 2;
  const audio = encodeVoiceWav([samples], 16000);
  const view = new DataView(await audio.arrayBuffer());
  assert.equal(audio.type, "audio/wav");
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(view.getUint32(40, true), 32000);
  assert.equal(view.getInt16(44, true), -32768);
  assert.equal(view.getInt16(46, true), 32767);
  for (const frames of [7999, 960001]) assert.throws(() => encodeVoiceWav([new Float32Array(frames)], 16000), /half a second and 60 seconds/);
  assert.throws(() => encodeVoiceWav([samples], 4000), /half a second and 60 seconds/);
  samples[0] = NaN;
  assert.throws(() => encodeVoiceWav([samples], 16000), /invalid audio samples/);
});

test("audio worklet caps recording at exactly 60 seconds and flushes stopped samples", () => {
  let Processor;
  class Base { constructor() { this.messages = []; this.port = { postMessage: value => this.messages.push(value) }; } }
  vm.runInNewContext(src("features/voice-worklet.js"), {
    AudioWorkletProcessor: Base, Float32Array, sampleRate: 8000,
    registerProcessor: (_name, constructor) => { Processor = constructor; },
  });
  const recorder = new Processor();
  const frames = new Float32Array(128).fill(0.5);
  for (let i = 0; i < 4000; i++) if (!recorder.process([[frames]])) break;
  const count = recorder.messages.filter(message => message.type === "samples")
    .reduce((total, message) => total + message.buffer.byteLength / 4, 0);
  assert.equal(count, 60 * 8000);
  assert.equal(recorder.messages.filter(message => message.type === "done").length, 1);
  const stopped = new Processor(); stopped.process([[frames]]);
  stopped.port.onmessage({ data: "stop" }); stopped.port.onmessage({ data: "stop" });
  assert.equal(stopped.messages[0].buffer.byteLength, 128 * 4);
  assert.equal(stopped.messages.filter(message => message.type === "done").length, 1);
});

test("voice controls remain visible, preserve recovery and keep chat submission separate", () => {
  const voice = src("components/AIVoiceInput.tsx");
  assert.match(voice, /Check saved transcription/);
  assert.match(voice, /Transcript \(edit before using\)/);
  assert.match(voice, /Add to message/);
  assert.match(voice, /requestKey \|\| crypto\.randomUUID/);
  assert.match(voice, /generation\.current/);
  assert.match(voice, /recordingAbort\.current\?\.abort/);
  assert.doesNotMatch(voice, /ai\.send\(/);
  const page = src("pages/TenaliAIPage.tsx");
  assert.match(page, /available=\{!!features\?\.voice_inputs_enabled\}/);
  assert.match(page, /canSend && selected\.status === "active" \? <AIVoiceInput/);
  assert.match(page, /combined\.length > 4000/);
  assert.match(page, /operationBusy \|\| voiceBusy/);
  const platform = src("components/PlatformAISettings.tsx");
  assert.match(platform, /transcription_cost_per_minute/);
  assert.match(platform, /voice_inputs_enabled/);
  assert.match(platform, /OPENAI_ALLOWED_MODELS/);
});

function voiceHarness({ available = true, transcribe = async () => ({ status: "completed", transcript: "Copper stock" }) } = {}) {
  const state = [], refs = [], calls = { busy: [], transcripts: [], sent: [], cancel: 0, stop: 0 };
  let stateIndex = 0, refIndex = 0, completed, failed;
  const jsx = (type, props) => ({ type, props: props || {} });
  const react = {
    useState(initial) {
      const index = stateIndex++;
      if (!(index in state)) state[index] = initial;
      return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
    },
    useRef(initial) {
      const index = refIndex++;
      return refs[index] || (refs[index] = { current: initial });
    },
    useEffect() {},
  };
  const voice = {
    startVoiceRecording: async (onComplete, onFailure) => {
      completed = onComplete; failed = onFailure;
      return { stop: () => { calls.stop++; }, cancel: () => { calls.cancel++; } };
    },
  };
  class Reader {
    readAsDataURL() { this.result = "data:audio/wav;base64,UENN"; this.onload(); }
  }
  const exports = {};
  vm.runInNewContext(ts.transpileModule(src("components/AIVoiceInput.tsx"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, {
    exports, Blob, AbortController, FileReader: Reader, crypto: { randomUUID: () => "voice-key" },
    require: name => name === "react" ? react : name === "react/jsx-runtime" ? { jsx, jsxs: jsx, Fragment: "fragment" } :
      name === "lucide-react" ? { Mic: "mic", Square: "square", X: "x" } :
      name === "../features/ai" ? { ai: {
        transcribe: async (...args) => { calls.sent.push(args); return transcribe(...args); },
        voiceOutcome: async () => ({ status: "completed", transcript: "Recovered" }),
      } } : name === "../features/voiceRecording" ? voice : require(name),
  });
  const props = { conversationId: "chat", available, disabled: false, onBusy: value => calls.busy.push(value),
    onTranscript: value => { calls.transcripts.push(value); return true; } };
  const render = () => { stateIndex = 0; refIndex = 0; return exports.AIVoiceInput(props); };
  const find = (node, label) => {
    if (!node || typeof node !== "object") return null;
    if (node.type === "button" && (node.props["aria-label"] === label || node.props.children === label)) return node;
    for (const child of [node.props?.children].flat(Infinity)) {
      const result = find(child, label);
      if (result) return result;
    }
    return null;
  };
  return { calls, render, find, complete: blob => completed(blob), fail: error => failed(error) };
}

test("mic records, stop transcribes once into the message, and discard sends nothing", async () => {
  const h = voiceHarness();
  h.find(h.render(), "Record voice").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const recording = h.render();
  assert.ok(h.find(recording, "Discard recording"));
  h.find(recording, "Stop and transcribe").props.onClick();
  assert.equal(h.calls.stop, 1);
  h.complete(new Blob(["PCM"]));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.calls.sent.length, 1);
  assert.deepEqual(h.calls.sent[0], ["chat", "voice-key", "auto", "UENN"]);
  assert.deepEqual(h.calls.transcripts, ["Copper stock"]);
  assert.ok(h.find(h.render(), "Record voice"));
  assert.equal(h.calls.busy.at(-1), false);

  const discarded = voiceHarness();
  discarded.find(discarded.render(), "Record voice").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  discarded.find(discarded.render(), "Discard recording").props.onClick();
  discarded.complete(new Blob(["PCM"]));
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(discarded.calls.cancel > 0);
  assert.equal(discarded.calls.sent.length, 0);
  assert.deepEqual(discarded.calls.transcripts, []);
});

test("unavailable voice explains configuration without requesting microphone access", () => {
  const h = voiceHarness({ available: false });
  h.find(h.render(), "Voice input unavailable").props.onClick();
  assert.match(JSON.stringify(h.render()), /platform administrator/);
  assert.deepEqual(h.calls.busy, []);
  assert.equal(h.calls.sent.length, 0);
});

test("failed transcription retains the recording and retries with the same reference", async () => {
  let attempt = 0;
  const h = voiceHarness({ transcribe: async () => {
    if (attempt++ === 0) throw new Error("Connection lost");
    return { status: "completed", transcript: "Recovered text" };
  } });
  h.find(h.render(), "Record voice").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  h.find(h.render(), "Stop and transcribe").props.onClick();
  h.complete(new Blob(["PCM"]));
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.find(h.render(), "Check saved transcription"));
  h.find(h.render(), "Retry same voice reference").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.calls.sent.length, 2);
  assert.equal(h.calls.sent[0][1], h.calls.sent[1][1]);
  assert.deepEqual(h.calls.transcripts, ["Recovered text"]);
});

test("voice client uses tenant transport and exact stable references without automatic retry", async () => {
  const calls = [], exports = {};
  const mockFetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({ status: "pending" }) }; };
  vm.runInNewContext(ts.transpileModule(src("features/ai.ts"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, { exports, require: () => ({ tenantFetch: mockFetch }), URLSearchParams });
  await exports.ai.transcribe("chat", "stable-voice-key", "ta", "PCM");
  await exports.ai.voiceOutcome("chat", "stable-voice-key");
  assert.equal(calls[0].url, "/api/ai/conversations/chat/voice");
  assert.deepEqual(JSON.parse(calls[0].options.body), { client_key: "stable-voice-key", language: "ta", data_base64: "PCM" });
  assert.equal(calls[1].url, "/api/ai/conversations/chat/voice/stable-voice-key");
  assert.equal(calls.length, 2);
});
