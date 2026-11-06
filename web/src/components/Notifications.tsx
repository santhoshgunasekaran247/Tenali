import { createContext, ReactNode, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Notice = { id: string; tone: "success" | "error" | "workflow"; content: ReactNode };
type Notifications = { show: (notice: Notice) => void; remove: (id: string) => void };
const Context = createContext<Notifications | null>(null);
const HEADINGS: Record<Notice["tone"], string> = { success: "Done", error: "Something needs attention", workflow: "Next step" };
// Workflow guidance stays longer than a success message so there is time to read and follow it.
const AUTO_DISMISS_MS: Partial<Record<Notice["tone"], number>> = { success: 5000, workflow: 15000 };

function NoticeCard({ notice, remove }: { notice: Notice; remove: (id: string) => void }) {
  useEffect(() => {
    const delay = AUTO_DISMISS_MS[notice.tone];
    if (!delay) return;
    const timer = window.setTimeout(() => remove(notice.id), delay);
    return () => window.clearTimeout(timer);
  }, [notice, remove]);
  return <section className={`floating-notice floating-notice-${notice.tone}`} role={notice.tone === "error" ? "alert" : "status"}>
    <div><strong>{HEADINGS[notice.tone]}</strong><div>{notice.content}</div></div>
    <button type="button" className="notice-dismiss" aria-label="Dismiss notification" onClick={() => remove(notice.id)}>&times;</button>
  </section>;
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const stack = useRef<HTMLElement>(null);
  const remove = useCallback((id: string) => setNotices(previous => previous.filter(notice => notice.id !== id)), []);
  const show = useCallback((notice: Notice) => setNotices(previous => [...previous.filter(item => item.id !== notice.id), notice]), []);
  const value = useMemo(() => ({ show, remove }), [show, remove]);
  const dialogs = document.querySelectorAll<HTMLDialogElement>("dialog[open]");
  const portalHost = dialogs[dialogs.length - 1] || document.body;
  useEffect(() => {
    if (typeof stack.current?.showPopover !== "function") return;
    if (notices.length) stack.current.showPopover();
    else stack.current.hidePopover();
  }, [notices]);
  return <Context.Provider value={value}>{children}
    {createPortal(<aside ref={stack} popover="manual" className="notification-stack" aria-label="Notifications">{notices.map(notice => <NoticeCard key={notice.id} notice={notice} remove={remove} />)}</aside>, portalHost)}
  </Context.Provider>;
}

export function useNotifications(): Notifications | null {
  return useContext(Context);
}

export function FloatingAlert({ children, tone = "error" }: { children: ReactNode; tone?: Notice["tone"] }) {
  const notifications = useContext(Context);
  if (!notifications) throw new Error("NotificationProvider missing");
  const id = useId();
  const { show, remove } = notifications;
  useEffect(() => {
    show({ id, content: children, tone });
    return () => remove(id);
  }, [children, tone, id, show, remove]);
  return null;
}
