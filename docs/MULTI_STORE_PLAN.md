# Multi-store plan: online and offline stores per tenant

Status: **Phase 1 implemented** (migrations 022–026 applied to the shared schema; services,
routes and UI in the local worktree). Decisions recorded from the owner:

- Online orders are fulfilled from a **warehouse**; a warehouse may also be a
  physical (offline) store. The online store does not hold separate stock.
- Online orders are not only Razorpay prepaid. The online channel also covers
  **WhatsApp enquiries**, **cash on delivery** and **store pickup** (pay at the
  store). Every mode must end in a normal invoice in the ledger.
- **Catalog/selling prices are GST-inclusive.** Vendor purchase prices stay
  GST-exclusive (entered from the vendor's bill).
- **Numbering is per store** for invoices and for an internal purchase voucher
  number; vendor bill numbers remain as entered. There is no live data, so numbering
  starts fresh at cut-over — no continuation of the current counter.
- **Stock transfers between stores are in phase 1.**
- Shipping on delivery orders: one common default (SAC 9968, 18%), editable per tenant.
- **COD is requested → approved → invoiced**, and courier settlements are tracked
  against each invoice.
- Reservation windows were left to this plan; defaults are in §2.5 rule 4.
- **Prepaid orders (delivery and pickup) are fulfilled by the warehouse**, which
  decides the ship-from store at dispatch. Pay-at-pickup orders reserve at the chosen
  shop.
- The storefront must show **nearby shops where stock is available**.
- **WhatsApp**: a common company number by default, overridable per store.

## 1. What the system does today (verified)

| Area | Current behaviour | Gap for multi-store |
| --- | --- | --- |
| Stock | `stock_balances` unique per `(company, product, variant)`; one pool per tenant. | No location dimension; cannot answer "how much is in store B". |
| Offline sales | Billing invoices: stock OUT, receivable, bank/cash inflow. | No store attribution on invoices, receivables, payments. |
| Purchases | Purchase receipt books stock IN to the shared pool. | Receipt cannot be directed to a store. |
| Online sales | `shop_orders` book stock OUT on Razorpay capture; `payment_review` if stock is short. **No invoice, receivable or account transaction is created.** | Online revenue is absent from sales register, GST register, AR and bank ledgers. Stock reconciliation's "missing document" check does not include `shop_order` references. |
| Accounts | Bank/cash accounts and transactions are company-level. | Cash drawers cannot be tied to a store; no gateway clearing account. |
| Numbering | `invoice_sequences(company, year, month)` → `INV-YYYYMM-NNNNN`; purchases have only the vendor-supplied `bill_number`. | Single series; no internal purchase voucher number. |
| Access | Membership roles are company-level. | No store-scoped staff. |
| Shop order amounts | `subtotal_paise`, `shipping_paise`; **no GST split**; shopper is not a `parties` row; only Razorpay prepaid exists (`checkout_settings.pickup_location` is a free-text label). | Invoice generation needs GST derivation and a customer party; no COD/pickup/enquiry flows. |
| Pricing | Catalog price is treated as the invoice **rate** and GST is added on top in Billing (`TaxLinesEditor` copies `catalog_price` into `rate`). | Contradicts GST-inclusive shelf prices: a 1,180 shelf price would invoice 1,392.40. |

## 2. Target model

### 2.1 `stores` master

```sql
create table stores (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    code text not null,                       -- short, upper-case, used in numbering: MAIN, WEB, WH1
    name text not null,
    kind text not null check (kind in ('offline','warehouse','online')),
    holds_stock boolean not null,             -- offline/warehouse: true; online: false
    fulfilment_store_id uuid references stores(id),  -- online only; delivery stock source, must be a holds_stock store
    allows_pickup boolean not null default false,    -- offline/warehouse: shoppers may collect orders here
    address text, state_code char(2), pincode text,
    latitude numeric(9,6), longitude numeric(9,6),   -- for "nearby shops"; geocoded from pincode if blank
    whatsapp_number text,                            -- E.164; null = use companies.whatsapp_number
    gst_number text,                          -- optional; only when the store is a separate GST registration
    settlement_account_id uuid references accounts(id), -- online: Razorpay clearing; offline: cash drawer (optional)
    is_default boolean not null default false,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    unique (company_id, code)
);
create unique index uq_stores_default on stores(company_id) where is_default;
```

Rules enforced in the service, not only in SQL:

- Exactly one default store per company (migration creates `MAIN`, kind `offline`,
  `holds_stock=true`, backfills everything to it).
- `kind='online'` ⇒ `holds_stock=false` and `fulfilment_store_id` required and must
  reference an active `holds_stock` store of the same company. Online stock
  availability = fulfilment store balance − reservations.
- A store with stock, movements or documents cannot be deleted; only deactivated.
  Deactivation is refused while its stock balance is non-zero.
- `gst_number` is validated with the same 15-character rule as the company GSTIN.
  Itemized invoices use the store GSTIN if present, else the company GSTIN; the
  place-of-supply/IGST decision uses the store's `state_code` if present, else the
  company's.

### 2.2 Stock per store

- Add `store_id uuid not null references stores(id)` to `stock_balances` and
  `stock_movements`. Backfill to the default store. Uniqueness becomes
  `(company_id, store_id, product_id, variant_id)` — implemented as a unique index
  on `coalesce(variant_id, '00000000-…')` so base-product rows cannot duplicate
  (today's constraint allows duplicate NULL-variant rows; `adjust_stock` tolerates
  this by summing, and the migration must merge any duplicates first).
- `InventoryService.adjust_stock(product_id, payload, store_id=…)`: every caller
  passes a store. Negative stock is checked **per store**; a positive company total
  never hides a negative store balance.
- `stock_transfers` (**phase 1**): header `(company, from_store, to_store, status,
  reference, notes, created_by)` plus two movements `TRANSFER_OUT` (from) and
  `TRANSFER_IN` (to), written in one transaction with
  `reference_type='stock_transfer'`. Movement check constraint gains the two new
  types. The OUT side is checked against the source store's available stock
  (balance − reservations). Phase 1 has no in-transit state: a transfer is
  instantaneous and is corrected by a reverse transfer, never by editing. Period
  locks apply to the transfer date; transfers are listed in the stock
  reconciliation with their own reference type.
- Product list shows total stock and a per-store breakdown; reorder alerts are
  evaluated per store (reorder level is company-level in phase 1).
- Stock reconciliation groups by `(store, product, variant)` and also checks
  `shop_order` and `stock_transfer` references.

### 2.3 Store attribution on documents

Add nullable `store_id` (backfilled to the default store, then set `not null`) to:
`invoices`, `purchases`, `shop_orders`, `receivables`, `receivable_payments`,
`purchase_payments`, `account_transactions`, `borrowings`, `accounting_period_locks`
(nullable = whole company). Rules:

- Invoice/purchase lines book stock against the **document's store**; for an online
  order, against the online store's **fulfilment store** while the document records
  the online store.
- Receivables, payments and the transactions they create inherit the document's
  store. Manual account transfers choose a store or "company".
- Period locks remain company-wide by default; a store-scoped lock is optional.

### 2.4 Numbering per store (fresh start)

`invoice_sequences` becomes `document_sequences(company_id, store_id, kind, year, month, last_number)`
with `kind in ('invoice','purchase')`. Formats:

- Invoice: `I<STOREID>YYYYMMDDNNNNN` (for example `I012026110600001`, exactly
  16 characters). Revision `035_invoice_store_codes` assigns each store a permanent
  two-character alphanumeric invoice ID, distinct from its longer editable display
  code. IDs are unique per company and cannot be changed; new stores receive the
  next available ID automatically, including stores created during registration.
  The full date is the invoice date, not the posting date. The existing per-store,
  per-month counter continues across days and format changes; it is not reset daily.
  At 99999 invoices per store/month the API rejects new invoices explicitly rather
  than truncating or exceeding 16 characters. Two-character IDs support 1295 stores
  per workspace (`01` through `ZZ`; `00` reserved).
- Purchase voucher: `PUR-<STORECODE>-YYYYMM-NNNNN` stored in a new
  `purchases.voucher_number`; the vendor's own `bill_number` stays as entered and is
  still what the GSTR-2B reconciliation matches on.

Because there is no live data, counters start at 1 for every store at cut-over.
Existing invoices keep their issued numbers, including older hyphenated formats.
Existing test invoices keep their old `INV-YYYYMM-…` strings (or are purged with the
rest of the test data); the migration does not try to continue or renumber them.
`invoice_number` uniqueness is per company, so old and new formats cannot collide.
Changing a store code after documents exist is refused.

### 2.5 Online channel: enquiry, prepaid, cash on delivery, store pickup

The online store is a **channel**, not a stock location. Each order carries
`channel='web'` (or `whatsapp`), a `payment_method` (`prepaid` | `cod` |
`pay_at_pickup`) and a `fulfilment_method` (`delivery` | `pickup`).

**One invariant for every mode: stock goes OUT exactly when the invoice is created,
and the invoice is created when the goods leave a store** (dispatch for delivery,
handover for pay-at-pickup). Before that, a per-store reservation holds availability.

| Mode | How it starts | Reservation | Invoice created | Series | Money |
| --- | --- | --- | --- | --- | --- |
| **WhatsApp enquiry** | Shopper taps "Enquire"; an `enquiries` row (product, variant, qty, contact, message, store context, status `open/quoted/converted/closed`) is created and a pre-filled WhatsApp link opens to the store's number (§2.5c). | None. | Manually: staff convert the enquiry to a Billing invoice (walk-in, delivery or COD). `enquiry.invoice_id` links them. | Store chosen by staff. | As the invoice records. |
| **Prepaid delivery (Razorpay)** | Checkout with delivery address. | Held at the **fulfilment warehouse** from checkout; Razorpay payment window applies. | **At dispatch.** Warehouse staff choose the ship-from store (default: warehouse); the reservation moves there and stock is booked OUT from it. The capture-time advance is applied, so the invoice is settled. | `WEB` | Capture posts a **customer advance** inflow to Razorpay clearing (`source_type='shop_order'`). Dispatch creates the invoice and attaches that transaction as its receipt (source re-pointed to the invoice, audited) — no double inflow. Payouts clearing → bank, fees → expense. |
| **Prepaid pickup** | Checkout chooses a pickup store, pays online. | Held at the **warehouse**, not the shop. | **At dispatch from the warehouse** to the pickup store (`WEB` series, settled from the advance). Arrival at the shop → `ready_for_pickup`; handover → `collected` with no further document. | `WEB` | Same as prepaid delivery. The pickup shop never books stock for this order. |
| **Cash on delivery** | Checkout with delivery address → status **`cod_requested`**. Nothing is reserved yet. Staff **approve** (checks: COD enabled, order ≤ COD limit, serviceable pincode, shopper history) → `confirmed`, reservation held at the warehouse; or **decline** → `cancelled` with reason. | From approval. | **At dispatch**, UNPAID receivable against the "Online shopper" party, order reference on the receivable. | `WEB` | Courier collects cash; remittance tracked in **`cod_settlements`** (§2.5b) and posted as a collection into **COD clearing**; clearing → bank when the courier pays out. Refused/returned → invoice cancelled, stock back to the ship-from store, courier return fee as an expense. |
| **Pay-at-pickup** | Storefront shows **nearby shops with stock** (§2.5d); shopper picks one; order `confirmed`. | Held at the **chosen shop** from confirmation. | **At handover** when shop staff mark "Collected" and record the payment mode; settled. | **Pickup shop's** series (the sale physically happens there; `channel='web'` kept for reporting). | Shop's cash/UPI/bank account. |

Common rules:

1. **Customer**: one **"Online shopper" walk-in party per company** (created by
   migration). The invoice `document_data` snapshot carries the real shopper
   name/address/phone from the order, so printed invoices are correct without a
   party per shopper. Enquiries converted by staff may pick or create a real party.
2. **GST derivation** (prices inclusive): per item `taxable = round(price / (1 + rate))`,
   `gst = price − taxable`, using the product's HSN rate; the last line absorbs paise
   rounding so the invoice total equals `total_paise` exactly. Shipping is its own
   line at **SAC 9968, 18%** (the same default for every tenant, editable in checkout
   settings). Place of supply = shipping address state (pickup: the pickup shop's
   state); IGST when it differs from the issuing store's state.
3. **Ship-from store** is chosen by warehouse staff at dispatch (default: the
   warehouse). If it differs from where the reservation is held, the dispatch action
   moves the reservation and books OUT from the chosen store in the same transaction;
   if that store lacks stock the action fails with the store's availability shown.
4. **Reservation windows** (defaults, all editable in checkout settings; the rationale
   is "hold stock only while someone is actively committed"):
   - Prepaid: held during the Razorpay payment session only (**20 minutes**); released
     if payment is not captured. After capture the hold is firm until dispatch.
   - COD request: **no hold** until approval. Approval SLA **24 h**; unapproved
     requests expire and the shopper is notified. After approval the hold is firm
     until dispatch.
   - Pay-at-pickup: **72 h** from confirmation, with a reminder at 48 h; uncollected
     orders expire and release the shop's stock.
   - Prepaid pickup: firm until collected; shops see an ageing list and can contact
     the shopper, but prepaid stock is never auto-released (refund is a staff action).
5. **Short stock or locked period** at invoice time → order goes to
   `fulfilment_review` with the reason; no invoice. Staff resolve by choosing another
   ship-from store, transferring stock, reopening the period, or cancelling/refunding.
6. **Idempotency**: `shop_orders.invoice_id` is set in the same transaction as the
   invoice; capture is idempotent on `razorpay_payment_id`, approval/dispatch/handover
   on the order status transition (row locked `for update`).
7. **Refunds / cancellation after invoice**: reverse the receipt (reopens the
   receivable), cancel the invoice (restores stock to the store that booked it), post
   the refund outflow from clearing/cash. Cancellation before invoice only releases
   the reservation; a prepaid cancellation before dispatch refunds the advance from
   clearing directly.

Order status set becomes:
`awaiting_payment` · `paid` (advance held) · `cod_requested` · `confirmed` ·
`fulfilment_review` · `shipment_booked` · `dispatched` · `delivered` ·
`ready_for_pickup` · `collected` · `expired` · `cancelled` · `refunded`.
COD money state is tracked separately on the receivable/settlement, not in the
order status.

### 2.5b COD settlement tracking

```sql
create table cod_settlements (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id),
    courier text not null,                 -- provider name or 'self'
    settlement_reference text not null,    -- courier remittance / UTR id
    settlement_date date not null,
    account_id uuid not null references accounts(id),   -- COD clearing or bank
    expected_amount numeric(14,2) not null,
    received_amount numeric(14,2) not null,
    notes text, created_by uuid, created_at timestamptz not null default now(),
    unique (company_id, courier, settlement_reference)
);
create table cod_settlement_items (
    settlement_id uuid references cod_settlements(id),
    order_id uuid references shop_orders(id),
    invoice_id uuid references invoices(id),
    amount numeric(14,2) not null,
    primary key (settlement_id, order_id)
);
```

- Recording a settlement posts one **collection per included invoice** (so each
  receivable settles against its own payment history, as the collection ledger
  requires) into the settlement's account on the settlement date, all in one
  transaction. Period locks apply to that date.
- `received_amount < expected_amount` is allowed but the difference must be
  explained: a courier-fee business payment, or a bad-debt status on the specific
  receivable with a reason. Nothing is written down silently.
- Views for staff: **COD outstanding** (dispatched COD invoices with open
  receivables, aged by dispatch date), **Settlements** (per courier, with unmatched
  differences), and the COD clearing balance (remitted by courier, not yet in bank).
- Delivered-but-unremitted after N days (default 15) appears in the outstanding
  view as overdue; this is a report, not an automatic write-off.

### 2.5c WhatsApp numbers

`companies.whatsapp_number` is the default; `stores.whatsapp_number` overrides it
when set. The storefront uses the number of the store in context: the nearby shop
the shopper selected or is viewing availability for, else the online store's
override, else the company default. The pre-filled message includes product, variant,
quantity, store name and the enquiry reference so staff can find the `enquiries`
row. Numbers are validated as E.164 and stored once; the public page receives only
the `wa.me` link.

### 2.5d Nearby shops with stock (public storefront)

- Stores gain `latitude`, `longitude`, `pincode`. Pickup-enabled shops without
  coordinates are geocoded from the pincode once on save (or entered manually).
- Public endpoint `GET /shop/{slug}/availability?product&variant&lat&lng|pincode`
  returns pickup-enabled, active shops sorted by distance (haversine; pincode
  centroid when the shopper declines geolocation) with an availability **band**, not
  a count: `available` (≥ 3 or ≥ MOQ), `few_left` (1–2), `unavailable`. Available =
  balance − reservations at that shop. Results are cached for 60 s per
  `(product, variant)`; the endpoint is rate-limited like the catalog.
- The product page shows "Pick up today at <shop> · 2.1 km" with the top three shops
  and a "More shops" list; selecting one sets the pickup shop for checkout and the
  WhatsApp number in context. If no shop has stock, the page offers delivery (from the
  warehouse) or enquiry.
- Prepaid pickup is **not** driven by shop stock: it is fulfilled by the warehouse and
  shipped to the chosen shop, so every pickup-enabled shop is offered for prepaid
  pickup regardless of its own stock, with an ETA note.
- Exact quantities are never exposed publicly; staff views keep the numbers.

### 2.5a GST-inclusive selling prices everywhere

- `companies.prices_include_gst` is **true** and not user-editable in phase 1 (all
  tenants are retail); the flag exists only so a future B2B tenant can flip it.
- **Billing**: when a product line is selected, the entered/auto-filled rate is the
  inclusive unit price. Server and `taxTotals.ts` back-calculate per line
  (`taxable = round(qty × rate / (1 + gst))`, `gst = qty × rate − taxable`) so the
  invoice total equals quantity × shelf price exactly. Manual/service lines get an
  "inclusive" toggle defaulting to inclusive. The invoice snapshot records
  `pricing='inclusive'` and both values per line.
  The document builder accepts the invoicing store and company pricing default;
  line-level `price_includes_gst` overrides that default. Store address/GSTIN/state
  override company values where provided, and the store snapshot is JSON-safe.
  Unregistered businesses issue a Bill of Supply with zero GST without requiring
  a GSTIN. These are application-code behaviors; fixing the builder contract
  does not require a database migration.
- **Purchases**: vendor rates stay **exclusive** (`taxable = qty × rate`, GST on top),
  matching vendor bills and GSTR-2B.
- `price_item` (checkout) already treats the catalog price as the amount charged;
  it only needs the GST split added for the invoice.
- Existing server/frontend rounding tests are extended with inclusive cases
  (e.g. 1,180.00 at 18% → 1,000.00 + 180.00; 0.075 × 27.40 inclusive).

### 2.6 Reports

Every finance export gets an optional `store_id` filter; the sales register also
gets a `channel` column (store code/kind). GST registers stay per GSTIN: when a
store has its own GSTIN, registers are produced per registration, otherwise per
company. AR/AP aging and account balances can be filtered by store; cash drawer
accounts are linked to a store so a store's cash position is reportable.

### 2.7 Access (phase 2)

`tenant_memberships.store_ids uuid[]` (null = all stores). Staff limited to a store
can post documents and stock movements only for that store and see only its
ledgers; owners/accountants see everything.

## 3. Migration sequence (shared schema — affects all tenants)

| Rev | Content | Safety |
| --- | --- | --- |
| 022 | `stores` table, RLS policy `company_scope`, grants to `tenali_runtime`, audit trigger (same pattern as 018). Insert default `MAIN` store and the "Online shopper" party per company. `companies.prices_include_gst boolean default true`, `companies.whatsapp_number`. | Additive. |
| 023 | `store_id` on `stock_balances`/`stock_movements` (nullable), backfill to default, merge duplicate NULL-variant balance rows, set `not null`, new unique index, drop old constraint; movement types `TRANSFER_IN/OUT`; `stock_transfers` table. | Needs a maintenance window; the merge must verify `sum(before) = sum(after)` per `(company, product, variant)` and abort otherwise. |
| 024 | `store_id` on finance documents and transactions, backfill, `not null`; replace `invoice_sequences` with `document_sequences(company, store, kind, year, month)` starting at 0; `purchases.voucher_number`. | Additive then constraint tightening; refuses to run if any company lacks a default store. Old sequence rows are dropped (no continuation). |
| 025 | `shop_orders`: `invoice_id`, `channel`, `payment_method`, `fulfilment_method`, `pickup_store_id`, `ship_from_store_id`, `advance_transaction_id`, widened status check, `expires_at`, `approved_by/at`; `enquiries`, `cod_settlements`, `cod_settlement_items` tables; `checkout_settings`: shipping SAC/rate, COD enabled/limit/approval SLA, pickup enabled, reservation windows, COD overdue days; `stores.settlement_account_id` validation; `account_transactions.source_type` gains `shop_order` (advance). | Additive. |
| 026 (phase 2) | `tenant_memberships.store_ids`. | Additive. |

Each migration follows the existing rules: idempotent upgrade, explicit duplicate
checks before adding unique indexes (as in 021), grants/RLS for new tables, and an
isolated-schema regression test like `test_finance_concurrency` **with
schema-qualified DDL** (the earlier unqualified `DROP INDEX` incident must not
recur).

## 4. Application changes

Backend

- `stores_service.py`: CRUD, default/fulfilment/pickup/GSTIN rules, deactivate guard.
- `InventoryService`: store-aware `adjust_stock`, per-store listing, reconciliation,
  alerts; `commerce_stock.book_stock(…, store_id)`; `stock_transfers` service
  (paired movements, source availability check, period lock, reverse-transfer).
- `BillingService`/`PurchasesService`: require `store_id` (default store when
  omitted by legacy clients), per-store numbering (`INV-`/`PUR-`), store GSTIN/state
  in `build_invoice_document`, **inclusive price back-calculation** for sales lines
  (`financial_amounts.py` + `invoice_document.py`), exclusive for purchases.
- `shop_checkout`: `payment_method`/`fulfilment_method` on `create_order`; per-store
  reservations (`reserved_stock(store)`); `confirm_payment` → **advance** to clearing
  (prepaid); `approve_cod` / `decline_cod`; `dispatch_order(ship_from_store)` →
  invoice (prepaid applies the advance; COD creates an UNPAID receivable);
  `mark_ready_for_pickup`, `collect_pickup` → invoice for pay-at-pickup, handover
  only for prepaid pickup; `record_cod_settlement`; reservation-expiry job;
  `enquiries` create/list/convert; public `availability` endpoint (§2.5d) with
  caching and rate limiting.
- `AccountsService`: `store_id` on transactions; advance re-pointing at dispatch
  (audited), clearing/payout helpers; "Unsettled online receipts" (Razorpay
  clearing), "COD outstanding" and "COD clearing" balances.
- Reports: store filter, channel column.
- Period-lock and reconciliation code paths unchanged except for store grouping.

Frontend

- Company Setup → **Stores** tab (list, add, set default, fulfilment store, allows
  pickup, pincode/coordinates, WhatsApp override, settlement account, GSTIN
  override) and **Online channel** settings (prepaid/COD/pickup toggles, COD limit
  and approval SLA, shipping SAC/rate, reservation windows, company WhatsApp number).
- Store selector in Billing, Purchases, Inventory (stock adjustments, transfers and
  the reconciliation panel), Accounts (optional), Reports (filter). Remember last
  selection per user in local storage.
- Billing: inclusive-price lines (`taxTotals.ts` back-calculation), per-line
  inclusive/exclusive toggle for manual lines.
- Inventory: per-store stock table, **Transfer stock** dialog, reorder alerts show store.
- Orders view: channel/payment/fulfilment columns; actions **Approve / Decline COD**,
  **Dispatch** (choose ship-from store; creates invoice), **Ready for pickup**,
  **Mark collected** (creates invoice for pay-at-pickup, takes payment mode),
  **Record COD settlement** (courier, reference, orders, received amount),
  **Resolve review** (other ship-from store / transfer / cancel / refund); generated
  invoice number and link; COD outstanding and settlements tabs.
- Storefront: "Enquire on WhatsApp" per product (store-aware number); **nearby shops
  with stock** on the product page; checkout offers prepaid delivery / prepaid pickup /
  COD request / pay-at-pickup per settings; order tracking shows the new statuses
  and, for COD, "approval pending".
- Enquiries list for staff with "Convert to invoice".

## 5. Edge cases and their resolutions

| Case | Resolution |
| --- | --- |
| Online order placed while two shoppers compete for the last unit in the fulfilment store | Reservation at checkout decides; the loser sees "not enough available stock" before paying. If both captures somehow succeed, the second dispatch fails into `fulfilment_review` and is refunded from clearing. |
| Sale posted in store A for stock physically in store B | Rejected (per-store negative check). Owner posts a **stock transfer** B → A first (phase 1 feature). |
| Return of an online order to a physical store | Cancel/refund the online invoice (restores stock to the store that booked it), then transfer to the receiving store if different. |
| COD order refused at the door / returned by courier | Order → `cancelled`; invoice cancelled (stock back to the fulfilment store); receivable closes with no payment. Courier return fee posted as an expense. |
| COD cash collected by courier but not yet remitted | Receivable stays open against the Online shopper party with the order reference; "COD outstanding" report = sum of open COD receivables. Remittance posts a collection into COD clearing/bank; shortfalls are a bad-debt or fee entry, never a silent write-down. |
| Pickup order never collected | Pay-at-pickup: reservation expires after 72 h (reminder at 48 h); order `expired`, stock released, no invoice. Prepaid pickup: never auto-released; ageing list → staff contact → refund from clearing if needed. |
| Shopper picks up at a different store than chosen | Pay-at-pickup: staff re-point the pickup shop before "Mark collected" if it has stock (reservation moves), otherwise transfer first. Prepaid pickup: warehouse re-routes the shipment; the invoice is unaffected. |
| Warehouse ships a prepaid order from shop B instead of the warehouse | Dispatch chooses ship-from = B; reservation moves, stock booked OUT from B, invoice still in the `WEB` series. B's reorder alerts react normally. |
| Prepaid order cancelled before dispatch | No invoice exists; the advance in Razorpay clearing is refunded (outflow from clearing) and the reservation is released. |
| COD requested above the limit or for an unserviceable pincode | Shown to the shopper at checkout as "COD not available for this order"; if it slips through, approval is refused with the reason. |
| Courier remits less than expected | Settlement recorded with the shortfall; the difference must be a courier-fee payment or a reasoned bad-debt status on the specific receivable. The settlement view shows unmatched differences until explained. |
| Two shops are "nearby" and the chosen one sells its last unit to a walk-in first | The reservation at confirmation blocks the walk-in sale of the reserved unit (existing `reserved_stock` check, now per store); the walk-in sees "reserved by an online order". |
| Shopper declines location sharing | Availability is sorted by pincode centroid; if no pincode, shops are listed unsorted with availability bands. |
| WhatsApp enquiry converted to an offline sale | Staff "Convert" creates a Billing draft with the product/qty and links `enquiry.invoice_id`; stock moves only when the invoice posts. |
| Inclusive price with a GST rate change | Rate comes from the HSN master at posting time; the shelf price stays the same and the taxable value changes. The snapshot records both. |
| Vendor bill where the vendor's number already exists for that vendor | Warn (not block) on duplicate `(vendor, bill_number)` — real vendors occasionally reuse numbers across years; the internal `PUR-` voucher stays unique. |
| Store with its own GSTIN sells to a customer in the store's state while the company is registered elsewhere | Tax split uses the store's state; registers per GSTIN. |
| Default store deactivated | Refused; set another default first. |
| Online store's fulfilment store deactivated | Refused while any online store points to it. |
| Legacy API clients omitting `store_id` | Server uses the default store; response includes `store_id` so clients can adopt it. |
| Razorpay payout differs from clearing balance | Clearing stays non-zero; the owner posts the fee/adjustment entry. Report "Unsettled online receipts" = clearing balance. |
| Period lock vs. automatic online invoice | Invoices are dated on dispatch/handover; if that day is locked, the action fails into `fulfilment_review` with the lock message instead of posting into a closed period. Capture-time advances are account transactions and are blocked by a lock the same way (the shopper sees a generic retry message and the capture is reconciled later). |
| Store code rename | Refused once documents exist (numbering must stay stable). |
| Duplicate NULL-variant balance rows during migration 023 | Merged with a verified-sum check; migration aborts on mismatch. |

## 6. Test plan

- Unit: store rules (default, fulfilment, pickup, GSTIN, code immutability),
  GST-inclusive back-calculation with rounding absorption (sum of lines ==
  `total_paise` for property-style cases, and `qty × shelf price` in Billing),
  per-store `INV-`/`PUR-` numbering starting at 1.
- Rollback-only DB tests: per-store negative-stock rejection; purchase receipt into a
  chosen store; invoice from store A does not touch store B; stock transfer pairs
  movements atomically, respects availability and period locks, and reverses
  correctly; prepaid capture posts the advance exactly once (idempotent replay) and
  dispatch creates the invoice with the advance attached (no second inflow, clearing
  balance unchanged); dispatch from a different ship-from store moves the reservation
  and books that store; COD request → approve → dispatch creates an UNPAID invoice,
  settlement posts per-invoice collections and explains shortfalls; pay-at-pickup
  collection creates the invoice in the shop's series; prepaid pickup handover creates
  no second document; review state when stock is short or period is locked; expiry
  releases reservations per the windows; refund/cancel paths restore stock to the
  booking store and refund advances from clearing; enquiry conversion; nearby
  availability bands never expose counts; per-store reconciliation and
  missing-source detection including `shop_order` and `stock_transfer`.
- Isolated-schema migration tests: 022–025 upgrade on a copied schema with duplicate
  NULL-variant rows; verify sums, unique indexes, fresh numbering.
- Concurrency: two online captures for the last unit; sale vs. transfer racing on the
  same store balance; two pickups of the same reserved unit.
- Playwright: store selector flows in Billing/Purchases/Inventory; Stores tab;
  transfer dialog; storefront checkout in each mode → order → invoice visible in
  Billing with the correct series; enquiry button opens WhatsApp link with the
  expected text.

## 7. Rollout

1. Deploy code that tolerates the absence of `store_id` (reads default) → run 022–025
   in a maintenance window with a database backup → deploy store-aware UI.
2. For `sourcebysru`: default store `MAIN` holds the current (unverified) balances;
   create `WEB` (online, fulfilment `MAIN`, pickup at `MAIN`), the Razorpay clearing
   and COD clearing accounts; set the real 15-character GSTIN before enabling online
   invoicing (itemized invoices are blocked without it). Purge remaining test
   documents so numbering starts clean.
3. Physical count per store after cut-over; adjust with noted manual movements.

## 8. Implementation notes (what was actually built)

- Migrations `022_stores` … `026_checkout_policy_grant`. A `before insert` trigger
  (`tenali_default_store`) derives `store_id` for receivables, payments, transactions
  and borrowings from their parent document, falling back to the default store, so
  every legacy insert path stays valid. `invoice_sequences` was dropped in favour of
  `document_sequences(company, store, kind, year, month)`; counters start at 1.
- Services: `stores_service.py`, store-aware `InventoryService.adjust_stock`
  (per-store negative check, per-store reservations), `transfer_stock` /
  `reverse_transfer`, per-store `stock_reconciliation`, `document_numbers.py`,
  `financial_amounts.line_amounts` (inclusive/exclusive), `shop_orders_service.py`
  (advance, COD approve/decline, dispatch→invoice, pickup collect→invoice, deliver,
  cancel/refund, COD settlements, expiry, enquiries, nearby availability),
  `gst_states.py` (place of supply from address state).
- Prepaid capture posts a **customer advance** to the online store's settlement
  account; dispatch creates the invoice and re-points that transaction as the
  invoice receipt (no second inflow). Pay-at-pickup invoices post in the shop's
  series with the counter payment. COD invoices are UNPAID until a settlement is
  recorded; settlements are atomic (one collection per invoice, shortfall reason
  required).
- Orders leave the stock-holding statuses *before* their invoice books stock, so an
  order's own reservation cannot block it. `create_invoice` commits internally, so
  dispatch/collect are retry-safe when the invoice link step fails.
- The runtime role may read checkout **policy** columns only (026); credentials are
  never granted to it.
- UI: Stores & Warehouses page, store selector on Billing/Purchases/Inventory,
  transfer dialog, per-store stock and reconciliation, inclusive-price billing
  preview (`taxTotals.ts` matches the server), checkout modes (prepaid / COD /
  pay-at-pickup, pickup store), nearby stores + recorded WhatsApp enquiry on the
  product page, staff order actions, COD settlements and enquiries tabs.
- Not yet built (phase 2): per-store pricing, in-transit transfers, pincode
  geocoding (nearby sorting uses coordinates when both sides have them, otherwise
  PIN prefix), automatic pickup reminders (the hold window is enforced; the
  reminder is a staff view only).
- Added after phase 1 (migration 027): `companies.gst_registered` (Bill of Supply
  for below-threshold businesses) and store/module-level access on
  `tenant_memberships` (owners/admins keep full access; staff and read-only members
  can be limited per store and per module from Users & Roles).

## 9. Decisions recorded

| Question | Decision |
| --- | --- |
| Shipping SAC/rate | Common default SAC 9968 at 18%, editable per tenant. |
| COD flow | Requested → approved (limit, pincode, history) → dispatched/invoiced; settlements tracked per courier remittance against each invoice; COD clearing account. |
| Reservation windows | Prepaid: payment session only (20 min), firm after capture. COD: no hold until approval; approval SLA 24 h. Pay-at-pickup: 72 h with a 48 h reminder. Prepaid pickup: never auto-released. All editable. |
| Prepaid pickup | Fulfilled by the warehouse, which chooses the ship-from store at dispatch and ships to the pickup shop; `WEB` series; handover is not a new document. |
| Nearby shops | Public availability endpoint with distance sorting and availability bands (no counts); drives pay-at-pickup and the WhatsApp number in context. |
| WhatsApp | Company default number, per-store override. |

Still worth a quick confirmation during implementation (defaults will be used
otherwise): the COD limit amount per tenant, the pincode-serviceability source for
COD (courier API vs. a tenant-maintained list), and the overdue threshold for
unremitted COD (default 15 days).
