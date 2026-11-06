import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { useAuth } from "../features/auth";

type PortalLink = {
  label: string;
  path?: string;
  status?: "live" | "coming";
};

type WorkflowSection = {
  key: "start" | "workday" | "eod" | "eom" | "eoy";
  title: string;
  cadence: string;
  steps: Array<{ id: string; label: string; path?: string }>;
};

const operationsLinks: (PortalLink & { module: string })[] = [
  { label: "Parties", path: "/portal/parties", status: "live", module: "parties" },
  { label: "Accounts", path: "/portal/accounts", status: "live", module: "accounts" },
  { label: "Reports & Exports", path: "/portal/reports", status: "live", module: "reports" },
  { label: "Borrowing & Settlements", path: "/portal/settlements", status: "live", module: "settlements" },
  { label: "Refund Settlements", path: "/portal/settlements/refunds", status: "live", module: "settlements" },
  { label: "Business Payments", path: "/portal/business-payments", status: "live", module: "accounts" },
  { label: "Receivables & Collections", path: "/portal/receivables", status: "live", module: "receivables" },
  { label: "Sales Billing", path: "/portal/billing", status: "live", module: "billing" },
  { label: "Purchases", path: "/portal/purchases", status: "live", module: "purchases" },
  { label: "Product Inventory", path: "/portal/inventory", status: "live", module: "inventory" },
];

const adminMaintenanceLinks: PortalLink[] = [
  { label: "Online Customers", path: "/portal/online-customers", status: "live" },
  { label: "Company Setup", path: "/portal/company", status: "live" },
  { label: "Store Policies", path: "/portal/policies", status: "live" },
  { label: "Stores & Warehouses", path: "/portal/stores", status: "live" },
  { label: "Users & Roles",path:"/portal/team",status:"live" },
  { label: "Storefront Domains",path:"/portal/domains",status:"live" },
  { label: "Audit Events", path:"/portal/audit",status:"live" },
  { label: "Master Data", path: "/portal/masters", status: "live" },
  { label: "Shopper Checkout & Orders", path: "/portal/checkout", status: "live" },
];

