import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";
import "./workspace-theme.css";
import { tenantBase } from "./features/tenantTransport";
import { installBusyIndicator } from "./features/busyIndicator";
import { installNumberInputs } from "./features/numberInputs";
import { AuthProvider,CanonicalTenantUrl } from "./features/auth";
import { CartProvider } from "./features/cart";
import { SocialLoginCallbackPage } from "./pages/SocialLoginCallbackPage";
import { NotificationProvider } from "./components/Notifications";

installBusyIndicator();
installNumberInputs();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><NotificationProvider>
    {window.location.pathname === "/social-login" ? <SocialLoginCallbackPage /> :
    <BrowserRouter basename={tenantBase()||undefined}>
      <AuthProvider><CanonicalTenantUrl><CartProvider><App /></CartProvider></CanonicalTenantUrl></AuthProvider>
    </BrowserRouter>}
  </NotificationProvider></React.StrictMode>
);
