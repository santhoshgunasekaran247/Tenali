export type FederationConfig = { enabled: boolean; supabase: { url: string; publicKey: string }; providers: string[]; callbackOrigin?: string };
export type SocialUser = { email: string; getIdToken: () => Promise<string> };
export const PROVIDER_LABELS: Record<string, string> = { google: "Google", facebook: "Facebook", "custom:yahoo": "Yahoo", azure: "Microsoft", apple: "Apple" };
const pending = new Set<() => void>();

async function socialLoginError(response: Response, fallback: string): Promise<Error> {
  const text = await response.text();
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    return new Error(`${fallback} (HTTP ${response.status})`);
  }
  if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
    return new Error(body.detail);
  }
  return new Error(`${fallback} (HTTP ${response.status})`);
}

export async function socialLogin(config: FederationConfig, provider: string): Promise<SocialUser> {
  if (!config.enabled || !config.providers.includes(provider)) throw new Error("This login provider is not configured.");
  const nonce = crypto.randomUUID();
  const channel = new BroadcastChannel(`tenali-social-${nonce}`);
  const callbackOrigin = tenantApiOrigin() ? config.callbackOrigin || window.location.origin : window.location.origin;
  const url = new URL("/social-login", callbackOrigin);
  const remote = url.origin !== window.location.origin;
  url.searchParams.set("nonce", nonce);
  url.searchParams.set("provider", provider);
  if (remote) url.searchParams.set("return_origin", window.location.origin);
  const popup = window.open(remote ? "about:blank" : url, `tenali-social-${nonce}`, "popup,width=520,height=720");
  if (!popup) { channel.close(); throw new Error("Allow popups for this site, then try social login again."); }
  let relay: { id: string; key: string } | undefined;
  if (remote) {
    try {
      const response = await tenantFetch("/api/auth/social-relays", { method: "POST" });
      if (!response.ok) throw await socialLoginError(response, "Unable to start secure social login.");
      relay = await response.json() as { id: string; key: string };
      url.hash = new URLSearchParams({ relay_id: relay.id, relay_key: relay.key }).toString();
      popup.location.href = url.toString();
    } catch (error) { channel.close(); popup.close(); throw error; }
  }
  return new Promise((resolve, reject) => {
    let finished = false;
    let polling = false;
    let interval: number | undefined;
    const cleanup = () => { finished = true; clearTimeout(timeout); window.clearInterval(interval); channel.close(); popup.close(); pending.delete(cancel); };
    const cancel = () => { cleanup(); reject(new Error("Social login was cancelled.")); };
    const timeout = window.setTimeout(() => { cleanup(); reject(new Error("Social login timed out or the login window was closed. Please try again.")); }, 180_000);
    pending.add(cancel);
    const accept = (data: { nonce?: string; error?: string; accessToken?: string; email?: string; expiresAt?: number }) => {
      if (finished || data?.nonce !== nonce) return;
      if (typeof data.error === "string") { cleanup(); reject(new Error(data.error)); return; }
      if (typeof data.accessToken !== "string" || typeof data.email !== "string" || typeof data.expiresAt !== "number") return;
      const { email, accessToken, expiresAt } = data;
      cleanup();
      resolve({ email, getIdToken: async () => {
        if (Date.now() >= expiresAt * 1000) throw new Error("Your social login expired. Sign in again.");
        return accessToken;
      } });
    };
    if (relay) {
      const ticket = relay;
      interval = window.setInterval(() => {
        if (finished || polling) return;
        polling = true;
        void tenantFetch(`/api/auth/social-relays/${ticket.id}/poll`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: ticket.key }),
        }).then(async response => {
          if (!response.ok) throw await socialLoginError(response, "Social login expired or could not be completed. Start again.");
          const body = await response.json();
          if (!body.pending) accept({ ...body.result, nonce });
        }).catch(error => {
          if (!finished) { cleanup(); reject(error); }
        }).finally(() => { polling = false; });
      }, 1000);
    } else channel.onmessage = event => accept(event.data);
  });
}

export async function clearSocialLogin() {
  for (const cancel of [...pending]) cancel();
}
import { tenantApiOrigin, tenantFetch } from "./tenantTransport";
