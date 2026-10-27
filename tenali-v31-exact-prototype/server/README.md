# SRU Global Operations Portal — backend starter

This folder is the server-side foundation for moving the static prototype to production.

## Run
1. Install Node.js 20+.
2. `cd server`
3. `npm install`
4. Copy `.env.example` to `.env` and set a strong `SESSION_SECRET`.
5. `npm start`
6. Open `http://localhost:8080/login.html`.

## Authentication
- Local users are read from `../data/users.csv`.
- For production, replace `password_sha256` with `password_hash` values generated with bcrypt/Argon2 and never expose them to browser code.
- Usernames may be based on verified email/phone; custom usernames must be unique.
- Federated providers are configuration points in this starter. Do not put OAuth client secrets in CSV, HTML or JS.
- Google and Microsoft should use the OAuth/OIDC authorization-code flow with server-side token handling; Yahoo supports OpenID Connect; Facebook/Instagram require Meta app configuration.
- OTP email/phone verification must be provided by a server-side email/SMS provider.

## Data model
CSV files are the initial import/export format for users, roles, menu configuration, company, accounts, transactions, stock, purchases, sales, bills and settlements. The intended production evolution is a transactional database plus object storage for bill files, while retaining CSV import/export.

## Accounting logic
Every financial transaction should record: date, from account, to account, amount, mode, reference number, category, description, bill ID, creator and status. Daily tally = total inflow - total outflow; discrepancy compares recorded movement with expected cash/bank/account movement. Unresolved items remain open and carry into the monthly settlement queue until fixed.
