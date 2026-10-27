export type Company = {
  id: string;
  company_name: string;
  nickname?: string;
  logo_url?: string;
  gst_number?: string;
  udyam_number?: string;
  phone?: string;
  email?: string;
  address?: string;
  website?: string;
  social_links?: Record<string, string>;
  is_active: boolean;
};

export type InvoiceSettings = {
  title: string;
  thank_you_note: string;
  signatory_label: string;
  signatory_name: string;
  signatory_designation: string;
  signature_image: string | null;
  footer_text: string;
  primary_color: string;
  accent_color: string;
  footer_text_color: string;
  bill_to_label: string;
  ship_to_label: string;
  amount_in_words_label: string;
  logo_width_mm: number;
  signature_width_mm: number;
};

export type SiteTheme = {
  primary_color: string;
  accent_color: string;
  background_color: string;
  surface_color: string;
  text_color: string;
  muted_text_color: string;
  border_color: string;
};

export type CompanySetup = Company & { invoice_settings: InvoiceSettings; site_theme: SiteTheme };
export type CompanyUpdateInput = Omit<CompanySetup, "id" | "is_active">;

export type AttachmentEntity = "purchase" | "business_payment";
export type AttachmentInput = {
  file_name: string;
  mime_type: "application/pdf" | "image/jpeg" | "image/png" | "image/webp";
  data_base64: string;
};
export type Attachment = {
  id: string;
  file_name: string;
  mime_type: string;
  file_size: number;
  created_at: string;
};

export type HsnMaster = {
  id: string;
  company_id: string;
  code: string;
  description: string;
  gst_rate: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};
export type HsnMasterInput = Pick<HsnMaster, "code" | "description" | "gst_rate" | "is_active">;
export type HsnMasterUpdateInput = Omit<HsnMasterInput, "code">;

export type Brand = {
  code: string;
  name: string;
  description?: string;
};

export type CatalogCategory = {
  category_slug: string;
  name: string;
  category_title: string;
  category_description: string;
  image_url: string;
  home_order: number;
};

export type CatalogProduct = {
  id: string;
  portal_product_id: string;
  name: string;
  description: string;
  image_url: string;
  image_urls: string;
  mrp_display: string;
  selling_price_display: string;
  best_seller: boolean;
  sru_special: boolean;
  home_order: number;
  is_active: boolean;
  brand_code: string;
  brand_name: string;
  category_slug: string;
  category_title: string;
  category_description: string;
  stock_qty: number;
  gallery?: string[];
};

export type CatalogHomeResponse = {
  company: Company;
  brands: Brand[];
  categories: CatalogCategory[];
  best_sellers: CatalogProduct[];
  sru_specials: CatalogProduct[];
};

export type CatalogProductResponse = {
  product: CatalogProduct;
};

export interface CatalogListResponse {
  company: Company;
  brands: Brand[];
  categories: CatalogCategory[];
  products: CatalogProduct[];
  selected_brand: Brand | null;
  selected_category: CatalogCategory | null;
}

export type PartyType =
  | "customer"
  | "vendor"
  | "customer_vendor"
  | "friend"
  | "employee"
  | "other";

export type Party = {
  id: string;
  company_id: string;
  party_type: PartyType;
  nickname?: string;
  legal_name: string;
  contact_person?: string;
  phone?: string;
  email?: string;
  address?: string;
  gst_number?: string;
  is_active: boolean;
};

export type PartyListResponse = {
  items: Party[];
};

export type PartyCreateInput = {
  party_type: PartyType;
  legal_name: string;
  nickname?: string;
  contact_person?: string;
  phone?: string;
  email?: string;
  address?: string;
  gst_number?: string;
};

export type PartyUpdateInput = Partial<PartyCreateInput> & {
  is_active?: boolean;
};

export type Account = {
  id: string;
  company_id: string;
  nickname: string;
  account_type: string;
  party_id?: string;
  holder_name?: string;
  phone?: string;
  email?: string;
  opening_balance: number;
  is_company_account: boolean;
  is_active: boolean;
};

export type AccountListResponse = {
  items: Account[];
};

export type AccountCreateInput = {
  nickname: string;
  account_type: string;
  party_id?: string;
  holder_name?: string;
  phone?: string;
  email?: string;
  opening_balance?: number;
  is_company_account?: boolean;
};

export type AccountUpdateInput = Partial<AccountCreateInput> & {
  is_active?: boolean;
};

export type AccountTransaction = {
  id: string;
  company_id: string;
  from_account_id?: string;
  from_account_name?: string;
  to_account_id?: string;
  to_account_name?: string;
  direction?: "INFLOW" | "OUTFLOW" | "TRANSFER";
  amount: number;
  payment_mode?: string;
  reference?: string;
  category?: string;
  description?: string;
  transaction_date: string;
  source_type?: string;
  source_id?: string;
  reversal_of_transaction_id?: string;
  is_reversed?: boolean;
  created_at: string;
};

export type AccountTransactionListResponse = {
  items: AccountTransaction[];
};

