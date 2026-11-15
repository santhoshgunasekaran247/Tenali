import { useEffect, useRef, useState } from "react";
import { Mic, Square, X } from "lucide-react";
import { ai, type VoiceOutcome } from "../features/ai";
import { startVoiceRecording, type VoiceRecorder } from "../features/voiceRecording";

export function AIVoiceInput({ conversationId, available, disabled, onBusy, onTranscript }: {
  conversationId: string; available: boolean; disabled: boolean; onBusy: (busy: boolean) => void;
  onTranscript: (text: string) => boolean;
}) {
  const [phase, setPhase] = useState<"idle" | "starting" | "recording" | "stopping" | "ready" | "processing" | "review">("idle");
  const [audio, setAudio] = useState<Blob | null>(null);
  const [audioUrl, setAudioUrl] = useState("");
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requestKey, setRequestKey] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const recorder = useRef<VoiceRecorder | null>(null), generation = useRef(0);
  const recordingAbort = useRef<AbortController | null>(null);
  useEffect(() => () => { generation.current++; recordingAbort.current?.abort(); recorder.current?.cancel(); onBusy(false); }, [onBusy]);
  useEffect(() => {
    if (!audio) { setAudioUrl(""); return; }
    const url = URL.createObjectURL(audio); setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [audio]);
  useEffect(() => {
    if (phase !== "recording") return;
    const start = Date.now();
    const timer = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - start) / 1000);
      setElapsed(Math.min(60, seconds));
      if (seconds >= 60) stop();
    }, 250);
    return () => window.clearInterval(timer);
  }, [phase]);
  const clear = () => {
    generation.current++; recordingAbort.current?.abort(); recorder.current?.cancel(); recorder.current = null;
    setAudio(null); setTranscript(""); setRequestKey(""); setError(""); setNotice(""); setPhase("idle"); onBusy(false);
  };
  const stop = () => {
    const capture = recorder.current;
    if (!capture) return;
    recorder.current = null;
    setPhase("stopping");
    capture.stop();
  };
  const record = async () => {
    if (!available) {
      setError("Voice transcription is unavailable. Ask a platform administrator to enable and configure Voice input in Platform AI settings.");
      return;
    }
    const token = ++generation.current;
    const controller = new AbortController(); recordingAbort.current = controller;
    setPhase("starting"); setError(""); setNotice(""); setElapsed(0); onBusy(true);
    try {
      const capture = await startVoiceRecording(blob => {
        if (token !== generation.current) return;
        recorder.current = null; setAudio(blob); void transcribe(false, blob);
      }, failure => {
        if (token !== generation.current) return;
        recorder.current = null; setError(failure.message); setPhase("idle"); onBusy(false);
      }, controller.signal);
      if (token !== generation.current) { capture.cancel(); return; }
      recorder.current = capture; setPhase("recording");
    } catch (failure) {
      if (token === generation.current) { setError(String(failure)); setPhase("idle"); onBusy(false); }
    }
  };
  const apply = (outcome: VoiceOutcome) => {
    if (outcome.transcript) {
      setAudio(null);
      if (onTranscript(outcome.transcript.trim())) {
        setRequestKey(""); setPhase("idle");
        setNotice(outcome.error_code === "usage_unknown"
          ? "Voice text added. Provider usage is unconfirmed, so the conservative reservation remains counted."
          : "Voice text added. Review it before sending.");
      } else {
        setTranscript(outcome.transcript); setPhase("review");
        setNotice("Shorten the transcript or message before adding it.");
      }
    } else {
      setPhase("ready");
      setError(outcome.status === "pending" ? "Voice is still processing. Check saved transcription later."
        : `No usable transcription (${outcome.error_code || outcome.status}). The request will not be automatically resent.`);
    }
  };
  const transcribe = async (recover = false, capturedAudio?: Blob) => {
    const key = requestKey || crypto.randomUUID(), token = generation.current;
    if (!recover && !capturedAudio && !audio) return;
    setRequestKey(key); setPhase("processing"); setError(""); onBusy(true);
    try {
      let outcome: VoiceOutcome;
      if (recover) outcome = await ai.voiceOutcome(conversationId, key);
      else {
        const recording = capturedAudio || audio;
        if (!recording) throw new Error("Recording is unavailable.");
        const data = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onerror = () => reject(new Error("Recording could not be read."));
          reader.onload = () => typeof reader.result === "string" ? resolve(reader.result.split(",")[1]) : reject(new Error("Invalid recording."));
          reader.readAsDataURL(recording);
        });
        outcome = await ai.transcribe(conversationId, key, "auto", data);
      }
      if (token === generation.current) apply(outcome);
    } catch (failure) {
      if (token === generation.current) { setPhase("ready"); setError(String(failure) + " Check saved transcription or retry the same voice reference. No automatic resend occurs."); }
    } finally { if (token === generation.current) onBusy(false); }
  };
  return <section className="ai-voice" data-active={phase !== "idle"} aria-label="Voice input">
    {phase === "idle" ? <button type="button" className="ai-icon-button" title={available ? "Record voice" : "Voice input unavailable"}
      aria-label={available ? "Record voice" : "Voice input unavailable"} disabled={disabled} onClick={() => void record()}><Mic size={19} /></button> : <>
      {phase === "starting" ? <p role="status">Allow microphone access to start recording.</p> : null}
      {phase === "recording" || phase === "starting" ? <div className="ai-voice-controls">
        <button type="button" className="ai-icon-button" aria-label="Discard recording" title="Discard recording" onClick={clear}><X size={19} /></button>
        {phase === "recording" ? <><span role="status">Recording {elapsed}s / 60s</span>
          <button type="button" className="ai-icon-button" aria-label="Stop and transcribe" title="Stop and transcribe" onClick={stop}><Square size={18} /></button></> : null}
      </div> : null}
      {phase === "stopping" ? <p role="status">Finishing recording...</p> : null}
      {phase === "ready" && audioUrl ? <audio controls src={audioUrl} aria-label="Review voice recording" /> : null}
      {phase === "ready" ? <div className="shop-actions">
        {audio ? <button type="button" disabled={disabled} onClick={() => void transcribe()}>{requestKey ? "Retry same voice reference" : "Transcribe recording"}</button> : null}
        {requestKey ? <button type="button" disabled={disabled} onClick={() => void transcribe(true)}>Check saved transcription</button> : null}
      </div> : null}
      {phase === "processing" ? <p role="status">Transcribing... Your request reference is preserved for recovery.</p> : null}
      {phase === "review" ? <>
        <label>Transcript (edit before using)<textarea rows={3} maxLength={4000} value={transcript} disabled={disabled}
          onChange={event => setTranscript(event.target.value)} /></label>
        <button type="button" disabled={disabled || !transcript.trim()} onClick={() => { if (onTranscript(transcript.trim())) clear(); }}>Add to message</button>
      </> : null}
      {phase === "ready" || phase === "review" ? <button type="button" onClick={clear}>Discard voice input</button> : null}
    </>}
    {error ? <p role="alert">{error}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    {phase === "recording" || phase === "starting" ? <p className="social-caption">Stop sends audio for transcription, which uses your AI budget. At 60 seconds it stops and transcribes automatically. Discard does not send audio.</p> : null}
    {phase !== "idle" ? <details className="social-caption"><summary>Voice privacy & usage</summary>
      <p>Stop sends your recording to OpenAI for transcription. Audio is not stored on the server; recovery transcripts expire after 10 minutes. Transcription counts toward AI requests and spend. Send your message separately.</p>
    </details> : null}
  </section>;
}
