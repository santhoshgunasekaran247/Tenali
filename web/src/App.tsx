import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { BrandPage } from "./pages/BrandPage";
import { HomePage } from "./pages/HomePage";
import { ProductPage } from "./pages/ProductPage";

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
      </Routes>
    </div>
  );
}
