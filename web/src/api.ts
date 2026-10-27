import type {
  InventoryAlert, InventoryLookups, InventoryMovement, InventoryOfferInput, InventoryProduct, InventoryProductInput, InventoryItemInput,
  SiteTheme,
  Attachment,
  AttachmentEntity,
  AttachmentInput,
  HsnMaster,
  HsnMasterInput,
  HsnMasterUpdateInput,
  CompanySetup,
  CompanyUpdateInput,
  Account,
  AccountCreateInput,
  AccountListResponse,
  AccountTransaction,
  AccountTransactionCreateInput,
  AccountTransactionListResponse,
  PeriodLock,
  PeriodLockCreateInput,
  PeriodLockListResponse,
  PeriodLockReopenInput,
  AccountTallyResponse,
  AccountUpdateInput,
  AuditJournalResponse,
  BusinessPaymentCreateInput,
  BusinessPaymentResponse,
  BorrowingEntry,
  BorrowingEntryCreateInput,
  BorrowingListResponse,
  BorrowingSummaryResponse,
  CatalogHomeResponse,
  CatalogListResponse,
  CatalogProductResponse,
  Party,
  PartyCreateInput,
  Invoice,
  InvoiceCreateInput,
  InvoiceListResponse,
  InvoiceReconcileResponse,
  InvoiceReconcileRunListResponse,
  Purchase,
  PurchaseCreateInput,
  PurchaseListResponse,
  PurchasePaymentCreateInput,
  PurchasePaymentListResponse,
  PurchaseReceiptConfirmInput,
  PartyListResponse,
  PartyUpdateInput,
  Receivable,
  ReceivableCreateInput,
  ReceivableListResponse,
  ReceivablePayment,
  ReceivablePaymentCreateInput,
  ReceivableReminderLogListResponse,
  ReceivableReminderUpdateInput,
  ReceivableStatusUpdateInput,
  TransactionReverseCreateInput,
  TransactionReverseResponse,
} from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return response.json();
}

