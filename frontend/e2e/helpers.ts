import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API = "http://127.0.0.1:8100";
export const ADMIN = { username: "e2e_admin", password: "e2e-admin-password-123" };

let counter = 0;
/** 실행마다 겹치지 않는 가입용 아이디 (영문 소문자·숫자, 4~20자) */
export const uniqueUser = () => `e2e${Date.now().toString(36)}${(counter++).toString(36)}`.slice(0, 20).toLowerCase();

export async function signup(page: Page, username: string, name = "테스터") {
  await page.goto("/signup");
  await page.getByLabel("아이디").fill(username);
  await page.getByLabel("이름 (닉네임 가능)").fill(name);
  await page.getByLabel("비밀번호", { exact: true }).fill("pass1234");
  await page.getByLabel("비밀번호 확인").fill("pass1234");
  await page.getByLabel("출생연도").fill("1995");
  await page.getByLabel("여", { exact: true }).check();
  await page.locator(".consent input[type=checkbox]").check();
  await page.getByRole("button", { name: "가입하고 시작하기" }).click();
  await expect(page.locator(".browser")).toContainText("환자");
}

export async function loginForm(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("아이디").fill(username);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
}

/** 데모 페이지의 카드로 입장한다 (roleLabel: 환자·간호사·의사·원무·시스템 관리자) */
export async function enterDemo(page: Page, roleLabel: string) {
  await page.goto("/demo");
  await page.locator("button.account", { hasText: roleLabel }).click();
  await expect(page.locator(".browser .who")).toBeVisible();
}

export async function logout(page: Page) {
  await page.locator("button.logout").click();
  await expect(page).toHaveURL(/\/login/);
}

export async function openTab(page: Page, label: string) {
  await page.locator("nav button", { hasText: label }).click();
}

export async function ask(page: Page, text: string) {
  await page.getByLabel("메시지 입력").fill(text);
  await page.getByRole("button", { name: "보내기" }).click();
}

/** API로 환자 계정을 만든다 (화면 없이 준비용). 토큰을 돌려준다. */
export async function apiSignup(request: APIRequestContext, username: string) {
  const r = await request.post(`${API}/auth/register`, {
    data: { username, password: "pass1234", name: "준비계정", birth_year: 1990, sex: "M" },
  });
  expect(r.status()).toBe(201);
  return (await r.json()).access_token as string;
}
