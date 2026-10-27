import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { CompanySetup } from "../types";
import { toAssetUrl } from "../features/catalog/utils";
import { setSavedSiteTheme } from "../features/siteTheme";

type HeaderProps = {
  menuOpen: boolean;
  onMenuToggle: () => void;
};

export function Header({ menuOpen, onMenuToggle }: HeaderProps) {
  const [company, setCompany] = useState<CompanySetup | null>(null);
  useEffect(() => {
    let active = true;
    const load = () => {
      void api.company().then((result) => {
        if (active) { setCompany(result); setSavedSiteTheme(result.site_theme); }
      }).catch(() => {});
    };
    load();
    window.addEventListener("company-updated", load);
    return () => { active = false; window.removeEventListener("company-updated", load); };
  }, []);
  const logo = company ? company.logo_url : "sru-global-logo.png";
  return (
    <header className="header">
      <Link className="brand" to="/">
        {logo ? <img src={toAssetUrl(logo)} alt={company?.company_name || "SRU Global"} /> : <strong>{company?.company_name}</strong>}
      </Link>
      <nav className={menuOpen ? "open" : ""}>
        <a href="/#collection-special">SRU Collection Special</a>
        <a href="/#categories">Categories</a>
        <a href="/#best-sellers">Best Sellers</a>
        <a href="/#sru-specials">SRU Specials</a>
        <a href="/#brands">Brands</a>
        <a href="/#contact">Contact</a>
        <Link to="/portal">Portal</Link>
      </nav>
      <button className="menu" aria-label="Open menu" onClick={onMenuToggle}>
        ☰
      </button>
    </header>
  );
}
