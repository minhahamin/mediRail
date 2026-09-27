// E2E용 백엔드 기동 스크립트 (Windows·Linux 공통). Playwright의 webServer가 실행한다.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const backend = path.resolve(here, "../../backend");
const python = process.env.E2E_PYTHON || (process.platform === "win32" ? "python" : "python3");
const dbFile = path.join(os.tmpdir(), `medirail-e2e-${process.pid}-${Date.now()}.db`);

const env = {
  ...process.env,
  MEDIRAIL_FAKE_LLM: "1", // 결정적 가짜 LLM: 실제 모델·외부 API를 쓰지 않는다
  MEDIRAIL_ENV: "development",
  MEDIRAIL_DB: dbFile, // 실행마다 새 임시 DB
  MEDIRAIL_CORS_ORIGINS: "http://127.0.0.1:4173",
  MEDIRAIL_SUPERADMIN_USERNAME: "e2e_admin",
  MEDIRAIL_SUPERADMIN_PASSWORD: "e2e-admin-password-123",
  // 테스트가 짧은 시간에 로그인·가입을 많이 하므로 요청 제한을 넉넉하게
  MEDIRAIL_LOGIN_PER_IP_MIN: "100000",
  MEDIRAIL_REGISTER_PER_IP_HOUR: "100000",
  MEDIRAIL_CHAT_PER_USER_HOUR: "100000",
  MEDIRAIL_CHAT_PER_IP_HOUR: "100000",
  MEDIRAIL_DAILY_CHAT_LIMIT: "100000",
  MEDIRAIL_MAX_USERS: "100000",
};
delete env.DATABASE_URL; // 항상 SQLite

const child = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8100"], { cwd: backend, env, stdio: "inherit" });

const stop = () => {
  child.kill();
  try {
    fs.rmSync(dbFile, { force: true });
  } catch {
    /* 임시 파일 정리 실패는 무시 */
  }
};
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { stop(); process.exit(0); });
process.on("exit", stop);
child.on("exit", (code) => process.exit(code ?? 0));
