# Next.js + FastAPI 完整重做

**Goal：** 在本機以 Web 介面跑通附件 R01–R12 的學習流程、帳號、搜尋、私有文件與配圖；每階段有端到端驗收與可解釋的設計。

**上層：** 暫代主清單。本檔是唯一進度與待決清單。

**附件：** [功能與來源盤點](2026-10-01-full-rebuild/inventory.md)、[固定版本盤點](2026-10-01-full-rebuild/source-review.md)、[逐項清單](2026-10-01-full-rebuild/source-inventory.json)。原始碼拓撲盤點與離線驗證已完成；離線技術 spike 與 D2–D7 的本輪選擇已確認；可配置 adapters／eval 已納入本輪；實際服務、預算與品質評測延後。

**機制沿用盤點與新版 review：** [mechanism-audit.md](2026-10-01-full-rebuild/mechanism-audit.md)。

## 全域約束與完成定義

- 學習專案，不替換原 repo 的部署或資料；Next.js + TypeScript、FastAPI、Email／密碼與訪客體驗已決。
- 全新實作；原 repo 作為行為參考，不能盲目照搬 schema、框架、prompt、認證與任務機制。若直接採用原碼，保留其 license 與 attribution。
- 同網域 `/api` 反向代理 FastAPI 已決。瀏覽器只呼叫同源 `/api/v1/*`，代理保留 `/api/v1/*` 路徑；FastAPI 負責 session，Next.js 不新增 BFF 權威層。
- 本 session 已授權必要的一般操作、依賴下載與安裝，不在實作階段邊界重問；費用與真實服務仍依 D1／D3b 選定後驗收。
- 每個產品步驟需有瀏覽器端到端流程、相應後端測試、失敗案例及 mutation；mock 驗收與真實 provider 驗收分開。
- 完成定義：R01–R12 每組及步驟 1 補出的細項有去向、實作、測試；權限與答案邊界通過；可配置 cloud adapters 的離線契約與 opt-in eval 通過；本機 container demo 可重跑。實際服務、費用與模型品質依 Will 最新選擇延後，不作本輪完成條件。
- 每步完成附簡短學習解說：請求資料流、選型取捨、故障案例與可自行修改的練習。不預設 Will 或 agent 哪方必須寫程式。

## 前提（2026-10-01）

- 會改到或取代的既有部署是否在線：無既有部署（本專案是獨立學習重做）；不觸及上游正式環境。
- 用途、stack、位置、登入及目錄建立：使用者對話已確認。
- 完整範圍參考原 repo 目前能力：已確認意圖；固定版本 API/model/table/prompt/test/page/consumer 已盤點，原 runtime 行為未全部驗證。
- 步驟 2 已建立產品 code、manifests、lockfiles 與驗收入口；Git 已初始化 main，尚無 commit。
- 新工具鏈預設 pnpm、Python 虛擬環境、pytest、Playwright；可推翻，需在步驟 2 查本機工具並固定依賴。
- PostgreSQL + pgvector：Will 已確認，取代 MySQL + Chroma；AI adapter 協定：D1 已決；實際服務待定。來源已固定 d68cf0b77dd89cae1143abe8c300b239da79a6ea。

**驗收基線：** 原 prompt contract 4 tests 通過；完整 suite 未跑（依賴缺漏且未獲安装授權），五項 AST fake service probes 重現、盤點 gate 與 mutation 通過。詳見 source-review.md。新應用基線已由步驟 2 建立；各項實跑結果見進度。

## 不變量

