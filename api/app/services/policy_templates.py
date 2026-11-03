"""Original starting copy, never published without an operator's review."""

TITLES = {
    "privacy": "Privacy Policy",
    "terms": "Terms of Service",
    "shipping": "Shipping and Delivery Policy",
    "payment": "Payment Policy",
    "returns": "Cancellation, Refunds, Returns and Exchanges",
    "data-deletion": "Account and Data Deletion",
    "contact": "Contact and Business Information",
}
PLATFORM_KINDS = ("privacy", "terms", "data-deletion", "contact")
TENANT_KINDS = tuple(TITLES)

PLATFORM_COPY = {
    "privacy": """WHO WE ARE
Tenali is a business workspace and storefront platform operated by Sru Global. This notice covers platform operation. Each tenant is responsible for its own storefront and customer dealings; consult that store's separate privacy policy.

INFORMATION AND PURPOSES
We process workspace and account identifiers, provider-supplied name and email, contact details, business records, uploaded files, orders, payment references, delivery details and activity/audit records as needed to provide and secure the services. Workspace administrators control their business records and team access.

AUTHENTICATION AND COOKIES
Social sign-in uses Supabase and enabled providers such as Google, Facebook, Yahoo, Microsoft or Apple. We use the provider's verified account identifier, name and email to establish a Tenali account. We do not receive your social-provider password or request access to your contacts, messages or social posts for sign-in. Existing workspace/staff password accounts and separate platform-operator credentials may also be used. Session and CSRF cookies support sign-in and request protection; browser storage supports features such as carts and sign-in routing. Sign-in to one tenant does not grant access to another.

SERVICE PROVIDERS AND DISCLOSURES
Supabase supports authentication and file storage. Where a tenant enables online payments or delivery, Razorpay processes payments and Shiprocket/couriers receive the order and delivery information needed for fulfilment. Tenali stores payment/order references and statuses, not full card numbers, CVV or UPI PINs. Hosting and service providers process information for the services they provide. Information may also be disclosed where required by law or to investigate abuse. Review the relevant providers' own privacy notices.

RETENTION, SECURITY AND YOUR CHOICES
Access controls and tenant separation help protect records, but no service is risk-free. We retain information needed to operate the service and for legitimate accounting, legal, security and dispute purposes. Unneeded personal information should be deleted or anonymised; legally required transaction records may be retained. Provider processing locations and retention may differ; do not assume all information stays in India.
Contact us using the details on this page to request access, correction, deletion or a review of a privacy concern. Identify your workspace and the account email; never send passwords, payment PINs or identity documents in an initial request. Identity/authority verification may be needed. See Account and Data Deletion for the request process.

AUDIENCE AND UPDATES
Business operators must have authority to use and share information they upload. The platform is not intended for children to create accounts independently. We may update this notice; the published date identifies the current version. Mandatory legal rights are not excluded.""",
    "terms": """PLATFORM OPERATOR AND SCOPE
Tenali is provided by Sru Global at tenali.biz. These terms cover access to the platform, not the separate sale contract between a tenant and its customers.

ACCOUNTS AND AUTHORISED USE
Use accurate details and access only workspaces you are authorised to use. Protect sign-in credentials and provider accounts; administrators are responsible for granting and reviewing team permissions. Do not misuse personal data, upload unlawful content, impersonate others, probe other tenants, or disrupt the service. Social sign-in is subject to the provider's terms and availability.

TENANT RESPONSIBILITIES
The tenant is the seller for its own products and is responsible for descriptions, prices in INR, taxes, fulfilment, customer support, required licences and published policies. Tenants must have rights to uploaded content and obtain any required permissions for personal information. Tenali's software and record-keeping do not replace professional accounting, tax or legal advice.

INTEGRATIONS AND COMMERCIAL ARRANGEMENTS
Supabase/social providers, Razorpay, Shiprocket and couriers supply separate services under their own terms. A provider order or shipment submission is not proof of payment, dispatch or delivery. Tenants use their own configured payment/delivery accounts. Any platform subscription, pricing, cancellation or refund arrangement must be stated separately in an agreed plan or written agreement; storefront product refunds are handled by the relevant seller.

AVAILABILITY AND LIABILITY
Services may be interrupted for maintenance, provider outages or security reasons. We may restrict misuse or unlawful activity. Contact support about access or data export before ending use. Nothing in these terms removes mandatory consumer/privacy rights or excludes liability that cannot lawfully be excluded. Any additional commercial allocation of liability requires an applicable agreement.

DISPUTES AND CHANGES
Contact the operator first with platform concerns and the seller with order concerns. Indian law applies, with Chennai as the agreed forum subject to mandatory law and any non-waivable right to another forum. Published changes apply prospectively subject to applicable law; material changes requiring notice or agreement must be handled accordingly.""",
    "data-deletion": """REQUEST ACCOUNT OR PERSONAL-DATA DELETION
1. Email the contact address on this page with the subject "Tenali account/data deletion".
2. Provide the email used to sign in, the workspace name/address, and whether the request concerns a shopper account, a workspace user, or the whole business workspace. Describe the data you want removed. Never send a password, OTP, CVV, UPI PIN or social access token.
3. We will verify identity and authority using an appropriate channel before changing records. For store purchases, contact the seller as well; their transaction records and retention obligations are separate.
4. We will explain what can be deleted or anonymised and what must be kept for legal, accounting, fraud-prevention or dispute reasons, and respond in accordance with applicable law. Follow up by email for status. A request is not an immediate automated erasure or cancellation/refund of an order.

SOCIAL LOGIN
You may also remove Tenali in your identity provider's connected-app settings (for example Google, Facebook, Yahoo, Microsoft or Apple). Revoking provider access alone does not delete Tenali or tenant business records. This is a manual request/instructions page, not an automated Facebook data-deletion callback.

SCOPE AND LIMITS
Deleting a tenant account does not delete the underlying social-provider or Supabase identity or unrelated tenants' records. We may need the relevant tenant to authorise deletion of business-owned data. Retained records should be limited to what is needed and access restricted. Ask the contact on this page for clarification or escalation.""",
    "contact": """TENALI PLATFORM
Application: Tenali
Operator: Sru Global
Website: https://tenali.biz
Use the business address and contact email shown on this page for platform support, privacy concerns and account/data-deletion requests.

STORE ORDERS
For product specifications, prices, dispatch, delivery, cancellation, refunds, returns and exchanges, contact the seller identified on the tenant storefront and invoice. The seller's commercial policies apply to that transaction, subject to mandatory law.

SUPPORT REQUESTS
Include a workspace address and a concise description. Provide an order reference where relevant, but never send passwords, payment PINs or full card details. If a concern is unresolved, reply in the same email thread asking for escalation.""",
}

