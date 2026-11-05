import { FloatingAlert } from "./Notifications";
import { FormEvent, useEffect, useState } from "react";
import { accountRequest, type Shopper } from "../features/shop";
import type { FederationConfig, SocialUser } from "../features/shopperFederation";
import { socialLogin } from "../features/shopperFederation";
import { SocialProviderButtons } from "./SocialProviderButtons";
import { PolicyNotice } from "./PolicyLinks";

type ProfileNeeded = { needs_profile: true; email: string; display_name: string };

export function FederatedShopperLogin({ onSignedIn }: { onSignedIn: (shopper: Shopper) => void }) {
  const [config, setConfig] = useState<FederationConfig | null>(null);
  const [social, setSocial] = useState<SocialUser | null>(null);
  const [form, setForm] = useState({ display_name: "", phone: "", email: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    accountRequest<FederationConfig>("/auth-config").then(result => { if (active) setConfig(result); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, []);
  const exchange = async (user: SocialUser, profile?: { display_name: string; phone: string }) => {
    const result = await accountRequest<Shopper | ProfileNeeded>("/federated", {
      method: "POST", body: JSON.stringify({ id_token: await user.getIdToken(), ...profile }),
    });
    if ("needs_profile" in result) {
      setSocial(user);
      setForm({ display_name: result.display_name, email: result.email, phone: "" });
    } else onSignedIn(result);
  };
  const login = async (provider: string) => {
    if (!config) return;
    setBusy(true); setError("");
    try {
      await exchange(await socialLogin(config, provider));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to sign in."); }
    finally { setBusy(false); }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!social) return;
    setBusy(true); setError("");
    try { await exchange(social, { display_name: form.display_name, phone: form.phone }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to create account."); }
    finally { setBusy(false); }
  };
  return <section className="access-panel">
    <PolicyNotice scope="tenant" />
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {!config ? <p>Loading sign-in options...</p> : !config.enabled ? <p role="status">Social sign-in is not configured yet. Please contact the store. Email/password registration is disabled.</p> :
      social ? <form className="ops-form" onSubmit={submit}><fieldset disabled={busy} className="access-fields">
        <legend>Complete your shopper profile</legend>
        <label>Email from your login provider<input type="email" value={form.email} readOnly /></label>
        <label>Your name<input required autoComplete="name" maxLength={150} value={form.display_name} onChange={event => setForm({ ...form, display_name: event.target.value })} /></label>
        <label>Phone number<input required type="tel" autoComplete="tel" maxLength={40} value={form.phone} onChange={event => setForm({ ...form, phone: event.target.value })} placeholder="Mobile number or +country code" /></label>
        <p>No OTP is sent. Your phone is unverified. Online and counter customer records stay separate.</p>
        <button className="btn" disabled={busy}>{busy ? "Saving..." : "Create shopper account"}</button>
        <button className="ops-link-btn" type="button" disabled={busy} onClick={() => setSocial(null)}>Use a different social account</button>
      </fieldset></form> : <>
        <p>Sign in or create an account using your social account. No store password is needed.</p>
        <SocialProviderButtons providers={config.providers} busy={busy} onLogin={provider => void login(provider)} />
      </>}
  </section>;
}
