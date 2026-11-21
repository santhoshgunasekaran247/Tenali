import { Children, isValidElement, useEffect, useId, useState, type ReactNode } from "react";

type Props = { children: ReactNode };

export function PaginatedTableBody({ children }: Props) {
  const rows = Children.toArray(children);
  const placeholder = rows.length === 1 && isValidElement<{ children?: ReactNode }>(rows[0]) &&
    Children.toArray(rows[0].props.children).some(cell =>
      isValidElement<{ colSpan?: number }>(cell) && Number(cell.props.colSpan) > 1);
  const count = placeholder ? 0 : rows.length;
  const [size, setSize] = useState(10);
  const [page, setPage] = useState(0);
  const id = useId();
  const signature = rows.map(row => isValidElement(row) ? row.key : String(row)).join("|");
  useEffect(() => { setPage(0); }, [signature]);
  const lastPage = Math.max(0, Math.ceil(count / size) - 1);
  const current = Math.min(page, lastPage);
  const start = current * size;
  return <>
    <tbody>{placeholder ? rows : rows.slice(start, start + size)}</tbody>
    {count ? <tfoot><tr><td colSpan={1000}><div className="table-pagination" role="group" aria-label="Pagination for loaded rows">
      <label htmlFor={id}>Rows per page</label>
      <select id={id} value={size} onChange={event => { setSize(Number(event.target.value)); setPage(0); }}>
        {[10, 25, 50, 100].map(value => <option value={value} key={value}>{value}</option>)}
      </select>
      <span role="status">{start + 1}–{Math.min(start + size, count)} of {count} loaded rows</span>
      <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button>
      <button type="button" disabled={current >= lastPage} onClick={() => setPage(current + 1)}>Next</button>
    </div><small>Pagination covers loaded rows only; some views may have server limits.</small></td></tr></tfoot> : null}
  </>;
}
