import { Link,useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Company,SiteTheme } from "../types";
import { useAuth } from "../features/auth";
import { toAssetUrl } from "../features/catalog/utils";
import { setSavedSiteTheme } from "../features/siteTheme";
import { tenantBase } from "../features/tenantTransport";
import { WorkspaceBar } from "./WorkspaceBar";
import { storefrontText } from "../features/catalog/storefrontText";
import { useCart } from "../features/cart";

type HeaderProps = {
  menuOpen: boolean;
  onMenuToggle: () => void;
};

export function Header({ menuOpen, onMenuToggle }: HeaderProps) {
  const auth=useAuth();
  const cart=useCart();
  const location=useLocation();
  const [company, setCompany] = useState<(Pick<Company,'company_name'|'logo_url'|'storefront_content'>&{site_theme?:SiteTheme}) | null>(null);
  useEffect(() => {
    let active = true;
    const load = () => {
      if(!auth.user){setCompany(auth.storefront);setSavedSiteTheme(auth.storefront?.site_theme);return;}
      void api.company().then((result) => {
        if (active) { setCompany(result); setSavedSiteTheme(result.site_theme); }
      }).catch(() => {});
    };
    load();
    window.addEventListener("company-updated", load);
    return () => { active = false; window.removeEventListener("company-updated", load); };
  }, [auth.user?.company_id,auth.storefront]);
  const tenantLogo=company?.logo_url||auth.storefront?.logo_url||auth.user?.logo_url;
  const platformBrand = !auth.loading && !auth.error && !tenantBase() && !auth.storefront && !auth.user;
  const logo=tenantLogo||(platformBrand?"/tenali-logo.png":undefined);
  const logoSrc=logo==="/tenali-logo.png"?logo:toAssetUrl(logo);
  const companyName=company?.company_name||auth.storefront?.company_name||auth.user?.company_name;
  const displayBrand=auth.storefront||company||{company_name:companyName||"Tenali",nickname:auth.user?.nickname};
  const navigation=company?.storefront_content?.navigation||auth.storefront?.storefront_content?.navigation||{};
  const storefrontCompany=company||auth.storefront;
  const navText=(key:string,fallback:string)=>storefrontText(navigation[key]||fallback,displayBrand);
  const inPortal=location.pathname.startsWith("/portal");
  const storefrontHref=auth.user?(auth.storefront?.id===auth.user.company_id?(tenantBase()||"/"):`/c/${auth.user.tenant_slug}`):"/";
  const brandHref=auth.user&&inPortal?"/portal":"/";
  const browserTitle=storefrontText(storefrontCompany?.storefront_content?.home.browser_title||"{nickname} | Catalogue & Workspace",displayBrand);
  useEffect(()=>{if(!auth.loading)document.title=companyName?browserTitle:'Tenali | Business Workspace';},[auth.loading,companyName,browserTitle]);
  useEffect(()=>{
    if (!logo) return;
    const image=new URL(toAssetUrl(logo),window.location.origin).href;
    document.querySelector('meta[property="og:image"]')?.setAttribute("content",image);
    document.querySelector('meta[name="twitter:image"]')?.setAttribute("content",image);
  },[logo]);
  return (
    <header className="header">
      <Link className="brand" to={brandHref} aria-label={companyName||(platformBrand?'Tenali':'Workspace home')}>
        {logo ? <img src={logoSrc} alt={companyName || "Tenali"} loading="eager" decoding="async" /> : companyName?<strong>{companyName}</strong>:<span className="brand-loading" aria-hidden="true"/>}
      </Link>
      <nav className={`${auth.user?"workspace-header-nav":""}${menuOpen?" open":""}`} onClick={(event)=>{if(menuOpen&&(event.target as HTMLElement).closest("a,button"))onMenuToggle();}}>
        {auth.user ? <div className="workspace-nav-links">
          {inPortal ? <>
            <Link to="/portal">{navText("operations_portal","Operations Portal")}</Link>
            {auth.storefront?.id === auth.user.company_id ? <Link to="/">{navText("storefront","Storefront")}</Link> : <a href={storefrontHref}>{navText("storefront","Storefront")}</a>}
          </> : storefrontCompany ? <>
            <Link to="/#collection-special">{navText("collection","Collection")}</Link>
            <Link to="/#categories">{navText("categories","Categories")}</Link>
            <Link to="/#best-sellers">{navText("best_sellers","Best Sellers")}</Link>
            <Link to="/#sru-specials">{navText("specials","Specials")}</Link>
            <Link to="/#brands">{navText("brands","Brands")}</Link>
            <Link to="/#contact">{navText("contact","Contact")}</Link>
          </> : null}
        </div> : storefrontCompany ? <>
          <Link to="/#collection-special">{navText("collection","Collection")}</Link>
          <Link to="/#categories">{navText("categories","Categories")}</Link>
          <Link to="/#best-sellers">{navText("best_sellers","Best Sellers")}</Link>
          <Link to="/#sru-specials">{navText("specials","Specials")}</Link>
          <Link to="/#brands">{navText("brands","Brands")}</Link>
          <Link to="/#contact">{navText("contact","Contact")}</Link>
        </> : null}
        {auth.storefront&&!inPortal?<Link to="/cart">Cart ({cart.items.reduce((total,item)=>total+item.quantity,0)})</Link>:null}
        {storefrontCompany&&!inPortal?<Link to="/account">{navText("shopper_account","Shopper Account")}</Link>:null}
        {!auth.user?<Link to="/login" onClick={()=>menuOpen&&onMenuToggle()}>{navText("sign_in","Workspace Staff Sign In")}</Link>:null}
        <WorkspaceBar/>
      </nav>
      <button className="menu" aria-label={menuOpen?"Close menu":"Open menu"} aria-expanded={menuOpen} onClick={onMenuToggle}>{menuOpen?"×":"☰"}</button>
    </header>
  );
}
