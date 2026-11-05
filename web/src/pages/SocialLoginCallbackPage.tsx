import { FloatingAlert } from "../components/Notifications";
import { useEffect, useState } from "react";
import type { Provider } from "@supabase/supabase-js";
import type { FederationConfig } from "../features/shopperFederation";

let completion: Promise<void> | undefined;

async function completeLogin() {
  const params = new URLSearchParams(window.location.search);
  const nonce = params.get("nonce") || "";
  const provider = params.get("provider") || "";
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(nonce)) throw new Error("Invalid social login request. Start again from the login page.");
  const channel = new BroadcastChannel(`tenali-social-${nonce}`);
  const storageKey = `tenali-social-${nonce}`;
  let redirecting = false;
  try {
    const response = await fetch("/api/auth/social-config", { credentials: "same-origin" });
    if (!response.ok) throw new Error("Unable to load social login configuration.");
    const config: FederationConfig = await response.json();
    if (!config.enabled || !config.providers.includes(provider)) throw new Error("This social provider is disabled or not configured.");
    const error = params.get("error_description") || params.get("error");
    if (error) throw new Error(error);
    const { createClient } = await import("@supabase/supabase-js");
    const memory = new Map<string, string>();
    // Only PKCE must survive the provider redirect; sessions stay in memory.
    const storage = {
      getItem: (key: string) => key.endsWith("-code-verifier") ? sessionStorage.getItem(key) : memory.get(key) ?? null,
      setItem: (key: string, value: string) => {
        if (key.endsWith("-code-verifier")) sessionStorage.setItem(key, value);
        else memory.set(key, value);
      },
      removeItem: (key: string) => { sessionStorage.removeItem(key); memory.delete(key); },
    };
    const client = createClient(config.supabase.url, config.supabase.publicKey, {
      auth: { flowType: "pkce", storage, storageKey, persistSession: true,
        autoRefreshToken: false, detectSessionInUrl: false },
    });
    const code = params.get("code");
    if (!code) {
      sessionStorage.setItem(storageKey + "-flow", provider);
      const redirect = new URL("/social-login", window.location.origin);
      redirect.searchParams.set("nonce", nonce);
      redirect.searchParams.set("provider", provider);
      const { data, error: startError } = await client.auth.signInWithOAuth({
        provider: provider as Provider,
        options: { redirectTo: redirect.toString(), skipBrowserRedirect: true,
          ...(provider === "google" ? { queryParams: { prompt: "select_account" } } : {}) },
      });
      if (startError) throw startError;
      if (!data.url) throw new Error("Supabase did not return a login URL.");
      window.location.replace(data.url);
      redirecting = true;
      return;
    }
    if (sessionStorage.getItem(storageKey + "-flow") !== provider) throw new Error("Social login state is missing. Start again from the login page.");
    const { data, error: exchangeError } = await client.auth.exchangeCodeForSession(code);
    if (exchangeError) throw exchangeError;
    if (!data.session) throw new Error("Supabase did not return a session.");
    window.history.replaceState(null, "", "/social-login");
    channel.postMessage({ nonce, accessToken: data.session.access_token,
      email: data.session.user.email || "", expiresAt: data.session.expires_at });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to complete social login.";
    channel.postMessage({ nonce, error: message });
    throw new Error(message);
  } finally {
    if (!redirecting) {
      for (let index = sessionStorage.length - 1; index >= 0; index--) {
        const key = sessionStorage.key(index);
        if (key === storageKey || key?.startsWith(storageKey + "-")) sessionStorage.removeItem(key);
      }
      window.history.replaceState(null, "", "/social-login");
    }
    channel.close();
  }
}

export function SocialLoginCallbackPage() {
  const [message, setMessage] = useState("Connecting to Supabase social login...");
  useEffect(() => {
    completion ??= completeLogin();
    void completion.then(() => setMessage("Login complete. Return to the original window."))
      .catch(error => setMessage(error instanceof Error ? error.message : "Social login failed."));
  }, []);
  return <main className="access-panel"><h1>Social login</h1><FloatingAlert tone="success">{message}</FloatingAlert></main>;
}