| 不變量 | 預計依賴模組（實作後補實際路徑） |
|---|---|
| 後端逐題判分，提交後揭露答案；統計與經驗值由程式計算 | quiz API、scoring、report、frontend quiz |
| 外部輸出經 schema 驗證、逾時及次數限制 | provider adapters、generation jobs、search、RAG、image |
| 同一答案／結算重試不重複發放經驗值 | answer submission、history、experience transactions |
| 私有資源按 owner 隔離，向量檢索不能跨文件或帳號 | auth dependency、document repository、retrieval、jobs、assets |
| secrets 與密碼不進瀏覽器、log 或測試 fixture | auth、settings、provider adapters、API error handlers |
| 一般驗收不觸發真實服務 | fake adapters、pytest fixtures、Playwright environment、CI |

## 範圍

- 做：附件 R01–R12，包含搜尋、RAG、AI 配圖；先完成核心流程再擴展，不把第一階段誤當最終範圍。
- 不做：微信小程序、微信登入與微信發布流程，因為平台改為 Web。付款、PK、排行榜、影片解析不屬已確認完整範圍。
- 延後：公開部署、Email 驗證／密碼恢復、正式監控／備份（觸發：Will 決定對外開放）；水平擴展／多 worker（觸發：任務 spike 證明需要，須重新決定任務契約）。
- 延後：remote CI 執行（觸發：Will 授權建立／發布 remote）；本輪完成要求可重跑的本機 CI 等價入口，不發布 remote。

## 步驟

所有指令以 repo 根目錄為 workdir；shell 使用絕對路徑。步驟 2 已建立 `make check`、`make e2e`、`make inventory-check`、`make mutation-check`、`make schema`；其他 `make` target 仍是後續步驟的驗收契約，未建立前不能當已可執行。target 可以組合工具，不得用 echo 假通過。每步開始用 `rg -n` 重查列出的 consumer，補齊實際檔案。

依賴語意：步驟 3–7 各分「fake 功能驗收」與「真實 provider 驗收」。步驟 4–7 的前一步依賴，只要求 fake 功能驗收通過；本輪以 fake 功能、cloud adapter 離線契約及 opt-in eval 入口作完成條件。依最新 D1／D3a 決定，真實品質評測延後至服務與費用選定，不阻擋本輪收尾。

- [x] **1a. 固定來源與盤點**（原碼下載已授權；本輪只讀來源）
  - 範圍：固定 full SHA，API/models/tables/prompts/tests/pages/consumer/current OpenSpec 逐項去向、來源差異與離線缺陷重現；不把 fake probe 當原完整測試。
  - 消費端：source-inventory.json 含每個前端 exported function 在完整 frontend/src（包括 api.ts）的 call 語法匹配檔案／行號；不是 TypeScript symbol resolver。後端對應與完整 route 去向在 source-review.md。新應用尚無 consumer。
  - 不能動：來源 code、來源部署、正式資料、憑證與外部服務。
  - 驗收：`python3 <attachment>/audit_source.py --self-test`、`python3 <attachment>/offline_probes.py`；去向清空與 model 缺失必須失敗；prompt contract 4 tests 通過；`git -C <source> status --short` 空白。
  - 完成後：可以評估 D2/D6/D7，不能把未做的性能／費用 spike 或 runtime 基線算完成。
- [x] **1b. 技術 spike 與計畫定稿**（被擋於：步驟 1a；付費部分另需 D1/D3b 與 secrets 授權）
  - 範圍：離線 fake pipeline／bounded tool-loop、同步／job polling／SSE 的停止條件及重啟契約；依 D2/D6/D7 更新範圍，補決定與獨立設計審查。來源 runtime 完整基線待依賴安装授權後執行；無授權則保留未跑原因。
  - 消費端：`rg -n 'create_task|quiz_tasks|fetch_knowledge_context|fetch_rag_context' <source>/backend/app/services <source>/backend/app/repositories`；新產品尚無 consumer。
  - 不能動：來源 code；不從 fake 延遲推論真實性能。
  - 驗收：spike 附可執行命令、觀察數字與限制；故意無限 tool-loop／job 重啟漏轉態要失敗。fake 與真實量測分開，實際品質／費用／延遲未測就標未知。D5 在 fake 事實後決定，provider 相關數字待真實測量後設定；不得用新分類或 CI 發布填補未授權步驟。
  - 停止條件：未決選擇會改範圍／契約時先交使用者；來源差異已有 D6/D7，不能自己拍板。
