import { Link } from "react-router-dom";
import { useAuth } from "../features/auth";
import { visiblePortalEntries } from "../features/portalNavigation";

const paths = {
  hsn: "/portal/masters/hsn",
  brands: "/portal/masters/brands",
  categories: "/portal/masters/categories",
} as const;

export function MastersNavigation({ current }: { current: keyof typeof paths }) {
  const { user } = useAuth();
  const entries = user ? visiblePortalEntries(user) : [];
  return <nav className="masters-nav" aria-label="Product and tax data">
    {Object.values(paths).map(path => {
      const entry = entries.find(item => item.path === path);
      return entry ? <Link key={path} to={path} aria-current={path === paths[current] ? "page" : undefined}>{entry.label}</Link> : null;
    })}
  </nav>;
}
