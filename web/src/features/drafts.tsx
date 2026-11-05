import { createContext, Dispatch, ReactNode, SetStateAction, useCallback, useContext, useRef, useState } from "react";

const Context = createContext<Map<string, unknown> | null>(null);

export function useClearDrafts() {
  const drafts = useContext(Context);
  if (!drafts) throw new Error("WorkspaceDraftProvider missing");
  return useCallback((prefix: string) => {
    for (const key of drafts.keys()) if (key.startsWith(prefix)) drafts.delete(key);
  }, [drafts]);
}

export function WorkspaceDraftProvider({ children }: { children: ReactNode }) {
  const drafts = useRef(new Map<string, unknown>());
  return <Context.Provider value={drafts.current}>{children}</Context.Provider>;
}

export function useDraftState<T>(key: string, initial: T | (() => T)): [T, Dispatch<SetStateAction<T>>] {
  const drafts = useContext(Context);
  if (!drafts) throw new Error("WorkspaceDraftProvider missing");
  const read = () => {
    if (drafts.has(key)) return drafts.get(key) as T;
    const first = typeof initial === "function" ? (initial as () => T)() : initial;
    drafts.set(key, first);
    return first;
  };
  const [snapshot, setSnapshot] = useState(() => ({ key, value: read() }));
  let value = snapshot.value;
  if (snapshot.key !== key) {
    value = read();
    setSnapshot({ key, value });
  }
  const update = useCallback<Dispatch<SetStateAction<T>>>((action) => {
    const previous = drafts.get(key) as T;
    const next = typeof action === "function" ? (action as (value: T) => T)(previous) : action;
    drafts.set(key, next);
    setSnapshot({ key, value: next });
  }, [drafts, key]);
  return [value, update];
}