const workflowSections: WorkflowSection[] = [
  {
    key: "start",
    title: "Start of Day",
    cadence: "Daily",
    steps: [
      { id: "start-dashboard", label: "Open the dashboard: receivables, pending refunds and low stock", path: "/portal/dashboard" },
      { id: "start-kpi", label: "Review receivable reminders and open receivables", path: "/portal/receivables?focus=reminders" },
      { id: "start-cash", label: "Check account balances match yesterday's closing cash and bank", path: "/portal/accounts" },
      { id: "start-refunds", label: "Check pending refunds to pay customers or receive from vendors", path: "/portal/settlements/refunds" },
      { id: "start-reorder", label: "Review reorder alerts and place purchase orders", path: "/portal/inventory?view=alerts" },
      { id: "start-receipts", label: "Check purchases awaiting goods receipt", path: "/portal/purchases" },
      { id: "start-online", label: "Process online orders and COD settlements", path: "/portal/checkout" },
      { id: "start-priority", label: "List today's customer collections and vendor payments" },
    ],
  },
  {
    key: "workday",
    title: "Working Day Loop",
    cadence: "Daily",
    steps: [
      { id: "work-sales", label: "Post sales invoices as they happen", path: "/portal/billing" },
      { id: "work-collections", label: "Record collections with payment mode + account", path: "/portal/receivables" },
      { id: "work-purchase", label: "Post purchase bills and vendor payments", path: "/portal/purchases" },
      { id: "work-receipt", label: "Confirm goods receipt so purchased stock is added", path: "/portal/purchases" },
      { id: "work-drafts", label: "Confirm or merge new product drafts from purchases", path: "/portal/inventory" },
      { id: "work-transfer", label: "Transfer stock between stores when needed", path: "/portal/inventory" },
      { id: "work-settle", label: "Capture borrow/repay settlements", path: "/portal/settlements" },
      { id: "work-cancel", label: "Cancel wrong invoices or bills (reverse, don't delete), then reissue", path: "/portal/billing" },
      { id: "work-refunds", label: "Confirm refunds for cancelled invoices and bills", path: "/portal/settlements/refunds" },
      { id: "work-funds", label: "Record business outflows and transfers", path: "/portal/business-payments" },
    ],
  },
  {
    key: "eod",
    title: "End of Day Close",
    cadence: "Daily",
    steps: [
      { id: "eod-cash", label: "Count cash and match it with the account tally", path: "/portal/accounts" },
      { id: "eod-refunds", label: "Settle refunds paid out today", path: "/portal/settlements/refunds" },
      { id: "eod-collect", label: "Mark all reminders attempted for the day", path: "/portal/receivables?focus=reminders" },
      { id: "eod-audit", label: "Review audit journal for unusual entries", path: "/portal/accounts" },
      { id: "eod-events", label: "Review audit events (deletions, cancellations, logins)", path: "/portal/audit" },
      { id: "eod-export", label: "Export transactions and journal CSV backup", path: "/portal/reports" },
      { id: "eod-pending", label: "Note pending payments/collections for tomorrow", path: "/portal/receivables?status=OPEN" },
    ],
  },
  {
    key: "eom",
    title: "End of Month Close",
    cadence: "Monthly",
    steps: [
      { id: "eom-reconcile", label: "Run invoice reconciliation and verify receivable status", path: "/portal/billing" },
      { id: "eom-baddebt", label: "Review stale dues and mark bad debt where needed", path: "/portal/receivables?status=BAD_DEBT" },
      { id: "eom-refunds", label: "Settle every pending refund before closing", path: "/portal/settlements/refunds" },
      { id: "eom-receipts", label: "Confirm all pending goods receipts and vendor payments", path: "/portal/purchases" },
      { id: "eom-stock", label: "Run the stock check and fix differences", path: "/portal/inventory?view=check" },
      { id: "eom-gst", label: "Export sales and purchase GST registers; match purchases with GSTR-2B", path: "/portal/reports" },
      { id: "eom-ledgers", label: "Finalize account tally and month journal exports", path: "/portal/reports" },
      { id: "eom-lock", label: "Lock the month: Accounts → Period Close / Lock", path: "/portal/accounts#period-locks" },
      { id: "eom-reopen", label: "Correction needed later? Reopen the period, reverse and re-post, then lock again", path: "/portal/accounts#period-locks" },
    ],
  },
  {
    key: "eoy",
    title: "End of Year Close",
    cadence: "Yearly",
    steps: [
      { id: "eoy-months", label: "Confirm every month of the financial year (Apr–Mar) is locked", path: "/portal/accounts#period-locks" },
      { id: "eoy-aging", label: "Finalize receivable aging and recovery plan", path: "/portal/receivables" },
      { id: "eoy-stock", label: "Physical year-end stock count and stock check", path: "/portal/inventory?view=check" },
      { id: "eoy-summary", label: "Freeze year-end account exports, GST registers and journal", path: "/portal/reports" },
      { id: "eoy-lock", label: "Lock the full financial year after approval", path: "/portal/accounts#period-locks" },
      { id: "eoy-reset", label: "Prepare next-year opening balances and checklist", path: "/portal/accounts" },
    ],
  },
];

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthKey(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function yearKey(): string {
  return String(new Date().getFullYear());
}

function sectionScope(section: WorkflowSection["key"]): string {
  if (section === "eom") return monthKey();
  if (section === "eoy") return yearKey();
  return todayKey();
}

function checkpointStorageKey(company: string, user: string, section: WorkflowSection["key"]): string {
  return `ops-workflow:${company}:${user}:${section}:${sectionScope(section)}`;
}

function LinkTile({ item }: { item: PortalLink }) {
  const classes = `portal-tile ${item.status === "coming" ? "coming" : ""}`;
  if (!item.path) {
    return (
      <div className={classes}>
        <strong>{item.label}</strong>
        <span>Coming soon</span>
      </div>
    );
  }

  return (
    <Link className={classes} to={item.path}>
      <strong>{item.label}</strong>
      <span>Open module</span>
    </Link>
  );
}

export function PortalPage() {
  const auth=useAuth();
  const showAdminMaintenance=auth.user?.role==='owner'||auth.user?.role==='admin';
  const canAccess = (path?: string) => {
    const base = path?.split(/[?#]/)[0];
    if (adminMaintenanceLinks.some(item => item.path === base)) return showAdminMaintenance;
    const module = operationsLinks.find(item => item.path === base)?.module;
    return !module || showAdminMaintenance || !auth.user?.modules || auth.user.modules.includes(module);
  };
  const storageKey = (section: WorkflowSection["key"]) => checkpointStorageKey(auth.user!.company_id, auth.user!.user_id, section);
  const [completedBySection, setCompletedBySection] = useState<Record<string, Record<string, boolean>>>({});

  useEffect(() => {
    const initial: Record<string, Record<string, boolean>> = {};
    for (const section of workflowSections) {
      const stored = window.localStorage.getItem(storageKey(section.key));
      initial[section.key] = stored ? (JSON.parse(stored) as Record<string, boolean>) : {};
    }
    setCompletedBySection(initial);
  }, [auth.user?.company_id, auth.user?.user_id]);

  const setCompleted = (sectionKey: WorkflowSection["key"], stepId: string, checked: boolean) => {
    setCompletedBySection((prev) => {
      const nextSection = { ...(prev[sectionKey] || {}), [stepId]: checked };
      const next = { ...prev, [sectionKey]: nextSection };
      window.localStorage.setItem(storageKey(sectionKey), JSON.stringify(nextSection));
      return next;
    });
  };

  const resetSection = (sectionKey: WorkflowSection["key"]) => {
    setCompletedBySection((prev) => {
      const next = { ...prev, [sectionKey]: {} };
      window.localStorage.removeItem(storageKey(sectionKey));
      return next;
    });
  };

  return (
    <div className="ops-page">
      <section className="ops-hero">
        <p className="eyebrow">Unified Workspace</p>
        <h1>Operations Portal</h1>
        <p>
          Modules are grouped by business flow so teams can move faster. Admin and
          maintenance functions are consolidated into one control area.
        </p>
      </section>

      <section className="portal-groups">
        <article className="portal-group-card">
          <div className="portal-group-head">
            <h2>Operations Dashboard</h2>
            <span>Sales, inventory and purchasing at a glance</span>
          </div>
          <Link className="btn" to="/portal/dashboard">Open Dashboard</Link>
        </article>
      </section>

      <section className="portal-groups">
        <article className="portal-group-card">
          <details className="portal-workflow-disclosure">
            <summary className="portal-group-head">
              <h2>Single-Person Workflow</h2>
              <span>One sequence for day, month, and year closing</span>
            </summary>
            <div className="ops-workflow-grid">
            {workflowSections.map((section) => {
              const doneMap = completedBySection[section.key] || {};
              const visibleSteps = section.steps.filter(step => canAccess(step.path));
              const doneCount = visibleSteps.filter((step) => doneMap[step.id]).length;
              return (
                <article className="ops-workflow-card" key={section.key}>
                  <div className="ops-workflow-card-head">
                    <h3>{section.title}</h3>
                    <span>{section.cadence}</span>
                  </div>
                  <p className="ops-workflow-progress">
                    {doneCount}/{visibleSteps.length} completed
                  </p>
                  <div className="ops-workflow-steps">
                    {visibleSteps.map((step) => (
                      <label className="ops-workflow-step" key={step.id}>
                        <input
                          type="checkbox"
                          checked={Boolean(doneMap[step.id])}
                          onChange={(event) =>
                            setCompleted(section.key, step.id, event.target.checked)
                          }
                        />
                        <span>{step.label}</span>
                        {step.path ? (
                          <Link className="ops-inline-link" to={step.path}>
                            Open
                          </Link>
                        ) : null}
                      </label>
                    ))}
                  </div>
                  <button className="ops-link-btn" type="button" onClick={() => resetSection(section.key)}>
                    Reset this checklist
                  </button>
                </article>
              );
            })}
            </div>
            <p className="ops-copy-note">Locked periods block new, cancelled or deleted entries dated inside them; reopen, correct and lock again. After each save a &quot;Next step&quot; message suggests what to do next{showAdminMaintenance ? <> (turn it on or off in <Link to="/portal/company#portal-settings">Company Setup → Operations Portal</Link>)</> : null}.</p>
          </details>
        </article>
      </section>

      <section className="portal-groups">
        <article className="portal-group-card">
          <div className="portal-group-head">
            <h2>Operations</h2>
            <span>Daily execution modules</span>
          </div>
          <div className="portal-grid">
            {operationsLinks.filter((item) => !auth.user?.modules || ["owner", "admin"].includes(auth.user.role) || auth.user.modules.includes(item.module)).map((item) => (
              <LinkTile key={item.label} item={item} />
            ))}
          </div>
        </article>

        {showAdminMaintenance?<article className="portal-group-card">
          <div className="portal-group-head">
            <h2>Admin & Maintenance</h2>
            <span>Governance, setup, and controls</span>
          </div>
          <div className="portal-grid">
            {adminMaintenanceLinks.map((item) => (
              <LinkTile key={item.label} item={item} />
            ))}
          </div>
        </article>:null}
      </section>
    </div>
  );
}