- [x] **2. Walking skeleton**（被擋於：步驟 1a、D4、D6、依賴下載授權；步驟 1b 與付費 spike 可未完成）
  - 範圍：Next.js、FastAPI、OpenAPI types、fake provider、一題瀏覽器出題／提交路徑、Git 初始化與本機 CI 等價入口；remote CI 發布延後至授權建立 remote。
  - 消費端：`rg -n 'api|quiz|health' frontend/src backend/app`；實際為 frontend/src/app/page.tsx → src/lib/api.ts → generated/api.ts，backend/app/main.py 三個 routes；rewrite 在 frontend/next.config.ts。
  - 不能動：已決 stack、安全邊界與隔離要求。
  - 驗收：建立並跑 `make check`（lint、typecheck、backend tests、frontend build）、`make e2e`（自動啟動測試服務，用 fake provider）、`make inventory-check`；D4 的 browser → `/api/v1/*` → FastAPI 路徑保留 prefix，破壞 proxy destination 或移除 schema 驗證，相關測試必須失敗。skeleton 建好後補 proxy 設定檔、API client 的實際 consumer 與測試名稱。測試 harness 預設阻擋外部連線，只允許本機測試服務；故意呼叫外部 endpoint 必須立即失敗，且不真正送出請求。真實 eval 用獨立 opt-in 入口。
  - 停止條件：工具鏈不支援、需額外系統安裝或下載，先取得授權；未生成可用 OpenAPI types 不能手寫平行契約假完成。
- [x] **3. 核心學習流程**（被擋於：步驟 2、D6）
  - 範圍：R01–R04；三題型、模型結構驗證、後端判分、錯題解析、統計與復盤，加入 provider adapter。
  - 消費端：`rg -n 'quiz|question|answer|report|score' frontend backend`。
  - 不能動：提交前答案保密、統計權威與 mock 預設。
  - 驗收：`make check`、`make e2e`；三題型正／錯／非法提交、模型壞 JSON、超時、報告失敗可重試。修改判分或提前暴露答案時測試必須失敗。`make eval` 預設 fake harness；cloud 評測須顯式 opt-in，實際品質門檻依 D3b 延後。
- [x] **4. 帳號與持久化**（被擋於：步驟 3；D2 已決）
  - 範圍：R05–R06；註冊、登入、登出、cookie session、CSRF、訪客流程、nickname/avatar 資料與編輯、profile 統計、分頁歷史與報告、經驗值冪等；建立版本化 migration。
  - 消費端：`rg -n 'session|user|guest|history|experience|owner' frontend backend`。
  - 不能動：Email／密碼選擇、核心訪客體驗、既有已驗收題型。
  - 驗收：`make check`、`make e2e`、`make integration`（測試專用 DB，fresh migration）；雙帳號越權、登出 token 撤銷、CSRF、重複結算、process restart 後歷史保留。匿名 session 7 天到期前／後、清理、登入後明確認領、重複與跨帳號認領皆驗收；並發認領只能一次成功，XP 不重複結算。取消 owner 條件／冪等機制／到期檢查或認領 session 證明，各使對應測試失敗。
- [x] **5. 搜尋與網址**（被擋於：步驟 4、D5）
  - 範圍：R07–R08；按來源語意處理 URL、搜尋出題、可見生成狀態與明確 retry；將步驟 2/3 的暫時同步生成入口與全部前端 consumer 一次改為持久 job + polling，純文本出題也使用同一 job 契約。若採直接抓 URL，需 SSRF 防護及重新導向檢查。
  - 消費端：`rg -n 'search|url|job|status|generation' frontend backend`。
  - 不能動：無搜尋的純文本流程、登入與資源隔離。
  - 驗收：`make check`、`make e2e`、`make integration`；成功、空結果、逾時、額度耗盡、重複啟動與 job restart 行為按 D5 測試。移除搜尋次數限制／URL 安全檢查時相應測試失敗；真實搜尋另跑 `make eval-search`，未跑記原因。
