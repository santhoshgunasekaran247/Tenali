export type FederationConfig = { enabled: boolean; supabase: { url: string; publicKey: string }; providers: string[] };
export type SocialUser = { email: string; getIdToken: () => Promise<string> };
export const PROVIDER_LABELS: Record<string, string> = { google: "Google", facebook: "Facebook", "custom:yahoo": "Yahoo", azure: "Microsoft", apple: "Apple" };
const pending = new Set<() => void>();

export async function socialLogin(config: FederationConfig, provider: string): Promise<SocialUser> {
  if (!config.enabled || !config.providers.includes(provider)) throw new Error("This login provider is not configured.");
  const nonce = crypto.randomUUID();
  const channel = new BroadcastChannel(`tenali-social-${nonce}`);
  const url = new URL("/social-login", window.location.origin);
  url.searchParams.set("nonce", nonce);
  url.searchParams.set("provider", provider);
  const popup = window.open(url, `tenali-social-${nonce}`, "popup,width=520,height=720");
  if (!popup) { channel.close(); throw new Error("Allow popups for this site, then try social login again."); }
  return new Promise((resolve, reject) => {
    const cleanup = () => { clearTimeout(timeout); channel.close(); popup.close(); pending.delete(cancel); };
    const cancel = () => { cleanup(); reject(new Error("Social login was cancelled.")); };
    const timeout = window.setTimeout(() => { cleanup(); reject(new Error("Social login timed out or the login window was closed. Please try again.")); }, 180_000);
    pending.add(cancel);
    channel.onmessage = event => {
      const data = event.data;
      if (data?.nonce !== nonce) return;
      if (typeof data.error === "string") { cleanup(); reject(new Error(data.error)); return; }
      if (typeof data.accessToken !== "string" || typeof data.email !== "string" || typeof data.expiresAt !== "number") return;
      cleanup();
      resolve({ email: data.email, getIdToken: async () => {
        if (Date.now() >= data.expiresAt * 1000) throw new Error("Your social login expired. Sign in again.");
        return data.accessToken;
      } });
    };
  });
}

export async function clearSocialLogin() {
  for (const cancel of [...pending]) cancel();
}
