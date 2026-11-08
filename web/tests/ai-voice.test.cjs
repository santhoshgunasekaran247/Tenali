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

test("voice requires explicit transcription, editable review and separate chat submission", () => {
  const voice = src("components/AIVoiceInput.tsx");
  assert.match(voice, /Transcribe recording/);
  assert.match(voice, /Check saved transcription/);
  assert.match(voice, /Transcript \(edit before using\)/);
  assert.match(voice, /Add to message/);
  assert.match(voice, /requestKey \|\| crypto\.randomUUID/);
  assert.match(voice, /generation\.current/);
  assert.match(voice, /recordingAbort\.current\?\.abort/);
  assert.doesNotMatch(voice, /ai\.send\(/);
  const page = src("pages/TenaliAIPage.tsx");
  assert.match(page, /features\?\.voice_inputs_enabled && canSend/);
  assert.match(page, /combined\.length > 4000/);
  assert.match(page, /operationBusy \|\| voiceBusy/);
  const platform = src("components/PlatformAISettings.tsx");
  assert.match(platform, /transcription_cost_per_minute/);
  assert.match(platform, /voice_inputs_enabled/);
  assert.match(platform, /OPENAI_ALLOWED_MODELS/);
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
