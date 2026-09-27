import { expect, test } from "@playwright/test";
import { ask, enterDemo, openTab } from "./helpers";

test.describe("AI 채팅: 출처·도구 기록·응급 안내", () => {
  test("진료시간 질문: 도구 호출 결과에 [D1] 출처 카드와 면책 문구가 붙는다", async ({ page }) => {
    await enterDemo(page, "환자");
    await ask(page, "토요일 진료시간 알려줘");
    const answer = page.locator(".msg.assistant").last();
    await expect(answer).toContainText("13:00까지");
    await expect(answer.locator(".cite")).toHaveText("D1"); // 인용 칩
    await expect(answer.locator(".source")).toContainText("MediRail 클리닉 안내"); // 출처 핀 카드
    await expect(answer.locator(".disclaimer")).toContainText("최종 판단은 반드시 의사와 상담하세요");
    await answer.locator("summary").click();
    await expect(answer).toContainText("진료 안내"); // 도구 호출 기록
  });

  test("[D1] 칩을 누르면 해당 출처 카드가 강조된다", async ({ page }) => {
    await enterDemo(page, "환자");
    await ask(page, "일요일에도 진료해?");
    const answer = page.locator(".msg.assistant").last();
    await answer.locator(".cite").click();
    await expect(answer.locator(".source.flash")).toBeVisible();
  });

  test("응급 문장: LLM 없이 즉시 119 안내와 응급 스타일, 안전장치 기록", async ({ page }) => {
    await enterDemo(page, "환자");
    await ask(page, "가슴이 쥐어짜듯 아프고 식은땀이 나요");
    const answer = page.locator(".msg.emergency");
    await expect(answer).toContainText("119");
    await expect(answer.locator(".em-head")).toContainText("응급 안내");
    await expect(answer).not.toContainText("[D"); // 근거 인용 없이 고정 안내문
    await answer.locator("..").locator("summary").click();
    await expect(page.locator(".trace")).toContainText("응급 즉시 안내 (LLM 호출 없음)");
    await expect(page.locator(".msg.emergency .bubble")).toHaveCSS("border-top-color", /.+/);
  });

  test("자살·자해 표현에는 109 상담전화도 함께 안내한다", async ({ page }) => {
    await enterDemo(page, "환자");
    await ask(page, "요즘 죽고 싶다는 생각이 계속 들어요");
    await expect(page.locator(".msg.emergency")).toContainText("109");
  });

  test("추천 질문 버튼으로 바로 질문할 수 있다", async ({ page }) => {
    await enterDemo(page, "환자");
    await page.locator(".suggest button", { hasText: "토요일 오후 3시" }).click();
    await expect(page.locator(".msg.user").last()).toContainText("토요일 오후 3시");
    await expect(page.locator(".msg.assistant").last()).toContainText("진료 안내입니다");
  });

  test("Enter로 전송하고 Shift+Enter는 줄바꿈이며, 빈 입력은 보내기가 비활성화된다", async ({ page }) => {
    await enterDemo(page, "환자");
    const box = page.getByLabel("메시지 입력");
    await expect(page.getByRole("button", { name: "보내기" })).toBeDisabled();
    await box.fill("안녕");
    await box.press("Shift+Enter");
    await expect(box).toHaveValue("안녕\n");
    await box.press("Backspace");
    await box.press("Enter");
    await expect(page.locator(".msg.user").last()).toContainText("안녕");
    await expect(box).toHaveValue("");
  });

  test("탭을 옮겨도 대화가 유지된다", async ({ page }) => {
    await enterDemo(page, "환자");
    await ask(page, "일요일에도 진료해?");
    await expect(page.locator(".msg.assistant").last()).toContainText("휴진");
    await openTab(page, "내 예약");
    await openTab(page, "상담");
    await expect(page.locator(".msg.user").last()).toContainText("일요일에도 진료해?");
  });

  test("서버 오류는 화면에 오류 말풍선으로 보인다", async ({ page }) => {
    await enterDemo(page, "환자");
    await page.route("**/chat", (route) => route.fulfill({ status: 429, json: { detail: "AI 요청이 너무 많습니다. 약 1분 후 다시 시도해 주세요." } }));
    await ask(page, "안녕");
    await expect(page.locator(".msg.error")).toContainText("AI 요청이 너무 많습니다");
  });
});
