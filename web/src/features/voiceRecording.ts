export type VoiceRecorder = { stop: () => void; cancel: () => void };

export function encodeVoiceWav(chunks: Float32Array[], sampleRate: number): Blob {
  const frames = chunks.reduce((total, chunk) => total + chunk.length, 0);
  if (!Number.isInteger(sampleRate) || sampleRate < 8000 || sampleRate > 96000
      || frames < sampleRate / 2 || frames > sampleRate * 60) {
    throw new Error("Record between half a second and 60 seconds.");
  }
  const buffer = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(buffer);
  const label = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index++) view.setUint8(offset + index, value.charCodeAt(index));
  };
  label(0, "RIFF"); view.setUint32(4, buffer.byteLength - 8, true); label(8, "WAVE");
  label(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  label(36, "data"); view.setUint32(40, frames * 2, true);
  let offset = 44;
  for (const chunk of chunks) for (const value of chunk) {
    if (!Number.isFinite(value)) throw new Error("Microphone returned invalid audio samples.");
    const sample = Math.max(-1, Math.min(1, value));
    view.setInt16(offset, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export async function startVoiceRecording(
  completed: (audio: Blob) => void, failed: (error: Error) => void, signal: AbortSignal,
): Promise<VoiceRecorder> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
    throw new Error("Microphone recording needs HTTPS (or localhost) and a browser with audio recording support.");
  }
  const context = new AudioContext();
  let stream: MediaStream | null = null;
  let node: AudioWorkletNode | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let stopped = false;
  const chunks: Float32Array[] = [];
  const dispose = () => {
    signal.removeEventListener("abort", cancel);
    stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    source?.disconnect(); node?.disconnect();
    if (context.state !== "closed") void context.close().catch(() => failed(new Error("Microphone audio context could not be closed. Reload this page.")));
  };
  const cancel = () => { stopped = true; chunks.length = 0; dispose(); };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    signal.throwIfAborted();
    // Resume before requesting permission while the user's button gesture is active.
    await context.resume();
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
    signal.throwIfAborted();
    if (!context.audioWorklet) throw new Error("This browser does not support microphone recording. Use keyboard dictation instead.");
    await context.audioWorklet.addModule(new URL("./voice-worklet.js?no-inline", import.meta.url).href);
    signal.throwIfAborted();
    source = context.createMediaStreamSource(stream);
    node = new AudioWorkletNode(context, "tenali-voice-capture", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
    node.port.onmessage = (event: MessageEvent<unknown>) => {
      if (stopped) return;
      const data = event.data;
      if (!data || typeof data !== "object" || !("type" in data)) return;
      if (data.type === "samples" && "buffer" in data && data.buffer instanceof ArrayBuffer) {
        chunks.push(new Float32Array(data.buffer));
      } else if (data.type === "done") {
        stopped = true; dispose();
        try { completed(encodeVoiceWav(chunks, context.sampleRate)); }
        catch (error) { failed(error instanceof Error ? error : new Error("Recording could not be encoded.")); }
        finally { chunks.length = 0; }
      }
    };
    node.onprocessorerror = () => { cancel(); failed(new Error("Microphone recording failed. Please record again.")); };
    for (const track of stream.getTracks()) track.onended = () => { cancel(); failed(new Error("Microphone access ended before recording completed.")); };
    source.connect(node); node.connect(context.destination);
    return { stop: () => {
      node?.port.postMessage("stop");
      stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    }, cancel };
  } catch (error) {
    cancel();
    throw new Error("Microphone could not start. Check browser permissions. " + (error instanceof Error ? error.message : String(error)));
  }
}
