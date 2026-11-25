import { Link,useLocation,useNavigate } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { api } from "../api";
import type { Company,SiteTheme,StorefrontTemplate } from "../types";
import { useAuth } from "../features/auth";
import { toAssetUrl } from "../features/catalog/utils";
import { setSavedSiteTheme } from "../features/siteTheme";
import { applyCornerStyle, storefrontDisplay } from "../features/catalog/storefrontDisplay";
import { tenantBase } from "../features/tenantTransport";
import { WorkspaceBar } from "./WorkspaceBar";
import { storefrontText } from "../features/catalog/storefrontText";
import { useCart } from "../features/cart";
import { useCartMode } from "../features/useCheckoutAvailability";
import { cartWords } from "../features/cartMode";
import { PortalNavigation } from "./PortalNavigation";
import { isStorefrontHref, storefrontHeaderMenu, storefrontLink } from "../features/catalog/storefrontLinks";

type HeaderProps = {
  menuOpen: boolean;
  onMenuToggle: () => void;
  previewCompany?: Pick<Company, "storefront_template" | "site_theme" | "logo_url" | "storefront_content">;
};

export function Header({ menuOpen, onMenuToggle, previewCompany }: HeaderProps) {
  const auth=useAuth();
  const cart=useCart();
  const location=useLocation();
  const navigate=useNavigate();
  const [searchText,setSearchText]=useState("");
  const [company, setCompany] = useState<(Pick<Company,'company_name'|'logo_url'|'storefront_content'|'storefront_enabled'>&{site_theme?:SiteTheme;storefront_template?:StorefrontTemplate}) | null>(null);
  const previewCompanyRef = useRef(previewCompany);
  previewCompanyRef.current = previewCompany;
  useEffect(() => {
    let active = true;
    const load = () => {
      if(!auth.user){setCompany(auth.storefront);setSavedSiteTheme(previewCompanyRef.current?.site_theme || auth.storefront?.site_theme, previewCompanyRef.current?.storefront_template || auth.storefront?.storefront_template);applyCornerStyle(storefrontDisplay(previewCompanyRef.current || auth.storefront).corner_style);return;}
      void api.company().then((result) => {
        if (active) { setCompany(result); setSavedSiteTheme(previewCompanyRef.current?.site_theme || result.site_theme, location.pathname.startsWith("/portal") ? undefined : previewCompanyRef.current?.storefront_template || result.storefront_template); applyCornerStyle(storefrontDisplay(previewCompanyRef.current || result).corner_style); }
      }).catch(() => {});
    };
    load();
    window.addEventListener("company-updated", load);
    return () => { active = false; window.removeEventListener("company-updated", load); };
  }, [auth.user?.company_id,auth.storefront,location.pathname.startsWith("/portal")]);
  useEffect(() => {
    if (!previewCompany) return;
    setSavedSiteTheme(previewCompany.site_theme, previewCompany.storefront_template);
    applyCornerStyle(storefrontDisplay(previewCompany).corner_style);
  }, [previewCompany]);
  const tenantLogo=previewCompany ? previewCompany.logo_url : company?.logo_url||auth.storefront?.logo_url||auth.user?.logo_url;
  const platformBrand = !auth.loading && !auth.error && !tenantBase() && !auth.storefront && !auth.user;
  const logo=tenantLogo||(platformBrand?"/tenali-logo.png":undefined);
  const logoSrc=logo==="/tenali-logo.png"?logo:toAssetUrl(logo);
  const companyName=company?.company_name||auth.storefront?.company_name||auth.user?.company_name;
  const displayBrand=auth.storefront||company||{company_name:companyName||"Tenali",nickname:auth.user?.nickname};
  const navigation=previewCompany?.storefront_content?.navigation||company?.storefront_content?.navigation||auth.storefront?.storefront_content?.navigation||{};
  const storefrontCompany=previewCompany ? { ...company, ...previewCompany } : company||auth.storefront;
  const storefrontOpen=previewCompany ? true : (auth.storefront||company)?.storefront_enabled!==false;
  const navText=(key:string,fallback:string)=>storefrontText(navigation[key]||fallback,displayBrand);
  const inPortal=location.pathname.startsWith("/portal");
  const marketplace=!inPortal&&storefrontOpen&&["marketplace","category_first"].includes(storefrontCompany?.storefront_template||"");
  const boutique=!inPortal&&storefrontOpen&&storefrontCompany?.storefront_template==="boutique";
  const collectionHeader=!inPortal&&storefrontOpen&&["heritage","supermarket","jewellery"].includes(storefrontCompany?.storefront_template||"");
  const link = (key: string, href: string, label: string) => storefrontLink({ ...displayBrand, storefront_content: storefrontCompany?.storefront_content }, key, href, label);
  const menuItems=storefrontHeaderMenu({ ...displayBrand, storefront_template: storefrontCompany?.storefront_template,
    storefront_content: storefrontCompany?.storefront_content }).filter(item=>item.is_enabled);
  const sectionLinks=menuItems.map(item=>{
    const href=item.href&&isStorefrontHref(item.href)?item.href:"/";
    return <Link key={item.key} to={href.startsWith("#")?`/${href}`:href}>{storefrontText(item.label,displayBrand)}</Link>;
  });
  const primaryMenu=menuItems.length?<div className="storefront-primary-menu">{sectionLinks}</div>:null;
  const cartModeState=useCartMode(!inPortal);
  const storefrontHref=auth.user?(auth.storefront?.id===auth.user.company_id?(tenantBase()||"/"):`/c/${auth.user.tenant_slug}`):"/";
  const brandHref=auth.user&&inPortal?"/portal":"/";
  const browserTitle=storefrontText(storefrontCompany?.storefront_content?.home.browser_title||"{nickname} | Catalogue & Workspace",displayBrand);
  useEffect(()=>{setSearchText(new URLSearchParams(location.search).get("q")||"");},[location.search]);
  useEffect(()=>{if(!auth.loading)document.title=companyName?browserTitle:'Tenali | Business Workspace';},[auth.loading,companyName,browserTitle]);
  useEffect(()=>{
    if (!logo) return;
    const image=new URL(toAssetUrl(logo),window.location.origin).href;
    document.querySelector('meta[property="og:image"]')?.setAttribute("content",image);
    document.querySelector('meta[name="twitter:image"]')?.setAttribute("content",image);
  },[logo]);
  return (
    <header className={`header${inPortal ? " header-portal" : ""}${marketplace ? " header-marketplace" : ""}${boutique ? " header-boutique" : ""}${collectionHeader ? ` header-collections header-${storefrontCompany?.storefront_template}` : ""}`}>
      {marketplace ? <div className="marketplace-utility"><span>{companyName}</span><span>Prices in INR <Link {...link("nav.contact", "/#contact", navText("contact","Contact"))} /></span></div> : null}
      <Link className="brand" to={brandHref} aria-label={companyName||(platformBrand?'Tenali':'Workspace home')}>
        {logo ? <img src={logoSrc} alt={companyName || "Tenali"} loading="eager" decoding="async" /> : companyName?<strong>{companyName}</strong>:<span className="brand-loading" aria-hidden="true"/>}
      </Link>
      {storefrontCompany&&storefrontOpen&&!inPortal?<form className="header-search" role="search" onSubmit={(event)=>{
        event.preventDefault();
        const query=searchText.trim();
        navigate(query?`/brand?q=${encodeURIComponent(query)}`:"/brand?category=all");
      }}>
        <label className="visually-hidden" htmlFor="storefront-search">Search products</label>
        <input id="storefront-search" type="search" maxLength={120} placeholder="Search products, brands or categories" value={searchText}
          onChange={event=>setSearchText(event.target.value)} />
        <button type="submit" aria-label="Search products"><Search size={18} aria-hidden="true" /></button>
      </form>:null}
      <nav id="header-navigation" className={`${auth.user?"workspace-header-nav":""}${menuOpen?" open":""}`} onKeyDown={event => {
        if (event.key === "Escape" && menuOpen) { onMenuToggle(); document.querySelector<HTMLButtonElement>(".header .menu")?.focus(); }
      }} onClick={(event)=>{if(menuOpen&&(event.target as HTMLElement).closest("a,button"))onMenuToggle();}}>
        {auth.user ? <div className="workspace-nav-links">
          {inPortal ? <>
            <Link to="/portal">{navText("operations_portal","Operations Portal")}</Link>
            <PortalNavigation mobile />
            {auth.storefront?.id === auth.user.company_id ? <Link to="/">{navText("storefront","Storefront")}</Link> : <a href={storefrontHref}>{navText("storefront","Storefront")}</a>}
          </> : storefrontCompany&&storefrontOpen&&!marketplace&&!boutique&&!collectionHeader ? primaryMenu : null}
        </div> : storefrontCompany&&storefrontOpen&&!marketplace&&!boutique&&!collectionHeader ? primaryMenu : null}
        {auth.storefront&&storefrontOpen&&!inPortal&&cartModeState.mode&&(cartModeState.mode!=="none"||cart.items.length)?<Link to={link("nav.cart", "/cart", "").to} className={`header-cart-link${cartModeState.mode==="enquiry"?" header-enquiry-link":""}`}>{link("nav.cart", "/cart", cartWords(cartModeState.mode).list).children} ({cart.items.reduce((total,item)=>total+item.quantity,0)})</Link>:null}
        {storefrontCompany&&!inPortal?<Link {...link("nav.shopper_account", "/account", navText("shopper_account","Shopper Account"))} />:null}
        {!auth.user?<Link {...link("nav.sign_in", "/login", navText("sign_in","Workspace Staff Sign In"))} onClick={()=>menuOpen&&onMenuToggle()} />:null}
        <WorkspaceBar navigation={navigation}/>
      </nav>
      <button className="menu" aria-label={menuOpen?"Close menu":"Open menu"} aria-controls="header-navigation" aria-expanded={menuOpen} onClick={onMenuToggle}>{menuOpen?"×":"☰"}</button>
      {marketplace&&menuItems.length ? <nav className="marketplace-departments" aria-label="Store departments">
        {sectionLinks}
      </nav> : null}
      {boutique&&menuItems.length ? <nav className="boutique-navigation" aria-label="Store collections">
        {sectionLinks}
      </nav> : null}
      {collectionHeader&&menuItems.length ? <nav className="storefront-collection-navigation" aria-label="Store collections">{sectionLinks}</nav> : null}
    </header>
  );
}
