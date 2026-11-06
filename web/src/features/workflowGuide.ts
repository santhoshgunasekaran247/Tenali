export type WorkflowStep = { label: string; path?: string };
export type WorkflowGuidance = { title: string; steps: WorkflowStep[]; note?: string };
export type WorkflowResult = { method: string; path: string; ok: boolean; status?: number; data?: unknown; message?: string };

type Data = Record<string, unknown>;
type Rule = { method: string; pattern: RegExp; guide: (data: Data) => WorkflowGuidance | null };

const TALLY: WorkflowStep = { label: "Check the account tally matches your cash and bank", path: "/portal/accounts" };
const ID = "[^/]+";
const route = (method: string, path: string, guide: Rule["guide"]): Rule => ({ method, pattern: new RegExp(`^${path.replace(/:id/g, ID)}$`), guide });
const asData = (value: unknown): Data => (value && typeof value === "object" ? value as Data : {});

const SUCCESS_RULES: Rule[] = [
  route("POST", "/billing/invoices", data => ({
    title: "Invoice created",
    steps: [
      ...(data.collection_status && data.collection_status !== "SETTLED" ? [{ label: "Record the customer payment when it arrives, or set a reminder", path: "/portal/receivables" }] : []),
      { label: "Share or print the invoice PDF", path: "/portal/billing" },
      { label: "Check reorder alerts for the items sold", path: "/portal/inventory?view=alerts" },
    ],
  })),
  route("POST", "/billing/invoices/:id/cancel", data => cancelled("Invoice cancelled", data, [
    { label: "Issue a corrected invoice if the sale still stands", path: "/portal/billing" },
  ], "If the invoice was already reported in a filed GSTR-1, also record a credit note in your GST return.")),
  route("POST", "/purchases/:id/cancel", data => cancelled("Purchase bill cancelled", data, [
    { label: "Record the corrected bill if goods were still bought", path: "/portal/purchases" },
  ], "If the vendor already reported this bill, ask them for a credit note so GSTR-2B matches.")),
  route("POST", "/purchases", data => ({
    title: "Purchase recorded",
    steps: [
      ...(data.receipt_status === "PENDING" ? [{ label: "Confirm receipt when the goods arrive so stock is added", path: "/portal/purchases" }] : [{ label: "Review new product drafts and stock", path: "/portal/inventory" }]),
      ...(data.payment_status && data.payment_status !== "PAID" ? [{ label: "Pay the vendor and record the payment", path: "/portal/purchases" }] : []),
      { label: "Attach the vendor bill", path: "/portal/purchases" },
    ],
  })),
  route("POST", "/purchases/:id/payments", data => ({
    title: "Vendor payment recorded",
    steps: [
      ...(data.payment_status && data.payment_status !== "PAID" ? [{ label: "A balance is still due to this vendor", path: "/portal/purchases" }] : []),
      TALLY,
    ],
  })),
  route("POST", "/purchases/:id/confirm-receipt", () => ({
    title: "Goods received",
    steps: [
      { label: "Confirm or merge any new product drafts", path: "/portal/inventory" },
      { label: "Set selling price and reorder level for new items", path: "/portal/inventory" },
    ],
  })),
  route("POST", "/collections/receivables", () => ({
    title: "Receivable added",
    steps: [{ label: "Set a due date and reminder so it is followed up", path: "/portal/receivables" }],
  })),
  route("POST", "/collections/receivables/:id/payments", () => ({
    title: "Customer payment recorded",
    steps: [
      TALLY,
      { label: "If a balance is still open, set the next reminder", path: "/portal/receivables" },
    ],
  })),
  route("POST", "/collections/receivables/:id/remind", () => ({
    title: "Reminder logged",
    steps: [{ label: "Review pending reminders again tomorrow", path: "/portal/receivables" }],
  })),
  route("POST", "/accounts/transactions", () => ({
    title: "Transaction posted",
    steps: [TALLY, { label: "Attach the receipt or bill if you have one", path: "/portal/accounts" }],
  })),
  route("POST", "/accounts/transactions/:id/reverse", () => ({
    title: "Transaction reversed",
    steps: [{ label: "Post the corrected entry", path: "/portal/accounts" }, TALLY],
  })),
  route("POST", "/accounts/period-locks", () => ({
    title: "Period closed",
    steps: [
      { label: "Export the journal and GST registers for your accountant", path: "/portal/reports" },
      { label: "Start the next period with the daily checklist", path: "/portal" },
    ],
    note: "Entries dated inside this period are now blocked until an owner or admin reopens it.",
  })),
  route("POST", "/accounts/period-locks/:id/reopen", () => ({
    title: "Period reopened",
    steps: [
      { label: "Make the corrections (reverse and re-post, cancel, or delete)", path: "/portal/accounts" },
      { label: "Close the period again once corrections are done", path: "/portal/accounts#period-locks" },
    ],
  })),
  route("POST", "/settlements/borrowings", () => ({
    title: "Borrowing recorded",
    steps: [{ label: "Check the borrowing summary and repayment plan", path: "/portal/settlements" }, TALLY],
  })),
  route("POST", "/settlements/refunds/:id/settle", () => ({
    title: "Refund settled",
    steps: [{ label: "Settle any other pending refunds", path: "/portal/settlements/refunds" }, TALLY],
  })),
  route("POST", "/accounts/business-payments", () => ({
    title: "Business payment recorded",
    steps: [{ label: "Attach the bill or receipt", path: "/portal/business-payments" }, TALLY],
  })),
  route("POST", "/company/deletions", () => ({
    title: "Record deleted",
    steps: [
      TALLY,
      { label: "Review stock if inventory was affected", path: "/portal/inventory" },
      { label: "Re-enter the record if it was deleted by mistake", path: "/portal" },
    ],
  })),
  route("POST", "/inventory/transfers", () => ({
    title: "Stock transferred",
    steps: [{ label: "Check stock at the destination store", path: "/portal/inventory" }],
  })),
  route("POST", "/inventory/transfers/:id/reverse", () => ({
    title: "Transfer reversed",
    steps: [{ label: "Record the corrected transfer if needed", path: "/portal/inventory" }],
  })),
  route("POST", "/inventory/products/:id/stock", () => ({
    title: "Stock adjusted",
    steps: [
      { label: "Review reorder alerts", path: "/portal/inventory?view=alerts" },
      { label: "Run a stock check against the books", path: "/portal/inventory?view=check" },
    ],
  })),
  route("POST", "/inventory/products", productReady),
  route("POST", "/inventory/products/:id/confirm", productReady),
  route("POST", "/inventory/products/:id/merge", () => ({
    title: "Draft merged",
    steps: [{ label: "Check the merged stock and vendor offers", path: "/portal/inventory" }],
  })),
  route("DELETE", "/inventory/products/:id", () => ({
    title: "Product deleted",
    steps: [{ label: "Run a stock check to confirm totals", path: "/portal/inventory?view=check" }],
  })),
  route("POST", "/parties", partyReady),
  route("POST", "/billing/customers", partyReady),
  route("POST", "/accounts", () => ({
    title: "Account created",
    steps: [{ label: "Post the opening balance or first transaction", path: "/portal/accounts" }],
  })),
];

