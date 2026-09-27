import { defineConfig, devices } from "@playwright/test";

/**
 * E2E: 실제 프로덕션 빌드를 브라우저로 끝까지 검증한다.
 * - 백엔드: 임시 SQLite + 결정적 가짜 LLM(외부 호출·비용 없음) + 넉넉한 요청 한도 (e2e/start-backend.mjs)
 * - 프론트: `npm run build` 결과를 vite preview로 서빙 (배포되는 번들과 같은 코드)
 */
const API = "http://127.0.0.1:8100";
const WEB = "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // 하나의 임시 DB를 공유하므로 순차 실행
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: WEB, locale: "ko-KR", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    { command: "node e2e/start-backend.mjs", url: `${API}/health`, timeout: 120_000, reuseExistingServer: !process.env.CI },
    {
      command: "npm run build && npx vite preview --port 4173 --host 127.0.0.1 --strictPort",
      url: WEB,
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
      env: { VITE_API_URL: API },
    },
  ],
});
