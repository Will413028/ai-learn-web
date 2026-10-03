# Walking skeleton 實作規格

目標：瀏覽器輸入主題 → 同源代理 → FastAPI fake provider 產生一題 → 選答案 → 後端判分並揭露解析。這是步驟 2 的薄路徑，不宣稱完整功能完成。

## 產物與邊界

- frontend：Next.js App Router、TypeScript、React；首頁提供主題、生成、單選與提交，loading／失敗可見。
- backend：FastAPI、Pydantic 嚴格 request／response schemas、fake provider、server-owned quiz 與 scoring。步驟 2 只作單程序記憶體儲存；重啟不保留，步驟 4 替換成 PostgreSQL。
- 匿名 session 先以不透明 HttpOnly cookie 隔離 quiz，期限 7 天；cookie 使用 SameSite=Lax、Path=/api，本機 HTTP 可不設 Secure，公開 HTTPS 必須 Secure。登入與明確認領於步驟 4 完成。公開環境 HTTPS 尚非本步範圍。
- `POST /api/v1/quiz/generate`；題目公開 schema 不包含答案或解析。答案只有後端內部模型持有。
- `POST /api/v1/quiz/{quiz_id}/answers`：question_id、selected_answers、duration_ms；驗證所屬 session、題目與合法選項，提交後返回判分／答案／解析。
- 首次有效答案固定；完全相同答案重送返回原結果，不同答案重送回 conflict，不能藉修改答案重新結算。三題型与報告於步驟 3 擴充；XP 於步驟 4 實作。
- 第一個 cookie endpoint 即有 CSRF 防護：所有 unsafe methods 只接受 JSON，Origin 必須符合明確配置的前端 origin；拒絕缺少 Origin、null Origin 與不符來源，不以可偽造的 forwarded host 擴大信任。測試 API client 明確帶合法 Origin；步驟 4 沿用此邊界。依據：[OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)。
- Next.js rewrite 保留 `/api/v1/*`，API client 只用同源 URL；不新增 BFF 權威。
- OpenAPI 由 FastAPI 產生，openapi-typescript 生成 TypeScript types，禁止另寫平行欄位契約。
- 尚不引入 ReAct／worker／RAG／配圖套件；D5 在步驟 5 實作，屆時同步入口、generated types 與全部生成 consumer 一次轉為 job + polling；不能把離線 spike 搬成產品 worker。
- 根目錄初始化獨立 Git repository；不 commit、不建立 remote、不發布。

## 下載與安裝（本 session 已授權）

前端 runtime：next、react、react-dom。
前端工具：typescript、@types/node、@types/react、@types/react-dom、eslint、eslint-config-next、openapi-typescript、@playwright/test。
後端 runtime：fastapi、pydantic、uvicorn。
後端工具：pytest、httpx、ruff、mypy。
另下載 Playwright 對應 Chromium，以執行瀏覽器測試。

使用現有 pnpm／uv 與 Python；安裝在 frontend/node_modules、backend/.venv，產生 pnpm-lock.yaml／uv.lock 固定實際解析版本。只選 stable packages；本輪現有 Python／Node 可用，無額外 runtime 下載。本步不下載 PostgreSQL container、原版完整依賴或 AI SDK。

官方依據：[Next.js 安裝](https://nextjs.org/docs/app/getting-started/installation)、[FastAPI 虛擬環境](https://fastapi.tiangolo.com/virtual-environments/)、[Playwright browsers](https://playwright.dev/docs/browsers)。本機已確認 Node 26.10.0、pnpm 11.2.2、Python 3.14.7、uv 0.7.2；FastAPI／Pydantic／HTTPX／ruff 尚未安裝，不能假設可執行。

## 驗收與故意破壞

- `make check`：ruff／mypy、pytest、ESLint、TypeScript、frontend build；OpenAPI types 重新生成後應無 drift。
- `make e2e`：啟動 FastAPI 與 Next.js，Chromium 走生成／提交／揭露解析，並測 API 錯誤與越權 session。
- `make inventory-check`：固定來源盤點 gate 與已存在 mutation self-tests。
- CSRF 負向驗收：foreign／null／missing Origin、非 JSON 均拒絕且不建立或修改 quiz；移除 Origin 判定必須使測試失敗。
- 答案提前洩露、client 傳入 is_correct、非法 option、跨 session quiz、重複提交／衝突提交皆有負向驗收。
- 把 rewrite destination 改壞、移除 provider 結果 schema 驗證、移除外部網路阻擋，各使對應驗收失敗；mutation 用附件臨時副本，結束清除。
- pytest 阻擋外部 socket；Playwright context 阻擋非本機 HTTP／WebSocket；Next.js／後端 fake 測試程序不載入真實 providers。故意外部 endpoint 請求應在送出前失败。
- 完成前獨立 code review／design-review，主 agent 重跑全部驗收；安裝或啟動受阻不得把本步標完成。

## 教學交付

附請求資料流、公開／內部 schema 的差異、如何改 fake 題目與故意觸發錯誤。使用者可自行修改 fake provider，再跑後端及瀏覽器驗收。

實際依賴以 lockfiles 為準；TypeScript 固定 5.9.3、ESLint 固定相容的 9.x，因最新主版本與 openapi-typescript／eslint-plugin-react 不相容。pnpm-workspace.yaml 明確允許 unrs-resolver 的 install script，不開放所有套件 scripts。