- [x] **6. 文件與 RAG**（被擋於：步驟 5、D7（真實 provider 驗收另需 D1／D3b））
  - 範圍：R09–R10；四種文件、解析狀態、chunk、embedding、檢索、依指定文件出題與刪除清理。本步前設計並 review PostgreSQL 內 document／chunk／vector 的 transaction 邊界，以及解析、embedding、檔案儲存等非交易性作業的失敗恢復；不得預設引入獨立向量庫。固定 embedding 模型版本、維度、distance metric，先做精確檢索基線再量測索引取捨。
  - 消費端：`rg -n 'document|chunk|embedding|retriev|knowledge|doc_id' frontend backend`。
  - 不能動：private owner 不變量、搜尋與純文本流程。
  - 驗收：`make check`、`make e2e`、`make integration`；有效匿名 session 上傳仍拒絕，不建立 document 或呼叫 provider；移除登入檢查時測試必須失敗。每種格式 fixture、檔案大小超限／壞檔、每人文件數到上限時拒絕且不建立文件紀錄、無命中、雙帳號／雙文件隔離、embedding 部分失敗與刪除重試。去掉 owner/doc filter 或文件數量檢查，對應測試必須失敗；真實檢索跑 `make eval-rag` 依 D3b 門檻判定。
- [x] **7. AI 配圖**（被擋於：步驟 6（真實 provider 驗收另需 D1／D3b））
  - 範圍：R11；生成、轉存、狀態、每日額度、併發限制與失敗降級。
  - 消費端：`rg -n 'image|asset|quota|storage' frontend backend`。
  - 不能動：圖片失敗不阻止答題；同一 retry 不能重複占用額度。
  - 驗收：`make check`、`make e2e`、`make integration`；有效匿名 session 配圖仍拒絕，不建立 asset 或呼叫 provider；移除登入檢查時測試必須失敗。並發請求 quota、轉存失敗、重試、物件與紀錄清理，關閉原子 quota 判定必須失敗。配圖 adapter／離線契約本輪驗收；服務與費用拍板後執行 `make eval-image` 真實品質評測。
- [x] **8. 收尾與學習驗收**（被擋於：步驟 1a、1b、2–7 實際驗收通過）
  - 範圍：R12；本機容器、README 可重跑步驟、錯誤與觀測、完成定義逐項核對、獨立 design-review 與 code review；長期檢查接入本機 CI 等價入口，remote CI 留在延後清單。
  - 消費端：`rg -n 'localhost|api|health|DATABASE|provider' frontend backend docs`，只查 code／docs，不讀任何憑證來源。
  - 驗收：`make inventory-check`、`make check`、`make integration`、`make e2e`、所有已選 provider eval、`make smoke-container`；乾淨環境按 README 重跑。斷 backend container 應讓 smoke 失敗。範圍矩陣零空白，review finding 全處置；全部命令由主 agent 重跑。
  - 停止條件：核心功能、adapters／eval 入口或容器未驗收，不標本輪程式完成；依 Will 最新選擇，真實服務與費用待定，不宣稱實際模型品質。
  - 需要人做的事：對外部署、remote 建立／發布若有意願另拍板；保留延後清單與觸發條件。

使用者要求本 session 持續完成完整功能，不以步驟邊界停止；每項仍需獨立驗收。對新儲存、認證、任務、外部介面執行 design-review 沿用盤點，完成前獨立設計審查。

## 決定

