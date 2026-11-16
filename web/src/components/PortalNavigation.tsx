import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../features/auth";
import { portalGroups, visiblePortalEntries } from "../features/portalNavigation";

export function PortalNavigation({ mobile = false }: { mobile?: boolean }) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  if (!user) return null;
  const entries = visiblePortalEntries(user);
  const link = (entry: typeof entries[number]) => <NavLink key={entry.path} to={entry.path} end
    className={({ isActive }) => isActive ? "portal-nav-active" : undefined}>{entry.label}</NavLink>;
  return <div role="navigation" className={mobile ? "portal-mobile-links" : "portal-sidebar"} aria-label="Workspace modules">
    {entries.filter(entry => !entry.group).map(link)}
    {portalGroups.map(group => {
      const children = entries.filter(entry => entry.group === group);
      if (!children.length) return null;
      return <details className="portal-nav-group" key={`${group}:${pathname}`}
        open={children.some(entry => entry.path === pathname.replace(/\/+$/, ""))}>
        <summary>{group}<span aria-hidden="true" className="portal-group-chevron">›</span></summary>
        <div className="portal-group-links">{children.map(link)}</div>
      </details>;
    })}
  </div>;
}

export function TenaliLauncher() {
  return <NavLink to="/portal/ai" className="tenali-launcher" aria-label="Ask Tenali AI for help">
    <img src="/tenali-assistant.png" width="60" height="60" alt="" />
    <span>Ask Tenali</span>
  </NavLink>;
}
