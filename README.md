# Tenali Web

This folder contains the web application structure for the project.

## Separate Render UI and API (native runtimes)

The UI uses relative `/api` requests. On the free Render Static Site, configure
these rules as **Rewrite**, not Redirect, in this order:

1. `/api/*` -> `https://tenali-api.onrender.com/api/*`
2. `/*` -> `/index.html`

The storefront generates extensionless `/brand` links. Keep the catch-all rewrite
for direct navigation and refreshes, including older shared `/brand.html` links;
the application retains the older route, but it cannot repair a hosting 404.

For the paid Python API service, configure these environment variables for the
current temporary UI hostname:

```text
TENALI_ENV=production
TENALI_API_HOST=tenali-api.onrender.com
TENALI_PUBLIC_ORIGIN=https://tenali-web-dq3a.onrender.com
TENALI_BASE_DOMAIN=tenali-web-dq3a.onrender.com
CORS_ORIGINS=https://tenali-web-dq3a.onrender.com
```

`TENALI_API_HOST` and `TENALI_PUBLIC_ORIGIN` are opt-in and must be set together.
Only requests to that exact API hostname are mapped to the configured public
origin before tenant, login and CSRF validation. Caller-supplied forwarding
headers cannot select the public origin. This is deployment routing, not API
authentication: protected endpoints still require the appropriate session and
write protection. Leave both variables unset for existing same-host deployments.

Use `/platform` for platform administrators and `/c/<tenant-slug>` for workspace
storefronts. This fixed-origin rewrite supports one public UI origin and path-based
workspace selection; it does not forward arbitrary tenant/custom domain identity.
Do not treat tenant subdomains or custom storefront domains as supported by this
configuration without separate routing verification.

The platform root (`/`) presents Tenali's public marketing website, including a
silent, screen-based product tour with a transcript. The dashboard and AI
screens use sample data; the tour does not show live interactions or AI
responses and should be refreshed when the workspace changes. It does not replace tenant
storefronts. The contact email is taken from the **published platform contact
policy**; publish and maintain that policy, including its current email and
business details, before using the website for marketing. If the policy cannot
be loaded, the page displays a link to the business information page instead.

