import { useEffect,useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

export function AuditPage(){
  const [items,setItems]=useState<Array<{id:string;action:string;entity_type:string;entity_id:string;created_at:string;old_value:unknown;new_value:unknown}>>([]);
  const [offset,setOffset]=useState(0);const[from,setFrom]=useState('');const[to,setTo]=useState('');const[error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  useEffect(()=>{let active=true;setLoading(true);setError('');void api.auditEvents(from,to,offset).then(result=>{if(active)setItems(result.items);}).catch(failure=>{if(active)setError(String(failure));}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[from,to,offset]);
  return <main className="ops-page masters-page"><header className="masters-heading"><Link className="ops-inline-link" to="/portal">Portal</Link><h1>Audit Events</h1></header><section className="ops-grid ops-grid-single"><article className="ops-card">
    <div className="ops-form"><label>From Date<input type="date" value={from} onChange={event=>{setFrom(event.target.value);setOffset(0);}}/></label><label>To Date<input type="date" value={to} onChange={event=>{setTo(event.target.value);setOffset(0);}}/></label></div>
    {error?<p role="alert" className="ops-error">{error}</p>:null}{loading?<p role="status">Loading audit events...</p>:!items.length?<p role="status">No audit events found for the selected period.</p>:null}<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Date</th><th>Action</th><th>Entity</th><th>Record</th><th>Change</th></tr></thead><tbody>{items.map(item=><tr key={item.id}><td>{new Date(item.created_at).toLocaleString()}</td><td>{item.action}</td><td>{item.entity_type}</td><td>{item.entity_id}</td><td><details><summary>Details</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify({before:item.old_value,after:item.new_value},null,2)}</pre></details></td></tr>)}</tbody></table></div>
    <div className="reports-actions-row"><button className="btn" disabled={!offset} onClick={()=>setOffset(previous=>Math.max(0,previous-100))}>Previous</button><button className="btn" disabled={items.length<100} onClick={()=>setOffset(previous=>previous+100)}>Next</button></div>
  </article></section></main>;
}