import { expect, test } from "@playwright/test";
import { apiSignup, enterDemo, logout, openTab, uniqueUser } from "./helpers";

const tabs = (page: import("@playwright/test").Page) => page.locator("nav button");

test.describe("역할별 화면과 권한", () => {
  test("환자: 상담과 내 예약만 보인다 (환자·SOAP·감사 메뉴 없음)", async ({ page }) => {
    await enterDemo(page, "환자");
    await expect(tabs(page)).toHaveText([/상담/, /내 예약/]);
    await expect(page.locator("nav")).not.toContainText("SOAP");
    await expect(page.locator("nav")).not.toContainText("감사 로그");
  });

  test("간호사: 환자 메뉴는 있지만 SOAP은 없다", async ({ page }) => {
    await enterDemo(page, "간호사");
    await expect(tabs(page)).toHaveText([/상담/, /환자/, /예약 현황/]);
  });

  test("의사: SOAP 메뉴가 있고 환자 상세에 문진·진료 기록이 보인다", async ({ page }) => {
    await enterDemo(page, "의사");
    await expect(tabs(page)).toHaveText([/상담/, /환자/, /SOAP/, /예약 현황/]);
    await openTab(page, "환자");
    await page.locator(".plist button", { hasText: "김하늘" }).click();
    await expect(page.locator(".notebook", { hasText: "문진 원문" })).toContainText("페니실린");
    await expect(page.getByText("알레르기").first()).toBeVisible();
  });

  test("원무: 임상 정보는 잠겨 있고 감사 로그는 볼 수 있다", async ({ page }) => {
    await enterDemo(page, "원무");
    await openTab(page, "환자");
    await page.locator(".plist button", { hasText: "김하늘" }).click();
    await expect(page.getByText("이 역할은 접근할 수 없습니다")).toBeVisible();
    await expect(page.locator("main")).not.toContainText("문진 원문");
    await expect(page.locator("main")).not.toContainText("페니실린");
    await openTab(page, "감사 로그");
    await expect(page.locator("table")).toBeVisible();
  });

  test("시스템 관리자(읽기 전용): 채팅이 없고 변경 컨트롤이 비활성화되며 가입자 정보는 가려진다", async ({ page, request }) => {
    const user = uniqueUser();
    await apiSignup(request, user);
    await enterDemo(page, "시스템 관리자");
    await expect(page.locator(".browser")).toContainText("읽기 전용");
    await expect(tabs(page)).toHaveText([/사용자·권한/, /시스템 현황/, /임상 열람/, /감사 로그/]);
    await expect(page.locator("nav")).not.toContainText("상담");
    const table = page.locator("table");
    await expect(table).toContainText("patient1"); // 데모 계정은 그대로
    await expect(table).not.toContainText(user); // 가입자 아이디는 마스킹
    await expect(table).toContainText("변경 불가");
    await expect(table.getByRole("combobox")).toHaveCount(0); // 역할 선택 컨트롤 없음
  });

  test("시스템 관리자(읽기 전용): 시드 환자는 열람 가능, 그 외는 차단", async ({ page, request }) => {
    await enterDemo(page, "시스템 관리자");
    await openTab(page, "임상 열람");
    const reason = "포트폴리오 시연을 위한 열람 사유입니다";
    await page.locator("#bg-pid").fill("2");
    await page.locator("#bg-reason").fill(reason);
    await page.getByRole("button", { name: "사유를 남기고 열람" }).click();
    await expect(page.getByText("감사 로그에 기록되었습니다")).toBeVisible();
    await expect(page.locator("main")).toContainText("이도윤");
    // 가입자(시드 이후 환자 번호)는 차단
    await apiSignup(request, uniqueUser());
    await page.locator("#bg-pid").fill("999");
    await page.getByRole("button", { name: "사유를 남기고 열람" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("로그아웃하면 보호된 화면이 사라진다", async ({ page }) => {
    await enterDemo(page, "의사");
    await logout(page);
    await expect(page.locator("nav")).toHaveCount(0);
  });
});