For self-service custom tenant domains while **keeping the static site and API as
two separate Render services**, use the optional automated onboarding described in
[Render tenant domains](docs/MULTI_TENANT_DEPLOYMENT.md#self-service-tenant-domains-on-two-render-services).
It pairs each storefront domain with `api.<storefront-domain>`, provisions Render
hostnames server-side and uses exact-origin credentialed requests. The existing
platform rewrite remains unchanged.

Once `tenali.biz` is connected to the UI and HTTPS is ready, change
`TENALI_PUBLIC_ORIGIN` to `https://tenali.biz`, `TENALI_BASE_DOMAIN` to `tenali.biz`
and `CORS_ORIGINS` to `https://tenali.biz`. Keep `TENALI_API_HOST` unchanged.
Use that canonical UI origin for login; other UI origins are not interchangeable
for authentication. Verify health, login, cookies and authenticated writes after
redeploying. Health alone does not establish database or login readiness.

Keep database, encryption and Supabase storage secrets in the API service's
Render Environment settings, never in the static UI or the repository.

## Classic storefront editor

- Open **Storefront Design** in the workspace. A store without saved sections
  starts with editable Hero, Categories, Best sellers, Specials and Brands,
  populated from its existing Classic content and visible catalogue selections.
  Opening or editing these sections preserves the Classic layout and hero service
  panel; adding a section no longer replaces the rest of the homepage.
- Header and Footer have fixed-position editor panels. Header controls include
  the logo and navigation labels. Footer text defaults to the existing contact
  email until an override is saved. Why, Contact and About / collection story
  expose the existing homepage copy, including the three About points.
- Changes preview before saving. Save design persists the company copy and
  curated section mappings. These settings use the existing company JSON and
  storefront tables; no additional database migration is needed for this editor.
- Desktop preview renders at 1440px and automatically zooms out to fit the panel,
  retaining desktop layouts instead of wrapping to the editor's width. Mobile
  preview uses 390px. Both resize with the panel, show the zoom percentage and
  scroll inside the preview.
- Unmapped product sections show theme-specific sample products and photographs
  only in the designer. Selecting real products replaces that shelf's samples,
  without filling gaps or missing images in real selections. Samples are not added
  to inventory, saved in sections or rendered on the live storefront. Preview
  shopping/navigation actions are disabled for pointer and keyboard input.
  **Use sample products for all product sections** also lets an established store
  preview a theme's examples without changing its mappings. Selecting products
  switches back to actual selections; this preview switch is never saved.
  Saved product/category/brand selections reload in their original order.
  Explicitly selected active categories remain visible even before products
  have been assigned; their catalogue page shows the normal empty state.
- **Homepage sections** keeps link and button controls with the content they
  affect: Header for menus/account/cart, Hero for its actions, category/brand
  sections for card actions, product sections for purchase-button labels, Why
  and Contact for their actions, and Footer for footer/fallback links. There is
  no separate Links & buttons panel. Hero and view-all overrides remain
  section-specific; card actions and product-button labels are shared settings,
  explicitly identified in their section panels. The destination
  picker lists enabled homepage sections (with stable anchors), store pages and
  custom HTTP(S), email or telephone links. Existing destinations and copy remain
  the defaults until overridden. Category/brand cards still use their selected
  catalogue items unless a destination is explicitly overridden.
  Purchase controls retain their original shopping actions. Existing global
  overrides remain defaults for section controls. Changes preview immediately
  and save in the existing `storefront_content` JSON; no migration is needed.
  Marketplace's Hero panel has four independent action controls: primary and
  secondary buttons, plus the category and story large links.
- **Homepage sections → Header** manages up to nine primary menu items. Add an
  item, edit its label/destination, hide it temporarily or remove it. Cart,
  shopper account and workspace controls remain separate. Existing menus are
  retained until edited; an empty menu intentionally hides the primary links.
  Settings preview live and save in `storefront_content.header_menu` without a
  database migration.

The Marketplace theme uses the same Classic sections and saved selections with a
retail header, full-width search, department navigation, a three-column campaign
hero, compact category/brand tiles and four-column product shelves. Why, Contact,
About and footer copy are shared with Classic. Marketplace uses the sample HTML's
fashion hero and decorative story/collection photographs; an uploaded hero image
takes precedence. Product images always come from the actual catalogue.
Search, product actions, cart/enquiry mode and WhatsApp use the existing flows.
The layout adapts to mobile without adding promotional offers, ratings, newsletter
subscriptions or other data that the store does not maintain.

Boutique uses the reference HTML's centered masthead, separate collection menu,
split fashion hero, circular category images, editorial journal, quiet brand
cards and rose/cream product shelves. It keeps the same editable sections,
selections, Why, Contact and About copy as Classic. The Hero image overrides the
reference photograph; **Why → Journal images** replaces or removes the two
decorative reference images. These image settings save in the existing
`storefront_content.images` JSON without a database migration. Product/category
images remain catalogue-driven; product buttons retain cart, variant and enquiry
behavior. Header, section, card, contact and footer links use the existing
controls in their respective section panels. No nonfunctional wishlist or
newsletter form is added.
Boutique category, brand and search listings use compact, text-only headers;
catalogue images remain on their category, brand and product cards.

Catalogue/category/brand listings, search results, product details, cart, checkout
and shopper account use the main header navigation and shared colour tokens,
without an extra duplicate navigation row. The all-brands directory is available
at `/brand?view=brands`; brand shelves and brand back-links use this destination
unless explicitly overridden. Classic uses
navy, warm white and gold; Marketplace uses the sample's navy, white and yellow.
The other designs also have palettes drawn from their sample HTML. Existing default
palettes follow the selected design; custom colours are preserved. **Reset colours**
in Storefront Design restores the selected design's palette, not the generic one.
Product cards have separate Classic and Marketplace treatments, and shared brand
cards use a logo/monogram for Classic and a wordmark tile for Marketplace. These
are presentation changes only; no database migration or catalogue reseeding is needed.
Product image frames follow the theme/section size rather than the photograph's
intrinsic dimensions, keeping portrait and landscape images aligned in each shelf.

## Inventory and customers

- Variants can have their own uploaded photo. If no variant photo is set, the
  storefront uses the main product photo; selecting a variant updates the
  gallery. Variant uploads use the product photo pipeline and retain the
  original. Existing variant updates that omit the image leave it unchanged.
  Apply Alembic migration `061_variant_images` before deploying this version.
- Inventory product and variant stock totals reflect only stores accessible to
  the signed-in member. Storefront browsing does not promise availability:
  checkout verifies unreserved stock at the selected fulfilment or pickup store.
- Tenali AI displays verified record lookups as compact result cards: available
  totals and lookup warnings stay visible, while individual records can be
  expanded. Ledger entries show money direction and labelled transaction
  details; they do not combine inflows, outflows and transfers into a total.
  Bounded results may not contain a total; narrow the question when more
  records match.
- The Operations Dashboard supports a month, a single day, or an inclusive
  custom date range. Sales and purchase bills reflect documents not cancelled
  by the end of the selected period. Net account cash flow is external money
  in minus money out, excluding transfers; reversals appear on their transaction
  dates. It includes loans, tax and other non-profit movements and is not
  profit. Profit is unavailable without reliable cost of goods sold, inventory
  valuation and other expenses. Cash flow and gross outflows are workspace-wide and are only
  shown with accounts access and access to all stores, with no store selected.
  Pending orders, inventory and receivables remain current all-date indicators.
- The personal operations checklists use India time and the April–March financial
  year. They are stored in the current user's browser and are not an audited or
  shared close. Existing calendar-year checklist marks are not migrated to the
  new financial-year keys because their period cannot be determined reliably.
- Online checkout requires both the Add to Cart switch in Payments & Delivery
  Setup and an active Online store linked to an active stock-holding warehouse
  or shop in Stores. The setup status and public availability use the same
  readiness rules; blocked setup links to Stores instead of claiming checkout
  is visible.
- Razorpay mode comes from the keys saved in Tenali, not the dashboard's active
  mode. Replace the key ID and secret together and configure the matching live
  webhook secret when switching to real payments. Run the read-only connection
  check after saving. Provider HTTP errors distinguish authentication, account
  access, validation and availability without exposing provider response bodies
  or credentials. Reconcile uncertain payment attempts before retrying.
- Home and catalogue cards offer Add to Cart when checkout is available. Quick
  add checks current product details and adds the minimum quantity; products
  with variants open their detail page so shoppers can select a size / colour.
  Cart and checkout totals are estimates until the server confirms the quote.
- Cart, checkout summaries and shopper/staff orders show product thumbnails and
  linked names that open the product page with the selected variant. Order images
  use the current catalogue; unavailable images show a placeholder without
  changing the order's saved quantities or prices.
- After Razorpay checkout, the browser confirms payment with the server and
  watches the shopper-owned order status for webhook updates. A lost callback
  triggers server-side reconciliation after three minutes; verification
  requests time out after 30 seconds instead of leaving checkout spinning.
  Cart items are removed and My Orders opens only after server-verified payment.
  If verification remains uncertain, use My Orders / Verify Payment before
  paying again. Verification is also available for expired prepaid orders;
  their stock hold has ended, so the store may need to review availability.
  Leaving checkout cancels its browser-side polling.
- Cancelling an unpaid order releases its stock hold but cannot stop a payment
  already in flight. A later verified capture, including after expiry or
  cancellation, is recorded and sent to fulfilment review; verify stock before
  dispatch or record a completed refund. For unbooked Shiprocket orders, choose
  the fulfilment store and resolve stock review before submitting a shipment.
  Payment verification remains available for cancelled prepaid orders without
  a recorded capture.
- For prepaid orders, configure a settlement (Razorpay clearing) account on the
  Online store in Stores. A captured payment remains paid if advance posting is
  blocked; Online Orders shows the reason and allows staff to retry after fixing
  the account or accounting period. Retry only reports success once the advance
  exists and does not charge the shopper again. Dispatch requires that advance.
  Staff ledger attribution uses the tenant audit trail, not the legacy
  user-profile field on account transactions.
- Cancelling a captured, uninvoiced prepaid order does not initiate a provider
  refund. First complete and verify the full order amount in Razorpay, then
  record its refund ID, account and confirmation in Online Orders. Partial
  refunds are not supported here. The payment advance must already be posted.
  This is a staff attestation, not provider verification. Orders with a shipment
  or dispatch in progress cannot be cancelled here: resolve the shipment with
  the provider and support before recording a refund.
- Shiprocket delivery orders must be submitted to Shiprocket (package weight and
  dimensions are entered on each order card) before Dispatch & invoice unlocks.
  Orders dispatched (or marked delivered) before this rule can still be submitted,
  or recovered with their Shiprocket order ID; they return to dispatched without
  touching the invoice or stock. Mark delivered also waits for a Shiprocket
  booking and asks for confirmation. When Shiprocket rejects a submission (HTTP
  4xx) nothing is created: the order is restored, the rejected field names are
  shown, and it can be corrected and resubmitted. A timeout or 5xx is
  unconfirmed and must be recovered; if the Tenali order ID is not in
  Shiprocket, staff can use "Not in Shiprocket: allow resubmission" to retry.
  AWB and courier sync automatically from Shiprocket while the Online Orders
  tab is open (at most every 2 minutes, up to 10 booked orders without an AWB);
  "Recover shipment / update tracking" remains available as a manual refresh.

- Inventory has separate Products, Reorder Alerts and Stock check tabs. Stock
  check shows problems first, with optional matching entries and store filtering.
  It compares on-hand balances with recorded activity, not a physical count.
  Missing document evidence does not change stock quantities.
- Billing keeps document creation on the left and stacks quotations, invoices
  and reconciliation history in the wider right column. On smaller screens the
  records follow the form; wide invoice tables scroll within their card.
- Product search matches words across names, product IDs, SKUs, brands,
  categories and variant details. Vendor selection and inactive products remain
  separate filters.
- Owners and administrators can delete unused products after typing the product
  code. Stock, movements, enquiries, invoices, purchases, orders and transfer
  history block deletion; make those products inactive instead. Deletion removes
  variants and vendor mappings, but does not delete shared storage objects.
  Apply Alembic migration `033_inventory_product_deletion` before enabling this
  endpoint: it adds DELETE privileges on just products, zero balances and vendor
  mappings to the existing row-level-security-constrained runtime role. The API
  additionally requires an owner/admin identity and blocks business history.
- Online customer accounts are under `/portal/online-customers`, separate from
  Parties. Owner/admin access and explicit identity-confirmed counter-customer
  linking remain required; matching phone numbers never automatically merge users.
