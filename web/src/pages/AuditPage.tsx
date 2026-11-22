import { FloatingAlert } from "../components/Notifications";
import { CursorPagination } from "../components/CursorPagination";
import { useEffect,useState } from "react";
import { historyClient, type AuditEvent } from "../features/historyClient";
import { PortalHomeLink } from "../components/PortalHomeLink";

export function AuditPage(){
  const [items,setItems]=useState<AuditEvent[]>([]);
  const [from,setFrom]=useState(""); const [to,setTo]=useState(""); const [error,setError]=useState("");
  const [pageSize,setPageSize]=useState(100); const [page,setPage]=useState(0);
  const [cursors,setCursors]=useState<Array<string|null>>([null]); const [next,setNext]=useState<string|null>(null);
  const [loading,setLoading]=useState(true);
  const invalid=!!from && !!to && from>to;
  const reset=()=>{setCursors([null]);setPage(0);};
  useEffect(()=>{
    let active=true; setItems([]); setNext(null); setError("");
    if(invalid){setLoading(false);return ()=>{active=false;};}
    setLoading(true);
    void historyClient.audit({from_date:from,to_date:to,page_size:pageSize,cursor:cursors[page]})
      .then(result=>{if(active){setItems(result.items);setNext(result.next_cursor);}})
      .catch(failure=>{if(active)setError(failure instanceof Error?failure.message:"Unable to load audit events.");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[from,to,page,pageSize,cursors,invalid]);
  return <main className="ops-page masters-page"><header className="masters-heading"><PortalHomeLink/><h1>Audit Events</h1></header><section className="ops-grid ops-grid-single"><article className="ops-card">
    <div className="ops-form"><label>From Date<input type="date" value={from} onChange={event=>{setFrom(event.target.value);reset();}}/></label><label>To Date<input type="date" value={to} onChange={event=>{setTo(event.target.value);reset();}}/></label></div>
    {invalid?<FloatingAlert>From date cannot be after To date.</FloatingAlert>:null}{error?<FloatingAlert>{error}</FloatingAlert>:null}{loading?<p role="status">Loading audit events...</p>:!error&&!invalid&&!items.length?<p role="status">No audit events found for the selected period.</p>:null}<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Date</th><th>Action</th><th>Entity</th><th>Record</th><th>Change</th></tr></thead><tbody>{items.map(item=><tr key={item.id}><td>{new Date(item.created_at).toLocaleString()}</td><td>{item.action}</td><td>{item.entity_type}</td><td>{item.entity_id}</td><td><details><summary>Details</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify({before:item.old_value,after:item.new_value},null,2)}</pre></details></td></tr>)}</tbody></table></div>
    <CursorPagination size={pageSize} page={page} hasNext={!!next} busy={loading||invalid} onSize={size=>{setPageSize(size);reset();}} onPrevious={()=>setPage(value=>value-1)} onNext={()=>{if(next){setCursors(previous=>[...previous.slice(0,page+1),next]);setPage(value=>value+1);}}}/>
  </article></section></main>;
}
