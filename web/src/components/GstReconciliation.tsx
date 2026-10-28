import { useState } from "react";
import { Download,Upload } from "lucide-react";
import { api } from "../api";

const HEADERS=['supplier_gstin','invoice_number','invoice_date','taxable_value','cgst','sgst','igst','cess'];
const download=(content:string,name:string)=>{const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
export function GstReconciliation({fromDate,toDate,invalid}:{fromDate:string;toDate:string;invalid:boolean}){
  const [csv,setCsv]=useState('');const[fileName,setFileName]=useState('');const[busy,setBusy]=useState(false);const[error,setError]=useState('');
  const [result,setResult]=useState<Awaited<ReturnType<typeof api.reconcileGstr2b>>|null>(null);
  const run=async()=>{setBusy(true);setError('');setResult(null);try{setResult(await api.reconcileGstr2b(csv,fromDate,toDate));}catch(failure){setError(String(failure));}finally{setBusy(false);}};
  return <article className="ops-card ops-list-card"><div className="ops-card-head"><h2>GSTR-2B Reconciliation Working Paper</h2></div>
    <div className="ops-form"><label>Normalized GSTR-2B CSV<input type="file" accept=".csv,text/csv" disabled={busy} onChange={event=>{const file=event.target.files?.[0];if(!file)return;if(file.size>5_000_000){setError('Maximum CSV size is 5 MB.');return;}setFileName(file.name);setResult(null);void file.text().then(setCsv).catch(failure=>setError(String(failure)));}}/></label></div>
    <div className="reports-actions-row"><button className="btn light" type="button" onClick={()=>download(HEADERS.join(',')+'\n','gstr2b_normalized_template.csv')}><Download size={16}/>CSV Template</button><button className="btn" type="button" disabled={!csv||busy||invalid} onClick={()=>void run()}><Upload size={16}/>{busy?'Reconciling...':'Reconcile'}</button>{result?<button className="btn" type="button" onClick={()=>{const keys=Object.keys(result.items[0]||{supplier_gstin:'',invoice_number:'',status:''});download([keys,...result.items.map(row=>keys.map(key=>row[key]))].map(row=>row.map(cell=>'"'+String(cell??'').replace(/"/g,'""')+'"').join(',')).join('\n'),`gstr2b_reconciliation_${fromDate}_${toDate}.csv`);}}><Download size={16}/>Export Results</button>:null}</div>
    {fileName?<p>{fileName}</p>:null}{error?<p role="alert" className="ops-error">{error}</p>:null}
    {result?<><p role="status">{Object.entries(result.counts).map(([key,count])=>`${key.replace(/_/g,' ')}: ${count}`).join(' | ')}</p><div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Supplier GSTIN</th><th>Invoice</th><th>Status</th><th>Books GST</th><th>2B GST</th><th>Difference</th></tr></thead><tbody>{result.items.map((row,index)=><tr key={index}><td>{row.supplier_gstin}</td><td>{row.invoice_number}</td><td>{row.status}</td><td>{row.books_gst}</td><td>{row.statement_gst}</td><td>{row.gst_difference}</td></tr>)}</tbody></table></div><p className="ops-copy-note">{result.limitations.join(' ')}</p></>:null}
  </article>;
}