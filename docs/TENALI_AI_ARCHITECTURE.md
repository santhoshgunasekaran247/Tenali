# Tenali AI: Phase 0 architecture and implementation plan

Status: proposed design; implementation and live migrations require separate approval.

Phase 1A implementation is now present: platform defaults/limits page, tenant
entitlements, platform-aware storefront status, tenant AI opt-in, version checks,
and database permissions. Revision `041_ai_feature_controls` must be applied before
deploying the API. This phase intentionally leaves the AI runtime unavailable;
models are unverified candidates and usage/retention settings are not yet enforced.
Read-only discovery, capabilities, private chat, execution and usage charts remain
later-phase work. See [deployment details](MULTI_TENANT_DEPLOYMENT.md#platform-feature-controls-and-ai-settings-phase-1a).

Phase 1B implementation now adds private persistent chat/preferences, an OpenAI
Responses gateway, exact budget reservations/usage accounting, aggregate usage,
request replay/recovery, and an explicit retention scrub command. It requires revision
`042_ai_conversations`, server model approval/allowlisting, pricing and tenant opt-in.
Live business reads, uploads, draft/approval/execution remain later phases. The
Phase 1A runtime-unavailable notes above describe that earlier release only.
See [Phase 1B deployment and limitations](MULTI_TENANT_DEPLOYMENT.md#tenali-ai-conversational-foundation-phase-1b).

This plan incorporates the supplied AI specification and the additional request for
platform-managed AI configuration and platform-overridable tenant AI/storefront switches.
Phase 0 changes documentation only. It does not activate AI, call OpenAI, or change the database.

## 1. Design decisions

- Add **Tenali Platform -> AI** as a separate platform-admin page.
- Manage AI defaults, tenant overrides, usage limits, validated models, registered
  capabilities, and operational status there, without redeploying for routine configuration.
- Add AI and storefront entitlement switches to **Platform -> Client administration**.
  Disabling either feature does not disable the workspace or revoke staff access.
- Keep **Company Setup -> Operations Portal** as the tenant-admin settings location.
  Add an AI switch and make the existing storefront switch platform-aware.
- A platform-disabled feature appears off with a disabled control, a
  **Contact platform** tag, and an accessible explanation. The tenant cannot override it.
- AI interprets requests; existing Tenali schemas/services enforce business rules;
  the authenticated user approves a specific draft; existing services execute.
- Do not change business tables, posting rules, tax calculations, invoice generation,
  cancellation/refund behavior, or stock workflows.
- Allow small, explicit integration changes to route registration, navigation, company
  settings responses, and storefront access checks. The requested platform storefront
  override cannot be enforced through AI-only files.
- New business capabilities still require reviewed adapters and contract tests.
  An admin UI cannot safely turn arbitrary URLs, Python functions, SQL, or discovered
  endpoints into tools. Configuration is not executable code.

## 2. Verified repository integration points

| Area | Existing implementation | Planned reuse |
| --- | --- | --- |
| Authentication | [auth.py](../api/app/api/routes/auth.py), [tenant_auth.py](../api/app/services/tenant_auth.py) | Existing tenant session, current identity, CSRF, owner/admin checks |
| Social identity | [federation_settings.py](../api/app/services/federation_settings.py), [shopper_federation.py](../api/app/services/shopper_federation.py) | Supabase-backed social sign-in already exists; it resolves into Tenali's own sessions, not a new AI login |
| Tenant boundary | [tenant_context.py](../api/app/services/tenant_context.py) | Tenant from authenticated session; verified host/slug checks; no model-supplied identity |
| Database isolation | [database.py](../api/app/core/database.py), [014_multi_tenant.py](../api/alembic/versions/014_multi_tenant.py) | `tenali_runtime`, `app.tenant_id`, `app.actor_user_id`, company RLS |
| Permissions | [access.py](../api/app/services/access.py) | Module/store restrictions; owners/admins do not bypass platform feature policy |
| Platform boundary | [platform.py](../api/app/api/routes/platform.py) | `admin_identity`, platform host checks, separate admin cookies/CSRF, `platform_audit` |
| Platform UI | [PlatformAdminPage.tsx](../web/src/pages/PlatformAdminPage.tsx) | Existing platform sign-in/sidebar and client pagination |
| Tenant settings | [CompanySetupPage.tsx](../web/src/pages/CompanySetupPage.tsx), [company_service.py](../api/app/services/company_service.py) | Existing save flow; preserve omitted settings and workflow-guidance toggle |
| Storefront gates | [storefront_access.py](../api/app/services/storefront_access.py), [catalog.py](../api/app/api/routes/catalog.py), [shop.py](../api/app/api/routes/shop.py), [StorefrontGate.tsx](../web/src/components/StorefrontGate.tsx) | Central backend gate plus public availability response and frontend gate |
| API registration | [router.py](../api/app/api/router.py), [main.py](../api/app/main.py) | Register isolated routers; existing app exposes routes both bare and under `/api` |
| Frontend transport | [tenantTransport.ts](../web/src/features/tenantTransport.ts), [api.ts](../web/src/api.ts), [shop.ts](../web/src/features/shop.ts) | Tenant-aware transport and platform `accountRequest`; no browser OpenAI calls |
| Business replay | [posting_service.py](../api/app/services/posting_service.py) | Existing request hashes, advisory locks, and `posting_requests` where actually supported |
| Private files | [object_storage.py](../api/app/services/object_storage.py), [documents.py](../api/app/schemas/documents.py) | Private Supabase storage, verified files, existing 5 MB/file limit |
| Workflow messages | [WorkflowGuide.tsx](../web/src/components/WorkflowGuide.tsx), [workflowGuide.ts](../web/src/features/workflowGuide.ts) | Reuse next-step guidance without duplicate notifications |

The current worktree was clean during inspection. Earlier assumptions that Supabase
authentication is absent, that every mutation is idempotent, or that expenses must use
generic account transactions are not accurate.

## 3. Platform and tenant feature policy

### 3.1 Independent controls

Use a new `tenant_feature_controls` table, not additional business-table columns:

- `company_id`, `feature_key` (`ai` or `storefront`), `platform_allowed`
- `version`, `updated_at`, `updated_by` (platform admin)
- Unique `(company_id, feature_key)`; foreign keys to company/admin.
- Tenant runtime can read its own entitlement, never modify it.
- Platform writes require `admin_identity` and append `platform_audit` events.

Keep `companies.storefront_enabled` as the existing tenant preference. Store the
new tenant AI preference in `ai_tenant_settings.tenant_enabled`.

```text
storefront_effective = workspace_active
                       AND platform_storefront_allowed
                       AND tenant_storefront_enabled

ai_effective = workspace_active
               AND platform_ai_global_enabled
               AND platform_ai_allowed
               AND tenant_ai_enabled
               AND provider_configuration_valid
```

AI operations additionally require available budget, current user permissions,
and a compatible enabled capability. Exhausted budget is not stored as tenant opt-out.

Platform policies form ceilings; tenant choices can only further restrict them.
Turning AI off does not turn the storefront off, or vice versa.

### 3.2 Defaults and restoration

| Setting | Proposed rollout default |
| --- | --- |
| Existing/new tenant platform storefront entitlement | Allowed, preserving current behavior |
| Existing `companies.storefront_enabled` values | Unchanged |
| Platform global AI switch | Off |
| Tenant platform AI entitlement | Not allowed until explicitly enabled |
| Tenant AI preference | Off until the tenant admin opts in |

Seed entitlements for existing tenants and create them for new workspaces. Missing
expected configuration is an explicit configuration error, not a silent grant.
Do not guess numerical usage limits or model names: activation requires valid settings.

Platform disabling preserves tenant preferences. Re-enabling platform access restores
the earlier preference, not necessarily an enabled feature. Show this consequence in
the platform confirmation. Do not overwrite preferences when composing status responses.

### 3.3 Tenant settings and API enforcement

- Show effective state and, when relevant, the saved tenant preference separately.
- When platform-blocked: checkbox disabled/off; tag **Contact platform**;
  description "Disabled by Tenali Platform. Contact the platform administrator."
- Use a platform-configured support URL/email; if none is configured, show the
  explanation without inventing a destination. Validate allowed URL schemes.
- Tenant controls require owner/admin; other users can read a sanitized status.
- Reject attempts to change a blocked tenant preference from off to on with 403.
  Resubmitting an unchanged legacy preference never grants effective access.
- The current company form sends `storefront_enabled` on every save. Update it to
  omit platform-locked controls so unrelated company saves continue working.
- Never accept `platform_allowed`, identity, approval actor, or usage ceilings from
  a tenant settings payload. Use strict schemas.
- Use version checks on platform/tenant settings saves; conflicting edits return 409.
- Policy lookup failures return a controlled unavailable response, never enabled.

### 3.4 Storefront compatibility

Apply the effective policy in the existing shared storefront gate, not just the UI.
`GET /catalog/company` continues to work while closed, but returns the effective
`storefront_enabled` value so public clients display the unavailable page.
Authenticated `/company` retains the stored preference and gains a feature-status object.

Cover catalog/home/list/product, availability, cart/quote/checkout/order creation,
and enquiries through their existing gate dependencies. Recheck before accepting a
new order; a stale browser must not bypass a platform disable.

Keep policies, shopper sign-in, existing order tracking, already-created order
payment reconciliation/webhooks, and Operations Portal access working as intended.
Do not stop reconciliation of money already accepted. Review each gate dependency
before changing behavior; feature disable is not workspace suspension.
The owner-only note in `StorefrontGate` must distinguish platform block from tenant opt-out.
Public visitors see the neutral unavailable message, not subscription/admin details.

### 3.5 Disable and in-flight AI behavior

- Recheck policy when receiving messages/uploads, discovering tools, approving,
  and immediately before business execution.
- A disable prevents new provider calls and unstarted execution. Persisted drafts/history
  remain; eligible users may read them without making provider calls.
- Let a transaction already inside its business service finish or roll back normally.
  Disabling does not reverse a committed transaction or terminate database connections.
- Store policy/capability revisions on execution attempts; invalidate stale approvals
  after relevant execution-policy changes. Re-enable requires revalidation/reapproval.
- Read persisted execution status to resolve a response lost during disable.

## 4. Separate Tenali Platform AI page

Frontend route: `/platform/ai`, inside the existing platform-authenticated layout.
Reuse the platform boundary; tenant/shopping sessions cannot access this page or APIs.

Sections within one page:

1. **Overview:** global AI enable/disable, provider readiness (configured/not configured),
   integration health, aggregate usage, pending/unknown executions.
2. **Defaults:** routine/document model, request/context/output/file limits,
   daily requests, monthly token/spend ceilings, concurrency, timeouts, retention,
   approved user-facing guidance, support contact.
3. **Tenants:** searchable/paginated tenant entitlements, effective state,
   inheritance/overrides, usage, reset-to-defaults. Reuse the client administration
   feature controls; do not maintain a second independent enable flag.
4. **Capabilities:** reviewed adapter inventory, version/schema fingerprints,
   enable/disable and permitted operation restrictions; incompatible tools clearly blocked.
5. **Usage and audit:** tenant/model aggregates, configuration changes, correlation IDs,
   controlled errors; no default access to private user transcripts or attachments.

Store operational settings in PostgreSQL. Environment values bootstrap deployment;
validated platform settings supply runtime defaults. Keep `OPENAI_API_KEY` and any
storage secrets server-side. The page must not accept, return, or display secret values.
Secret rotation remains a deployment/secret-management operation.

No-code settings may change models within a validated allowlist, quotas, opt-ins,
capability subsets, support contact, and bounded non-security guidance.
They cannot relax approval, module/store authorization, tenant/user isolation,
tool schema constraints, or idempotency requirements. Model support is validated
against required Responses/tool/structured-output/image features before activation.
No arbitrary provider endpoints or executable prompt templates.

Overrides use `null` to mean inherit; reset is explicit. Limits must have positive,
bounded values; zero must not accidentally mean unlimited. Tenant overrides cannot
exceed deployment/global safety ceilings or grant a globally disabled capability.
Price schedules are versioned estimates in a declared currency, not customer billing.

## 5. Business capability inventory

Paths below are relative to `/api`; adapters must be registered explicitly.
This is the initial integration inventory, not authorization to expose every endpoint.

| Capability | Existing route/service | Proposed availability |
| --- | --- | --- |
| Company configuration read | `GET /company`, `CompanyService` | Filtered context, Phase 1 |
| Store lookup | `GET /stores`, `StoresService` | Read, Phase 2; permitted stores only |
| Product lookup/detail/stock | `GET /inventory/products`, `GET /inventory/products/{id}`, `InventoryService` | Read, Phase 2 |
| Brand/category lookup | `GET /inventory/lookups`, `InventoryService` | Read, Phase 2 |
| HSN lookup | `GET /masters/hsn`, `MastersService` | Read, Phase 2; actual module authorization applies |
| Vendor/customer lookup | `GET /parties`, `PartiesService` | Read, Phase 2; not a separate vendor module |
| Account lookup/balances/expense history | `GET /accounts`, `/accounts/tally`, `/accounts/transactions`, `AccountsService` | Read, Phase 2 |
| Purchases/outstanding vendor payments | `GET /purchases`, `PurchasesService` | Read, Phase 2 |
| Invoices/sales | `GET /billing/invoices`, `BillingService` | Read, Phase 2 |
| Receivables | `GET /collections/receivables`, `CollectionsService` | Read, Phase 2 |
| Refund/borrowing state | `GET /settlements/refunds`, `/settlements/borrowings/summary` | Read, Phase 2 |
| Reorder/reconciliation | `GET /inventory/alerts`, `/inventory/reconciliation` | Read, Phase 2 |
| Period lock status | `GET /accounts/period-locks`, `AccountsService` | Read, Phase 2 |
| Purchase create | `POST /purchases`, `PurchaseCreate`, `PurchasesService.create_purchase` | Draft + approval, Phase 4; existing posting replay |
| Expense payment | `POST /accounts/business-payments`, `BusinessPaymentCreate`, `purpose="expense"` | Draft + approval, Phase 4; existing posting replay |
| Purchase payment | `POST /purchases/{id}/payments`, `PurchasePaymentCreate` | Draft + approval, Phase 4 after replay-contract tests |
| Customer collection receipt | `POST /collections/receivables/{id}/payments` | Draft + approval, Phase 4 after replay-contract tests |
| Stock adjustment/transfer | `POST /inventory/products/{id}/stock`, `/inventory/transfers` | Draft + approval, Phase 4; existing posting replay |
| Purchase goods received | `POST /purchases/{id}/confirm-receipt` | Later activation after concurrency/recovery validation |
| Product create/confirm/merge | `POST /inventory/products`, `/{id}/confirm`, `/{id}/merge` | AI drafts supported; execution blocked until safe recovery verified |
| Vendor/customer create/update | `POST /parties`, `PATCH /parties/{id}` | Later activation; duplicate-safe recovery not yet verified |
| Invoice create | `POST /billing/invoices`, `InvoiceCreate`, `BillingService` | Later approved integration, not first-release scope |
| Cancellation/refunds/deletion/period reopen | Existing billing/purchase/settlement/deletion/accounts APIs | Read/explain initially; destructive/high-impact tools off |

Expense payments may also create borrowing entries when funded from a non-company
account. Draft cards must show this side effect and require confirmation of
`create_borrowing`, account, amount, category/purpose, date, and payment mode.
Do not misclassify payment against an existing purchase as a new expense.

Purchase approval must show goods-received state, payment state, tax treatment,
store, line items, and any new draft products. Existing purchase posting creates
draft products when requested and computes totals from lines; do not separately
add stock and double-count goods. Preserve `received_now` and existing receipt workflow.
Clarify whether "15,000" is the bill total, taxable amount, or amount paid.

Generic `POST /accounts/transactions` does not expose an idempotency key in
`AccountTransactionCreate`; it is not the initial expense execution path.
An AI "receipt" initially means a collection against a resolved receivable;
other receipt meanings require an explicitly verified adapter or a reported gap.

## 6. Capability registry and orchestration

Use explicit code adapters plus versioned database metadata/settings, not hardcoded
keyword-to-command rules. The model understands freely phrased requests using
descriptions and schemas for the capabilities currently available to that user.

Registry entry:

- Stable key, module, read/draft/mutate classification, description.
- Reviewed adapter key; existing operation reference and Pydantic input/output schema.
- Schema version/fingerprint, adapter version, compatible application contract.
- Required module/role/store restrictions, tenant scope, allowed output projection.
- Immutable safety classification: approval requirement, replay/recovery contract.
- Platform enabled state and tenant allowed subset.

Generate candidate metadata from OpenAPI where useful; validate against existing
schemas. Discovery never activates an endpoint. A changed incompatible schema blocks
only its capability, invalidates affected approvals, and records an integration event.

Per request:

1. Resolve authenticated tenant/user and effective platform/tenant policy.
2. Filter capabilities by policy and current role/module/store restrictions.
3. Build minimal authorized tenant/user/conversation context.
4. Ask OpenAI Responses for structured understanding/tool proposals.
5. Backend validates schemas and runs only authorized read tools or AI-draft operations.
6. Resolve ambiguous records and missing fields conversationally; do not invent IDs,
   tax rates, accounts, payment status, HSN codes, or quantities.
7. Produce an editable draft; execution is a separate authenticated approval path.

Read tools have bounded result sizes and sanitized output. Current product/party
lists are not a ready-made bounded semantic-search API; filter and cap service output
server-side, measure catalog size, and report a bounded-retrieval integration gap if
the existing service interface cannot scale. Never send entire catalogs/history to OpenAI.
Start with scoped lookup, not a vector database or copies of all business records.

## 7. Draft, approval, execution, and recovery

Preserve the specification's clarification/draft/validation/approval/execution states.
Add `EXECUTION_UNKNOWN` for a timeout/crash where a business commit may have occurred;
this is distinct from a confirmed failure.

- Each draft has an increasing version, canonical payload hash, capability/schema
  version, policy revision, initiator, expiry, and referenced record snapshots.
- Editing material fields increments the version and invalidates approval.
- Only the authenticated user's explicit **Approve and submit** action counts.
  Chat text such as "yes", model output, or an uploaded instruction is not approval.
- Approval body contains expected draft version/hash, not an approver ID.
- Lock/check draft state when claiming execution. Unique draft/version execution
  identity plus a server-generated stable business submission key prevents double clicks.
- The execution gateway explicitly repeats business module/store/role checks.
  `/ai` requests do not automatically receive the original business path's
  middleware permission check; direct service calls cannot rely on that check.
- Use tenant-scoped business sessions with the actual authenticated actor; never
  a platform/service account to bypass business permissions.
- Do not hold a database transaction open while waiting for the model or human.
- Schema/read preflight is not a guarantee that posting will succeed. There is no
  verified general dry-run API. Never validate by posting real transactions and
  hoping to roll them back, or copy business calculation logic into AI.
- Before executing, re-resolve records and recheck relevant snapshots, authorization,
  period status, stock, and approved amounts. Changed material facts require a fresh
  draft/approval. Each adapter must demonstrate that service recalculation cannot
  silently change the approved action; otherwise keep it disabled pending a safe contract.

### Commit boundary

Existing purchase/business-payment services commit internally. A separate AI ledger
write is not automatically atomic with that commit.

1. Persist the approved execution claim and exact immutable business request first.
2. Execute using the business service's verified submission/replay contract.
3. Persist returned business references and final execution/audit state.
4. After a crash or lost response, mark unknown and reconcile the same submission key.
   Reconcile a confirmed outcome read-only even if AI is now disabled; do not post
   a missing transaction without current authorization, policy, and valid approval.
5. Retry business mutations only where the existing contract proves duplicate safety.
   Never issue a new submission key, fuzzy-match a transaction to infer success,
   or treat unknown as "nothing happened."

For non-idempotent endpoints, require a demonstrated atomic adapter integration or
an approved integration contract before transactional activation. An AI ledger alone
does not close the service-commit crash window. Product/vendor create is therefore
not promised safe merely because an AI draft exists.

For multi-step instructions, represent dependent drafts and results explicitly.
Do not claim all-or-nothing execution across multiple services that commit independently.
Show partial completion; dependent actions stop after failures, without automatic
financial compensation/cancellation.

## 8. Proposed AI data model and isolation

Use `company_id` to match Tenali, not a parallel tenant identity system. UUID primary
keys, `timestamptz`, JSONB for structured payloads, and indexed ownership/date fields.
Use precise numeric money/token accounting, not floating-point stored costs.

| New table | Main fields / ownership | Phase |
| --- | --- | --- |
| `tenant_feature_controls` | Platform entitlement per company/feature; version/admin attribution | 1A |
| `ai_platform_settings` | Singleton global enable, defaults, ceilings, support, retention, version | 1A |
| `ai_tenant_limits` | Platform-owned company model/budget/capability overrides; null means inherit | 1A |
| `ai_tenant_settings` | Company-owned AI opt-in and allowed restrictions; cannot edit platform ceilings | 1A |
| `ai_conversations` | Company/user/title/status/summary/version/timestamps | 1B |
| `ai_messages` | Company/user/conversation/role/content/type/turn status/client request key | 1B |
| `ai_user_context` | Company/user/key/value/provenance/version/expiry; explicit user preferences | 1B |
| `ai_tenant_context` | Company/key/value/provenance/permission classification/version/expiry | 1B, only when needed |
| `ai_usage_logs` | Company/user/conversation/provider request/model/token classes/estimated cost/status | 1B |
| `ai_usage_reservations` | Company/user/request/budget period/reserved limits/settled state/expiry | 1B |
| `ai_capabilities` | Global reviewed adapter metadata/schema fingerprints/safety/version/status | 2 |
| `ai_action_drafts` | Company/user/conversation/capability/payload/version/hash/status/expiry | 3 |
| `ai_action_approvals` | Company/user/draft/version/hash/actor/status/timestamp/policy revision | 3 |
| `ai_tool_executions` | Company/user/conversation/draft/version/claim/key/status/business reference/error | 2 reads; 4 writes |
| `ai_audit_events` | Company/user/conversation/draft/event/correlation/version/reference/timestamp | 1B onward |
| `ai_attachments` | Company/user/conversation/stored-file reference/hash/status/extraction/provenance | 5 |

The extra platform/reservation tables separate platform-owned ceilings from
tenant-owned preferences and prevent concurrent requests from overspending a limit.
Do not create all tables in one first migration.

Isolation:

- Company-owned rows use existing company RLS. Private conversation/message/context/
  draft/approval/execution/attachment rows additionally require
  `user_id = app.actor_user_id` for tenant runtime.
- Composite parent ownership keys/FKs ensure a message/draft/attachment cannot name
  another company's or user's conversation even if its individual IDs exist.
- Settings permissions must be enforced at both endpoints and database grants/policies:
  staff cannot opt in tenants; tenant admins cannot edit platform controls/limits.
- Global metadata/default reads use a deliberately restricted non-secret projection.
  Tenant runtime gets no global settings write privilege; private platform data
  remains behind the platform service. No new tenant-side unscoped database access.
- Runtime audit/approval history is append-only, with no update/delete grants for
  immutable events. Retention cleanup uses a separately authorized maintenance path.
- Business references are linked in the AI ledger rather than adding AI columns
  to transaction tables. Preserve existing actor/audit semantics.
- Tenant admins/platform admins do not automatically gain access to private user chats.
  Platform audit reports expose operational metadata, not transcript/extraction contents.
- Deleting a conversation must not cascade-delete approvals/execution audit.
  Define retention/pseudonymization before enabling permanent purge.
- Store only authorized minimal context; do not automatically promote user preferences
  into shared tenant context. Tag cached business content by permission provenance.
  Recheck permissions on retrieval and exclude/redact content after module/store access
  changes; summaries must not reintroduce inaccessible records.

## 9. API contracts

All tenant AI endpoints use current identity, tenant-scoped `get_db`, CSRF for writes,
strict payloads, and ownership checks. List/search APIs are paginated.

| Endpoint under `/api` | Contract |
| --- | --- |
| `GET /company/features` | Sanitized AI/storefront platform permission, tenant preference, effective state, reason/support |
| `GET /ai/settings` | Current tenant AI preferences/effective status; no credentials |
| `PATCH /ai/settings` | Owner/admin only; tenant preference/restrictions + expected version |
| `POST, GET /ai/conversations` | Create or paginated own history |
| `GET, PATCH, DELETE /ai/conversations/{id}` | Own history, rename/archive; policy-governed deletion |
| `POST, GET /ai/conversations/{id}/messages` | Idempotent message submission and paginated retrieval |
| `GET /ai/capabilities`, `GET /ai/capabilities/{key}` | Only compatible capabilities permitted to this user |
| `GET /ai/drafts/{id}`, `PATCH /ai/drafts/{id}` | Own versioned structured draft; edit invalidates approval |
| `POST /ai/drafts/{id}/validate` | Schema + authorized read preflight; warnings and readiness |
| `POST /ai/drafts/{id}/approve`, `/reject` | Explicit authenticated decision on expected version/hash |
| `POST /ai/drafts/{id}/execute` | Execute exact approved action, return stable execution ID/status |
| `GET /ai/executions/{id}` | Recover/poll own persisted outcome; no execution side effect |
| `POST /ai/conversations/{id}/attachments` | Private verified uploads, Phase 5 |
| `GET /ai/attachments/{id}` | Own authenticated download/metadata; no public object URL |
| `GET /ai/usage`, `GET /ai/context` | Own usage/context; tenant aggregates only for authorized admin |
| `PATCH, DELETE /ai/context/preferences/{key}` | Own explicit preference management, not shared business facts |
| `GET, PUT /platform/ai/settings` | Platform defaults, expected version, audit |
| `GET /platform/ai/tenants` | Paginated/searchable settings and aggregates |
| `GET, PATCH /platform/ai/tenants/{company_id}` | Platform-owned overrides; reset via explicit nullable fields |
| `GET, PATCH /platform/ai/capabilities/{key}` | Reviewed metadata/config only; cannot change safety classification |
| `GET /platform/ai/capabilities` | Registry inventory including blocked compatibility status |
| `GET /platform/ai/usage`, `/platform/ai/audit` | Paginated operational metadata/aggregates |
| `GET, PATCH /platform/workspaces/{company_id}/features` | Platform AI/storefront entitlements, expected version |

Use existing FastAPI `detail` errors, with documented typed detail only where the
new client requires status/reason. Never return success-shaped fallbacks.
409 covers stale versions/claim conflicts; 403 covers policy/permission blocks;
429 covers quota/rate limits; 503 covers provider/configuration unavailability.
Mutation ambiguity returns a persisted execution status, not an invitation to repeat posting.

Message responses contain assistant text, structured clarification/draft data,
turn/execution references, and controlled errors. Serialize competing turns within a
conversation and deduplicate by client request key. Initially use bounded request/response
plus status recovery; add streaming only with persistent turn state and disconnect tests.

Existing viewer-role middleware blocks non-GET requests, including chat creation.
Initial release preserves viewer read-only behavior; enabling conversational read tools
for viewers would require a separately reviewed, narrowly scoped metadata-write exception.
Never relax viewer business mutation restrictions as a side effect of introducing AI.

## 10. Frontend and files

Implement only the files needed by each phase, not the specification's entire
suggested class/service tree upfront.

New backend groups:

- `api/app/ai/router.py`, `schemas.py`, `settings.py`, `policy.py`
- `provider.py`, `orchestrator.py`, `context.py`, `conversations.py`, `usage.py`, `audit.py`
- `capabilities.py`, `drafts.py`, `execution.py`, reviewed `adapters/`
- `attachments.py` in Phase 5; incremental Alembic revisions and focused AI tests.

New frontend groups:

- `web/src/pages/TenaliAIPage.tsx` at `/portal/ai`
- `web/src/components/PlatformAISettings.tsx` rendered at `/platform/ai`
- `web/src/features/ai/`: typed API client, history/messages, draft editor/approval/
  execution cards and attachment components as their phases are implemented.

Existing integration files:

- Backend router registration, `requirements.txt` for OpenAI SDK when implementation
  begins, deployment environment documentation without secrets.
- Platform page/sidebar and route registration; shared client feature controls.
- Company settings/schema/types; storefront helper/public-company response/gate note.
- Portal navigation and tenant-aware frontend transport; reuse notification styles.

Keep review/edit/clarify/approve/execute inside the assistant. Business reference links
are available after execution, not required to finish approval. Respect responsive
layouts, keyboard focus, accessible disabled-state explanations, and checkbox alignment.
Reuse shared validation/error rendering. AI-internal message/draft mutations should not
trigger generic record-success workflow notices; confirmed business execution may show
the existing relevant next steps once. Logout/workspace changes clear in-memory AI state.

## 11. Cost, privacy, and operational safety

- Use a small provider interface; OpenAI Responses is the only initial production
  provider. Keep tool/structured responses normalized and schema-validated locally.
- Runtime model changes require validated settings; do not hardcode model IDs across files.
- Reserve conservative request/token/spend budgets atomically before provider calls,
  then settle actual usage. Track retries, failed/unknown calls, cached token classes,
  images/documents, user/tenant/model totals, and pricing version.
- Bound context/output/tool loops/concurrency and enforce daily/monthly budgets with
  explicit accounting periods. Unknown usage retains a conservative reservation
  until reconciled; timeouts must not make cost vanish.
- Retry transient provider/read failures within a limited budget; never blindly retry
  non-idempotent business writes. Do not send a second model request to replay execution.
- AI subscription usage has no customer-facing per-request charge initially.
  Display limits and availability; actual provider costs are measured, not promised.
- Use private verified file storage; initial attachments honor the existing 5 MB/file,
  count/total limits, plus explicit PDF page/extraction limits at Phase 5.
- Storage currently has no verified signed-URL method. Start with authenticated AI
  downloads/backend file transfer; implement and review short-lived signing only if needed.
- AI attachment ownership wraps `stored_files`: a company-scoped file ID alone does
  not establish user ownership. Do not use business attachment endpoints to expose chats.
- Define deletion/reference cleanup so deleting a chat never deletes a file already
  attached to a posted purchase/payment. Provider-uploaded files need cleanup/expiry too.
- Treat documents/tool output as untrusted data; never instructions, executable code,
  or permission claims. UI renders sanitized text/structured cards, not executable HTML.
- Minimize data sent externally; deployment needs an approved privacy/retention policy
  covering OpenAI processing and provider storage settings before production enablement.
- Log correlation IDs, statuses, token counts, and controlled errors; no secrets,
  raw document contents, hidden model reasoning, or unrestricted payloads in application logs.

## 12. Phased delivery and acceptance gates

| Phase | Deliverable | Exit criteria |
| --- | --- | --- |
| 0: this plan | Architecture, registry inventory, policy/data/API contracts, integration gaps | Review and approve scope/defaults |
| 1A: control plane | Platform AI page; client AI/storefront entitlements; tenant toggles/contact tags; migrations | Policy matrix tested server/UI; existing storefront behavior preserved |
| 1B: assistant foundation | OpenAI gateway, own persistent chat/context, usage reservations/logs, portal page | Mock-provider tests; isolation and budget limits verified; no business write tools |
| 2: read orchestration | Registry and scoped reads, dynamic tool selection, clarification | Module/store permissions, bounded context, changed/disabled capabilities tested |
| 3: draft approval | Editable versioned drafts, preflight, approvals, audit | Edits invalidate approval; no business execution before approval |
| 4: verified writes | Purchase/expense first, then verified receipts/stock operations | Replay, concurrency, timeout/crash recovery, side effects and attribution tested |
| 5: documents | Private uploads, extraction/matching, duplicate hints, editable extracted values | Malicious files/prompts, ownership, totals, cleanup and no automatic posting tested |
| 6: production hardening | Operational monitoring, failure drills, retention, rollout | End-to-end scenarios A-D, isolation, quotas and rollback/deployment readiness |

Each implementation phase reports changed files, verification, gaps, and next approval.
Migration files are reviewed before application; live database deployment needs explicit
authorization. No code commit, provider invocation, or production activation is implied
by approval of this document.

Tests:

- Mock OpenAI and storage; use isolated test PostgreSQL for write/concurrency/recovery
  tests. Existing rollback fixtures are useful but do not prove independent commit/crash
  behavior. Do not run AI financial simulations against the live database.
- Feature truth table: platform allowed/blocked x tenant on/off, inactive workspace,
  missing config, stale browser, direct API override, other tenant, global AI off.
- Confirm platform storefront disable leaves Operations, policies, order tracking and
  legitimate existing-order reconciliation intact.
- Confirm tenant/shopping sessions cannot use new platform routes; platform config
  access does not imply private chat access.
- Cross-tenant and cross-user CRUD, composite ownership, RLS, role/store revocation,
  context summaries, file downloads, admin-write restrictions.
- Duplicate messages/approvals/executions, concurrent edits, unknown execution recovery,
  replay payload mismatch, policy disable while pending, permission loss before execute.
- Purchase inventory/receipt/payment effects, non-company-account expense borrowing,
  closed periods, required fields and changed approved tax/amounts.
- Parallel quota reservations, retries/timeouts, month/day rollover, inherited overrides,
  invalid models/settings, exhausted budgets, provider failure.
- Frontend disabled checkbox/contact tag, keyboard/mobile behavior, draft editing,
  logout isolation, execution recovery, no duplicate workflow notifications.
- Run focused backend unittests, existing web Node tests, TypeScript checks, production
  build, migration upgrade checks in the test database, and relevant regression tests.
  Phase 0 documentation requires no build or database migration.

## 13. Approval items before implementation

Recommended implementation start: **Phase 1A**, then **Phase 1B**, rather than deploying
all AI components at once.

Confirm before activating provider requests:

1. Approved model(s) and daily/monthly token/spend limits; API key configured privately
   in the backend environment, never pasted into chat or the admin page.
2. Platform support contact and chat/file/audit retention rules.
3. Pilot tenant(s), data-processing consent/privacy notice, and test database availability.
4. Viewer conversation support is deferred by default; product/vendor transactional
   integration remains gated on a demonstrated safe execution/recovery contract.

No numerical cost estimate, safe arbitrary-tool onboarding, atomic multi-service execution,
or complete non-mutating business validation is claimed by this plan.

## 14. Phase 2A implementation: bounded catalogue reads

Revision `043_ai_read_capabilities` adds an opt-in reviewed read registry and
platform-owned per-tenant grants. The first slice includes stores, product/SKU stock
lookup, parties, HSN/SAC, brands and categories. Financial history/totals, invoices,
purchases, receivables, settlements, reorder/reconciliation and period-lock lookups
remain Phase 2B work; they are not advertised as available adapters yet.

- All capabilities start disabled, unreviewed and denied to tenants. A platform
  administrator reviews/enables the deployed contract and separately grants it to a
  tenant in Platform -> Tenali AI. Existing AI feature/opt-in gates still apply.
- Compatibility fingerprints cover the actual input schema, output projection,
  module path and adapter version. Changed contracts block only their capability
  until explicitly reviewed. Behaviour-only adapter changes must bump adapter version.
  Configuration cannot add executable adapters, arbitrary SQL or provider URLs.
- The current membership role/module/store restrictions are read from a narrow
  security-definer function. Tenant runtime gains no identity-table read permission.
  Membership, global/tenant AI policy, capability revisions and module/store scope
  are rechecked after the provider responds, before business reads.
- One structured provider call proposes at most two validated lookup arguments.
  The backend appends bounded, projected **verified Tenali lookup** data to the reply.
  This deliberately avoids a second paid synthesis call in the initial economical
  implementation. The provider does not see fresh results during that call; earlier
  saved results can appear in subsequent bounded chat history. Replies and results
  must distinguish historical facts and incomplete matches from current/full totals.
- Reads use database-side search and `limit + 1` (at most 11 fetched rows) rather than
  fetching entire catalogues. Result projection omits party contacts, addresses and
  account credentials. Product stock sums only permitted stores and all variants;
  it is not vendor availability or a price quote. Exact variant-specific stock and
  pricing are not implemented in this slice.
- Context reservations now include the serialized structured-output schema bytes
  plus protocol overhead. Reads do not create additional provider requests. Unknown
  provider outcomes retain reservations, and rejected reads still settle known
  provider usage. Stable message replay repeats neither reads nor provider calls.
- Read audit events contain capability/outcome metadata, not copied business bodies.
  No business tables are mutated by the adapters. No drafts, execution, document/image
  uploads or image generation are included.

Validation uses mocked provider responses and rollback-only read/configuration
fixtures. Live migration, API restart and paid verification need separate approval.
After this slice's deployment gate, continue Phase 2B before draft/approval (Phase 3),
verified writes (Phase 4), private documents/images (Phase 5) and hardening (Phase 6).

## 15. Phase 2B implementation: financial and business-state reads

Revision `044_ai_business_reads` adds opt-in reviewed adapters for accounts, posted
transactions, invoices, purchases, receivables, refunds, borrowing balances, reorder
reminders, stock reconciliation and active period locks. It only inserts disabled
registry metadata; the six existing catalogue contracts/grants are preserved.

Strict business arguments are separate from catalogue arguments. Each capability
documents its supported dates/status/store filters; unsupported combinations are
rejected. Lookups return at most 10 projected records (11 fetched for truncation
detection), and no complete company financial totals. Existing services provide
balance/cancellation/reversal rules through optional bounded read filters while
preserving ordinary API list defaults. Runtime schema fallback writes are refused
by AI adapters; database migrations are mandatory.

Company-wide account/transaction/borrowing ledgers require unrestricted stores.
Store-limited members cannot discover or execute those adapters. Other documents
are filtered by permitted stores; standalone receivables and refunds without a
matching document store are excluded for restricted members. Module access and
current membership are rechecked before reads as in Phase 2A.

Account as_of returns historical ledger balances. Lock as_of checks the date against
currently active locks, not historical lock state. Other date filters select document
date/due date/creation date as documented, not historical payment snapshots. Scoped
reorder uses permitted quantities versus configured thresholds and can differ from
company-wide alerts. No matches/partial results must not be interpreted as certified
posting eligibility or complete financial totals.

Validation seeds finance records only in an explicitly authorised isolated PostgreSQL
database, never the live database, and mocks provider calls. No live migration or paid
test is implied. Phase 3 editable drafts/approvals is described below; business writes
and private document/image processing remain gated on their later contracts and tests.

## 16. Phase 3 implementation: private operational drafts (historical)

This describes revision 045. The posting, private-file and interface changes in
section 17 supersede its draft-only release restrictions.

Revision `045_ai_action_drafts` adds separate platform/tenant draft controls and
private versioned drafts. All eleven operational actions start disabled, unreviewed
and without tenant grants: expense, purchase and invoice creation; party/product
creation and update; stock adjustment/transfer; purchase payment and receivable
collection. Administrative settings, deletion/cancellation and document uploads are
excluded. Read grants never grant draft permission, and draft permission never
grants execution. New tenants inherit denial through absent grants.

The same metered provider call can propose at most one unvalidated private draft.
Only deployed, reviewed and currently permitted actions are offered. JSON proposals
are untrusted: the backend checks capability revisions, current membership/module/
store scope, ownership, size and server-owned submission identity. Missing fields
stay incomplete; they are not authorisation to invent values. Saving a draft and
settling its originating message/usage occur in the same transaction. Stable client
references replay saved outcomes instead of repeating provider calls or resetting
edited/approved drafts.

The tenant page displays private draft cards with an advanced JSON field editor,
schema inspection, validation and an explicit **Approve draft only (no posting)**
confirmation. Validation normalises fields against existing business schemas and
checks selected references, current permissions and accounting locks. Its report
explicitly states that full business-service validation, tax recalculation, stock
and duplicate-safe execution are **not yet certified**. Defaulted fields are shown
in the canonical draft and must be reviewed. Product update is a full replacement:
every field must be supplied to avoid resetting omitted settings.

Approval binds current version/hash, contract/policy revisions and hashed reference/
permission snapshots. Any edit clears approval and increments the version. Approval
also records append-only hash/version/contract/snapshot proof in `ai_draft_approvals`;
old proof survives edits and content scrubbing, but never approves a later version.
Tenant runtime cannot update or delete approval records. Approval
rechecks these facts, rejects stale references, and cannot be granted by chat text,
model output or another user's session. The ledger has no executing/executed status,
and there is deliberately no `/execute` route. Phase 4 must establish certified
service preflight and atomic/recoverable idempotent execution before posting can be
introduced; a Phase 3 approval is not a promise of posting eligibility.
Phase 4 must revalidate and obtain renewed approval on a certified full business
preview; it must never automatically promote existing Phase 3 intent approvals.

Drafts expire within seven days or the earlier conversation expiry. Conversation
deletion scrubs draft payload/validation; explicit discard and maintenance scrub
expired/deleted drafts while preserving audit event metadata. Own history remains
readable when AI is disabled, but validation/edit/approval require effective AI and
current action permissions. Runtime RLS and composite conversation ownership FKs
isolate users and tenants; platform operators get contract/control metadata, not
private content.

Apply revision 045 before deploying this API/frontend. Live migration requires
explicit approval. Validation uses a disposable, explicitly authorised synthetic
database and mocked provider, never live financial fixtures or paid calls.

## 17. Approved operational execution and private document inputs

Apply revisions `046_ai_execution` and `047_ai_private_media` before deploying the
updated API/frontend. Deployment and live migration still require explicit approval.
Existing read settings, limits, user preferences and tenant grants are preserved.
Execution switches and document inputs default off. All action fingerprints change,
so older reviewed contracts cannot enable posting; old Phase 3 approvals must be
validated and explicitly approved again.

The eleven add/update actions dispatch existing business services with `commit=False`.
Their default `commit=True` preserves ordinary API behavior. The gateway holds the
conversation/draft, policy and relevant reference locks, recalculates the approved
preview, verifies the matching immutable approval proof, and uses one database transaction for business mutations, audit and an
append-only `ai_executions` result. Server-generated submission identity is stable
for draft/version. Concurrent submissions serialize, and retries replay that exact
outcome without calling OpenAI or posting again. Rejected business validation rolls
back the complete savepoint and records a failed outcome. Edit/review/reapprove a new
draft version to try corrected values. A transport/commit error returns 503 with
same-draft recovery instructions, never a replacement key or automatic retry.
Failed outcomes retain only a generic reason and status code; detailed business
validation errors are returned only on the initial submission, not retained or replayed.
An outcome-read failure after commit also requires same-draft/version recovery.
Downgrading to 045 discards and scrubs executed drafts, rather than restoring approval;
re-upgrade starts with posting disabled.

Document previews reuse read-only product resolution, configured HSN rates, shared
purchase line calculations and `build_invoice_document`; they never post and roll
back a business document as validation. Approved impact includes authoritative totals,
payment amounts, document identity, new products, missing product-HSN updates, stock before/change/after/reservations,
and borrowing side effects. Changes require reapproval. Existing final business rules
remain authoritative and can reject submission atomically.

Separate high-impact actions cover invoice/purchase cancellation, unused-product
deletion and one transaction deletion. Owners/admins need unrestricted store scope,
the underlying module, reviewed action, tenant grant and separately enabled posting.
They require an impact preview and exact typed business label. Existing cancellation
and deletion dependency rules are reused: invoice deletion/reset-all/administrative
settings are not offered, used products cannot be deleted, paid cancellations create
pending refunds rather than immediate cash refunds, and reserved/consumed stock blocks
invalid cancellation. Existing immutable deletion archives remain authoritative.
Stock transfers record workspace-user attribution in a narrowly validated new column;
legacy profile attribution is retained and tenant credentials receive no SELECT grant.

Private uploads accept UTF-8 `.txt`, text PDF (one to five unencrypted pages), or a
single PNG/JPEG/WebP image, at most 2 MB/file, ten retained files/conversation and two
files/message. Text extraction is limited to 12,000 UTF-8 bytes. Scanned PDFs must
be uploaded as page images. Images are decoded, orientation-corrected, stripped of metadata and normalized
to a JPEG no larger than 512 x 512, sent at low detail for economical reading.
Original binary PDFs/images are not forwarded to the provider or exposed through
public URLs. Normalized private bytes/text are stored in `ai_attachments`, protected
by company/user/conversation ownership, RLS and expiry. There is intentionally no
download or public-storage endpoint in this initial extraction release.

Upload alone does not call OpenAI. **Send** explicitly processes only selected files
using the allowlisted document model, `store=False`, existing structured output and
no executable provider tools. The model may propose an unvalidated draft, never
approve it. File instructions are untrusted data. Message replay binds both text and
attachment IDs; it cannot change attached files or repeat provider processing.
The existing atomic tenant budget function reserves text byte bounds plus 16,000
tokens per normalized image, then settles provider-reported usage at separately
configured document prices. Failed/unknown calls retain conservative accounting.
Images are not guaranteed accurate; users must review extracted figures and fields.

Removing a private file or deleting/expiring a chat scrubs its normalized bytes,
extracted text and filename. Maintenance scrubs expired attachments alongside chats
and drafts. Private AI uploads are not automatically attached to posted business
documents; business receipt retention remains the existing separate workflow.
Platform operators see usage/control metadata, not private files/transcripts.

The simplified assistant has collapsible conversations, tools/preferences/usage and
operation review. Titles save after a 600 ms pause or blur, with expected versions,
in-flight race protection and visible retry errors. Add/update and cancel/delete have
separate review views; structured fields and readable impact replace default raw JSON
(advanced JSON remains available). Message roles remain accessible without visible
speaker-name clutter. Mobile inputs use at least 16 px to avoid iOS focus zoom, without
disabling user pinch zoom.

## 18. Private metered microphone transcription

Revision `048_ai_voice` adds a separately enabled, duration-priced transcription
contract (`gpt-transcribe`), using the backend key and model allowlist. English/Tamil
microphone recordings become editable text, never an automatically sent message or
an action approval. Users explicitly transcribe, review/correct, add text to the
composer, then Send separately. Audio-file uploads and synthesized voice replies
remain outside this release.

Web Audio captures mono PCM using an AudioWorklet capped at 60 seconds; cancellation,
navigation and completion stop microphone tracks and close the audio context. HTTPS
or localhost and microphone permission are required. The server verifies WAV frames,
duration (0.5-60 seconds), format and 12 MB maximum before any provider call, re-encodes
without metadata, and never persists raw audio. Short-lived transcripts are private,
limited to 4,000 characters, expire after ten minutes and are scrubbed with deleted
or expired conversations. Only explicitly sent text enters ordinary chat history.

`ai_voice_requests` binds an authenticated conversation, stable client key, normalized
audio hash and language. Claim/reservation commits before calling the provider.
Concurrent/replayed requests recover the same pending/completed/failed/unknown result;
they never repeat transcription. Usage joins the existing reservation ledger and
tenant budget lock. Request/spend ceilings include voice while chat tokens are not
invented for duration billing. Reserve rounded-up seconds at versioned per-minute
pricing; settle known provider duration, retaining conservative cost on missing usage
or transport uncertainty. Permission/configuration is rechecked before processing;
deleted/expired conversations never receive late transcript content. No tools,
business context, previous messages or private preferences are sent for transcription.
Downgrade cannot erase recorded voice usage; disable the feature for operational rollback.
