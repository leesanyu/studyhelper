import { defineConfig } from "vite";
import uni from "@dcloudio/vite-plugin-uni";
import type { ProxyOptions } from "vite";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [uni()],
  server: {
    proxy: {
      // SSE 流式接口：与生产环境 Nginx 对齐，禁用压缩和缓冲
      "/api/v1/chat": {
        target: "http://localhost:8000",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            // 禁止 Vite 压缩中间件对 SSE 响应做 gzip，否则事件被缓冲
            delete proxyRes.headers["content-encoding"];
            proxyRes.headers["x-accel-buffering"] = "no";
          });
        },
      },
      // 通用 API 代理
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // 静态资源代理
      "/assets": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
