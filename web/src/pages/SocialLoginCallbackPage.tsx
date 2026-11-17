import { FloatingAlert } from "../components/Notifications";
import { useEffect, useState } from "react";
import type { Provider } from "@supabase/supabase-js";
import type { FederationConfig } from "../features/shopperFederation";
import { tenantFetch } from "../features/tenantTransport";

let completion: Promise<void> | undefined;

async function completeLogin() {
  const params = new URLSearchParams(window.location.search);
  const nonce = params.get("nonce") || "";
  const provider = params.get("provider") || "";
  const returnOrigin = params.get("return_origin") || "";
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(nonce)) throw new Error("Invalid social login request. Start again from the login page.");
  const channel = new BroadcastChannel(`tenali-social-${nonce}`);
  const storageKey = `tenali-social-${nonce}`;
  const relayStorageKey = storageKey + "-relay";
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  if (fragment.has("relay_id") && fragment.has("relay_key")) {
    sessionStorage.setItem(relayStorageKey, JSON.stringify({
      id: fragment.get("relay_id"), key: fragment.get("relay_key"),
    }));
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  const relay: { id: string; key: string } | null = JSON.parse(sessionStorage.getItem(relayStorageKey) || "null");
  let redirecting = false;
  let returnVerified = false;
  const deliver = async (data: object) => {
    if (returnOrigin) {
      if (!returnVerified) return;
      if (!relay) throw new Error("Social login state is missing. Start again from your storefront.");
      const response = await tenantFetch(`/api/auth/social-relays/${relay.id}/complete`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: relay.key, origin: returnOrigin, result: data }),
      });
      if (!response.ok) throw new Error("Unable to return social login to your storefront. Start again.");
    } else channel.postMessage(data);
  };
  try {
    const response = await tenantFetch("/api/auth/social-config");
    if (!response.ok) throw new Error("Unable to load social login configuration.");
    const config: FederationConfig = await response.json();
    if (!config.enabled || !config.providers.includes(provider)) throw new Error("This social provider is disabled or not configured.");
    if (returnOrigin) {
      const allowed = await tenantFetch(`/api/auth/social-return-origin?${new URLSearchParams({ origin: returnOrigin })}`);
      if (!allowed.ok) throw new Error("The social login return domain is not authorized.");
      returnVerified = true;
    }
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
      sessionStorage.setItem(storageKey + "-flow", JSON.stringify({ provider, returnOrigin }));
      const redirect = new URL("/social-login", window.location.origin);
      redirect.searchParams.set("nonce", nonce);
      redirect.searchParams.set("provider", provider);
      if (returnOrigin) redirect.searchParams.set("return_origin", returnOrigin);
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
    if (sessionStorage.getItem(storageKey + "-flow") !== JSON.stringify({ provider, returnOrigin })) throw new Error("Social login state is missing. Start again from the login page.");
    const { data, error: exchangeError } = await client.auth.exchangeCodeForSession(code);
    if (exchangeError) throw exchangeError;
    if (!data.session) throw new Error("Supabase did not return a session.");
    window.history.replaceState(null, "", "/social-login");
    await deliver({ nonce, accessToken: data.session.access_token,
      email: data.session.user.email || "", expiresAt: data.session.expires_at });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to complete social login.";
    await deliver({ nonce, error: message });
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
