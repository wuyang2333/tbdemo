import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    // 生产构建分包：核心依赖单独成 chunk，配合路由懒加载减少首屏体积
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          antd: ["antd", "@ant-design/icons"],
          utils: ["axios", "dayjs"],
        },
      },
    },
  },
  server: {
    host: "0.0.0.0",
    // 允许内网穿透域名（cpolar / ngrok 等）访问 dev server，公司可通过公网地址打开
    allowedHosts: [".cpolar.top", ".ngrok-free.app", ".lhr.life"],
    port: 5178,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8008",
        changeOrigin: true,
      },
    },
  },
});



