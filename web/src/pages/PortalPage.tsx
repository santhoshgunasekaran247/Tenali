import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../api";
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

const operationsLinks: PortalLink[] = [
  { label: "Parties", path: "/portal/parties", status: "live" },
  { label: "Accounts", path: "/portal/accounts", status: "live" },
  { label: "Reports & Exports", path: "/portal/reports", status: "live" },
  { label: "Borrowing & Settlements", path: "/portal/settlements", status: "live" },
  { label: "Business Payments", path: "/portal/business-payments", status: "live" },
  { label: "Receivables & Collections", path: "/portal/receivables", status: "live" },
  { label: "Sales Billing", path: "/portal/billing", status: "live" },
  { label: "Purchases", path: "/portal/purchases", status: "live" },
  { label: "Product Inventory", path: "/portal/inventory", status: "live" },
];

const adminMaintenanceLinks: PortalLink[] = [
  { label: "Company Setup", path: "/portal/company", status: "live" },
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
      { id: "start-kpi", label: "Review receivable reminders and open receivables", path: "/portal/receivables?focus=reminders" },
      { id: "start-cash", label: "Check account balances and yesterday ending", path: "/portal/accounts" },
      { id: "start-priority", label: "List today customer collections and vendor payments", path: "/portal" },
    ],
  },
  {
    key: "workday",
    title: "Working Day Loop",
    cadence: "Daily",
    steps: [
      { id: "work-sales", label: "Post sales invoices as they happen", path: "/portal/billing" },
      { id: "work-collections", label: "Record collections with payment mode + account", path: "/portal/receivables" },
      { id: "work-purchase", label: "Post purchase bills and payments", path: "/portal/purchases" },
      { id: "work-settle", label: "Capture borrow/repay settlements", path: "/portal/settlements" },
      { id: "work-funds", label: "Record business outflows and transfers", path: "/portal/business-payments" },
    ],
  },
  {
    key: "eod",
    title: "End of Day Close",
    cadence: "Daily",
    steps: [
      { id: "eod-collect", label: "Mark all reminders attempted for the day", path: "/portal/receivables?focus=reminders" },
      { id: "eod-audit", label: "Review audit journal for unusual entries", path: "/portal/accounts" },
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
      { id: "eom-ledgers", label: "Finalize account tally and month journal exports", path: "/portal/reports" },
      { id: "eom-lock", label: "Close accounting period after checks", path: "/portal/accounts" },
    ],
  },
  {
    key: "eoy",
    title: "End of Year Close",
    cadence: "Yearly",
    steps: [
      { id: "eoy-aging", label: "Finalize receivable aging and recovery plan", path: "/portal/receivables" },
      { id: "eoy-summary", label: "Freeze year-end account exports and journal", path: "/portal/reports" },
      { id: "eoy-lock", label: "Lock final year period after approval", path: "/portal/accounts" },
      { id: "eoy-reset", label: "Prepare next-year opening workflow and checklist" },
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

function checkpointStorageKey(section: WorkflowSection["key"]): string {
  return `ops-workflow:${section}:${sectionScope(section)}`;
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
  const [kpi, setKpi] = useState({
    openReceivables: 0,
    dueReminders: 0,
    badDebtCount: 0,
    netBorrowingOutstanding: 0,
    inventoryAlerts: 0,
  });
  const [kpiLoading, setKpiLoading] = useState(true);
  const [completedBySection, setCompletedBySection] = useState<Record<string, Record<string, boolean>>>({});

  useEffect(() => {
    const initial: Record<string, Record<string, boolean>> = {};
    for (const section of workflowSections) {
      const stored = window.localStorage.getItem(checkpointStorageKey(section.key));
      initial[section.key] = stored ? (JSON.parse(stored) as Record<string, boolean>) : {};
    }
    setCompletedBySection(initial);
  }, []);

  useEffect(() => {
    const loadKpi = async () => {
      setKpiLoading(true);
      try {
        const [receivableRes, reminderRes, borrowingSummaryRes, inventoryRes] = await Promise.all([
          api.receivables(),
          api.dueReceivableReminders(),
          api.borrowingSummary(),
          api.inventoryAlerts(),
        ]);

        const openReceivables = receivableRes.items.filter(
          (item) => item.status === "UNPAID" || item.status === "PARTIAL"
        ).length;
        const badDebtCount = receivableRes.items.filter((item) => item.status === "BAD_DEBT").length;
        const netBorrowingOutstanding = borrowingSummaryRes.items.reduce(
          (sum, row) => sum + row.net_outstanding,
          0
        );

        setKpi({
          openReceivables,
          dueReminders: reminderRes.items.length,
          badDebtCount,
          netBorrowingOutstanding,
          inventoryAlerts: inventoryRes.items.length,
        });
      } finally {
        setKpiLoading(false);
      }
    };

    void loadKpi();
  }, []);

  const setCompleted = (sectionKey: WorkflowSection["key"], stepId: string, checked: boolean) => {
    setCompletedBySection((prev) => {
      const nextSection = { ...(prev[sectionKey] || {}), [stepId]: checked };
      const next = { ...prev, [sectionKey]: nextSection };
      window.localStorage.setItem(checkpointStorageKey(sectionKey), JSON.stringify(nextSection));
      return next;
    });
  };

  const resetSection = (sectionKey: WorkflowSection["key"]) => {
    setCompletedBySection((prev) => {
      const next = { ...prev, [sectionKey]: {} };
      window.localStorage.removeItem(checkpointStorageKey(sectionKey));
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
          <details className="portal-workflow-disclosure">
            <summary className="portal-group-head">
              <h2>Single-Person Workflow</h2>
              <span>One sequence for day, month, and year closing</span>
            </summary>
            <div className="ops-workflow-grid">
            {workflowSections.map((section) => {
              const doneMap = completedBySection[section.key] || {};
              const doneCount = section.steps.filter((step) => doneMap[step.id]).length;
              return (
                <article className="ops-workflow-card" key={section.key}>
                  <div className="ops-workflow-card-head">
                    <h3>{section.title}</h3>
                    <span>{section.cadence}</span>
                  </div>
                  <p className="ops-workflow-progress">
                    {doneCount}/{section.steps.length} completed
                  </p>
                  <div className="ops-workflow-steps">
                    {section.steps.map((step) => (
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
          </details>
        </article>
      </section>

      <section className="portal-kpi-grid inventory-kpis">
        <Link className="portal-kpi-card portal-kpi-link" to="/portal/inventory?view=alerts"><p>Inventory Reorder Alerts</p><strong>{kpiLoading?"...":kpi.inventoryAlerts}</strong></Link>
        <Link className="portal-kpi-card portal-kpi-link" to="/portal/receivables?status=OPEN">
          <p>Open Receivables</p>
          <strong>{kpiLoading ? "..." : kpi.openReceivables}</strong>
        </Link>
        <Link className="portal-kpi-card portal-kpi-link" to="/portal/receivables?focus=reminders">
          <p>Reminders Due</p>
          <strong>{kpiLoading ? "..." : kpi.dueReminders}</strong>
        </Link>
        <Link className="portal-kpi-card portal-kpi-link" to="/portal/receivables?status=BAD_DEBT">
          <p>Bad Debt Cases</p>
          <strong>{kpiLoading ? "..." : kpi.badDebtCount}</strong>
        </Link>
        <Link className="portal-kpi-card portal-kpi-link" to="/portal/settlements">
          <p>Net Borrowing Outstanding</p>
          <strong>
            {kpiLoading
              ? "..."
              : kpi.netBorrowingOutstanding.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
          </strong>
        </Link>
      </section>

      <section className="portal-groups">
        {showAdminMaintenance?<article className="portal-group-card">
          <div className="portal-group-head">
            <h2>Operations</h2>
            <span>Daily execution modules</span>
          </div>
          <div className="portal-grid">
            {operationsLinks.map((item) => (
              <LinkTile key={item.label} item={item} />
            ))}
          </div>
        </article>:null}

        <article className="portal-group-card">
          <div className="portal-group-head">
            <h2>Admin & Maintenance</h2>
            <span>Governance, setup, and controls</span>
          </div>
          <div className="portal-grid">
            {adminMaintenanceLinks.map((item) => (
              <LinkTile key={item.label} item={item} />
            ))}
          </div>
        </article>
      </section>
    </div>
  );
}