- **D0 用途、stack 與登入**：已決 2026-10-01，Will；學習用途、Next.js + FastAPI、Email／密碼、保留訪客核心體驗。沒有公開部署承諾。
- **D-DB 資料層**（已決 2026-10-01，Will）
  - A：MySQL + Chroma；貼近來源，但要處理兩種儲存的一致性。
  - B：PostgreSQL + pgvector；資料與向量整合，增加 relational／vector 的 schema、索引與 transaction 練習。
  - 結論：B。使用者明確選擇增加資料庫整合練習；AI 服務另選，不推定保留上游 providers。決定原文為「改 PostgreSQL + pgvector，AI 服務另選，增加資料庫整合練習」。目前決定記在本計畫；三份獨立草稿對照後的 ADR 已建立，取回入口見 ignored AGENTS.local.md。
- **D1 AI providers**（adapter 方向已決；實際服務待定）
  - A：單一供應商提供 LLM／Embedding／生圖，搜尋與物件儲存另選；帳號少，但功能受同一供應商限制。
  - B：按能力分開選；彈性高，但需更多帳號、費用管理與 adapter（建議先比能力與價格再選）。
  - 最新結論：先完成可配置 OpenAI-compatible text／embedding／base64 image 協定與 Tavily-compatible search／extract，都是可替換 endpoint；不代替選服務。以 mock transport 驗契約與 total deadline，真實 eval 顯式 opt-in。服務／費用待定，本輪不呼叫真實服務。
- **D2 訪客與資料生命週期**（已決 2026-10-01，Will；不再擋 4、6）
  - 結論：匿名 session 保存 7 天，登入後明確認領紀錄；私有文件與配圖限定登入。
  - 步驟 4 實作與驗收：伺服器保存期限、過期拒絕存取與清理；認領需同時持有有效匿名 session 與登入 session，以 transaction 防止重複／跨帳號認領。不可只憑提交 guest ID 認領。
- **D3a 開發與驗收模式**（已決 2026-10-01，Will）
  - 結論：先用 fake provider 完成各功能，再選服務與預算做真實驗收。fake 開發不受 D1／D3b 阻擋；最新 Will 選擇「先做可配置的雲端 adapters 與 eval，服務與費用待定」：本輪完成以 adapters、離線契約與可執行 opt-in eval 為準；真實品質驗收延後至服務／費用拍板。
  - 此決定不授權費用、金鑰讀取或依賴下載。
- **D3b 費用與品質界線**（未決；只擋真實驗收與付費 spike）
  - 待選服務後確認總預算、每局限制、評測資料集與品質門檻；無付費授權不得呼叫真實服務。fake spike 的工具上限僅測試參數，不是正式產品限制。
- **D4 前後端入口**（已決 2026-10-01，Will；不再擋 2）
  - A：同網域 `/api` 反向代理 FastAPI；cookie 與 local demo 單純（建議）。
  - B：瀏覽器直接跨網域 FastAPI；部署獨立但需 CORS／cookie 配置。
  - C：Next.js BFF 管 session 並轉接 FastAPI；集中前端 session，但增加權限與契約層。
  - 結論：A。同源 `/api/v1/*` 代理至 FastAPI 同一路徑；本機可用 Next.js rewrite，容器使用反向代理；兩者使用相同契約。cookie Path 為 `/api`，認證／CSRF 均由 FastAPI 管理，API base URL 不在瀏覽器指向跨域後端。
