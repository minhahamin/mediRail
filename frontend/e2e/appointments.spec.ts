import { expect, test } from "@playwright/test";
import { openTab, signup, uniqueUser } from "./helpers";

test.describe("예약 (환자)", () => {
  test("가능한 시간을 골라 예약하고 목록에 보이며 취소할 수 있다", async ({ page }) => {
    await signup(page, uniqueUser());
    await openTab(page, "내 예약");
    await expect(page.getByText("예정된 예약이 없습니다")).toBeVisible();

    await page.locator('input[type="date"]').fill("2031-03-03"); // 월요일
    await expect(page.locator(".slot").first()).toHaveText("09:00");
    await expect(page.locator(".slot")).toHaveCount(16); // 09:00-18:00 30분 슬롯 - 점심 2개
    await expect(page.locator(".slot", { hasText: "12:30" })).toHaveCount(0); // 점심시간 제외
    await page.locator(".slot", { hasText: "10:00" }).click();
    await page.getByLabel("방문 사유 (선택)").fill("E2E 예약 테스트");
    await page.getByRole("button", { name: /예약하기/ }).click();

    await expect(page.getByText(/예약되었습니다/)).toBeVisible();
    const item = page.locator(".player", { hasText: "3월 3일(월) 10:00" });
    await expect(item).toContainText("E2E 예약 테스트");
    await expect(page.locator(".slot", { hasText: "10:00" })).toHaveCount(1); // 정원(의사 2명) 중 1자리 사용, 아직 남음

    await item.getByRole("button", { name: "취소" }).click();
    await expect(page.getByText("예약을 취소했습니다")).toBeVisible();
    await expect(page.getByText("예정된 예약이 없습니다")).toBeVisible();
  });

  test("일요일은 예약 가능한 시간이 없고, 토요일은 13:00까지다", async ({ page }) => {
    await signup(page, uniqueUser());
    await openTab(page, "내 예약");
    await page.locator('input[type="date"]').fill("2031-03-09"); // 일요일
    await expect(page.getByText("예약 가능한 시간이 없습니다")).toBeVisible();
    await page.locator('input[type="date"]').fill("2031-03-08"); // 토요일
    await expect(page.locator(".slot")).toHaveCount(8);
    await expect(page.locator(".slot").last()).toHaveText("12:30");
  });

  test("시간을 고르기 전에는 예약 버튼이 비활성화되어 있다", async ({ page }) => {
    await signup(page, uniqueUser());
    await openTab(page, "내 예약");
    await expect(page.getByRole("button", { name: "시간을 선택하세요" })).toBeDisabled();
  });

  test("채팅으로 내 예약을 조회하면 도구 결과가 출처로 붙는다", async ({ page }) => {
    await signup(page, uniqueUser());
    await page.getByLabel("메시지 입력").fill("내 예약 알려줘");
    await page.getByRole("button", { name: "보내기" }).click();
    const answer = page.locator(".msg.assistant").last();
    await expect(answer).toContainText("예약 목록을 확인했습니다");
    await expect(answer.locator(".source")).toContainText("예약 목록");
  });
});