export const api = {
  inventoryProducts: () => request<{ items: InventoryProduct[] }>("/inventory/products"),
  inventoryLookups: () => request<InventoryLookups>("/inventory/lookups"),
  inventoryCreateLookup: (kind: "brands" | "categories", name: string) => request<{id: string; name: string; code: string}>(`/inventory/lookups/${kind}`, {method:"POST",body:JSON.stringify({name})}),
  inventorySaveProduct: (payload: InventoryProductInput, id?: string) => request<InventoryProduct>(`/inventory/products${id ? `/${encodeURIComponent(id)}` : ""}`, {method:id ? "PUT" : "POST",body:JSON.stringify(payload)}),
  inventorySaveVariant: (product: string, payload: InventoryItemInput & {variant_name: string}, id?: string) => request<InventoryProduct>(`/inventory/products/${encodeURIComponent(product)}/variants${id ? `/${encodeURIComponent(id)}` : ""}`, {method:id ? "PUT" : "POST",body:JSON.stringify(payload)}),
  inventorySaveOffer: (product: string, payload: InventoryOfferInput, id?: string) => request<InventoryProduct>(`/inventory/products/${encodeURIComponent(product)}/offers${id ? `/${encodeURIComponent(id)}` : ""}`, {method:id ? "PUT" : "POST",body:JSON.stringify(payload)}),
  inventoryBulkMap: (vendor_id: string, product_ids: string[]) => request<{mapped_count:number}>("/inventory/products/vendor-mappings", {method:"POST",body:JSON.stringify({vendor_id,product_ids})}),
  inventoryAdjustStock: (product: string, payload: {variant_id:string|null;direction:"IN"|"OUT";quantity:number;notes:string}) => request<InventoryProduct>(`/inventory/products/${encodeURIComponent(product)}/stock`, {method:"POST",body:JSON.stringify(payload)}),
  inventoryMovements: (product: string) => request<{items:InventoryMovement[]}>(`/inventory/products/${encodeURIComponent(product)}/movements`),
  inventoryAlerts: () => request<{items:InventoryAlert[]}>("/inventory/alerts"),
  inventoryRemind: (product:string,variant_id:string|null,reminder_date:string) => request<{items:InventoryAlert[]}>(`/inventory/products/${encodeURIComponent(product)}/reminder`, {method:"PUT",body:JSON.stringify({variant_id,reminder_date})}),
  attachments: (entity: AttachmentEntity, id: string) => request<{ items: Attachment[] }>(
    `/documents/${entity}/${encodeURIComponent(id)}`
  ),
  uploadAttachments: (entity: AttachmentEntity, id: string, items: AttachmentInput[]) => request<{ items: Attachment[] }>(
    `/documents/${entity}/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ items }) }
  ),
  async downloadAttachment(id: string) {
    const response = await fetch(`${API_BASE}/documents/${encodeURIComponent(id)}/download`);
    if (!response.ok) throw new Error(await response.text() || "Unable to download attachment.");
    return response.blob();
  },
  hsnMasters: (filters?: { active_only?: boolean; search?: string }) => {
    const params = new URLSearchParams();
    if (filters?.active_only !== undefined) params.set("active_only", String(filters.active_only));
    if (filters?.search) params.set("search", filters.search);
    return request<{ items: HsnMaster[] }>(`/masters/hsn?${params}`);
  },
  createHsnMaster: (payload: HsnMasterInput) => request<HsnMaster>("/masters/hsn", {
    method: "POST", body: JSON.stringify(payload),
  }),
  updateHsnMaster: (id: string, payload: HsnMasterUpdateInput) => request<HsnMaster>(`/masters/hsn/${encodeURIComponent(id)}`, {
    method: "PUT", body: JSON.stringify(payload),
  }),
  company: () => request<CompanySetup>("/company"),
  updateSiteTheme: (theme: SiteTheme) => request<CompanySetup>("/company/site-theme", {
    method: "PUT", body: JSON.stringify(theme),
  }),
  updateCompany: (payload: CompanyUpdateInput) => request<CompanySetup>("/company", {
    method: "PUT",
    body: JSON.stringify(payload),
  }),
  home: () => request<CatalogHomeResponse>("/catalog/home"),
  async list(filters?: { brand?: string; category?: string }) {
    const params = new URLSearchParams();
    if (filters?.brand) params.set("brand", filters.brand);
    if (filters?.category) params.set("category", filters.category);
    const qs = params.toString();
    return request<CatalogListResponse>(`/catalog/list${qs ? `?${qs}` : ""}`);
  },
  product: (productId: string) =>
    request<CatalogProductResponse>(`/catalog/products/${encodeURIComponent(productId)}`),
  async parties(filters?: { search?: string; active_only?: boolean }) {
    const params = new URLSearchParams();
    if (filters?.search) params.set("search", filters.search);
    if (typeof filters?.active_only === "boolean") {
      params.set("active_only", String(filters.active_only));
    }
    const qs = params.toString();
    return request<PartyListResponse>(`/parties${qs ? `?${qs}` : ""}`);
  },
  createParty(payload: PartyCreateInput) {
    return request<Party>("/parties", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  updateParty(partyId: string, payload: PartyUpdateInput) {
    return request<Party>(`/parties/${encodeURIComponent(partyId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  async accounts(filters?: { active_only?: boolean }) {
    const params = new URLSearchParams();
    if (typeof filters?.active_only === "boolean") {
      params.set("active_only", String(filters.active_only));
    }
    const qs = params.toString();
    return request<AccountListResponse>(`/accounts${qs ? `?${qs}` : ""}`);
  },
  createAccount(payload: AccountCreateInput) {
    return request<Account>("/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  updateAccount(accountId: string, payload: AccountUpdateInput) {
    return request<Account>(`/accounts/${encodeURIComponent(accountId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  async accountTransactions(filters?: {
    limit?: number;
    account_id?: string;
    from_date?: string;
    to_date?: string;
    category?: string;
    source_type?: string;
  }) {
    const params = new URLSearchParams();
    if (typeof filters?.limit === "number") {
      params.set("limit", String(filters.limit));
    }
    if (filters?.account_id) params.set("account_id", filters.account_id);
    if (filters?.from_date) params.set("from_date", filters.from_date);
    if (filters?.to_date) params.set("to_date", filters.to_date);
    if (filters?.category) params.set("category", filters.category);
    if (filters?.source_type) params.set("source_type", filters.source_type);
    const qs = params.toString();
    return request<AccountTransactionListResponse>(
      `/accounts/transactions${qs ? `?${qs}` : ""}`
    );
  },
  async accountTally(filters?: { as_of?: string; include_inactive?: boolean }) {
    const params = new URLSearchParams();
    if (filters?.as_of) params.set("as_of", filters.as_of);
    if (typeof filters?.include_inactive === "boolean") {
      params.set("include_inactive", String(filters.include_inactive));
    }
    const qs = params.toString();
    return request<AccountTallyResponse>(`/accounts/tally${qs ? `?${qs}` : ""}`);
  },
  async accountAuditJournal(filters?: {
    period?: "daily" | "weekly" | "monthly" | "yearly";
    from_date?: string;
    to_date?: string;
    category?: string;
    source_type?: string;
    limit?: number;
  }) {
    const params = new URLSearchParams();
    if (filters?.period) params.set("period", filters.period);
    if (filters?.from_date) params.set("from_date", filters.from_date);
    if (filters?.to_date) params.set("to_date", filters.to_date);
    if (filters?.category) params.set("category", filters.category);
    if (filters?.source_type) params.set("source_type", filters.source_type);
    if (typeof filters?.limit === "number") params.set("limit", String(filters.limit));
    const qs = params.toString();
    return request<AuditJournalResponse>(`/accounts/journal${qs ? `?${qs}` : ""}`);
  },
  createAccountTransaction(payload: AccountTransactionCreateInput) {
    return request<AccountTransaction>("/accounts/transactions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  reverseAccountTransaction(transactionId: string, payload: TransactionReverseCreateInput) {
    return request<TransactionReverseResponse>(
      `/accounts/transactions/${encodeURIComponent(transactionId)}/reverse`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  },
  async periodLocks(include_inactive?: boolean) {
    const params = new URLSearchParams();
    if (typeof include_inactive === "boolean") {
      params.set("include_inactive", String(include_inactive));
    }
    const qs = params.toString();
    return request<PeriodLockListResponse>(`/accounts/period-locks${qs ? `?${qs}` : ""}`);
  },
  closePeriodLock(payload: PeriodLockCreateInput) {
    return request<PeriodLock>("/accounts/period-locks", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  reopenPeriodLock(lockId: string, payload: PeriodLockReopenInput) {
    return request<PeriodLock>(`/accounts/period-locks/${encodeURIComponent(lockId)}/reopen`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  async exportAccountTransactionsCsv(filters?: {
    limit?: number;
    account_id?: string;
    from_date?: string;
    to_date?: string;
    category?: string;
    source_type?: string;
  }) {
    const params = new URLSearchParams();
    if (typeof filters?.limit === "number") params.set("limit", String(filters.limit));
    if (filters?.account_id) params.set("account_id", filters.account_id);
    if (filters?.from_date) params.set("from_date", filters.from_date);
    if (filters?.to_date) params.set("to_date", filters.to_date);
    if (filters?.category) params.set("category", filters.category);
    if (filters?.source_type) params.set("source_type", filters.source_type);
    const qs = params.toString();
    const response = await fetch(`${API_BASE}/accounts/transactions/export${qs ? `?${qs}` : ""}`);
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Request failed: ${response.status}`);
    }
    return response.blob();
  },
  async exportAccountJournalCsv(filters?: {
    period?: "daily" | "weekly" | "monthly" | "yearly";
    from_date?: string;
    to_date?: string;
    category?: string;
    source_type?: string;
    limit?: number;
  }) {
    const params = new URLSearchParams();
    if (filters?.period) params.set("period", filters.period);
    if (filters?.from_date) params.set("from_date", filters.from_date);
    if (filters?.to_date) params.set("to_date", filters.to_date);
    if (filters?.category) params.set("category", filters.category);
    if (filters?.source_type) params.set("source_type", filters.source_type);
    if (typeof filters?.limit === "number") params.set("limit", String(filters.limit));
    const qs = params.toString();
    const response = await fetch(`${API_BASE}/accounts/journal/export${qs ? `?${qs}` : ""}`);
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Request failed: ${response.status}`);
    }
    return response.blob();
  },
  async borrowings(filters?: { party_id?: string; limit?: number }) {
    const params = new URLSearchParams();
    if (filters?.party_id) params.set("party_id", filters.party_id);
    if (typeof filters?.limit === "number") params.set("limit", String(filters.limit));
    const qs = params.toString();
    return request<BorrowingListResponse>(`/settlements/borrowings${qs ? `?${qs}` : ""}`);
  },
  borrowingSummary() {
    return request<BorrowingSummaryResponse>("/settlements/borrowings/summary");
  },
  createBorrowing(payload: BorrowingEntryCreateInput) {
    return request<BorrowingEntry>("/settlements/borrowings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  createBusinessPayment(payload: BusinessPaymentCreateInput) {
    return request<BusinessPaymentResponse>("/accounts/business-payments", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  businessPayments: () => request<AccountTransactionListResponse>("/accounts/business-payments"),
  async receivables(filters?: { status?: string }) {
    const params = new URLSearchParams();
    if (filters?.status) params.set("status", filters.status);
    const qs = params.toString();
    return request<ReceivableListResponse>(`/collections/receivables${qs ? `?${qs}` : ""}`);
  },
  createReceivable(payload: ReceivableCreateInput) {
    return request<Receivable>("/collections/receivables", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  collectReceivable(receivableId: string, payload: ReceivablePaymentCreateInput) {
    return request<ReceivablePayment>(
      `/collections/receivables/${encodeURIComponent(receivableId)}/payments`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  },
  updateReceivable(receivableId: string, payload: ReceivableStatusUpdateInput) {
    return request<Receivable>(`/collections/receivables/${encodeURIComponent(receivableId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  dueReceivableReminders(asOf?: string) {
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
    return request<ReceivableListResponse>(`/collections/receivables-reminders${query}`);
  },
  markReceivableReminder(receivableId: string, payload: ReceivableReminderUpdateInput) {
    return request<Receivable>(
      `/collections/receivables/${encodeURIComponent(receivableId)}/remind`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  },
  receivableReminderHistory(
    receivableId: string,
    filters?: { from_date?: string; to_date?: string; reminded_by?: string }
  ) {
    const params = new URLSearchParams();
    if (filters?.from_date) params.set("from_date", filters.from_date);
    if (filters?.to_date) params.set("to_date", filters.to_date);
    if (filters?.reminded_by) params.set("reminded_by", filters.reminded_by);
    const qs = params.toString();
    return request<ReceivableReminderLogListResponse>(
      `/collections/receivables/${encodeURIComponent(receivableId)}/reminders${qs ? `?${qs}` : ""}`
    );
  },
  async invoices(filters?: { collection_status?: string }) {
    const params = new URLSearchParams();
    if (filters?.collection_status) params.set("collection_status", filters.collection_status);
    const qs = params.toString();
    return request<InvoiceListResponse>(`/billing/invoices${qs ? `?${qs}` : ""}`);
  },
  createInvoice(payload: InvoiceCreateInput) {
    return request<Invoice>("/billing/invoices", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  async exportSalesRegisterCsv(filters?: { from_date?: string; to_date?: string }) {
    const params = new URLSearchParams();
    if (filters?.from_date) params.set("from_date", filters.from_date);
    if (filters?.to_date) params.set("to_date", filters.to_date);
    const qs = params.toString();
    const response = await fetch(
      `${API_BASE}/billing/invoices/reports/sales-register/export${qs ? `?${qs}` : ""}`
    );
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Request failed: ${response.status}`);
    }
    return response.blob();
  },
  reconcileInvoices(triggeredBy?: string) {
    const query = triggeredBy ? `?triggered_by=${encodeURIComponent(triggeredBy)}` : "";
    return request<InvoiceReconcileResponse>(`/billing/invoices/reconcile${query}`, {
      method: "POST",
    });
  },
  invoiceReconcileRuns(limit = 10, offset = 0) {
    return request<InvoiceReconcileRunListResponse>(
      `/billing/invoices/reconcile-runs?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`
    );
  },
  async purchases(filters?: { payment_status?: string; vendor_party_id?: string }) {
    const params = new URLSearchParams();
    if (filters?.payment_status) params.set("payment_status", filters.payment_status);
    if (filters?.vendor_party_id) params.set("vendor_party_id", filters.vendor_party_id);
    const qs = params.toString();
    return request<PurchaseListResponse>(`/purchases${qs ? `?${qs}` : ""}`);
  },
  createPurchase(payload: PurchaseCreateInput) {
    return request<Purchase>("/purchases", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  addPurchasePayment(purchaseId: string, payload: PurchasePaymentCreateInput) {
    return request<Purchase>(`/purchases/${encodeURIComponent(purchaseId)}/payments`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  purchasePayments(purchaseId: string) {
    return request<PurchasePaymentListResponse>(
      `/purchases/${encodeURIComponent(purchaseId)}/payments`
    );
  },
  confirmPurchaseReceipt(purchaseId: string, payload: PurchaseReceiptConfirmInput) {
    return request<Purchase>(`/purchases/${encodeURIComponent(purchaseId)}/confirm-receipt`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  async exportPurchaseRegisterCsv(filters?: { from_date?: string; to_date?: string }) {
    const params = new URLSearchParams();
    if (filters?.from_date) params.set("from_date", filters.from_date);
    if (filters?.to_date) params.set("to_date", filters.to_date);
    const qs = params.toString();
    const response = await fetch(
      `${API_BASE}/purchases/reports/purchase-register/export${qs ? `?${qs}` : ""}`
    );
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Request failed: ${response.status}`);
    }
    return response.blob();
  },
  async exportApAgingCsv(filters?: { as_of?: string }) {
    const params = new URLSearchParams();
    if (filters?.as_of) params.set("as_of", filters.as_of);
    const qs = params.toString();
    const response = await fetch(`${API_BASE}/purchases/reports/ap-aging/export${qs ? `?${qs}` : ""}`);
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Request failed: ${response.status}`);
    }
    return response.blob();
  },
  async exportArAgingCsv(filters?: { as_of?: string }) {
    const params = new URLSearchParams();
    if (filters?.as_of) params.set("as_of", filters.as_of);
    const qs = params.toString();
    const response = await fetch(
      `${API_BASE}/collections/receivables/reports/ar-aging/export${qs ? `?${qs}` : ""}`
    );
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Request failed: ${response.status}`);
    }
    return response.blob();
  },
};
