import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API ayri bir portta calisiyor; gelistirmede vekil (proxy) ile ayni koken
// gorunumu saglaniyor. Boylece istemci kodunda mutlak URL veya CORS ozel
// durumu tutmaya gerek kalmiyor.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
