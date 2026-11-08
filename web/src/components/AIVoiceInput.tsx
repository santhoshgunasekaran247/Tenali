import { useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";
import { ai, type VoiceLanguage, type VoiceOutcome } from "../features/ai";
import { startVoiceRecording, type VoiceRecorder } from "../features/voiceRecording";

export function AIVoiceInput({ conversationId, disabled, onBusy, onTranscript }: {
  conversationId: string; disabled: boolean; onBusy: (busy: boolean) => void;
  onTranscript: (text: string) => boolean;
}) {
  const [phase, setPhase] = useState<"idle" | "starting" | "recording" | "ready" | "processing" | "review">("idle");
  const [language, setLanguage] = useState<VoiceLanguage>("auto");
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
      if (seconds >= 60) recorder.current?.stop();
    }, 250);
    return () => window.clearInterval(timer);
  }, [phase]);
  const clear = () => {
    generation.current++; recordingAbort.current?.abort(); recorder.current?.cancel(); recorder.current = null;
    setAudio(null); setTranscript(""); setRequestKey(""); setError(""); setNotice(""); setPhase("idle"); onBusy(false);
  };
  const record = async () => {
    const token = ++generation.current;
    const controller = new AbortController(); recordingAbort.current = controller;
    setPhase("starting"); setError(""); setNotice(""); setElapsed(0); onBusy(true);
    try {
      const capture = await startVoiceRecording(blob => {
        if (token !== generation.current) return;
        recorder.current = null; setAudio(blob); setPhase("ready"); onBusy(false);
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
      setTranscript(outcome.transcript); setPhase("review"); setAudio(null);
      setNotice(outcome.error_code === "usage_unknown" ? "Transcript ready; provider usage is unconfirmed, so the conservative reservation remains counted." : "Review and correct the transcript before adding it to your message.");
    } else {
      setPhase("ready");
      setError(outcome.status === "pending" ? "Voice is still processing. Check saved transcription later."
        : `No usable transcription (${outcome.error_code || outcome.status}). The request will not be automatically resent.`);
    }
  };
  const transcribe = async (recover = false) => {
    const key = requestKey || crypto.randomUUID(), token = generation.current;
    if (!recover && !audio) return;
    setRequestKey(key); setPhase("processing"); setError(""); onBusy(true);
    try {
      let outcome: VoiceOutcome;
      if (recover) outcome = await ai.voiceOutcome(conversationId, key);
      else {
        const recording = audio;
        if (!recording) throw new Error("Recording is unavailable.");
        const data = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onerror = () => reject(new Error("Recording could not be read."));
          reader.onload = () => typeof reader.result === "string" ? resolve(reader.result.split(",")[1]) : reject(new Error("Invalid recording."));
          reader.readAsDataURL(recording);
        });
        outcome = await ai.transcribe(conversationId, key, language, data);
      }
      if (token === generation.current) apply(outcome);
    } catch (failure) {
      if (token === generation.current) { setPhase("ready"); setError(String(failure) + " Check saved transcription or retry the same voice reference. No automatic resend occurs."); }
    } finally { if (token === generation.current) onBusy(false); }
  };
  return <section className="ai-voice" aria-label="Voice input">
    {phase === "idle" ? <button type="button" className="btn light" disabled={disabled} onClick={() => void record()}><Mic size={16} />Record voice</button> : <>
      <label>Spoken language<select value={language} disabled={phase !== "ready" || !!requestKey || disabled}
        onChange={event => {
          const value = event.target.value;
          if (value === "auto" || value === "en" || value === "ta") setLanguage(value);
          else setError("Choose English, Tamil or automatic language detection.");
        }}>
        <option value="auto">English & Tamil (auto)</option><option value="en">English</option><option value="ta">Tamil</option>
      </select></label>
      {phase === "starting" ? <p role="status">Allow microphone access to start recording.</p> : null}
      {phase === "recording" ? <div className="shop-actions"><span role="status">Recording {elapsed}s / 60s</span>
        <button type="button" onClick={() => recorder.current?.stop()}><Square size={14} />Stop recording</button></div> : null}
      {audioUrl ? <audio controls src={audioUrl} aria-label="Review voice recording" /> : null}
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
      <button type="button" disabled={phase === "processing"} onClick={clear}>{phase === "recording" || phase === "starting" ? "Cancel recording" : "Discard voice input"}</button>
    </>}
    {error ? <p role="alert">{error}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    <p className="social-caption">Up to 60 seconds. Transcription uses your AI budget. Review text before Send.</p>
    <details className="social-caption"><summary>Voice privacy & usage</summary>
      <p>Record locally, then explicitly transcribe with OpenAI. Audio is not stored on the server; recovery transcripts expire after 10 minutes. Transcription counts toward AI requests and spend. Send your message separately.</p>
    </details>
  </section>;
}
