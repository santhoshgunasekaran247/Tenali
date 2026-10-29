import { createContext,ReactNode,useContext,useEffect,useState } from "react";
import { Navigate,Outlet,useLocation } from "react-router-dom";
import { tenantBase,tenantFetch,tenantSlug } from "./tenantTransport";
import type { SiteTheme,StorefrontContent } from "../types";

export type Workspace={company_id:string;company_name:string;tenant_slug:string;role:'owner'|'admin'|'staff'|'viewer'};
export type Identity=Workspace&{user_id:string;email:string;display_name:string;nickname?:string;logo_url?:string};
export type PublicCompany={id:string;company_name:string;tenant_slug:string;logo_url?:string;nickname?:string;phone?:string;email?:string;site_theme:SiteTheme;storefront_content:StorefrontContent};
type Session={user:Identity;workspaces:Workspace[]};

export async function authRequest<T>(path:string,options?:RequestInit):Promise<T>{
  const response=await tenantFetch('/api/auth'+path,{...options,headers:{'Content-Type':'application/json',...options?.headers}});
  const body=await response.json();
  if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:Array.isArray(body.detail)?body.detail.map((entry:{msg?:string})=>(entry.msg||'Invalid input').replace('Value error, ','')).join(' '):'Unable to complete this request.');
  return body;
}

type AuthState={user:Identity|null;workspaces:Workspace[];storefront:PublicCompany|null;loading:boolean;error:string;refresh:()=>Promise<void>;
  login:(email:string,password:string,workspace?:string)=>Promise<Identity>;register:(payload:{company_name:string;slug:string;email:string;display_name:string;password:string})=>Promise<Identity>;
  logout:()=>Promise<void>;switchWorkspace:(id:string)=>Promise<void>};
const Context=createContext<AuthState|null>(null);

export function AuthProvider({children}:{children:ReactNode}){
  const [session,setSession]=useState<Session|null>(null);const[storefront,setStorefront]=useState<PublicCompany|null>(null);
  const [loading,setLoading]=useState(true);const[error,setError]=useState('');
  const refresh=async()=>{setLoading(true);setError('');try{
    const publicCompanyRequest=tenantFetch('/api/catalog/company').then(async response=>response.ok?await response.json() as PublicCompany:null).catch(()=>null);
    const response=await tenantFetch('/api/auth/session');
    if([401,403].includes(response.status)){setSession(null);setStorefront(await publicCompanyRequest);return;}
    if(!response.ok)throw new Error('Unable to connect to the workspace service.');
    const identity=await response.json() as Session;
    setSession(identity);
    let company=await publicCompanyRequest;
    if(company?.id!==identity.user.company_id){
      const publicResponse=await tenantFetch('/api/catalog/company',{headers:{'X-Tenant-Slug':identity.user.tenant_slug}});
      company=publicResponse.ok?await publicResponse.json() as PublicCompany:null;
    }
    setStorefront(company);
  }catch(failure){setSession(null);setError(failure instanceof Error?failure.message:'Unable to connect.');}finally{setLoading(false);}};
  useEffect(()=>{void refresh();},[]);
  useEffect(()=>{
    const updateCompany=()=>{void tenantFetch('/api/catalog/company',{headers:session?.user?{'X-Tenant-Slug':session.user.tenant_slug}:{}}).then(async response=>{
      if(response.ok)setStorefront(await response.json() as PublicCompany);
    }).catch(()=>{});};
    window.addEventListener('company-updated',updateCompany);
    return ()=>window.removeEventListener('company-updated',updateCompany);
  },[session?.user?.tenant_slug]);
  const accept=(result:Session)=>{setSession(result);setError('');window.dispatchEvent(new Event('auth-updated'));};
  return <Context.Provider value={{user:session?.user||null,workspaces:session?.workspaces||[],storefront,loading,error,refresh,
    login:async(email,password,workspace)=>{const result=await authRequest<Session>('/login',{method:'POST',headers:workspace?{'X-Tenant-Slug':workspace}:{},body:JSON.stringify({email,password})});accept(result);return result.user;},
    register:async payload=>{const result=await authRequest<Session>('/register',{method:'POST',body:JSON.stringify(payload)});accept(result);return result.user;},
    logout:async()=>{await authRequest('/logout',{method:'POST'});setSession(null);window.dispatchEvent(new Event('auth-updated'));},
    switchWorkspace:async()=>{throw new Error('Each workspace requires its own login. Open the destination workspace and sign in.');},
  }}>{children}</Context.Provider>;
}

export function useAuth(){const context=useContext(Context);if(!context)throw new Error('AuthProvider missing');return context;}

export function TenantRedirect({to}:{to:string}){
  useEffect(()=>{window.location.replace(to);},[to]);
  return <main className="loading">Opening workspace...</main>;
}

export function RequireWorkspace(){
  const auth=useAuth();const location=useLocation();
  if(auth.loading)return <main className="loading">Loading workspace...</main>;
  if(!auth.user)return <Navigate to="/login" replace state={{next:location.pathname+location.search}}/>;
  if(!auth.storefront&&!tenantBase()&&location.pathname!=="/portal/new-workspace")return <TenantRedirect to={`/c/${auth.user.tenant_slug}${location.pathname}${location.search}`}/>;
  return <Outlet/>;
}

export function StorefrontRoot({children}:{children:ReactNode}){
  const auth=useAuth();if(auth.loading)return <main className="loading">Loading...</main>;
  if(!auth.storefront)return auth.user?(tenantBase()?<Navigate to="/portal" replace/>:<TenantRedirect to={`/c/${auth.user.tenant_slug}/portal`}/>):<Navigate to="/login" replace/>;
  return <>{children}</>;
}

export function CanonicalTenantUrl({children}:{children:ReactNode}){
  const auth=useAuth();
  const current=tenantSlug();
  const canonical=auth.user?.tenant_slug||auth.storefront?.tenant_slug;
  if(!auth.loading&&current&&canonical&&current!==canonical){
    const remaining=window.location.pathname.slice(tenantBase().length)||"/";
    return <TenantRedirect to={`/c/${canonical}${remaining}${window.location.search}${window.location.hash}`}/>;
  }
  return <>{children}</>;
}