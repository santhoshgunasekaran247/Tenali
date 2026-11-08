import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ai, messageStatus, type AIUsage, type ChatMessage, type Conversation, type Preference, type ReadCapability, type AIAttachment } from "../features/ai";
import { featureExplanation } from "../features/featureControls";
import { useAuth } from "../features/auth";
import { FloatingAlert } from "../components/Notifications";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { AIDrafts } from "../components/AIDrafts";
import { AIVoiceInput } from "../components/AIVoiceInput";
import type { CompanyFeatures } from "../types";

export function TenaliAIPage() {
  const auth = useAuth();
  const [features, setFeatures] = useState<CompanyFeatures | null>(null);
  const [capabilities, setCapabilities] = useState<ReadCapability[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [offset, setOffset] = useState(0);
  const [messageOffset, setMessageOffset] = useState(0);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [preferences, setPreferences] = useState<Record<Preference["preference"], string>>({ language: "", instructions: "" });
  const [usage, setUsage] = useState<AIUsage | null>(null);
  const [error, setError] = useState("");
  const [operationBusy, setBusy] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const busy = operationBusy || voiceBusy;
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [notice, setNotice] = useState("");
  const [draftRefresh, setDraftRefresh] = useState(0);
  const [submission, setSubmission] = useState<{ id: string; content: string; key: string; attachments: string[] } | null>(null);
  const [attachments, setAttachments] = useState<AIAttachment[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [titleSaving, setTitleSaving] = useState(false);
  const [titleError, setTitleError] = useState("");
  const currentConversation = useRef(selected), currentTitle = useRef(title), titleRequest = useRef(false);
  currentConversation.current = selected; currentTitle.current = title;
  const generation = useRef(0);
  const messageEnd = useRef<HTMLDivElement>(null);
  const viewer = auth.user?.role === "viewer";
  const canSend = features?.ai.effective_enabled && !viewer;

  const refreshHistory = async () => setConversations((await ai.conversations(search, archived, offset)).items);
  const refreshConversation = async (conversation: Conversation) => {
    const token = generation.current;
    const [updated, history] = await Promise.all([ai.conversation(conversation.id), ai.messages(conversation.id, messageOffset)]);
    if (generation.current === token) { setSelected(updated); setMessages(history.items); setDraftRefresh(value => value + 1); }
  };
  useEffect(() => {
    if (!canSend) { setCapabilities([]); return; }
    let active = true;
    void ai.capabilities().then(result => { if (active) setCapabilities(result.items); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [canSend]);
  useEffect(() => {
    let active = true;
    void Promise.all([ai.settings(), ai.preferences(), ai.usage()]).then(([settings, context, totals]) => {
      if (!active) return;
      setFeatures(settings); setUsage(totals);
      setPreferences({ language: context.items.find(item => item.preference === "language")?.value || "",
        instructions: context.items.find(item => item.preference === "instructions")?.value || "" });
    }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; generation.current++; };
  }, []);
  useEffect(() => {
    let active = true;
    void ai.conversations(search, archived, offset).then(result => { if (active) setConversations(result.items); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [search, archived, offset]);
  useEffect(() => {
    if (!selected) return;
    const token = ++generation.current;
    setLoadingMessages(true); setMessages([]);
    void ai.messages(selected.id, messageOffset).then(result => { if (generation.current === token) setMessages(result.items); })
      .catch(failure => { if (generation.current === token) setError(String(failure)); })
      .finally(() => { if (generation.current === token) setLoadingMessages(false); });
    return () => { generation.current++; };
  }, [selected?.id, messageOffset]);
  useEffect(() => { if (!messageOffset) messageEnd.current?.scrollIntoView({ block: "nearest" }); }, [messages]);

  const saveTitle = async (): Promise<boolean> => {
    const conversation = currentConversation.current, value = currentTitle.current.trim();
    if (!conversation || value === conversation.title) return true;
    if (!value) { setTitleError("Enter a conversation title."); return false; }
    if (titleRequest.current) return false;
    titleRequest.current = true; setTitleSaving(true); setTitleError("");
    try {
      const updated = await ai.update(conversation, { title: value });
      if (currentConversation.current?.id === conversation.id) {
        currentConversation.current = updated; setSelected(updated);
        if (currentTitle.current.trim() === value) { currentTitle.current = value; setTitle(value); }
      }
      setConversations(previous => previous.map(item => item.id === updated.id ? updated : item));
      return true;
    } catch (failure) {
      setTitleError("Title not saved. " + String(failure));
      try {
        const latest = await ai.conversation(conversation.id);
        if (currentConversation.current?.id === conversation.id) { currentConversation.current = latest; setSelected(latest); }
      } catch (refreshFailure) { setTitleError("Title not saved. " + String(failure) + " " + String(refreshFailure)); }
      return false;
    } finally { titleRequest.current = false; setTitleSaving(false); }
  };
  useEffect(() => {
    if (!selected || viewer || busy || titleSaving || titleError || !title.trim() || title.trim() === selected.title) return;
    const timer = window.setTimeout(() => void saveTitle(), 600);
    return () => window.clearTimeout(timer);
  }, [selected?.id, selected?.title, title, viewer, busy, titleSaving, titleError]);

  const select = (conversation: Conversation) => {
    generation.current++; setSelected(conversation); setTitle(conversation.title); setText("");
    currentConversation.current = conversation; currentTitle.current = conversation.title;
    setSubmission(null); setAttachments([]); setMessageOffset(0); setNotice(""); setError(""); setTitleError(""); setHistoryOpen(false);
  };
  const choose = async (conversation: Conversation) => { if (await saveTitle()) select(conversation); };
  const create = async () => {
    if (!(await saveTitle())) return;
    setBusy(true); setError("");
    try {
      const conversation = await ai.create();
      select(conversation); setArchived(false); setSearch(""); setOffset(0);
      setConversations(previous => [conversation, ...previous.filter(item => item.id !== conversation.id)].slice(0, 30));
    }
    catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  const changeConversation = async (changes: { title?: string; status?: "active" | "archived" }) => {
    if (!selected) return;
    if (!(await saveTitle())) return;
    setBusy(true); setError("");
    try { const updated = await ai.update(currentConversation.current || selected, changes); setSelected(updated); setTitle(updated.title); await refreshHistory(); }
    catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!selected || !window.confirm("Delete this private conversation and its message content? Usage and audit metadata remain. No business records will be deleted.")) return;
    setBusy(true); setError("");
    try { await ai.remove(selected); generation.current++; setSelected(null); setMessages([]); setSubmission(null); await refreshHistory(); }
    catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !canSend || (!text.trim() && !submission)) return;
    if (!(await saveTitle())) return;
    const token = generation.current;
    const request = submission || { id: selected.id, content: text.trim(), key: crypto.randomUUID(), attachments: attachments.map(file => file.id) };
    setSubmission(request); setBusy(true); setError(""); setNotice("");
    try {
      await ai.send(request.id, request.content, request.key, request.attachments);
      if (token !== generation.current) return;
      setSubmission(null); setText(""); setAttachments([]);
      const [updated, history, totals, settings] = await Promise.all([ai.conversation(request.id), ai.messages(request.id), ai.usage(), ai.settings()]);
      if (token !== generation.current) return;
      setSelected(updated); setMessageOffset(0); setMessages(history.items); setUsage(totals); setFeatures(settings);
      setDraftRefresh(value => value + 1);
      await refreshHistory();
    } catch (failure) {
      if (token === generation.current) setError(String(failure) + " Refresh to inspect saved messages, or retry the same reference below. No automatic resend occurs.");
    } finally { setBusy(false); }
  };
  const refresh = async () => {
    setBusy(true); setError("");
    try {
      if (selected) await refreshConversation(selected);
      const [settings, totals] = await Promise.all([ai.settings(), ai.usage()]);
      setFeatures(settings); setUsage(totals); await refreshHistory();
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  const savePreferences = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      for (const key of ["language", "instructions"] as const) {
        if (preferences[key].trim()) await ai.preference(key, preferences[key].trim());
        else await ai.deletePreference(key);
      }
      setNotice("Private preferences saved. Blank preferences were removed.");
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  const upload = async (file: File) => {
    if (!selected || attachments.length >= 2) return;
    if (file.size > 2 * 1024 * 1024) { setError("Choose a file no larger than 2 MB."); return; }
    setBusy(true); setError("");
    try {
      const data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error("File could not be read."));
        reader.onload = () => typeof reader.result === "string" ? resolve(reader.result.split(",")[1]) : reject(new Error("Invalid file."));
        reader.readAsDataURL(file);
      });
      const uploaded = await ai.upload(selected.id, file.name, file.type || (file.name.toLowerCase().endsWith(".txt") ? "text/plain" : "application/octet-stream"), data);
      setAttachments(previous => [...previous, uploaded]);
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };

  return <main className="ops-page ai-page"><PortalHomeLink />
    <div className="ai-toolbar"><h1>Assistant</h1><div className="shop-actions">
      <button disabled={busy || titleSaving} aria-expanded={historyOpen} aria-controls="ai-history" onClick={() => setHistoryOpen(!historyOpen)}>Conversations</button>
      <button disabled={busy || titleSaving || viewer} onClick={() => void create()}>New chat</button></div></div>
    <details className="ai-help"><summary>Privacy, preferences & available tools</summary>
    <p className="ops-copy-note">Private assistant with platform-approved, permission-scoped business lookups.
      Operations need separate review, approval and submission. Cancellation and deletion are separate, high-impact operations.
      Chat sends your messages, recent conversation (including earlier lookup results), saved preferences and basic company context to OpenAI.
      Do not share passwords or unnecessary sensitive information.</p>
    {canSend ? <details><summary>Available business lookups ({capabilities.length})</summary>
      {capabilities.length ? <ul>{capabilities.map(item => <li key={item.key}><strong>{item.key}</strong>: {item.description}</li>)}</ul>
        : <p>No business lookups are permitted. Ask the platform administrator to review and enable individual capabilities.</p>}
      <p>Results are bounded partial matches, not complete catalogues or company financial totals.
        Financial lookups support only their documented date/status filters. Account and borrowing ledgers require unrestricted store access.
        Narrow your question when there are more matches.</p>
    </details> : null}
    <form className="ops-form" onSubmit={savePreferences}>
      <label>Preferred language<input maxLength={500} disabled={viewer || busy} value={preferences.language} onChange={event => setPreferences({ ...preferences, language: event.target.value })} /></label>
      <label>Workflow / wording preferences<textarea rows={3} maxLength={500} disabled={viewer || busy} value={preferences.instructions} onChange={event => setPreferences({ ...preferences, instructions: event.target.value })} /></label>
      <button disabled={busy || viewer}>Save private preferences</button>
    </form>
    {usage ? <section className="ai-usage"><h3>Usage</h3><p>{usage.period}: {usage.personal.requests} requests · {usage.personal.tokens} tokens · estimated {usage.currency} {Number(usage.personal.cost).toFixed(4)}</p>
      {usage.tenant ? <p>Tenant: {usage.tenant.requests} requests · {usage.tenant.tokens} tokens · estimated {usage.currency} {Number(usage.tenant.cost).toFixed(4)}</p> : null}
      <p>{usage.note}</p></section> : null}</details>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {notice ? <FloatingAlert tone="success">{notice}</FloatingAlert> : null}
    {!features ? <p>Loading AI availability...</p> : !features.ai.effective_enabled ? <section className="ops-card" role="status">
      <p>{featureExplanation(features.ai)}</p><p>Saved history remains accessible.</p>
      {auth.user?.role === "owner" || auth.user?.role === "admin" ? <Link to="/portal/company#portal-settings">Company AI settings</Link> : null}
      {features.support_url ? <p><a href={features.support_url}>Contact platform</a></p> : null}
    </section> : null}
    {viewer ? <p>Read-only members can view their own history but cannot create conversations or send messages.</p> : null}
    <div className={`ai-workspace${historyOpen ? " ai-history-open" : ""}`}>
      <aside id="ai-history" className="ops-card ai-sidebar"><h2>Conversations</h2>
        <label>Search titles<input maxLength={120} disabled={busy} value={search} onChange={event => { setSearch(event.target.value); setOffset(0); }} /></label>
        <label className="ops-toggle"><input type="checkbox" disabled={busy} checked={archived} onChange={event => { setArchived(event.target.checked); setOffset(0); }} />Archived history</label>
        <nav aria-label="Private conversation history">{conversations.map(conversation =>
          <button type="button" key={conversation.id} disabled={busy || titleSaving} aria-current={selected?.id === conversation.id ? "page" : undefined} onClick={() => void choose(conversation)}>{conversation.title}</button>)}</nav>
        {!conversations.length ? <p>No conversations in this view.</p> : null}
        <div className="shop-actions"><button disabled={busy || !offset} onClick={() => setOffset(Math.max(0, offset - 30))}>Previous</button>
          <button disabled={busy || conversations.length < 30} onClick={() => setOffset(offset + 30)}>Next</button></div>
      </aside>
      <section className="ops-card ai-chat" aria-label="Conversation">
        {!selected ? <p>Select a conversation or start a new one.</p> : <>
          <header className="ai-chat-header"><label><span className="ai-sr-only">Conversation title</span><input maxLength={120} disabled={busy || viewer} value={title}
            onChange={event => { setTitle(event.target.value); currentTitle.current = event.target.value; setTitleError(""); }}
            onBlur={() => { if (!busy && !titleRequest.current && !viewer) void saveTitle(); }} /></label>
            <span role="status" className="social-caption">{titleSaving ? "Saving title..." : titleError || (title.trim() === selected.title ? "Saved" : "Unsaved title")}</span>
            {titleError ? <button disabled={titleSaving || busy} onClick={() => void saveTitle()}>Retry title save</button> : null}
            <details><summary>Conversation options</summary><div className="shop-actions">
              <button disabled={busy || titleSaving || viewer} onClick={() => void changeConversation({ status: selected.status === "active" ? "archived" : "active" })}>{selected.status === "active" ? "Archive" : "Restore"}</button>
              <button disabled={busy || titleSaving || viewer} onClick={() => void remove()}>Delete conversation</button>
              <button disabled={busy || titleSaving} onClick={() => void refresh()}>Refresh saved outcome</button></div>
              <p className="social-caption">Private to you. Content expires {new Date(selected.expires_at).toLocaleDateString()}.</p></details>
          </header>
          {messageOffset || messages.length >= 50 ? <div className="shop-actions"><button disabled={busy || loadingMessages || messages.length < 50} onClick={() => setMessageOffset(messageOffset + 50)}>Older messages</button>
            <button disabled={busy || loadingMessages || !messageOffset} onClick={() => setMessageOffset(Math.max(0, messageOffset - 50))}>Newer messages</button></div> : null}
          <div className="ai-message-list" aria-live="polite">
            {loadingMessages ? <p>Loading private messages...</p> : !messages.length ? <p>Describe what you need help with.</p> : messages.map(message =>
              <article key={message.id} aria-label={message.role === "user" ? "Your message" : "Assistant reply"} className={`ai-message ai-message-${message.role}`}>
                <p>{message.content}</p>{messageStatus(message) ? <p className="ai-message-status" role="status">{messageStatus(message)}</p> : null}</article>)}
            {busy && submission ? <p role="status">Waiting for a reply. Your message reference is preserved for recovery.</p> : null}
            <div ref={messageEnd} />
          </div>
          <form className="ops-form ai-message-form" onSubmit={send}>
            <label><span className="ai-sr-only">Message</span><textarea placeholder="Ask about your business or prepare an operation..." rows={3} maxLength={4000}
              disabled={busy || !canSend || selected.status !== "active" || !!submission} value={submission?.content ?? text} onChange={event => setText(event.target.value)} /></label>
            {attachments.map(file => <div key={file.id} className="shop-actions"><span>{file.file_name}</span>
              <button type="button" disabled={busy || !!submission} onClick={() => {
                setBusy(true); void ai.removeAttachment(file.id).then(() => setAttachments(previous => previous.filter(item => item.id !== file.id)))
                  .catch(failure => setError(String(failure))).finally(() => setBusy(false));
              }}>Remove file</button></div>)}
            {features?.document_inputs_enabled ? <label>Attach text PDF, .txt or image (2 MB; up to two files)
              <input type="file" accept=".txt,.pdf,.png,.jpg,.jpeg,.webp" disabled={busy || !canSend || !!submission || attachments.length >= 2 || selected.status !== "active"}
                onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload(file); }} /></label> : null}
            {attachments.length ? <p>Only Send processes these private files with OpenAI; uploading does not make a paid call. Images are resized for economical reading. Review extracted figures before posting.</p> : null}
            {features?.voice_inputs_enabled && canSend && selected.status === "active" ? <AIVoiceInput key={selected.id}
              conversationId={selected.id} disabled={operationBusy || !!submission} onBusy={setVoiceBusy}
              onTranscript={transcript => {
                const combined = [text.trim(), transcript].filter(Boolean).join("\n");
                if (combined.length > 4000) { setError("Message plus transcript exceeds 4,000 characters. Shorten the message or transcript first."); return false; }
                setText(combined); setNotice("Voice text added. Review it, then Send when ready."); return true;
              }} /> : null}
            <div className="shop-actions"><button className="btn" disabled={busy || !canSend || selected.status !== "active" || (!text.trim() && !submission)}>
              {busy ? "Processing..." : submission ? "Retry same message reference" : "Send message"}</button>
              {submission ? <button type="button" disabled={busy} onClick={() => { setSubmission(null); setText(""); setNotice("Local retry cleared. The saved provider outcome and usage reservation are not changed."); }}>Clear local retry</button> : null}
            </div>
          </form>
          <details className="ai-operations"><summary>Operations to review</summary>
            <AIDrafts key={selected.id} conversationId={selected.id} refreshKey={draftRefresh}
              writable={!!canSend && selected.status === "active" && !busy && !titleSaving} aiEnabled={!!canSend} /></details>
        </>}
      </section>
    </div>
  </main>;
}
