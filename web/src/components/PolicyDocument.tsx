import type { PolicyContent } from "../features/policies";

export function PolicyDocument({ content }: { content: PolicyContent }) {
  return <article className="policy-document">
    <h1>{content.title}</h1>
    <dl className="policy-business-details">
      <dt>Business/operator</dt><dd>{content.business_name || "Not completed"}</dd>
      <dt>Business address</dt><dd>{content.address || "Not completed"}</dd>
      <dt>Support and privacy contact</dt><dd>{content.contact_email ? <a href={`mailto:${encodeURIComponent(content.contact_email)}`}>{content.contact_email}</a> : "Not completed"}</dd>
      <dt>Jurisdiction</dt><dd>{content.jurisdiction || "Not completed"} (subject to mandatory law)</dd>
      <dt>Currency</dt><dd>{content.currency}</dd>
    </dl>
    <div className="policy-body">{content.body}</div>
  </article>;
}
