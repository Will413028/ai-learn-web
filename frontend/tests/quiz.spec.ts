import { test as base, expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { guardRoute } from "../test-support/browser-network.mjs";

const test = base.extend<{ blockedURLs: string[] }>({
  blockedURLs: [[], { scope: "test" }],
  context: async ({ context, blockedURLs }, run) => {
    await context.route("**/*", route => guardRoute(route, blockedURLs));
    await context.routeWebSocket(/.*/, ws => { ws.close(); });
    await run(context);
  },
});

async function generate(page: Page, topic = "Python") {
  await expect(page.locator(".badge")).toHaveText("示範模式・模擬 AI");
  await page.getByLabel("學習主題或內容").fill(topic);
  await expect(page.getByRole("button", { name: "產生練習", exact: true })).toBeEnabled();
  const pending = page.waitForResponse(response => response.url().includes("/api/v1/quiz/") &&
    response.request().method() === "GET");
  const generation = page.waitForResponse("**/api/v1/quiz/generate");
  await page.getByRole("button", { name: "產生練習", exact: true }).click();
  expect((await generation).status()).toBe(202);
  const response = await pending;
  expect(response.status()).toBe(200);
  const quiz = await response.json();
  expect(Object.keys(quiz.questions[0]).sort()).toEqual(["id", "options", "text", "type"]);
  await expect(page.locator(".quiz")).toBeVisible();
  return quiz;
}

async function register(page: Page) {
  await expect(page.locator(".badge")).toHaveText("示範模式・模擬 AI");
  await page.getByRole("button", { name: "登入／註冊", exact: true }).click();
  await page.getByRole("button", { name: "註冊", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(`e2e-${randomUUID()}@example.com`);
  await page.getByLabel("密碼", { exact: true }).fill("test-only-password-123");
  await page.getByLabel("暱稱", { exact: true }).fill("測試學習者");
  await page.getByRole("button", { name: "建立帳號", exact: true }).click();
  await expect(page.getByRole("heading", { name: "個人資料", exact: true })).toBeVisible();
}

test("three types, server grading and complete learning report", async ({ page }) => {
  await page.goto("/");
  const quiz = await generate(page);
  expect(new Set(quiz.questions.map((q: { type: string }) => q.type))).toEqual(new Set(["single", "multiple", "boolean"]));
  await expect(page.getByText("正確答案：B", { exact: true })).toHaveCount(0);
  const questions = page.locator("article.question");
  await questions.nth(0).getByRole("radio", { name: /B\s*用自己的話/ }).check();
  await questions.nth(0).getByRole("button", { name: "提交第 1 題" }).click();
  await expect(questions.nth(0)).toContainText("答對了");
  await expect(questions.nth(0).getByRole("radio").first()).toBeDisabled();
  await questions.nth(1).getByRole("checkbox", { name: /A\s*用自己的話/ }).check();
  await questions.nth(1).getByRole("checkbox", { name: /B\s*完成小練習/ }).check();
  await questions.nth(1).getByRole("button", { name: "提交第 2 題" }).click();
  await expect(questions.nth(1)).toContainText("答對了");
  await questions.nth(2).getByRole("radio", { name: /T\s*正確/ }).check();
  await questions.nth(2).getByRole("button", { name: "提交第 3 題" }).click();
  await page.getByRole("button", { name: "查看學習復盤", exact: true }).click();
  await expect(page.locator(".report")).toContainText("100%");
  await expect(page.locator(".report")).toContainText("+25");
  await expect(page.locator(".report")).toContainText("知識掌握");
  await page.screenshot({ path: test.info().outputPath("full-learning-report.png"), fullPage: true });
  await page.getByRole("button", { name: "學習紀錄", exact: true }).click();
  await expect(page.getByRole("button", { name: "繼續／復盤" })).toHaveCount(1);
  await page.getByRole("button", { name: "繼續／復盤" }).click();
  await expect(page.locator(".report")).toContainText("100%");
});

test("wrong answer is scored by backend", async ({ page }) => {
  await page.goto("/");
  await generate(page, "PostgreSQL");
  const question = page.locator("article.question").first();
  await question.getByRole("radio", { name: /A\s*只閱讀/ }).check();
  await question.getByRole("button", { name: "提交第 1 題" }).click();
  await expect(question).toContainText("再理解一次");
  await expect(question).toContainText("正確答案：B");
});

test("API failure is visible and generation can retry", async ({ page }) => {
  await page.route("**/api/v1/quiz/generate", route => route.fulfill({
    status: 502, contentType: "application/json", body: JSON.stringify({ detail: "暫時出題失敗" }),
  }));
  await page.goto("/");
  await page.getByLabel("學習主題或內容").fill("Next.js");
  await page.getByRole("button", { name: "產生練習" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("暫時出題失敗");
  await page.unroute("**/api/v1/quiz/generate");
  await generate(page, "Next.js");
});

test("another anonymous browser cannot read or answer private quiz", async ({ browser, page }) => {
  await page.goto("/");
  const quiz = await generate(page);
  const other = await browser.newContext();
  try {
    await other.request.get("http://127.0.0.1:3100/api/v1/session");
    expect((await other.request.get(`http://127.0.0.1:3100/api/v1/quiz/${quiz.id}`)).status()).toBe(404);
    const response = await other.request.post(`http://127.0.0.1:3100/api/v1/quiz/${quiz.id}/answers`, {
      headers: { origin: "http://127.0.0.1:3100" },
      data: { question_id: quiz.questions[0].id, selected_answers: ["B"], duration_ms: 0 },
    });
    expect(response.status()).toBe(404);
  } finally { await other.close(); }
});

test("guest record is explicitly claimed after registration", async ({ page }) => {
  await page.goto("/");
  await generate(page);
  await register(page);
  await expect(page.getByRole("button", { name: "認領訪客紀錄" })).toBeVisible();
  await page.getByRole("button", { name: "認領訪客紀錄" }).click();
  await expect(page.getByRole("status")).toContainText("已認領 1 份紀錄");
  await expect(page.getByRole("button", { name: "認領訪客紀錄" })).toHaveCount(0);
  await page.getByLabel("暱稱", { exact: true }).fill("更新學習者");
  await page.getByRole("button", { name: "儲存資料" }).click();
  await expect(page.getByRole("button", { name: "更新學習者", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "學習紀錄", exact: true }).click();
  await expect(page.getByRole("button", { name: "繼續／復盤" })).toHaveCount(1);
});

test("private document processing, retrieval and deletion", async ({ page }) => {
  await page.goto("/");
  await register(page);
  await page.getByRole("button", { name: "私有文件", exact: true }).click();
  await page.getByLabel(/上傳文件/).setInputFiles({ name: "python.md", mimeType: "text/markdown", buffer: Buffer.from("Python lists and dictionaries") });
  await page.getByRole("button", { name: "上傳並處理" }).click();
  await page.getByRole("button", { name: "用此文件出題" }).click();
  const quiz = await generate(page, "Python lists");
  expect(quiz.source.mode).toBe("document");
  expect(quiz.source.degraded).toBe(false);
  expect(quiz.source.citations[0].document_id).toBeTruthy();
  await page.getByRole("button", { name: "私有文件", exact: true }).click();
  await page.getByRole("button", { name: "刪除文件" }).click();
  await expect(page.getByRole("heading", { name: "python.md" })).toHaveCount(0);
});

test("private image is generated and deleted without blocking quiz", async ({ page }) => {
  await page.goto("/");
  await register(page);
  await page.getByRole("button", { name: "開始學習", exact: true }).click();
  await generate(page);
  await page.getByRole("button", { name: "生成配圖", exact: true }).click();
  await expect(page.getByAltText("Python 學習配圖")).toBeVisible();
  const image = page.getByAltText("Python 學習配圖");
  await expect.poll(() => image.evaluate(node => (node as HTMLImageElement).naturalWidth),
                    { timeout: 10_000 }).toBeGreaterThan(0);
  await page.getByRole("button", { name: "刪除配圖" }).click();
  await expect(image).toHaveCount(0);
  await expect(page.getByRole("button", { name: "提交第 1 題" })).toBeVisible();
});

test("external browser request is blocked before being sent", async ({ page, blockedURLs }) => {
  await page.goto("/");
  const failed = page.waitForEvent("requestfailed", request => request.url() === "https://example.invalid/probe");
  const blocked = await page.evaluate(async () => {
    try { await fetch("https://example.invalid/probe"); return false; }
    catch { return true; }
  });
  expect(blocked).toBe(true);
  expect(blockedURLs).toContain("https://example.invalid/probe");
  expect((await failed).failure()?.errorText).toContain("ERR_BLOCKED_BY_CLIENT");
});


test("delayed guest restore cannot overwrite a new account quiz", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".badge")).toHaveText("示範模式・模擬 AI");
  const oldId = randomUUID();
  await page.evaluate(id => localStorage.setItem("ai-learn-active-job", id), oldId);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requested!: () => void;
  const started = new Promise<void>(resolve => { requested = resolve; });
  await page.route(`**/api/v1/jobs/${oldId}`, async route => {
    requested();
    await gate;
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ id: oldId, status: "pending", kind: "quiz", result_id: null, error: null }) });
  });
  await page.reload();
  await started;
  await register(page);
  await page.getByRole("button", { name: "開始學習", exact: true }).click();
  await generate(page, "新帳號專屬課程");
  const restored = page.waitForResponse(`**/api/v1/jobs/${oldId}`);
  release();
  await (await restored).finished();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByRole("button", { name: "產生練習", exact: true })).toBeEnabled();
  await expect(page.locator(".quiz")).toContainText("新帳號專屬課程");
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("ai-learn-active-job"))).toBeNull();
});