function cancelled(title: string, data: Data, next: WorkflowStep[], note: string): WorkflowGuidance {
  const refunds = Array.isArray(data.refunds) ? data.refunds.length : 0;
  return {
    title,
    steps: [
      ...(refunds ? [{ label: `Settle ${refunds} pending refund${refunds === 1 ? "" : "s"}: confirm the account and mode used`, path: "/portal/settlements/refunds" }] : []),
      ...next,
    ],
    note,
  };
}

function productReady(): WorkflowGuidance {
  return {
    title: "Product ready",
    steps: [
      { label: "Set the selling price and reorder level", path: "/portal/inventory" },
      { label: "Add vendor offers so purchases can pick this item", path: "/portal/inventory" },
    ],
  };
}

function partyReady(): WorkflowGuidance {
  return {
    title: "Party saved",
    steps: [
      { label: "Create an invoice for this customer", path: "/portal/billing" },
      { label: "Record a purchase from this vendor", path: "/portal/purchases" },
    ],
  };
}

const FAILURE_RULES: { pattern: RegExp; guide: (match: RegExpMatchArray) => WorkflowGuidance }[] = [
  {
    pattern: /Period (\S+) to (\S+) is closed/i,
    guide: match => ({
      title: "This date is in a closed period",
      steps: [
        { label: "Use a date in an open period" },
        { label: "Or reopen it under Accounts → Period Close / Lock (needs Accounts access)", path: "/portal/accounts#period-locks" },
        { label: "Correct the entry, then close the period again" },
      ],
      note: `Closed period: ${match[1]} to ${match[2]}.`,
    }),
  },
  {
    pattern: /does not include the (\w+) module/i,
    guide: match => ({
      title: "Module access needed",
      steps: [{ label: `Ask an owner or admin to grant the ${match[1]} module in Users & Roles`, path: "/portal/team" }],
    }),
  },
  {
    pattern: /Refresh the page before submitting/i,
    guide: () => ({ title: "The record changed elsewhere", steps: [{ label: "Reload the page, then submit again" }] }),
  },
  {
    pattern: /(cannot become negative|reserved by online orders|not enough available stock|transfer stock or decline)/i,
    guide: () => ({
      title: "Not enough stock",
      steps: [
        { label: "Record the purchase or confirm the pending receipt first", path: "/portal/purchases" },
        { label: "Or transfer stock from another store", path: "/portal/inventory" },
      ],
    }),
  },
];

export function nextSteps(result: WorkflowResult): WorkflowGuidance | null {
  const method = result.method.toUpperCase();
  if (method === "GET") return null;
  if (!result.ok) {
    const message = result.message || "";
    for (const rule of FAILURE_RULES) {
      const match = message.match(rule.pattern);
      if (match) return rule.guide(match);
    }
    return null;
  }
  const path = result.path.split("?")[0].replace(/\/+$/, "");
  const rule = SUCCESS_RULES.find(candidate => candidate.method === method && candidate.pattern.test(path));
  const guidance = rule ? rule.guide(asData(result.data)) : null;
  return guidance && guidance.steps.length ? guidance : null;
}
