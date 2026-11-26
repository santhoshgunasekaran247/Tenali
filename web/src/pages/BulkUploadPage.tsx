import { ArrowLeft, FileSpreadsheet } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { BulkWorkbookPanel } from "../components/BulkWorkbookPanel";
import { useAuth } from "../features/auth";

export function BulkUploadPage() {
  const { user } = useAuth();
  const { state } = useLocation();
  const selectedProducts = Array.isArray(state?.selectedProducts)
    ? state.selectedProducts.filter((id: unknown): id is string => typeof id === "string") : [];
  return <main className="ops-page bulk-page">
    <header className="ops-hero bulk-hero">
      <div>
        <p className="eyebrow"><FileSpreadsheet size={16} aria-hidden="true" /> DATA IMPORT & EXPORT</p>
        <h1>Bulk upload</h1>
        <p>Less manual entry. One organized workbook.</p>
      </div>
      <Link to="/portal/inventory" className="bulk-back"><ArrowLeft size={16} aria-hidden="true" /> Back to inventory</Link>
    </header>
    {user && ["owner", "admin"].includes(user.role)
      ? <BulkWorkbookPanel selectedProducts={selectedProducts} />
      : <p role="alert" className="bulk-content">Only workspace owners and administrators can use bulk upload.</p>}
  </main>;
}
