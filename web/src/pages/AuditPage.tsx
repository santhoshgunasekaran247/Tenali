import { FloatingAlert } from "../components/Notifications";
import { useEffect,useState } from "react";
import { api } from "../api";
import { PortalHomeLink } from "../components/PortalHomeLink";

export function AuditPage(){
  const [items,setItems]=useState<Array<{id:string;action:string;entity_type:string;entity_id:string;created_at:string;old_value:unknown;new_value:unknown}>>([]);
  const [offset,setOffset]=useState(0);const[from,setFrom]=useState('');const[to,setTo]=useState('');const[error,setError]=useState('');
  const [pageSize,setPageSize]=useState(100);
  const [loading,setLoading]=useState(true);
  useEffect(()=>{let active=true;setLoading(true);setError('');setItems([]);void api.auditEvents(from,to,offset,pageSize).then(result=>{if(active)setItems(result.items);}).catch(failure=>{if(active)setError(String(failure));}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[from,to,offset,pageSize]);
  return <main className="ops-page masters-page"><header className="masters-heading"><PortalHomeLink/><h1>Audit Events</h1></header><section className="ops-grid ops-grid-single"><article className="ops-card">
    <div className="ops-form"><label>From Date<input type="date" value={from} onChange={event=>{setFrom(event.target.value);setOffset(0);}}/></label><label>To Date<input type="date" value={to} onChange={event=>{setTo(event.target.value);setOffset(0);}}/></label></div>
    {error?<FloatingAlert>{error}</FloatingAlert>:null}{loading?<p role="status">Loading audit events...</p>:!error&&!items.length?<p role="status">No audit events found for the selected period.</p>:null}<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Date</th><th>Action</th><th>Entity</th><th>Record</th><th>Change</th></tr></thead><tbody>{items.map(item=><tr key={item.id}><td>{new Date(item.created_at).toLocaleString()}</td><td>{item.action}</td><td>{item.entity_type}</td><td>{item.entity_id}</td><td><details><summary>Details</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify({before:item.old_value,after:item.new_value},null,2)}</pre></details></td></tr>)}</tbody></table></div>
    <div className="table-pagination" role="group" aria-label="Audit event pagination"><label>Rows per page <select value={pageSize} onChange={event=>{setPageSize(Number(event.target.value));setOffset(0);}}>{[10,25,50,100].map(size=><option key={size} value={size}>{size}</option>)}</select></label><span>Page {Math.floor(offset/pageSize)+1}</span><button type="button" disabled={loading||!offset} onClick={()=>setOffset(previous=>Math.max(0,previous-pageSize))}>Previous</button><button type="button" disabled={loading||!!error||items.length<pageSize} onClick={()=>setOffset(previous=>previous+pageSize)}>Next</button></div>
  </article></section></main>;
}