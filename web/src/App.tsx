import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { AccountsPage } from "./pages/AccountsPage";
import { BrandPage } from "./pages/BrandPage";
import { BusinessPaymentsPage } from "./pages/BusinessPaymentsPage";
import { BillingPage } from "./pages/BillingPage";
import { CompanySetupPage } from "./pages/CompanySetupPage";
import { MasterDataPage } from "./pages/MasterDataPage";
import { InventoryPage } from "./pages/InventoryPage";
import { InventoryMasterPage } from "./pages/InventoryMasterPage";
import { AuditPage } from "./pages/AuditPage";
import { HomePage } from "./pages/HomePage";
import { PartiesPage } from "./pages/PartiesPage";
import { PortalPage } from "./pages/PortalPage";
import { ProductPage } from "./pages/ProductPage";
import { PurchasesPage } from "./pages/PurchasesPage";
import { ReceivablesPage } from "./pages/ReceivablesPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettlementsPage } from "./pages/SettlementsPage";

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div>
      <Header menuOpen={menuOpen} onMenuToggle={() => setMenuOpen((prev) => !prev)} />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/brand" element={<BrandPage />} />
        <Route path="/brand.html" element={<BrandPage />} />
        <Route path="/products/:productId" element={<ProductPage />} />
        <Route path="/portal" element={<PortalPage />} />
        <Route path="/portal/parties" element={<PartiesPage />} />
        <Route path="/portal/accounts" element={<AccountsPage />} />
        <Route path="/portal/settlements" element={<SettlementsPage />} />
        <Route path="/portal/business-payments" element={<BusinessPaymentsPage />} />
        <Route path="/portal/receivables" element={<ReceivablesPage />} />
        <Route path="/portal/purchases" element={<PurchasesPage />} />
        <Route path="/portal/billing" element={<BillingPage />} />
        <Route path="/portal/company" element={<CompanySetupPage />} />
        <Route path="/portal/masters" element={<MasterDataPage />} />
        <Route path="/portal/inventory" element={<InventoryPage />} />
        <Route path="/portal/masters/hsn" element={<MasterDataPage />} />
        <Route path="/portal/masters/brands" element={<InventoryMasterPage kind="brands" />} />
        <Route path="/portal/masters/categories" element={<InventoryMasterPage kind="categories" />} />
        <Route path="/portal/reports" element={<ReportsPage />} />
        <Route path="/portal/audit" element={<AuditPage />} />
      </Routes>
    </div>
  );
}
