import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 배포 시 정적 파일을 nginx가 서빙한다. API 주소는 빌드 시점의 VITE_API_URL로 주입한다.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: "127.0.0.1" },
  preview: { port: 4173, host: "127.0.0.1" },
});
