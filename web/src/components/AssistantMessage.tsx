import { Fragment } from "react";
import { Link } from "react-router-dom";
import { portalEntries } from "../features/portalNavigation";

const paths = new Set(portalEntries.map(entry => entry.path));

export function AssistantMessage({ content }: { content: string }) {
  const matches = [...content.matchAll(/\[([^\]\n]+)\]\((\/portal(?:\/[a-z-]+)*)\)/g)];
  let offset = 0;
  return <>{matches.map(match => {
    const before = content.slice(offset, match.index);
    offset = match.index! + match[0].length;
    return <Fragment key={match.index}>{before}{paths.has(match[2]) ?
      <Link to={match[2]}>{match[1]}</Link> : match[0]}</Fragment>;
  })}{content.slice(offset)}</>;
}