export type AccountTallyRow = {
  account_id: string;
  account_name: string;
  account_type: string;
  is_company_account: boolean;
  opening_balance: number;
  total_inflow: number;
  total_outflow: number;
  current_balance: number;
  transaction_count: number;
  last_transaction_date?: string;
};

export type AccountTallyResponse = {
  as_of: string;
  total_opening_balance: number;
  total_inflow: number;
  total_outflow: number;
  total_current_balance: number;
  items: AccountTallyRow[];
};

export type AuditJournalEntry = {
  transaction_id: string;
  transaction_date: string;
  period_key: string;
  direction: "INFLOW" | "OUTFLOW" | "TRANSFER";
  amount: number;
  from_account_id?: string;
  from_account_name?: string;
  to_account_id?: string;
  to_account_name?: string;
  payment_mode?: string;
  reference?: string;
  category?: string;
  description?: string;
  source_type?: string;
  source_id?: string;
  reversal_of_transaction_id?: string;
  is_reversed?: boolean;
  created_at: string;
};

export type AuditJournalBucket = {
  period_key: string;
  entry_count: number;
  total_inflow: number;
  total_outflow: number;
  total_transfer: number;
  net_flow: number;
};

export type AuditJournalResponse = {
  period: "daily" | "weekly" | "monthly" | "yearly";
  from_date: string;
  to_date: string;
  items: AuditJournalEntry[];
  buckets: AuditJournalBucket[];
};

export type AccountTransactionCreateInput = {
  from_account_id?: string;
  to_account_id?: string;
  amount: number;
  payment_mode?: string;
  reference?: string;
  category?: string;
  description?: string;
  transaction_date?: string;
};

export type TransactionReverseCreateInput = {
  transaction_date?: string;
  reference?: string;
  notes?: string;
};

export type TransactionReverseResponse = {
  original_transaction: AccountTransaction;
  reversal_transaction: AccountTransaction;
};

export type PeriodLock = {
  id: string;
  company_id: string;
  period_start: string;
  period_end: string;
  reason?: string;
  closed_by?: string;
  is_active: boolean;
  created_at: string;
  reopened_at?: string;
  reopened_by?: string;
  reopen_reason?: string;
};

export type PeriodLockListResponse = {
  items: PeriodLock[];
};

export type PeriodLockCreateInput = {
  period_start: string;
  period_end: string;
  reason?: string;
  closed_by?: string;
};

export type PeriodLockReopenInput = {
  reopened_by?: string;
  reopen_reason?: string;
};

export type BorrowingDirection = "borrow" | "repay";

export type BorrowingEntry = {
  id: string;
  company_id: string;
  party_id: string;
  party_name: string;
  direction: BorrowingDirection;
  amount: number;
  transaction_date: string;
  account_id?: string;
  reference?: string;
  notes?: string;
  created_at: string;
};

export type BorrowingEntryCreateInput = {
  party_id: string;
  direction: BorrowingDirection;
  amount: number;
  transaction_date?: string;
  account_id?: string;
  reference?: string;
  notes?: string;
  create_account_transaction?: boolean;
};

export type BorrowingListResponse = {
  items: BorrowingEntry[];
};

export type BorrowingSummary = {
  party_id: string;
  party_name: string;
  borrowed_amount: number;
  repaid_amount: number;
  net_outstanding: number;
};

export type BorrowingSummaryResponse = {
  items: BorrowingSummary[];
};

export type BusinessPaymentCreateInput = {
  attachments?: AttachmentInput[];
  from_account_id: string;
  amount: number;
  purpose: "purchase" | "billing" | "expense";
  related_party_id?: string;
  payment_mode?: string;
  reference?: string;
  notes?: string;
  transaction_date?: string;
  create_borrowing?: boolean;
};

export type BusinessPaymentResponse = {
  account_transaction: AccountTransaction;
  borrowing_id?: string;
};

export type Receivable = {
  id: string;
  company_id: string;
  party_id: string;
  party_name: string;
  invoice_id?: string;
  reference?: string;
  amount_due: number;
  amount_received: number;
  balance_amount: number;
  status: "UNPAID" | "PARTIAL" | "SETTLED" | "BAD_DEBT";
  due_date?: string;
  reminder_date?: string;
  bad_debt_reason?: string;
  notes?: string;
  created_at: string;
};

export type ReceivableListResponse = {
  items: Receivable[];
};

export type ReceivableCreateInput = {
  party_id: string;
  invoice_id?: string;
  reference?: string;
  amount_due: number;
  due_date?: string;
  reminder_date?: string;
  notes?: string;
};

export type ReceivablePaymentCreateInput = {
  amount: number;
  account_id: string;
  payment_mode: string;
  idempotency_key: string;
  reference?: string;
  payment_date?: string;
  notes?: string;
};

export type ReceivablePayment = {
  id: string;
  receivable_id: string;
  company_id: string;
  account_id?: string;
  amount: number;
  payment_mode: string;
  reference?: string;
  payment_date: string;
  notes?: string;
  created_at: string;
};

