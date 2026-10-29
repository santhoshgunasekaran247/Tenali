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

type HeaderProps = {
  menuOpen: boolean;
  onMenuToggle: () => void;
};

export function Header({ menuOpen, onMenuToggle }: HeaderProps) {
  const auth=useAuth();
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
  const logo=tenantLogo||(!auth.storefront&&!auth.user?"/tenali-logo.png":undefined);
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
    const image=new URL(logo?toAssetUrl(logo):"/tenali-logo.png",window.location.origin).href;
    document.querySelector('meta[property="og:image"]')?.setAttribute("content",image);
    document.querySelector('meta[name="twitter:image"]')?.setAttribute("content",image);
  },[logo]);
  return (
    <header className="header">
      <Link className="brand" to={brandHref} aria-label={companyName||'Tenali'}>
        {logo ? <img src={logoSrc} alt={companyName || "Tenali"} loading="eager" decoding="async" /> : auth.loading?<span className="brand-loading" aria-hidden="true"/>:<strong>{companyName||'Tenali'}</strong>}
      </Link>
      <nav className={`${auth.user?"workspace-header-nav":""}${menuOpen?" open":""}`} onClick={(event)=>{if(menuOpen&&(event.target as HTMLElement).closest("a,button"))onMenuToggle();}}>
        {auth.user ? <div className="workspace-nav-links">
          {inPortal ? <>
            <Link to="/portal">{navText("operations_portal","Operations Portal")}</Link>
            <a href={storefrontHref}>{navText("storefront","Storefront")}</a>
          </> : storefrontCompany ? <>
            <a href={`${tenantBase()}/#collection-special`}>{navText("collection","Collection")}</a>
            <a href={`${tenantBase()}/#categories`}>{navText("categories","Categories")}</a>
            <a href={`${tenantBase()}/#best-sellers`}>{navText("best_sellers","Best Sellers")}</a>
            <a href={`${tenantBase()}/#sru-specials`}>{navText("specials","Specials")}</a>
            <a href={`${tenantBase()}/#brands`}>{navText("brands","Brands")}</a>
            <a href={`${tenantBase()}/#contact`}>{navText("contact","Contact")}</a>
          </> : null}
        </div> : storefrontCompany ? <>
          <a href={`${tenantBase()}/#collection-special`}>{navText("collection","Collection")}</a>
          <a href={`${tenantBase()}/#categories`}>{navText("categories","Categories")}</a>
          <a href={`${tenantBase()}/#best-sellers`}>{navText("best_sellers","Best Sellers")}</a>
          <a href={`${tenantBase()}/#sru-specials`}>{navText("specials","Specials")}</a>
          <a href={`${tenantBase()}/#brands`}>{navText("brands","Brands")}</a>
          <a href={`${tenantBase()}/#contact`}>{navText("contact","Contact")}</a>
        </> : null}
        {!auth.user?<Link to="/login" onClick={()=>menuOpen&&onMenuToggle()}>{navText("sign_in","Sign In")}</Link>:null}
        <WorkspaceBar/>
      </nav>
      <button className="menu" aria-label={menuOpen?"Close menu":"Open menu"} aria-expanded={menuOpen} onClick={onMenuToggle}>{menuOpen?"×":"☰"}</button>
    </header>
  );
}
