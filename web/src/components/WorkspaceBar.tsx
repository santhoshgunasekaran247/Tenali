import { useEffect,useRef,useState } from "react";
import { Building2,ChevronDown,LogOut } from "lucide-react";
import { Link } from "react-router-dom";
import { useLocation } from "react-router-dom";
import { useAuth } from "../features/auth";
import { tenantBase } from "../features/tenantTransport";
import { storefrontText } from "../features/catalog/storefrontText";

export function WorkspaceBar(){
  const auth=useAuth();const[error,setError]=useState('');const[busy,setBusy]=useState(false);
  const location=useLocation();
  const menu=useRef<HTMLDetailsElement>(null);
  useEffect(()=>{if(menu.current?.open)menu.current.open=false;},[location.pathname,location.search,location.hash]);
  if(!auth.user)return null;
  const copy=auth.storefront?.storefront_content?.navigation||{};
  const label=(key:string,fallback:string)=>storefrontText(copy[key]||fallback,auth.user!);
  return <details ref={menu} className="workspace-menu">
    <summary aria-label={label("account_menu","My Account")}><Building2 size={16}/><span>{label("account_menu","My Account")}</span><ChevronDown size={14}/></summary>
    <div className="workspace-menu-panel">
      <div className="workspace-identity"><strong>{auth.user.company_name}</strong><span>{auth.user.display_name} · {auth.user.role}</span></div>
      {!location.pathname.startsWith('/portal')?<Link to="/portal" className="workspace-action">{label("operations_portal","Operations Portal")}</Link>:null}
      <Link to="/portal/account" className="workspace-action">{label("account","Account")}</Link>
      {auth.user.role==="owner"||auth.user.role==="admin"?<Link to="/portal/checkout" className="workspace-action">Shopper Checkout &amp; Orders</Link>:null}
      <button className="workspace-action" disabled={busy} onClick={()=>{setBusy(true);void auth.logout().catch(failure=>setError(String(failure))).finally(()=>setBusy(false));}}><LogOut size={15}/>{label("sign_out","Sign Out")}</button>
      {error?<p role="alert" className="ops-error">{error}</p>:null}
    </div>
  </details>;
}