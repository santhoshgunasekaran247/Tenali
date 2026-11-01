import { PROVIDER_LABELS } from "../features/shopperFederation";

export function SocialProviderButtons({ providers, busy, onLogin }: { providers: string[]; busy: boolean; onLogin: (provider: string) => void }) {
  return <div className="social-provider-list" aria-label="Social sign-in options">
    {providers.map(provider => <button key={provider} type="button" className="social-provider-button" disabled={busy} onClick={() => onLogin(provider)}>
      {provider === "google" ? <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-2 3.02v2.51h3.24c1.9-1.75 2.98-4.33 2.98-7.36Z" />
        <path fill="#34A853" d="M12 22c2.7 0 4.96-.9 6.62-2.41l-3.24-2.51c-.9.6-2.05.96-3.38.96-2.6 0-4.8-1.76-5.59-4.12H3.07v2.59A10 10 0 0 0 12 22Z" />
        <path fill="#FBBC05" d="M6.41 13.92a6 6 0 0 1 0-3.84V7.49H3.07a10 10 0 0 0 0 9.02l3.34-2.59Z" />
        <path fill="#EA4335" d="M12 5.96c1.47 0 2.79.51 3.83 1.51l2.87-2.87A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.93 5.49l3.34 2.59C7.2 7.72 9.4 5.96 12 5.96Z" />
      </svg> : <span className={`social-provider-mark social-provider-${provider.replace(":", "-")}`} aria-hidden="true">{provider === "facebook" ? "f" : provider === "custom:yahoo" ? "y!" : (PROVIDER_LABELS[provider] || provider).slice(0, 1)}</span>}
      <span>Continue with {PROVIDER_LABELS[provider] || provider}</span>
    </button>)}
    {busy ? <p className="social-caption" role="status">Connecting securely. Complete sign-in in the popup.</p> : null}
  </div>;
}
