import { useState } from "react";
import { indiaDateKey } from "../features/workflowDates";

export type HistoryDateRange = { from: string; to: string };
export const ALL_DATES: HistoryDateRange = { from: "", to: "" };

export function HistoryDateFilter({ onChange }: { onChange: (range: HistoryDateRange) => void }) {
  const [preset, setPreset] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState("");
  const select = (value: string) => {
    setPreset(value);
    setError("");
    if (value === "custom") return;
    const today = indiaDateKey();
    const range = value === "today" ? { from: today, to: today }
      : value === "month" ? { from: `${today.slice(0, 7)}-01`, to: today } : ALL_DATES;
    setFrom(range.from);
    setTo(range.to);
    onChange(range);
  };
  return <div className="ops-list-tools">
    <label>History dates <select value={preset} onChange={event => select(event.target.value)}>
      <option value="all">All time</option><option value="today">Today</option>
      <option value="month">This month</option><option value="custom">Custom range</option>
    </select></label>
    {preset === "custom" ? <>
      <label>From <input type="date" value={from} onChange={event => setFrom(event.target.value)} /></label>
      <label>To <input type="date" value={to} onChange={event => setTo(event.target.value)} /></label>
      <button type="button" className="btn light" onClick={() => {
        if (!from || !to || from > to) { setError("Select valid From and To dates."); return; }
        setError(""); onChange({ from, to });
      }}>Apply dates</button>
    </> : null}
    {error ? <span role="alert" className="ops-error">{error}</span> : null}
  </div>;
}
