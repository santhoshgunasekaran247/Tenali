import { FormEvent,useState } from "react";
import { Link } from "react-router-dom";
import { LockKeyhole } from "lucide-react";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { authRequest,useAuth } from "../features/auth";
import { tenantBase } from "../features/tenantTransport";

export function AccountPage(){
  const auth=useAuth();
  const [form,setForm]=useState({current_password:'',new_password:'',confirmation:''});const[busy,setBusy]=useState(false);const[error,setError]=useState('');const[message,setMessage]=useState('');
  const save=async(event:FormEvent)=>{event.preventDefault();setBusy(true);setError('');try{if(form.new_password!==form.confirmation)throw new Error('New passwords do not match.');await authRequest('/password',{method:'POST',body:JSON.stringify({current_password:form.current_password,new_password:form.new_password})});setForm({current_password:'',new_password:'',confirmation:''});setMessage('Password changed. Other sessions have been signed out.');}catch(failure){setError(String(failure));}finally{setBusy(false);}};
  return <main className="ops-page masters-page"><header className="masters-heading"><PortalHomeLink/><h1>Your Account</h1></header><section className="ops-grid ops-grid-single">
    <article className="ops-card account-settings"><h2>Workspace Access</h2><p>{auth.user?.company_name} · {auth.user?.role}</p>{auth.workspaces.length>1?<label>Switch workspace<select value={auth.user?.company_id} onChange={event=>void auth.switchWorkspace(event.target.value)}>{auth.workspaces.map(workspace=><option key={workspace.company_id} value={workspace.company_id}>{workspace.company_name}</option>)}</select></label>:null}{tenantBase()||!auth.storefront?<Link className="btn light" to="/portal/new-workspace">Add another company</Link>:null}</article>
    <article className="ops-card account-settings"><h2>Change Password</h2>{error?<p role="alert" className="ops-error">{error}</p>:null}{message?<p role="status">{message}</p>:null}<form className="ops-form" onSubmit={save}><label>Current Password<input required type="password" autoComplete="current-password" value={form.current_password} onChange={event=>setForm(previous=>({...previous,current_password:event.target.value}))}/></label><label>New Password<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={form.new_password} onChange={event=>setForm(previous=>({...previous,new_password:event.target.value}))}/></label><label>Confirm New Password<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={form.confirmation} onChange={event=>setForm(previous=>({...previous,confirmation:event.target.value}))}/></label><button className="btn" disabled={busy}><LockKeyhole size={16}/>Update Password</button></form></article>
  </section></main>;
}