- **D5 搜尋編排與任務契約**（已決 2026-10-01，Will；不再擋 5）
  - 結論：bounded ReAct，工具呼叫次數與 planner 輪數雙重上限；持久 job + polling；SSE 延後。執行中斷標記失敗，由使用者明確重試，不自動重新呼叫 provider。
  - 狀態保存在 PostgreSQL，獨立 worker claim pending job；lease／heartbeat 判定中斷，fencing 在任何結果寫入前檢查。瀏覽器斷線不取消已建立的 job；重連查詢同一 owner 的狀態。外部呼叫不包在長時間 DB transaction 內。
  - 同一 owner 的重複建立請求以 idempotency key 去重；相同 key 不同 payload 拒絕。明確重試建立新的 job 並指向前次失敗 job；已完成 job 不可重試。單 worker 為目前部署預設，不要求額外 queue 服務。步驟 2/3 的同步入口僅為薄路徑，步驟 5 一次更新其 OpenAPI types、API client 與全部生成頁面，最終不保留第二套同步生成權威。
  - 驗收：工具／planner 上限、owner 隔離、重複建立、失敗後明確重試、worker 中斷後轉失敗、過期 worker 不能提交、斷線後重讀結果；移除上限／fencing／owner 或讓中斷自動重試，測試必須失敗。步驟 5 以 PostgreSQL integration tests 驗證，不能以 SQLite spike 代替。
  - 依據：[runtime spike](2026-10-01-full-rebuild/runtime-spike.md)。正式 provider 限制於 D3b 真實驗收前固定；fake 測試使用可配置小上限。

- **D6 判分與報告契約**（已決 2026-10-01，Will；不再擋 2、3）
  - A：後端持有答案，每題提交後才揭露；報告 accuracy 由程式固定。可防偽造與模型統計誤差，但新增提交 API 與 server-owned attempt（建議）。
  - B：保留前端整包答案、自判 is_correct、上傳報告資料；較容易直接比較來源，但保留原權威邊界。
  - 結論：A，後端逐題判分。新 `POST /api/v1/quiz/{quiz_id}/answers` 只收 question_id、selected_answers、duration_ms；讀 server-owned quiz 的答案，验证題目與選項後返回正誤、答案和解析；同一題有效提交冪等，不重複結算。題庫輸出不含答案／解析；報告只引用 server-owned quiz／records，不收 client questions/is_correct，accuracy 與 XP 由程式固定。具體 schema 及同題修改政策在步驟 2/3 固定並測試。
- **D7 私有文件檢索降級**（已決 2026-10-01，Will；不再擋 6）
  - A：文件模式檢索失敗／來源不足時明確失敗，不改用模型常識；一般搜尋模式可顯示降級。來源語意清楚，但可用性較低（建議）。
  - B：保留來源 fallback：檢索失敗仍用常識出題；不中断流程，但無法保證題目來自指定文件。
  - 拍板含是否補聯網搜尋、降級是否需使用者同意與來源標示，會改出題可用性與費用；step 6 測試需依結論重寫。
  - 結論：A。指定文件時保留文件來源邊界；不自動補聯網或常識。解析／檢索失敗或沒有足夠來源時回傳可重試的明確錯誤，不生成看似基於文件的題目。一般搜尋模式可以降級為模型常識，但 response 與 UI 必須顯示降級來源；RAG 的相關性門檻在 D3/eval-rag 固定。

拍板順序：D4/D6/D7 已決；D2/D3a 已決；D1 可在 skeleton 後選；D5 已決；D3b 付費前補預算／門檻。D-DB 已確認；已新增三份 ADR，覆蓋本輪已決資料／入口、權威／認領與任務／來源／評測；D3b 未決保留 Followup。

## 進度

