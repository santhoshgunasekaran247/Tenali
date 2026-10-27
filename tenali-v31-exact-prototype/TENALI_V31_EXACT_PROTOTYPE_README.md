# Tenali — v31 Exact Prototype Baseline

This package intentionally preserves the supplied **SRU Global HTML/CSV Prototype v31**.
It is the UI/functionality baseline before API/database integration.

## Preserved
- All original HTML pages
- Original CSS
- Original JavaScript
- Original CSV/JS data
- Original assets/product images/brand logos
- Original navigation
- Original admin portal
- Original user/menu administration
- Original localStorage/CSV prototype functionality

## Run
```powershell
cd D:\GitRepo\Tenali\web
npm install
npm run dev
```

Open:
- Public site: http://localhost:5173/
- Operations portal: http://localhost:5173/portal.html
- Admin login: http://localhost:5173/admin-login.html
- Prototype admin: http://localhost:5173/prototype-admin.html

## Important
No visual redesign has been applied in this baseline.

The next phase will integrate these existing screens and workflows with FastAPI/PostgreSQL one module at a time, preserving the UI.
