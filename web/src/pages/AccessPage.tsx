import { FormEvent,useState } from "react";
import { Building2,Eye,EyeOff,LogIn,UserPlus } from "lucide-react";
import { Link,Navigate,useLocation,useNavigate } from "react-router-dom";
import { TenantRedirect,useAuth } from "../features/auth";
import { tenantBase } from "../features/tenantTransport";

export function AccessPage({register=false}:{register?:boolean}){
  const auth=useAuth();const navigate=useNavigate();const location=useLocation();
  const [form,setForm]=useState({company_name:'',slug:'',display_name:'',email:'',password:'',confirmation:''});
  const [show,setShow]=useState(false);const[busy,setBusy]=useState(false);const[error,setError]=useState('');
  if(auth.loading)return <main className="loading">Loading...</main>;
  if(auth.user)return !tenantBase()&&!auth.storefront?<TenantRedirect to={`/c/${auth.user.tenant_slug}/portal`}/>:<Navigate to="/portal" replace/>;
  const submit=async(event:FormEvent)=>{event.preventDefault();setBusy(true);setError('');try{
    let identity;
    if(register){if(form.password!==form.confirmation)throw new Error('Passwords do not match.');identity=await auth.register({company_name:form.company_name,slug:form.slug,display_name:form.display_name,email:form.email,password:form.password});}
    else identity=await auth.login(form.email,form.password);
    const next=(location.state as {next?:string}|null)?.next;const destination=next?.startsWith('/portal')?next:'/portal';
    if(!tenantBase()&&!auth.storefront){window.location.assign(`/c/${identity.tenant_slug}${destination}`);return;}
    navigate(destination,{replace:true});
  }catch(failure){setError(failure instanceof Error?failure.message:'Unable to sign in.');}finally{setBusy(false);}};
  return <main className="access-page"><section className="access-panel"><div className="access-title"><Building2 size={26}/><div><h1>{register?'Create Your Workspace':'Sign In'}</h1><p>{auth.storefront?.company_name||'Tenali Business Workspace'}</p></div></div>
    {auth.error?<p role="alert" className="ops-error">{auth.error}<button className="ops-link-btn" onClick={()=>void auth.refresh()}>Retry</button></p>:null}{error?<p className="ops-error" role="alert">{error}</p>:null}
    <form className="ops-form" onSubmit={submit}><fieldset disabled={busy} className="access-fields">
      {register?<><label>Company Name<input required maxLength={200} autoComplete="organization" value={form.company_name} onChange={event=>setForm(previous=>({...previous,company_name:event.target.value}))}/></label>
        <label>Workspace Address<input required minLength={3} maxLength={48} pattern="[a-z0-9](?:[a-z0-9]|-){1,46}[a-z0-9]" value={form.slug} onChange={event=>setForm(previous=>({...previous,slug:event.target.value.toLowerCase()}))}/><span className="access-workspace-url">/c/{form.slug||'your-company'}</span></label>
        <label>Your Name<input required maxLength={150} autoComplete="name" value={form.display_name} onChange={event=>setForm(previous=>({...previous,display_name:event.target.value}))}/></label></>:null}
      <label>Email<input required type="email" autoComplete="username" maxLength={254} value={form.email} onChange={event=>setForm(previous=>({...previous,email:event.target.value}))}/></label>
      <label>Password<div className="access-password"><input required type={show?'text':'password'} minLength={register?12:1} maxLength={128} autoComplete={register?'new-password':'current-password'} value={form.password} onChange={event=>setForm(previous=>({...previous,password:event.target.value}))}/><button type="button" className="ops-link-btn" title={show?'Hide password':'Show password'} aria-label={show?'Hide password':'Show password'} onClick={()=>setShow(previous=>!previous)}>{show?<EyeOff size={18}/>:<Eye size={18}/>}</button></div></label>
      {register?<label>Confirm Password<input required type={show?'text':'password'} minLength={12} maxLength={128} autoComplete="new-password" value={form.confirmation} onChange={event=>setForm(previous=>({...previous,confirmation:event.target.value}))}/></label>:null}
      <button className="btn" disabled={busy}>{register?<UserPlus size={16}/>:<LogIn size={16}/>} {busy?'Please wait...':register?'Create Workspace':'Sign In'}</button>
    </fieldset></form>
    {!tenantBase()&&!auth.storefront?<p>{register?'Already registered?':'New business?'} <Link to={register?'/login':'/register'}>{register?'Sign in':'Create a workspace'}</Link></p>:null}
    {auth.storefront?<Link className="ops-inline-link" to="/">Back to Storefront</Link>:null}
  </section></main>;
}