| 步驟 | 狀態 | 已跑的驗收 | 未跑的驗收與原因 | commit |
|---|---|---|---|---|
| 1a 來源盤點 | 完成 | 固定 SHA；盤點 gate + mutation；五項 offline probes；原 prompt 4 passed；來源 worktree clean | 原完整 suite 未跑：缺依賴／未授權安装；不影響靜態盤點完成 | 無 |
| 1b spike/定稿 | 本輪完成 | runtime_spike.py：13 tests、3 mutations；獨立設計審查；兩份fresh ADR草稿對照後落地3份 | 真實品質／費用依D1／D3a延後 | 無 |
| 2 skeleton | 完成 | make check；19 backend tests；5 Chromium E2E；inventory-check；6 mutations；獨立 design/code review | 真實 provider／DB 非本步範圍 | 無 |
| 3 核心 | 完成 | 完整後端103 tests、9 Chromium E2E、7 mutants；三題型／非法提交／報告重試 | 真實品質依 D1／D3a 延後 | 無 |
| 4 帳號 | 完成 | isolated PG17 migrations；session／profile／claim／XP、並發 claim、owner race E2E | 公開部署延後 | 無 |
| 5 搜尋 | 完成 | 持久 jobs／6 workers unique claim／lease fencing／deadline／bounded tools／visible fallback；cloud contracts | 真實搜尋品質待選服務 | 無 |
| 6 RAG | 完成 | 四格式 parser、atomic chunks、owner／doc／model／dimension隔離、strict失敗；browser上傳／出題／刪除 | 真實 embedding 品質與門檻待選服務 | 無 |
| 7 配圖 | 完成 | 原子 quota／charge／crash GC／private資源／browser flow；cloud image contracts | 真實圖片品質待選服務 | 無 |
| 8 收尾 | 本輪功能完成 | 103後端／9瀏覽器／7mutants；完整容器正負與恢復smoke；design／code修後review；recording | 真實品質依決定延後；獨立ADR草稿已完成，決策落地3份ADR | 無 |

## 下一次接手

[接手狀態](2026-10-01-full-rebuild/handoff.md)。

步驟 3–7 已完成本輪功能、fake／mock 契約與瀏覽器驗收，本輪容器與記錄收尾已完成。D2/D3a/D4/D5/D6/D7 已決，不需重問；本 session 持续授权。fake 功能不必等真實 provider，本輪程式完成含可配置 adapters／eval 入口；真實服務與費用依最新 Will 決定延後。skeleton 的舊 19／5／6 通過不能代表新版。

## 計畫審查紀錄

獨立唯讀審查找到 5 項，全部已修改；主 agent 已核對文件。此為草稿審查，不能替代來源盤點後的完整計畫審查或產品 code review。

| ID | 發現 | 處置與核對位置 |
|---|---|---|
| F1 | D4 未決卻固定 `/api` mutation | 已修：步驟 2 依已決入口破壞，拍板後補 consumer |
| F2 | fake 與真實驗收依賴不清 | 已修：fake 與真實驗收分開；最新 D1／D3a 將本輪收尾改為 adapters／eval，真實品質延後 |
| F3 | pgvector 決定後仍沿用跨庫前提 | 已修：步驟 6 改為 PostgreSQL transaction 與非交易性作業恢復 |
| F4 | 零外部請求只有原則 | 已修：步驟 2 增加連線阻擋與外部呼叫 mutation |
| F5 | remote CI 的完成與延後矛盾 | 已修：範圍、步驟 8、需要人做的事均改為授權後才發布 |

固定來源後的第二次獨立審查已核對計數及五項 probes，找到並處置以下四項；初輪 F1–F5 保留不回歸。

| ID | 發現 | 處置與核對位置 |
|---|---|---|
| F6 | JSON 把 async/task 誤派步驟 3 | 已修：audit_source.py 及 snapshot 派步驟 5，與 source-review 相同 |
| F7 | current spec disposition 誤指 D6 | 已修：指向 D5/D7 的來源契約審查 |
| F8 | 漏掉 api.ts 內部 helper consumer | 已修：掃 frontend/src ts/tsx call 語法，記錄同檔呼叫並排除宣告/import |
| F9 | 漏列每人文件數限制 | 已修：inventory D3 限制清單、步驟 6 拒絕／不建紀錄驗收與 mutation |

## 離線 runtime spike

結果與限制見 [runtime-spike.md](2026-10-01-full-rebuild/runtime-spike.md)。D5 已由 Will 按建議確認；SQLite 模型、fake provider 與虛擬輪詢不代表 PostgreSQL、HTTP SSE 或真實 AI 驗收。

