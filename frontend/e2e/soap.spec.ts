import { expect, test } from "@playwright/test";
import { enterDemo, openTab } from "./helpers";

test.describe("의사: 문진 요약과 SOAP (AI는 초안만, 승인은 의사)", () => {
  test("환자 화면에서 초안을 요청하면 저장되고, SOAP 탭에서 검토 후 승인한다", async ({ page }) => {
    await enterDemo(page, "의사");
    await openTab(page, "환자");
    await page.locator(".plist button", { hasText: "이도윤" }).click();
    await expect(page.locator("main")).toContainText("진료 기록");
    await page.getByRole("button", { name: "SOAP 초안 요청" }).click();

    // 상담 탭으로 이동하고 질문이 미리 채워진다 (선택한 환자 문맥과 함께)
    await expect(page.getByLabel("메시지 입력")).toHaveValue("이 환자 SOAP 초안 만들어서 저장해줘");
    await page.getByRole("button", { name: "보내기" }).click();
    const answer = page.locator(".msg.assistant").last();
    await expect(answer).toContainText("SOAP 초안을 저장했습니다");
    await answer.locator("summary").click();
    await expect(answer).toContainText("진료 기록");
    await expect(answer).toContainText("SOAP 초안 저장");

    await openTab(page, "SOAP");
    const draft = page.locator(".notebook", { hasText: "초안 (미승인)" }).first();
    await expect(draft).toContainText("이도윤");
    await expect(draft).toContainText("급성 상기도감염 의심 (의사 확인 필요)"); // 확정 진단이 아니라 의심 소견
    await expect(page.getByText("AI는 초안만 만들 수 있습니다")).toBeVisible();

    await draft.getByRole("button", { name: "검토 후 승인" }).click();
    await expect(page.locator(".notebook", { hasText: "승인됨" }).first()).toContainText("이도윤");
  });

  test("문진 요약: 문진이 있는 환자는 요약하고, 없는 환자는 없다고 안내한다", async ({ page }) => {
    await enterDemo(page, "의사");
    await openTab(page, "환자");
    await page.locator(".plist button", { hasText: "김하늘" }).click();
    await page.getByRole("button", { name: "문진 요약 요청" }).click();
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(page.locator(".msg.assistant").last()).toContainText("문진을 요약했습니다");
    await expect(page.locator(".msg.assistant").last().locator(".source")).toContainText("문진 기록");

    await openTab(page, "환자");
    await page.locator(".plist button", { hasText: "이도윤" }).click();
    await expect(page.getByText("등록된 문진 기록이 없습니다")).toBeVisible(); // 404가 아니라 정상 상태
    await page.getByRole("button", { name: "문진 요약 요청" }).click();
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(page.locator(".msg.assistant").last()).toContainText("문진 기록이 없습니다");
  });

  test("환자를 선택하지 않고 SOAP을 요청하면 환자 선택을 요청한다", async ({ page }) => {
    await enterDemo(page, "의사");
    await page.getByLabel("메시지 입력").fill("SOAP 초안 만들어줘");
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(page.locator(".msg.assistant").last()).toContainText("환자를 먼저 선택");
  });
});
