import { Fragment } from "react";
import { Link } from "react-router-dom";
import { ledgerRow, messageSections } from "../features/aiMessages";
import { portalEntries } from "../features/portalNavigation";

const paths = new Set(portalEntries.map(entry => entry.path));

function LinkedText({ content }: { content: string }) {
  const matches = [...content.matchAll(/\[([^\]\n]+)\]\((\/portal(?:\/[a-z-]+)*)\)/g)];
  let offset = 0;
  return <>{matches.map(match => {
    const before = content.slice(offset, match.index);
    offset = match.index! + match[0].length;
    return <Fragment key={match.index}>{before}{paths.has(match[2]) ?
      <Link to={match[2]}>{match[1]}</Link> : match[0]}</Fragment>;
  })}{content.slice(offset)}</>;
}

export function AssistantMessage({ content }: { content: string }) {
  return <div className="ai-answer">{messageSections(content).map((section, index) =>
    section.kind === "text" ? <p key={index}><LinkedText content={section.content} /></p> :
      <section className="ai-record-result" key={index} aria-label={`Tenali records: ${section.title}`}>
        <div className="ai-record-heading"><span>From your Tenali records</span><strong>{section.title}</strong></div>
        {section.total ? <div className="ai-record-total">{section.total}</div> : null}
        {section.notes.map((note, noteIndex) => <p className="ai-record-note" key={noteIndex}><LinkedText content={note} /></p>)}
        {section.rows.length ? <details className="ai-record-details"><summary>View {section.rows.length} {section.rows.length === 1 ? "record" : "records"}</summary>
          <ul className="ai-record-list">{section.rows.map((row, rowIndex) => {
            const transaction = ledgerRow(section.title, row);
            return transaction ? <li className="ai-ledger-item" key={rowIndex}>
              <div className="ai-ledger-heading"><strong>{transaction.amount}</strong><span>{transaction.direction}</span></div>
              <dl>{transaction.fields.map(field => <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>
            </li> : <li key={rowIndex}><LinkedText content={row} /></li>;
          })}</ul>
        </details> : null}
      </section>
  )}</div>;
}
