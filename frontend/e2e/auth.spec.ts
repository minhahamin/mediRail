import { expect, test } from "@playwright/test";
import { enterDemo, loginForm, logout, signup, uniqueUser } from "./helpers";

test.describe("로그인 · 회원가입 · 데모", () => {
  test("로그인 화면: 폼 아래에 회원가입 링크, 그 아래에 데모 링크가 있다", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel("아이디")).toBeVisible();
    const signupLink = page.getByRole("button", { name: "회원가입", exact: true });
    const demoLink = page.getByRole("button", { name: "데모 계정으로 바로 체험하기" });
    await expect(signupLink).toBeVisible();
    await expect(demoLink).toBeVisible();
    // 데모 구역이 로그인 화면에 펼쳐져 있지 않고(별도 페이지), 링크가 회원가입 문구보다 아래에 있다
    await expect(page.locator("button.account")).toHaveCount(0);
    const [a, b] = [await signupLink.boundingBox(), await demoLink.boundingBox()];
    expect(b!.y).toBeGreaterThan(a!.y);
    await expect(page.locator("footer, .demo-note")).toContainText("포트폴리오입니다");
    await expect(page.locator("body")).not.toContainText("포트폴리오 데모입니다");
  });

  test("데모 페이지: DB 안내와 역할별 카드 5개, 링크로 이동", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: "데모 계정으로 바로 체험하기" }).click();
    await expect(page).toHaveURL(/\/demo$/);
    await expect(page.locator(".note")).toContainText("하드코딩이 아닙니다");
    await expect(page.locator(".note")).toContainText("PostgreSQL DB에 저장");
    await expect(page.locator("button.account")).toHaveCount(5);
    for (const role of ["환자", "간호사", "의사", "원무", "시스템 관리자"]) {
      await expect(page.locator("button.account", { hasText: role })).toBeVisible();
    }
    await page.getByRole("button", { name: /로그인으로 돌아가기/ }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("데모 카드는 API 응답(DB)을 그대로 그린다 - 응답을 바꾸면 화면이 바뀐다", async ({ page }) => {
    await page.route("**/auth/demo-accounts", (route) =>
      route.fulfill({ json: [{ username: "patient1", role: "patient", name: "API가준이름" }] }));
    await page.goto("/demo");
    await expect(page.locator("button.account")).toHaveCount(1);
    await expect(page.locator("button.account")).toContainText("API가준이름");
  });

  test("데모 계정 카드를 누르면 바로 입장하고 로그아웃하면 로그인 화면으로 돌아온다", async ({ page }) => {
    await enterDemo(page, "환자");
    await expect(page.locator(".browser")).toContainText("환자");
    await expect(page).toHaveURL(/\/$/);
    await logout(page);
  });

  test("잘못된 비밀번호는 오류를 보여주고 입장하지 않는다", async ({ page }) => {
    await loginForm(page, "patient1", "wrong-password1");
    await expect(page.getByText("올바르지 않습니다")).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("로그인 버튼은 입력 전에는 비활성화되어 있다", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("button", { name: "로그인", exact: true })).toBeDisabled();
  });

  test("회원가입 검증: 빈 폼 제출 시 필드별 오류가 보이고 이동하지 않는다", async ({ page }) => {
    await page.goto("/signup");
    await page.getByRole("button", { name: "가입하고 시작하기" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "영문 소문자·숫자·밑줄(_) 4~20자" })).toBeVisible(); // 오류가 도움말을 대체한다
    await expect(page.getByText("성별을 선택해 주세요")).toBeVisible();
    await expect(page.getByText("동의가 필요합니다")).toBeVisible();
    await expect(page).toHaveURL(/\/signup$/);
  });

  test("회원가입 검증: 약한 비밀번호와 확인 불일치", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel("비밀번호", { exact: true }).fill("onlyletters");
    await page.getByLabel("비밀번호 확인").fill("different1");
    await page.getByRole("button", { name: "가입하고 시작하기" }).click();
    await expect(page.getByText("8~72자, 영문과 숫자를 모두 포함")).toBeVisible();
    await expect(page.getByText("비밀번호가 일치하지 않습니다")).toBeVisible();
  });

  test("직원 사칭 아이디와 데모 아이디는 가입할 수 없다", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel("아이디").fill("doctor99");
    await page.getByRole("button", { name: "가입하고 시작하기" }).click();
    await expect(page.getByText("사용할 수 없는 아이디입니다")).toBeVisible();
    await page.getByLabel("아이디").fill("patient1"); // 형식은 맞지만 이미 존재
    await page.getByLabel("이름 (닉네임 가능)").fill("사칭");
    await page.getByLabel("비밀번호", { exact: true }).fill("pass1234");
    await page.getByLabel("비밀번호 확인").fill("pass1234");
    await page.getByLabel("출생연도").fill("1990");
    await page.getByLabel("여", { exact: true }).check();
    await page.locator(".consent input[type=checkbox]").check();
    await page.getByRole("button", { name: "가입하고 시작하기" }).click();
    await expect(page.getByText("이미 사용 중인 아이디입니다")).toBeVisible();
  });

  test("회원가입 성공 → 환자 화면, 새로고침해도 로그인이 유지된다", async ({ page }) => {
    const user = uniqueUser();
    await signup(page, user, "새싹이");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator(".browser")).toContainText("새싹이");
    await page.reload();
    await expect(page.locator(".browser")).toContainText("새싹이"); // 세션 유지
    await expect(page.locator("nav button")).toHaveText([/상담/, /내 예약/]);
    await logout(page);
    await loginForm(page, user, "pass1234"); // 가입한 계정으로 다시 로그인
    await expect(page.locator(".browser")).toContainText("새싹이");
  });

  test("로그인한 상태에서 /login 으로 가면 앱 화면으로 돌아간다", async ({ page }) => {
    await enterDemo(page, "환자");
    await page.goto("/login");
    await expect(page.locator(".browser")).toBeVisible();
  });
});
