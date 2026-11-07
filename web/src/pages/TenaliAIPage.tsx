import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ai, messageStatus, type AIUsage, type ChatMessage, type Conversation, type Preference, type ReadCapability } from "../features/ai";
import { featureExplanation } from "../features/featureControls";
import { useAuth } from "../features/auth";
import { FloatingAlert } from "../components/Notifications";
import { PortalHomeLink } from "../components/PortalHomeLink";
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
  const [busy, setBusy] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [notice, setNotice] = useState("");
  const [submission, setSubmission] = useState<{ id: string; content: string; key: string } | null>(null);
  const generation = useRef(0);
  const messageEnd = useRef<HTMLDivElement>(null);
  const viewer = auth.user?.role === "viewer";
  const canSend = features?.ai.effective_enabled && !viewer;

  const refreshHistory = async () => setConversations((await ai.conversations(search, archived, offset)).items);
  const refreshConversation = async (conversation: Conversation) => {
    const token = generation.current;
    const [updated, history] = await Promise.all([ai.conversation(conversation.id), ai.messages(conversation.id, messageOffset)]);
    if (generation.current === token) { setSelected(updated); setMessages(history.items); }
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

  const select = (conversation: Conversation) => {
    generation.current++; setSelected(conversation); setTitle(conversation.title); setText("");
    setSubmission(null); setMessageOffset(0); setNotice(""); setError("");
  };
  const create = async () => {
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
    setBusy(true); setError("");
    try { const updated = await ai.update(selected, changes); setSelected(updated); setTitle(updated.title); await refreshHistory(); }
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
    const token = generation.current;
    const request = submission || { id: selected.id, content: text.trim(), key: crypto.randomUUID() };
    setSubmission(request); setBusy(true); setError(""); setNotice("");
    try {
      await ai.send(request.id, request.content, request.key);
      if (token !== generation.current) return;
      setSubmission(null); setText("");
      const [updated, history, totals, settings] = await Promise.all([ai.conversation(request.id), ai.messages(request.id), ai.usage(), ai.settings()]);
      if (token !== generation.current) return;
      setSelected(updated); setMessageOffset(0); setMessages(history.items); setUsage(totals); setFeatures(settings);
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

  return <main className="ops-page ai-page"><PortalHomeLink /><h1>Tenali AI</h1>
    <p className="ops-copy-note">Private assistant with platform-approved, permission-scoped business lookups.
      No transaction drafts, document uploads or business execution are enabled yet.
      Chat sends your messages, recent conversation (including earlier lookup results), saved preferences and basic company context to OpenAI.
      Do not share passwords or unnecessary sensitive information.</p>
    {canSend ? <details><summary>Available business lookups ({capabilities.length})</summary>
      {capabilities.length ? <ul>{capabilities.map(item => <li key={item.key}><strong>{item.key}</strong>: {item.description}</li>)}</ul>
        : <p>No business lookups are permitted. Ask the platform administrator to review and enable individual capabilities.</p>}
      <p>Results are bounded partial matches, not complete catalogues or financial totals. Narrow your question when there are more matches.</p>
    </details> : null}
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {notice ? <FloatingAlert tone="success">{notice}</FloatingAlert> : null}
    {!features ? <p>Loading AI availability...</p> : !features.ai.effective_enabled ? <section className="ops-card" role="status">
      <p>{featureExplanation(features.ai)}</p><p>Saved history remains accessible.</p>
      {auth.user?.role === "owner" || auth.user?.role === "admin" ? <Link to="/portal/company#portal-settings">Company AI settings</Link> : null}
      {features.support_url ? <p><a href={features.support_url}>Contact platform</a></p> : null}
    </section> : null}
    {viewer ? <p>Read-only members can view their own history but cannot create conversations or send messages.</p> : null}
    <div className="ai-workspace">
      <aside className="ops-card ai-sidebar"><h2>Your conversations</h2>
        <button className="btn" type="button" disabled={busy || viewer} onClick={() => void create()}>New conversation</button>
        <label>Search titles<input maxLength={120} disabled={busy} value={search} onChange={event => { setSearch(event.target.value); setOffset(0); }} /></label>
        <label className="ops-toggle"><input type="checkbox" disabled={busy} checked={archived} onChange={event => { setArchived(event.target.checked); setOffset(0); }} />Archived history</label>
        <nav aria-label="Private conversation history">{conversations.map(conversation =>
          <button type="button" key={conversation.id} disabled={busy} aria-current={selected?.id === conversation.id ? "page" : undefined} onClick={() => select(conversation)}>{conversation.title}</button>)}</nav>
        {!conversations.length ? <p>No conversations in this view.</p> : null}
        <div className="shop-actions"><button disabled={busy || !offset} onClick={() => setOffset(Math.max(0, offset - 30))}>Previous</button>
          <button disabled={busy || conversations.length < 30} onClick={() => setOffset(offset + 30)}>Next</button></div>
        <details><summary>Private preferences</summary><form className="ops-form" onSubmit={savePreferences}>
          <label>Preferred language<input maxLength={500} disabled={viewer || busy} value={preferences.language} onChange={event => setPreferences({ ...preferences, language: event.target.value })} /></label>
          <label>Workflow / wording preferences<textarea rows={3} maxLength={500} disabled={viewer || busy} value={preferences.instructions} onChange={event => setPreferences({ ...preferences, instructions: event.target.value })} /></label>
          <p className="social-caption">Used only for your assistant. Never shared with other tenant users; these preferences cannot change permissions.</p>
          <button className="btn light" disabled={busy || viewer}>Save private preferences</button>
        </form></details>
        {usage ? <section className="ai-usage"><h3>Your usage</h3><p>{usage.period}: {usage.personal.requests} requests · {usage.personal.tokens} tokens · estimated {usage.currency} {Number(usage.personal.cost).toFixed(4)}</p>
          {usage.tenant ? <p>Tenant: {usage.tenant.requests} requests · {usage.tenant.tokens} tokens · estimated {usage.currency} {Number(usage.tenant.cost).toFixed(4)}</p> : null}
          <p className="social-caption">{usage.note}</p></section> : null}
      </aside>
      <section className="ops-card ai-chat" aria-label="Conversation">
        {!selected ? <p>Select a conversation or start a new one.</p> : <>
          <header className="ai-chat-header"><label>Conversation title<input maxLength={120} disabled={busy || viewer} value={title} onChange={event => setTitle(event.target.value)} /></label>
            <div className="shop-actions"><button disabled={busy || viewer || !title.trim() || title === selected.title} onClick={() => void changeConversation({ title: title.trim() })}>Rename</button>
              <button disabled={busy || viewer} onClick={() => void changeConversation({ status: selected.status === "active" ? "archived" : "active" })}>{selected.status === "active" ? "Archive" : "Restore"}</button>
              <button disabled={busy || viewer} onClick={() => void remove()}>Delete conversation</button>
              <button disabled={busy} onClick={() => void refresh()}>Refresh saved outcome</button></div>
            <p className="social-caption">Private to you. Content expires {new Date(selected.expires_at).toLocaleDateString()}.</p>
          </header>
          <div className="shop-actions"><button disabled={busy || loadingMessages || messages.length < 50} onClick={() => setMessageOffset(messageOffset + 50)}>Older messages</button>
            <button disabled={busy || loadingMessages || !messageOffset} onClick={() => setMessageOffset(Math.max(0, messageOffset - 50))}>Newer messages</button></div>
          <div className="ai-message-list" aria-live="polite">
            {loadingMessages ? <p>Loading private messages...</p> : !messages.length ? <p>Describe what you need help with.</p> : messages.map(message =>
              <article key={message.id} className={`ai-message ai-message-${message.role}`}><strong>{message.role === "user" ? "You" : "Tenali AI"}</strong>
                <p>{message.content}</p>{messageStatus(message) ? <p className="ai-message-status" role="status">{messageStatus(message)}</p> : null}</article>)}
            {busy && submission ? <p role="status">Waiting for a reply. Your message reference is preserved for recovery.</p> : null}
            <div ref={messageEnd} />
          </div>
          <form className="ops-form ai-message-form" onSubmit={send}>
            <label>Message<textarea rows={3} maxLength={4000} disabled={busy || !canSend || selected.status !== "active" || !!submission} value={submission?.content ?? text} onChange={event => setText(event.target.value)} /></label>
            <div className="shop-actions"><button className="btn" disabled={busy || !canSend || selected.status !== "active" || (!text.trim() && !submission)}>
              {busy ? "Processing..." : submission ? "Retry same message reference" : "Send message"}</button>
              {submission ? <button type="button" disabled={busy} onClick={() => { setSubmission(null); setText(""); setNotice("Local retry cleared. The saved provider outcome and usage reservation are not changed."); }}>Clear local retry</button> : null}
            </div>
          </form>
        </>}
      </section>
    </div>
  </main>;
}
