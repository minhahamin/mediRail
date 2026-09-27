import { expect, test } from "@playwright/test";
import { ADMIN, API, apiSignup, loginForm, openTab, uniqueUser } from "./helpers";

async function adminLogin(page: import("@playwright/test").Page) {
  await loginForm(page, ADMIN.username, ADMIN.password);
  await expect(page.locator(".browser")).toContainText("시스템 관리자");
  await expect(page.locator(".browser")).not.toContainText("읽기 전용"); // 실제 관리자는 변경 가능
}

test.describe("시스템 관리자 콘솔", () => {
  test("역할을 부여하면 즉시 반영되고(같은 토큰), 2단계 확인과 감사 기록이 남는다", async ({ page, request }) => {
    const user = uniqueUser();
    const token = await apiSignup(request, user);
    const asUser = { headers: { Authorization: `Bearer ${token}` } };
    expect((await request.get(`${API}/patients`, asUser)).status()).toBe(403); // 환자

    await adminLogin(page);
    const row = page.locator("tr", { hasText: user });
    await row.getByRole("combobox").selectOption("nurse");
    await row.getByRole("button", { name: "적용" }).click();
    await expect(row.getByRole("button", { name: /변경 확인/ })).toBeVisible(); // 바로 적용되지 않는다 (2단계)
    expect((await request.get(`${API}/patients`, asUser)).status()).toBe(403);
    await row.getByRole("button", { name: /변경 확인/ }).click();
    await expect(page.getByText(/간호사 변경했습니다|→ 간호사/)).toBeVisible();

    expect((await request.get(`${API}/patients`, asUser)).status()).toBe(200); // 같은 토큰으로 즉시 간호사 권한
    await openTab(page, "감사 로그");
    await expect(page.locator("table")).toContainText("admin.role_change");
  });

  test("계정을 중지하면 로그인과 기존 토큰이 막히고, 활성화하면 복구된다", async ({ page, request }) => {
    const user = uniqueUser();
    const token = await apiSignup(request, user);
    await adminLogin(page);
    const row = page.locator("tr", { hasText: user });
    await row.getByRole("button", { name: "사용 중지" }).click();
    await expect(row.locator(".chip", { hasText: "중지" })).toBeVisible();
    expect((await request.get(`${API}/me`, { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(401);
    expect((await request.post(`${API}/auth/login`, { data: { username: user, password: "pass1234" } })).status()).toBe(403);

    await row.getByRole("button", { name: "활성화" }).click();
    await expect(row.locator(".chip", { hasText: "활성" })).toBeVisible();
    expect((await request.post(`${API}/auth/login`, { data: { username: user, password: "pass1234" } })).status()).toBe(200);
  });

  test("데모·최상위·내 계정은 '보호됨'이라 변경할 수 없다", async ({ page }) => {
    await adminLogin(page);
    for (const name of ["patient1", "doctor1", "superadmin_demo", ADMIN.username]) {
      const row = page.locator("tr", { hasText: name }).first();
      await expect(row).toContainText("보호됨");
      await expect(row.getByRole("combobox")).toHaveCount(0);
    }
    await expect(page.locator("tr", { hasText: ADMIN.username })).toContainText("나");
  });

  test("임상 열람(break-glass): 사유가 짧으면 막히고, 열람하면 감사 로그에 남는다", async ({ page }) => {
    await adminLogin(page);
    await openTab(page, "임상 열람");
    const submit = page.getByRole("button", { name: "사유를 남기고 열람" });
    await expect(submit).toBeDisabled();
    await page.locator("#bg-pid").fill("1");
    await page.locator("#bg-reason").fill("짧음");
    await expect(submit).toBeDisabled(); // 10자 미만
    await page.locator("#bg-reason").fill("환자 본인 요청에 따른 기록 정정 검토");
    await submit.click();
    await expect(page.getByText("감사 로그에 기록되었습니다")).toBeVisible();
    await expect(page.locator("main")).toContainText("페니실린"); // 사유를 남겼을 때만 임상 정보가 열린다
    await openTab(page, "감사 로그");
    await expect(page.locator("table")).toContainText("admin.break_glass");
    await expect(page.locator("table")).toContainText("기록 정정 검토");
  });

  test("시스템 현황: 사용자·환자·AI 요청 사용량이 표시된다", async ({ page }) => {
    await adminLogin(page);
    await openTab(page, "시스템 현황");
    await expect(page.locator("main")).toContainText("전체 사용자");
    await expect(page.locator("main")).toContainText("오늘 AI 요청 사용량");
    await expect(page.getByRole("progressbar")).toBeVisible();
    await expect(page.locator("main")).toContainText("모델");
  });

  test("시스템 관리자는 AI 채팅이 없고 일반 사용자 API를 직접 부르면 403이다", async ({ page, request }) => {
    await adminLogin(page);
    await expect(page.locator("nav")).not.toContainText("상담");
    const login = await request.post(`${API}/auth/login`, { data: { username: ADMIN.username, password: ADMIN.password } });
    const h = { headers: { Authorization: `Bearer ${(await login.json()).access_token}` } };
    expect((await request.post(`${API}/chat`, { ...h, data: { message: "안녕" } })).status()).toBe(403);
    expect((await request.get(`${API}/patients`, h)).status()).toBe(403);
  });
});
