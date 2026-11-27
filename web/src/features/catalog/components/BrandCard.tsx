import { useState } from "react";
import { Link } from "react-router-dom";
import type { Brand, StorefrontTemplate } from "../../../types";
import { toAssetUrl } from "../utils";

export function BrandCard({ brand, template = "current", caption, action, href }: {
  brand: Brand;
  template?: StorefrontTemplate;
  caption?: string;
  action: string;
  href?: string;
}) {
  const [failedLogo, setFailedLogo] = useState("");
  const logo = toAssetUrl(brand.image_url || `brand-logos/${brand.code}.png`);
  return <Link className="brand-card storefront-brand-card" data-brand-theme={template}
    to={href || `/brand?brand=${encodeURIComponent(brand.code)}`}>
    <div className="logo-box">
      {failedLogo !== logo ? <img src={logo} alt="" loading="lazy" onError={() => setFailedLogo(logo)} />
        : <span className="brand-monogram" aria-hidden="true">{brand.name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("").toUpperCase()}</span>}
    </div>
    <strong>{brand.name}</strong>
    <span>{caption || brand.description}</span>
    <em>{action}</em>
  </Link>;
}
