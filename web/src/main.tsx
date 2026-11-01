import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";
import { tenantBase } from "./features/tenantTransport";
import { AuthProvider,CanonicalTenantUrl } from "./features/auth";
import { CartProvider } from "./features/cart";
import { SocialLoginCallbackPage } from "./pages/SocialLoginCallbackPage";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname === "/social-login" ? <SocialLoginCallbackPage /> :
    <BrowserRouter basename={tenantBase()||undefined}>
      <AuthProvider><CanonicalTenantUrl><CartProvider><App /></CartProvider></CanonicalTenantUrl></AuthProvider>
    </BrowserRouter>}
  </React.StrictMode>
);
