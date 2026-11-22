import { useId } from "react";

export function CursorPagination({ size, page, hasNext, busy, onSize, onPrevious, onNext }: {
  size: number; page: number; hasNext: boolean; busy: boolean;
  onSize: (size: number) => void; onPrevious: () => void; onNext: () => void;
}) {
  const id = useId();
  return <div className="table-pagination" role="group" aria-label="Record pagination">
    <label htmlFor={id}>Rows per page</label>
    <select id={id} disabled={busy} value={size} onChange={event => onSize(Number(event.target.value))}>
      {[10, 25, 50, 100].map(value => <option value={value} key={value}>{value}</option>)}
    </select>
    <span role="status">Page {page + 1}</span>
    <button type="button" disabled={busy || page === 0} onClick={onPrevious}>Previous</button>
    <button type="button" disabled={busy || !hasNext} onClick={onNext}>Next</button>
  </div>;
}