本輪獨立審查：D2 七天期限與認領驗收、D3b 真實驗收阻擋語意、匿名文件／配圖拒絕驗收已補齊；runtime 報告與靜態 code 未見實質不符。

步驟 2 的具體產物、依賴及驗收見 [walking-skeleton.md](2026-10-01-full-rebuild/walking-skeleton.md)。

| F10 | cookie 提前至 skeleton 但 CSRF 延至步驟 4 | 已修：walking-skeleton 規格明列 SameSite、JSON-only、Origin allowlist／missing-origin 拒絕，與負向及 mutation 驗收；產品驗收於步驟 2 執行 |

獨立設計審查：檢查 ID、storage、schema、auth、jobs、transaction、providers 與 generated types，1 項採「改」；其餘未見需重開的設計決定。此為規格審查，不替代產品實作後審查。

## 步驟 2 審查紀錄

- 使用者已授權本 session 的專案依賴下載／安裝；不延伸到費用、secrets、commit 或 remote。
- 獨立 design review：NO DESIGN FINDINGS，暫時 memory／sync 實作有明確替換階段。
- S1：Python connect_ex 繞過 guard；已修 connect_ex／sendto／DNS，新增底層 sentinel regression，主 agent 驗收通過。
- S2：browser fetch 失敗可能假通過；已修共用 guard、blocked URL／ERR_BLOCKED_BY_CLIENT 證據與無網路 mock mutation；獨立核對已修，5 Chromium E2E 全通過，外部請求確認 ERR_BLOCKED_BY_CLIENT。

實際步驟 2 consumer 搜尋已核對 page.tsx／api.ts／generated/api.ts、main.py 與 next.config.ts。OpenAPI 為生成來源；公開 Question 不含答案，提交回應另有 AnswerResponse。

步驟 2 完成證據見 [skeleton-evidence.md](2026-10-01-full-rebuild/skeleton-evidence.md)，本機執行與練習見根 README。前端實際 browser consumer 為 page.tsx，API契約由 backend OpenAPI → generated/api.ts；後續步驟不得重建平行 schema。

## 本輪新增驗證

- 最新完整後端103 tests passed，最新版9 Chromium E2E再次passed；其中cloud adapter21 contracts、eval4 gates、smoke2 mock生命周期tests通過。所有一般驗收使用 fake／mock transport。
- C1 延遲 guest restore 已補 epoch fence並經 E2E；C2–C4 獨立 code follow-up 已核對。新增 namespace／GC／Compose design follow-up 無新 finding，D1–D3 維持 fixed。
- 新增可配置 cloud adapter、public fixture eval（fake harness9calls通過）與 full Compose；7 mutants由行為assertions捕獲；前後端container images建置通過，actual smoke正向／API停止負向／恢復後正向皆通過。
- ADR 首次 dispatch 受 thread limit 拒絕；recording／decision-log 收尾時改串行重試，兩份fresh獨立草稿完成，三份ADR已落地。

## 本輪完成證據

完整後端103tests、最新版9Chromium E2E、7行為mutants、Ruff、Mypy16sources、TypeScript／ESLint、schema drift、network guards、proxy與production build通過。R01–R12新版對照已補inventory；獨立design與code review修後核對，db init／health-timeout control也經獨立design follow-up。actual容器migration及完整smoke通過；API停止時make exit2、恢复後再次通過。服務目前loopback3100，可依README重跑。

決策記錄已落主計畫及專案Key Decisions；兩份fresh獨立ADR草稿已完成，三份ADR已落地。真實服務／預算／品質依Will最新決定延後；本輪未讀secrets、未產生AI費用、未commit／發布remote。

最後recording驗證：second-brain lint-rules.py及check-links.py全通過；新增health-timeout機制已追加既有tech頁。repo指令檔已對帳，個人路由與本機測試參數只放ignored AGENTS.local.md。
