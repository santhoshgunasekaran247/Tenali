import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { BarChart3, BriefcaseBusiness, ChevronLeft, ChevronRight, LayoutGrid, Settings, Sparkles, UserRound } from "lucide-react";
import { useAuth } from "../features/auth";
import { portalGroups, visiblePortalEntries } from "../features/portalNavigation";
import { useDismissOutside } from "../features/useDismissOutside";

export function PortalNavigation({ mobile = false }: { mobile?: boolean }) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const [expanded, setExpanded] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useDismissOutside(menuRef, () => { setExpanded(false); setSelectedGroup(null); }, !mobile && expanded);
  useEffect(() => { setExpanded(false); setSelectedGroup(null); }, [pathname]);
  if (!user) return null;
  const entries = visiblePortalEntries(user);
  const activeGroup = entries.find(entry => entry.group && entry.path === pathname.replace(/\/+$/, ""))?.group ?? null;
  const link = (entry: typeof entries[number]) => <NavLink key={entry.path} to={entry.path} end
    aria-label={entry.label} title={entry.label} onClick={mobile ? undefined : () => { setExpanded(false); setSelectedGroup(null); }}
    className={({ isActive }) => isActive ? "portal-nav-active" : undefined}>
    {!entry.group && !mobile ? entry.path === "/portal/dashboard" ? <BarChart3 size={19} aria-hidden="true" /> : <Sparkles size={19} aria-hidden="true" /> : null}
    <span className="portal-nav-label">{entry.label}</span></NavLink>;
  const icons = { Operations: BriefcaseBusiness, Admin: Settings, "My Workspace": UserRound };
  return <div ref={menuRef} role="navigation" className={mobile ? "portal-mobile-links" : `portal-sidebar${expanded ? " portal-sidebar-expanded" : " portal-sidebar-compact"}`} aria-label="Workspace modules" onKeyDown={event => {
    if (!mobile && expanded && event.key === "Escape") { setExpanded(false); setSelectedGroup(null); toggleRef.current?.focus(); }
  }}>
    {!mobile ? <button ref={toggleRef} type="button" className="portal-rail-toggle" aria-label={expanded ? "Collapse workspace menu" : "Expand workspace menu"} aria-expanded={expanded} onClick={() => { setExpanded(!expanded); setSelectedGroup(expanded ? null : activeGroup); }}>
      {expanded ? <ChevronLeft size={19} /> : <LayoutGrid size={19} />}<span className="portal-nav-label">{expanded ? "Collapse menu" : "Expand menu"}</span>
    </button> : null}
    {entries.filter(entry => !entry.group).map(link)}
    {portalGroups.map(group => {
      const children = entries.filter(entry => entry.group === group);
      if (!children.length) return null;
      const Icon = icons[group];
      return <details className={`portal-nav-group${!mobile && activeGroup === group ? " portal-nav-group-active" : ""}`} key={`${group}:${pathname}`}
        open={mobile ? children.some(entry => entry.path === pathname.replace(/\/+$/, "")) : expanded && selectedGroup === group}>
        <summary aria-label={group} title={group} onClick={mobile ? undefined : event => {
          event.preventDefault();
          setSelectedGroup(expanded && selectedGroup === group ? null : group);
          setExpanded(true);
        }}>{!mobile ? <Icon size={19} aria-hidden="true" /> : null}<span className="portal-nav-label">{group}</span><ChevronRight aria-hidden="true" size={16} className="portal-group-chevron" /></summary>
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