TENANT_COPY = {
    "privacy": """SCOPE AND INFORMATION
This store's operator is identified on this page. We use your name, email, unverified phone number, delivery address, account identifier, order details, payment references and relevant support communications to operate your store account, process purchases, deliver orders and resolve queries. We also maintain necessary accounting and audit records.

AUTHENTICATION AND BROWSER STORAGE
Shopper social sign-in is verified through Supabase and enabled providers such as Google, Facebook, Yahoo, Microsoft or Apple. The verified provider identifier, name and email establish your account; we do not receive your social password or request contacts, messages or social posts for sign-in. A typed phone number is not proof of identity. Shopper accounts are separate from workspace staff accounts and other stores; linking to a counter-customer record requires administrator identity review. Session/CSRF cookies support sign-in and browser storage supports the cart and sign-in flow.

SHARING AND SERVICE PROVIDERS
Tenali, operated by Sru Global, supplies the software platform. Supabase supports authentication and file storage. If enabled for your purchase, Razorpay processes payments and Shiprocket/couriers receive necessary fulfilment and contact details. We store references/statuses, not full card numbers, CVV or UPI PINs. Data may be shared for legal obligations, security or dispute resolution. Provider processing locations and practices may differ; consult their notices.

RETENTION, RIGHTS AND CONTACT
We retain order, invoice and other records as needed for service, statutory accounting, security and disputes. Information no longer needed should be deleted or anonymised. Contact the email shown on this page to request access, correction, deletion or escalation; reasonable identity verification may be required. See Account and Data Deletion for instructions. Legal rights are not waived and deletion does not automatically cancel an order or refund a payment.

STORE-SPECIFIC PRACTICES
[[Describe any additional analytics, marketing, cookies, data recipients and retention periods; say explicitly if none. Confirm the actual practices and lawful handling of children's data.]]""",
    "terms": """SELLER AND SCOPE
The business identified on this page is the seller. Tenali provides the software platform, not the seller's goods. These terms apply to this storefront and operate alongside the published shipping, payment, cancellation/refund and returns policies, subject to mandatory law.

ORDERS, PRICING AND ACCOUNTS
All prices and payments are in Indian rupees (INR). Review the product specifications, quantity, taxes, delivery charges and final total before placing an order. An order/payment acknowledgement is not proof of dispatch or delivery. Use accurate contact/address details and only an account you are authorised to use; social-provider security and terms also apply. Do not misuse this store or other customers' information.

SELLER COMMITMENTS
We are responsible for product information, applicable taxes, fulfilment and customer support. Material availability or pricing issues will be communicated for resolution; any cancellation/refund must follow applicable law and the published policy. No policy removes mandatory consumer remedies.

ORDER ACCEPTANCE AND SPECIAL PRODUCTS
[[Describe when orders are accepted, stock/quotation confirmation, any minimum quantities, customisation approvals, age/product restrictions and how customers correct mistakes before acceptance.]]

DISPUTES AND CHANGES
Contact the seller using the details on this page to resolve an issue. Indian law and the stated jurisdiction apply subject to mandatory consumer rights and other non-waivable forums. The policies disclosed at the time of an order govern that order; later edits do not silently change past transactions.""",
    "shipping": """DELIVERY AND PICKUP
Delivery availability, pickup options and applicable charges are displayed before order confirmation. All charges are in INR. Delivery is subject to serviceable addresses and correct recipient details. Store pickup applies only where offered; wait for the store's ready-for-pickup confirmation.

HANDLING AND TRANSIT
[[State dispatch/processing time in business days, delivery time ranges by region, serviceable areas, business days/holidays and the process for personalised or bulk orders.]]

CHARGES AND TRACKING
[[State shipping charges or calculation method, any free-shipping threshold, and how/when tracking is supplied. Include any pickup deadline and identification requirements.]]

DELAYS, FAILED DELIVERY AND DAMAGE
[[Explain delay notifications, lost/damaged parcels, wrong addresses, delivery attempts, return-to-origin, any re-delivery charges and the customer support/reporting process.]]
Couriers or Shiprocket may assist fulfilment. A shipment submission is not confirmation of dispatch or delivery. Contact the seller if tracking stalls; statutory remedies for non-delivery or defective goods remain available.""",
    "payment": """CURRENCY AND TOTALS
All prices, payment amounts, shipping charges and refunds are in INR. Review the final item, tax and delivery totals before confirmation. Request a quotation where no fixed price is offered.

PAYMENT OPTIONS
Only options enabled at checkout are offered. Online prepaid payments use Razorpay where configured; cash on delivery requires store approval where offered; pay-at-pickup is available only for eligible store pickups. Do not treat closing a payment window as payment confirmation.

PAYMENT VERIFICATION AND SAFETY
Use My Orders to check status. If debited without confirmation, contact us with the order and payment reference before paying again. We verify payment status before treating the payment as successful. Never send passwords, OTPs, CVV, UPI PINs or full card details to support. Banks/payment providers control their own authorisation and settlement processes.

STORE-SPECIFIC CONDITIONS
[[State accepted methods, COD limits/charges, pickup payment options, quotation/deposit terms if any, handling of failed/duplicate payments and customer support/expected investigation times.]]

REFUNDS
Cancellation and refund eligibility, deductions (if lawful), processing time and original-method/bank-credit timelines are explained in our Cancellation, Refunds, Returns and Exchanges policy. This policy does not promise an automated refund merely because an accounting entry is recorded.""",
    "returns": """REQUESTS AND STATUTORY RIGHTS
Contact the email shown on this page with your order number and issue. Do not send sensitive payment credentials. Nothing in this policy limits mandatory remedies for defective, misdescribed or undelivered goods.

CANCELLATION
[[State how to request cancellation, the deadline/order stage, any lawful custom-order restrictions, cancellation charges and what happens if the seller cancels or cannot fulfil.]]

RETURNS AND EXCHANGES
[[State the request window from delivery, eligibility, condition/packaging requirements, exchange availability, and lawful exclusions for personalised/perishable/other goods. Explain defective, damaged and incorrect-item handling separately.]]

RETURN PROCESS AND COSTS
[[Describe approval, pickup/return address, evidence needed, who pays return shipping in each case and inspection/decision timelines.]]

REFUNDS
[[State eligibility, refund method, any lawful deductions, seller processing time after approval/receipt, expected provider/bank credit time and escalation for delayed credits.]]
Refunds require confirmation through the payment provider/bank as appropriate; a bookkeeping entry alone does not transfer money. A later policy change does not remove rights attached to an existing order.""",
    "data-deletion": """HOW TO REQUEST
1. Email the contact shown on this page with the subject "Store account/data deletion".
2. Include your sign-in email, this store's workspace address and the data/account concerned. Include an order reference only if needed. Do not send passwords, OTPs, payment PINs or social access tokens.
3. We will verify identity and authority before deleting or anonymising eligible personal information. This is a manual request; it does not instantly erase records, cancel an order or issue a refund.
4. We will explain any information retained for tax/accounting, fraud prevention, legal obligations or open disputes. Request status or escalation by replying to the same contact thread.

SOCIAL ACCOUNTS AND OTHER STORES
You may revoke Tenali's access in your identity provider's connected-app settings (for example Google, Facebook, Yahoo, Microsoft or Apple). This alone does not delete our business records or your provider account. A request here concerns this store; for Tenali platform data or another store, contact that operator separately. This page provides instructions, not an automated social-provider deletion callback.

STORE RESPONSE
[[State the request acknowledgement/response process and target times consistent with applicable law, retention exceptions and escalation contact.]]""",
    "contact": """ABOUT THIS STORE
The business named on this page operates this storefront and is responsible for the products it sells. Product descriptions and available prices are shown in the catalogue/product pages; quotation-only products require seller confirmation. All prices are in INR.

CUSTOMER SUPPORT
Use the email and business address shown on this page for product, order, shipping, cancellation, refund, return, exchange and privacy/account-deletion queries. Include your order number where relevant, not passwords or sensitive payment details.

BUSINESS DETAILS
[[Confirm trading/legal name, business address and full postal code, support hours, telephone if offered, and grievance/escalation contact or required registration details.]]

PLATFORM
Tenali is the software platform operated by Sru Global. Platform-specific support and policies are available at https://tenali.biz/policies; the seller handles store orders.""",
}


def template(kind: str, company: dict | None = None, owner_email: str = "") -> dict:
    platform = company is None
    return {
        "title": TITLES[kind],
        "business_name": "Sru Global (Tenali)" if platform else company["company_name"],
        "address": "425A, Kamakotti Nagar, Pallikaranai, Chennai 100" if platform else company.get("address") or "",
        "contact_email": "sourcedbysru@gmail.com" if platform else company.get("email") or owner_email,
        "jurisdiction": "Chennai" if platform else "",
        "currency": "INR",
        "body": (PLATFORM_COPY if platform else TENANT_COPY)[kind],
    }
