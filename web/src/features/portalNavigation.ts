import type { Identity } from "./auth";

type PortalGroup = "Operations" | "Admin" | "My Workspace";
type PortalEntry = { label: string; path: string; module?: string; admin?: boolean; group?: PortalGroup };
export const portalGroups: PortalGroup[] = ["Operations", "Admin", "My Workspace"];

export const portalEntries: PortalEntry[] = [
  { label: "Operations Portal", path: "/portal", group: "My Workspace" },
  { label: "Dashboard", path: "/portal/dashboard" },
  { label: "Tenali AI", path: "/portal/ai" },
  { label: "Online Orders", path: "/portal/checkout", admin: true, group: "Operations" },
  { label: "Sales & Quotations", path: "/portal/billing", module: "billing", group: "Operations" },
  { label: "Purchases", path: "/portal/purchases", module: "purchases", group: "Operations" },
  { label: "Product Inventory", path: "/portal/inventory", module: "inventory", group: "Operations" },
  { label: "Bulk Upload", path: "/portal/bulk-upload", admin: true, group: "Operations" },
  { label: "Brands", path: "/portal/masters/brands", module: "inventory", group: "Operations" },
  { label: "Categories", path: "/portal/masters/categories", module: "inventory", group: "Operations" },
  { label: "HSN / GST", path: "/portal/masters/hsn", module: "masters", group: "Operations" },
  { label: "Contacts", path: "/portal/parties", module: "parties", group: "Operations" },
  { label: "Accounts", path: "/portal/accounts", module: "accounts", group: "Operations" },
  { label: "Business Payments", path: "/portal/business-payments", module: "accounts", group: "Operations" },
  { label: "Receivables & Collections", path: "/portal/receivables", module: "receivables", group: "Operations" },
  { label: "Borrowing & Lending", path: "/portal/settlements", module: "settlements", group: "Operations" },
  { label: "Refund Settlements", path: "/portal/settlements/refunds", module: "settlements", group: "Operations" },
  { label: "Reports & Exports", path: "/portal/reports", module: "reports", group: "Operations" },
  { label: "Company Setup", path: "/portal/company", admin: true, group: "Admin" },
  { label: "Stores & Warehouses", path: "/portal/stores", admin: true, group: "Admin" },
  { label: "Users & Roles", path: "/portal/team", admin: true, group: "Admin" },
  { label: "Storefront Design", path: "/portal/storefront-design", admin: true, group: "Admin" },
  { label: "Storefront Domains", path: "/portal/domains", admin: true, group: "Admin" },
  { label: "Store Policies", path: "/portal/policies", admin: true, group: "Admin" },
  { label: "Payments & Delivery Setup", path: "/portal/checkout-setup", admin: true, group: "Admin" },
  { label: "Online Customers", path: "/portal/online-customers", admin: true, group: "Admin" },
  { label: "Audit Events", path: "/portal/audit", admin: true, group: "Admin" },
  { label: "My Account", path: "/portal/account", group: "My Workspace" },
  { label: "New Workspace", path: "/portal/new-workspace", group: "My Workspace" },
];

export function visiblePortalEntries(user: Identity) {
  const admin = user.role === "owner" || user.role === "admin";
  return portalEntries.filter(entry => (!entry.admin || admin) &&
    (!entry.module || admin || !user.modules || user.modules.includes(entry.module)));
}
