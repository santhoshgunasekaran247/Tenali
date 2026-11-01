import { FormEvent,useState } from "react";
import { Building2,Eye,EyeOff,LogIn } from "lucide-react";
import { Link,Navigate,useLocation,useNavigate } from "react-router-dom";
import { TenantRedirect,useAuth } from "../features/auth";
import { tenantBase } from "../features/tenantTransport";
import { WorkspaceSocialAccess } from "../components/WorkspaceSocialAccess";

export function AccessPage({register=false}:{register?:boolean}){
  const auth=useAuth();const navigate=useNavigate();const location=useLocation();
  const [form,setForm]=useState({slug:'',email:'',password:''});
  const [show,setShow]=useState(false);const[busy,setBusy]=useState(false);const[error,setError]=useState('');
  if(auth.loading)return <main className="loading">Loading...</main>;
  if(auth.user)return !tenantBase()&&!auth.storefront?<TenantRedirect to={`/c/${auth.user.tenant_slug}/portal`}/>:<Navigate to="/portal" replace/>;
  if(register)return <main className="access-page workspace-access-page"><section className="access-panel workspace-access-panel"><div className="access-title"><span className="access-title-icon"><Building2 size={26}/></span><div><h1>Create your workspace</h1><p>Your business, in one place.</p></div></div><WorkspaceSocialAccess register /><p className="access-footer">Already registered? <Link to="/login">Sign in</Link></p></section></main>;
  const submit=async(event:FormEvent)=>{event.preventDefault();setBusy(true);setError('');try{
    const identity=await auth.login(form.email,form.password,!tenantBase()&&!auth.storefront?form.slug:undefined);
    const next=(location.state as {next?:string}|null)?.next;const destination=next?.startsWith('/portal')?next:'/portal';
    if(!tenantBase()&&!auth.storefront){window.location.assign(`/c/${identity.tenant_slug}${destination}`);return;}
    navigate(destination,{replace:true});
  }catch(failure){setError(failure instanceof Error?failure.message:'Unable to sign in.');}finally{setBusy(false);}};
  return <main className="access-page workspace-access-page"><section className="access-panel workspace-access-panel"><div className="access-title"><span className="access-title-icon"><Building2 size={26}/></span><div><h1>Welcome back</h1><p>{auth.storefront?.company_name||'Tenali Business Workspace'}</p></div></div>
    {auth.error?<p role="alert" className="ops-error">{auth.error}<button className="ops-link-btn" onClick={()=>void auth.refresh()}>Retry</button></p>:null}{error?<p className="ops-error" role="alert">{error}</p>:null}
    {!tenantBase()&&!auth.storefront?<label className="social-workspace-label">Workspace address<input aria-label="Workspace address" aria-describedby="workspace-address-help" form="workspace-password-login" required minLength={3} maxLength={48} value={form.slug} autoComplete="organization" placeholder="e.g. sourcebysru" onChange={event=>setForm(previous=>({...previous,slug:event.target.value.toLowerCase().trim()}))}/><span id="workspace-address-help" className="access-workspace-url">Used for both owner and staff sign-in.</span></label>:null}
    <WorkspaceSocialAccess workspaceSlug={form.slug} />
    <div className="access-divider"><span>or sign in with a password</span></div>
    <form id="workspace-password-login" className="ops-form" onSubmit={submit}><fieldset disabled={busy} className="access-fields">
      <legend className="access-staff-legend">Staff &amp; existing accounts</legend>
      <label>Email<input required type="email" autoComplete="username" maxLength={254} value={form.email} onChange={event=>setForm(previous=>({...previous,email:event.target.value}))}/></label>
      <label>Password<div className="access-password"><input aria-label="Password" required type={show?'text':'password'} minLength={1} maxLength={128} autoComplete="current-password" value={form.password} onChange={event=>setForm(previous=>({...previous,password:event.target.value}))}/><button type="button" className="ops-link-btn" title={show?'Hide password':'Show password'} aria-label={show?'Hide password':'Show password'} onClick={()=>setShow(previous=>!previous)}>{show?<EyeOff size={18}/>:<Eye size={18}/>}</button></div></label>
      <button className="btn access-submit" disabled={busy||(!tenantBase()&&!auth.storefront&&!form.slug)}><LogIn size={16}/>{busy?'Please wait...':'Sign in to workspace'}</button>
    </fieldset></form>
    {!tenantBase()&&!auth.storefront?<p>New business? <Link to="/register">Create a workspace</Link></p>:null}
    {auth.storefront?<><p><Link to="/account">Shopper sign in / Create shopper account</Link></p><Link className="ops-inline-link" to="/">Back to Storefront</Link></>:null}
  </section></main>;
}