export type ReceivableStatusUpdateInput = {
  status: "UNPAID" | "PARTIAL" | "SETTLED" | "BAD_DEBT";
  bad_debt_reason?: string;
  reminder_date?: string;
};

export type ReceivableReminderUpdateInput = {
  next_reminder_date?: string;
  notes?: string;
  reminded_by?: string;
};

export type ReceivableReminderLog = {
  id: string;
  receivable_id: string;
  company_id: string;
  reminder_date?: string;
  next_reminder_date?: string;
  reminded_at: string;
  reminded_by?: string;
  notes?: string;
};

export type ReceivableReminderLogListResponse = {
  items: ReceivableReminderLog[];
};

export type InvoiceLineInput = {
  description: string;
  hsn: string;
  quantity: number;
  rate: number;
  gst_rate: number;
};

export type InvoiceDocument = {
  seller: Pick<Company, "company_name" | "address" | "gst_number" | "udyam_number" | "logo_url" | "phone" | "email" | "website"> & { invoice_settings?: Partial<InvoiceSettings> };
  bill_to: { name: string; address: string; gst_number?: string };
  ship_to: { name: string; address: string };
  place_of_supply: string;
  interstate: boolean;
  lines: Array<Omit<InvoiceLineInput, "quantity" | "rate" | "gst_rate"> & {
    quantity: string; rate: string; gst_rate: string;
    taxable: string; cgst: string; sgst: string; igst: string; total: string;
  }>;
  subtotal: string;
  gst_total: string;
  total: string;
};

export type Invoice = {
  id: string;
  company_id: string;
  invoice_number: string;
  customer_party_id: string;
  customer_name: string;
  customer_gst?: string;
  invoice_date: string;
  subtotal: number;
  gst_total: number;
  total: number;
  payment_mode?: string;
  account_id?: string;
  reference?: string;
  status: string;
  collection_status: "UNPAID" | "PARTIAL" | "SETTLED" | "BAD_DEBT";
  amount_received: number;
  due_date?: string;
  reminder_date?: string;
  bad_debt_reason?: string;
  created_at: string;
  document_data?: InvoiceDocument | null;
};

export type InvoiceListResponse = {
  items: Invoice[];
};

export type InvoiceReconcileResponse = {
  healed_count: number;
};

export type InvoiceReconcileRun = {
  id: string;
  company_id: string;
  healed_count: number;
  triggered_by?: string;
  created_at: string;
};

export type InvoiceReconcileRunListResponse = {
  items: InvoiceReconcileRun[];
  total: number;
  limit: number;
  offset: number;
};

export type InvoiceCreateInput = {
  customer_party_id: string;
  invoice_date?: string;
  subtotal: number;
  gst_total: number;
  total?: number;
  payment_mode?: string;
  account_id?: string;
  reference?: string;
  due_date?: string;
  reminder_date?: string;
  amount_received?: number;
  notes?: string;
  auto_create_receivable?: boolean;
  lines?: InvoiceLineInput[];
  billing_address?: string;
  shipping_name?: string;
  shipping_address?: string;
  place_of_supply?: string;
};

export type Purchase = {
  id: string;
  company_id: string;
  vendor_party_id: string;
  vendor_name: string;
  bill_number?: string;
  purchase_date: string;
  subtotal: number;
  gst_total: number;
  total: number;
  amount_paid: number;
  balance_amount: number;
  payment_status: "UNPAID" | "PARTIAL" | "PAID";
  payment_mode?: string;
  account_id?: string;
  reference?: string;
  due_date?: string;
  notes?: string;
  receipt_type: "PRODUCT" | "STOCK" | "SERVICE";
  receipt_status: "PENDING" | "RECEIVED";
  received_at?: string;
  received_notes?: string;
  status: string;
  created_at: string;
};

export type PurchaseListResponse = {
  items: Purchase[];
};

export type PurchaseCreateInput = {
  attachments?: AttachmentInput[];
  lines?: InvoiceLineInput[];
  vendor_party_id: string;
  purchase_date?: string;
  bill_number?: string;
  subtotal: number;
  gst_total?: number;
  total?: number;
  amount_paid?: number;
  payment_mode?: string;
  account_id?: string;
  reference?: string;
  due_date?: string;
  notes?: string;
  receipt_type?: "PRODUCT" | "STOCK" | "SERVICE";
};

export type PurchasePaymentCreateInput = {
  amount: number;
  account_id: string;
  payment_mode: string;
  idempotency_key: string;
  payment_date?: string;
  reference?: string;
  notes?: string;
};

export type PurchasePayment = {
  id: string;
  purchase_id: string;
  company_id: string;
  account_id: string;
  amount: number;
  payment_mode: string;
  idempotency_key?: string;
  reference?: string;
  payment_date: string;
  notes?: string;
  created_at: string;
};

export type PurchasePaymentListResponse = {
  items: PurchasePayment[];
};

export type PurchaseReceiptConfirmInput = {
  receipt_type?: "PRODUCT" | "STOCK" | "SERVICE";
  received_at?: string;
  received_notes?: string;
};
