import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const enabled = env.VITE_TENALI_CUSTOM_DOMAINS_ENABLED === "true";
  const hosts = (env.VITE_TENALI_PLATFORM_HOSTS || "").split(",").map(host => host.trim().toLowerCase()).filter(Boolean);
  if (enabled && (!hosts.length || hosts.some(host => !/^[a-z0-9.-]+$/.test(host)))) {
    throw new Error("Custom domains require VITE_TENALI_PLATFORM_HOSTS with exact platform/frontend hostnames.");
  }
  return {
  define: {
    __TENALI_CUSTOM_DOMAINS__: JSON.stringify(enabled),
    __TENALI_PLATFORM_HOSTS__: JSON.stringify(hosts),
  },
  plugins: [react()],
  server: {
    port: 5173,
    proxy:{'/api':{target:'http://127.0.0.1:8000',changeOrigin:false}}
  }
  };
});
