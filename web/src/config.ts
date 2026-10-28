export type ModuleKey = "dashboard" | "catalogue" | "vendor-contributions" | "sales" | "purchases" | "accounts" | "parties" | "employees" | "reports" | "company" | "audit" | "admin";

export type NavItem = {
  key: ModuleKey;
  label: string;
  description: string;
};

export const navigation: NavItem[] = [
  { key: "dashboard", label: "Dashboard", description: "Business overview and alerts" },
  { key: "catalogue", label: "Catalogue & Stock", description: "Products, stock and reorder" },
  { key: "vendor-contributions", label: "Vendor Contributions", description: "Vendor product and pricing data" },
  { key: "sales", label: "Sales & Invoices", description: "Sales, billing and invoices" },
  { key: "purchases", label: "Purchases, Expenses & Documents", description: "Purchases, expenses and files" },
  { key: "accounts", label: "Money & Accounts", description: "Money movement and settlements" },
  { key: "parties", label: "Customers & Vendors", description: "Party master" },
  { key: "employees", label: "Employees & Payroll", description: "Employees and salary" },
  { key: "reports", label: "Reports & Tally", description: "Reports and reconciliation" },
  { key: "company", label: "Company Configuration", description: "Company and system configuration" },
  { key: "audit", label: "Audit & Export", description: "Audit trail and exports" },
  { key: "admin", label: "Admin", description: "Users, roles and menu administration" }
];
