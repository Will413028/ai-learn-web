# AI Learn Web

以 Next.js + FastAPI + PostgreSQL／pgvector 完整重做 [yu-ai-learn](https://github.com/liyupi/yu-ai-learn) 的學習專案。

目前已有三題型、逐題判分與復盤、Email／密碼登入、個人資料、七天訪客紀錄與明確認領、歷史與 XP、持久任務、搜尋／網址、四種文件與 RAG、私有配圖與額度管理。預設使用 fake providers 示範功能，整合驗收仍進行中；真實 AI 品質與完整容器 demo 尚未驗收。

## 本機執行

需 Python 3.14、uv、Node.js、pnpm 11.2.2、Docker Compose。依賴固定在 uv.lock／pnpm-lock.yaml。

```sh
uv sync --directory backend --frozen
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend exec playwright install chromium
docker compose up -d --wait db
make db-migrate
```

資料庫由本專案 Compose 管理，開發入口為 `127.0.0.1:55483`，資料在專用 volume；本機開發 role `ai_learn` 採 loopback trust。執行中的其他專案資料庫不會被 migration 或測試使用。

在本專案根目錄開三個 terminal：

```sh
make dev-backend
```

```sh
make dev-worker
```

```sh
make dev-frontend
```

開啟 http://127.0.0.1:3100 。Next.js 同源 `/api/v1/*` 代理至 FastAPI 8100，路徑 prefix 保留。請使用 `127.0.0.1`；Cookie／CSRF allowlist 對應此入口。沒有啟動 worker 時，任務會保持等待，API 重啟不會丟失資料。

本機 PostgreSQL 可透過 `DATABASE_URL` 配置給 API／worker。一般測試只使用固定 localhost role 與新建專用資料庫，`TEST_DATABASE_PORT` 可切換本機測試 port（預設 55483）；不接受測試對既有資料庫做 truncate。

## 功能流程

1. 訪客輸入主題／文字、搜尋或公開網址，選題型與題數，取得持久 job 並輪詢結果。
2. 逐題提交後才顯示答案、解析與知識點；完整作答後取得統計與復盤。重新整理可透過 history 接續。
3. Email／密碼註冊（至少 12 字元）後可編輯暱稱／頭像網址。登入不自動搬移訪客紀錄，帳號頁提供明確認領。
4. 私有文件支援 PDF、docx、Markdown、txt；最多 10 MB／10 份。處理成功才能指定文件出題，無相關內容明確失敗。
5. 配圖需要登入，預設每日 3 張、同時 1 個 reservation。失敗不阻止測驗，成功圖片刪除後仍保留當日 charge；可手動重試生成。

fake 圖片與題目只為流程練習，畫面有示範標示。搜尋／網址不可用時會顯示降級訊息；指定文件不降級為常識。

## 驗收

先啟動資料庫，停止本專案手動預覽以釋放 3100／8100，再依序執行：

```sh
make check
make integration
make e2e
make inventory-check
make mutation-check
```

`make check` 包含 schema drift、lint、型別、後端 tests、網路 guard、production build。`make integration` 使用新建、migration 後的 PostgreSQL 測試資料庫；結束只刪除自己建立的資料庫。`make e2e` 自動建立獨立資料庫／資產目錄、啟動 API 與 worker、production Next.js，再清理。

`make mutation-check` 在臨時程式副本破壞 exact scoring、owner、CSRF、quota、charge、report accuracy、worker fencing；先確認 baseline 通過，只有測試 assertion 確實失敗才算捕獲 mutation。SQL setup errors 不算成功。

API schema 改動後執行 `make schema`；前端使用生成的 TypeScript types。一般測試以網路 guard 阻擋真實外部呼叫；真實 provider 與品質評測需獨立設定與驗收。

## 學習路線

- `backend/app/main.py`：HTTP 契約、Cookie／CSRF 與公開回應。
- `backend/app/services.py`：server scoring、冪等答案、XP 與復盤。
- `backend/app/auth.py`：密碼、opaque sessions、登入限制、七天訪客與認領。
- `backend/app/worker.py`：持久任務、lease／heartbeat／fencing、ReAct 與 strict RAG。
- `backend/app/resources.py`：owner 邊界、atomic chunks、image reservation／charge。
- `backend/app/db.py`、`backend/migrations/`：PostgreSQL 關聯與原生 UUID migration。
- `frontend/src/app/page.tsx`：同源 API、輪詢、答題、帳號與資源操作。

練習：改 `backend/app/providers.py` 的 fake 題目，故意產生無效答案選項，觀察任務失敗；改成部分正確的多選題，確認判分採完整集合而非只要命中；並發請求配圖，確認僅一個 reservation 成功。

## 計畫

- [執行計畫](docs/plans/2026-10-01-full-rebuild.md)：唯一進度與待決。
- [功能與來源盤點](docs/plans/2026-10-01-full-rebuild/inventory.md)。
- [原始碼盤點](docs/plans/2026-10-01-full-rebuild/source-review.md)。
- [機制沿用盤點與設計審查](docs/plans/2026-10-01-full-rebuild/mechanism-audit.md)。

上游固定 SHA 僅作只讀行為參考。公開部署、remote CI、真實 provider 費用另行選定。

## Container demo

`docker compose up --build -d` 建置並啟動 db、一次性 migrate、api、worker、web。等 api healthy 後開 http://127.0.0.1:3100；`make smoke-container` 經同源 Web 入口驗證登入、文件 RAG、job、三題型判分、report、history、配圖與刪除。smoke 在 demo 建立 synthetic 測試帳號與紀錄。API／worker 共用 assets volume，migration 成功才啟動。DB 使用 init 回收健康探測 orphan，避免 PostgreSQL PID1 把 exit2 當 backend crash；同源 smoke 不只看 healthy 標籤。

## 可配置 cloud adapters／eval

一般測試與 Compose 預設 `PROVIDER_MODE=fake`。`PROVIDER_MODE=cloud` 才載入 server-side environment；缺設定會拒絕啟動，不降級 fake。Text／embedding／image 採 OpenAI-compatible HTTPS API，search／extract 採 Tavily-compatible HTTPS API；協定相容不代表選定供應商或品質已驗收。

| 設定 | 用途 |
|---|---|
| AI_API_BASE_URL | HTTPS API base，含 `/v1`（如供應商需要） |
| AI_TEXT_MODEL／AI_EMBEDDING_MODEL／AI_IMAGE_MODEL | 顯式 model ID，沒有默認的付費 model |
| AI_EMBEDDING_DIMENSIONS | 顯式維度；DB model identity 包含 endpoint、model、dimension hash |
| AI_API_KEY | 只在 backend／worker environment 使用，不放前端或 Git |
| AI_JSON_MODE | `json_schema`（預設）或經服務驗證的 `json_object` |
| AI_IMAGE_RESPONSE_FORMAT | `default` 僅用於預設回 base64 的 model；需指定格式的相容 API 設 `b64_json`；不下載未知 image URL |
| SEARCH_API_BASE_URL／SEARCH_API_KEY | 相容 search／extract endpoint 與 server-side token；未設定搜尋會明確失敗／依搜尋模式降級 |
| AI_RAG_MIN_SIMILARITY | 真實 embedding 的 cosine 門檻，需先 eval-rag 校準；不沿用 fake 的 0.15 |

HTTP／DNS 真實 transport 由一次性子程序處理；deadline 到就終止並等待子程序。Key 與 payload 經 stdin，不放 argv／子程序 env，不打印 provider 原始錯誤；不自動重試。API／worker 應使用相同設定。更換 embedding endpoint／model／dimension 後需重新處理文件。

`make eval` 預設只跑 public fixtures 的 fake harness；`make eval-search`、`make eval-rag`、`make eval-image` 為分項入口。服務與費用確定後才顯式執行例如 `make eval EVAL_ARGS="--provider cloud --allow-external --max-requests 9"`。結果放在 ignored `backend/.data/evals/`，涵蓋 schema、工具來源、embedding Recall@1、latency、圖片格式；題目事實準確、來源相關性與圖片可讀性需人工 review，不能把 schema pass 當品質 pass。`--min-recall` 可設定檢索驗收門檻。

目前依本輪選定範圍完成 adapters／eval 程式，服務、費用與實際品質評測延後；沒有執行真實 provider，也沒有產生 AI 費用。

協定來源：[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、[Embeddings](https://developers.openai.com/api/docs/guides/embeddings)、[Image generation](https://developers.openai.com/api/docs/guides/image-generation)、[Tavily search](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[Tavily extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract)。
