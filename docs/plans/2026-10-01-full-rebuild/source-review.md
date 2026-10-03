# 固定版本原始碼盤點與離線驗證

來源：liyupi/yu-ai-learn，commit `d68cf0b77dd89cae1143abe8c300b239da79a6ea`。日期：2026-10-01。

`source/` 是本機只讀參考 checkout，不屬新應用程式，也不納入新 repo 的 Git 歷史。未讀 `.env.example` 或 config 的憑證設定；未啟動 app、DB 或外部服務。

## 可重跑入口

以下 `<attachment>` 是本文件所在的絕對目錄：

```text
git -C <attachment>/source rev-parse HEAD
git -C <attachment>/source ls-files
python3 <attachment>/audit_source.py
python3 <attachment>/audit_source.py --self-test
python3 <attachment>/offline_probes.py
```

[source-inventory.json](source-inventory.json) 是 AST／文字產生的逐項清單，包含行號、去向與前端 consumer。`audit_source.py` 限定讀取 code，不 import app；變更來源版本、刪除清單項目或缺去向都會失敗。`--update` 只在重新審核盤點後使用。

| 類別 | 計數 | 來源與計數方式 |
|---|---|---|
| REST route | 14 | routes/*.py 的 router decorators，prefix 由 main.py 核對為 /api/v1 |
| Pydantic model | 24 | models/*.py 的 class，逐列欄位在 JSON |
| MySQL table | 7 | core/db.py 的 CREATE TABLE；不是舊 sql/init_mysql.sql |
| Prompt 常數 | 7 | prompts/*.py 的 module assignments |
| 測試函式 | 139 | tests/test_*.py 的 test_ 函式，含 class methods；不是已通過數 |
| 前端 API/helper | 22 | services/api.ts 的 exported functions，consumer 搜尋完整 frontend/src 的 ts/tsx，包含 api.ts 內部呼叫；排除宣告／import，記錄 call 語法匹配 |
| 前端單元 | 6 | 五個 page + app.ts bootstrap |
| 現行 OpenSpec requirement | 8 | openspec/specs/*/spec.md 的 Requirement headings；archive 另作歷史比對 |

## API、頁面與契約去向

| 原 API（均以 /api/v1 開頭） | 原前端 consumer／來源 | Web 去向 |
|---|---|---|
| GET /health | routes/health.py:8；未有 page consumer | 保留 health，步驟 2 |
| POST /quiz/generate | api.ts:156 同步 helper；五個 page 沒呼叫 | 保留出題能力；D5 已決最終持久 job + polling，步驟 2/3 薄路徑同步入口於步驟 5 統一替換 |
| POST /quiz/generate/async | api.ts:99；index:49、knowledge:148 | 按 D5 重做 job 流程，步驟 5 |
| GET /quiz/task/{task_id} | api.ts:118、pollQuizTask:123；index:54、knowledge:151 | 重做 owner-scoped 查詢與狀態，步驟 5 |
| POST /report/generate | api.ts:170；report:83 | 依已決 D6 改按 server-owned quiz/records 計算；步驟 3 |
| POST /user/login | api.ts:186；app.ts:16 | 換註冊、Email／密碼登入與登出，步驟 4 |
| GET /user/profile | api.ts:194；profile:17 | 保留 nickname/avatar、xp、quiz_count、correct_count、average_accuracy，步驟 4 |
| PUT /user/profile | api.ts:199；profile:59、71 | 保留編輯 nickname/avatar 能力；Web 上傳 avatar 不屬已確認來源能力 |
| GET /user/quizzes | api.ts:207；profile:28、index:21、33 | 保留分頁歷史，步驟 4 |
| GET /user/quizzes/{quiz_id} | api.ts:212；report:59 | 保留歷史詳情與復盤回看，步驟 4 |
| POST /knowledge/documents | api.ts:219；knowledge:100 | multipart 上傳，登入限定，步驟 6 |
| GET /knowledge/documents | api.ts:257；knowledge:35 | 保留登入者列表，步驟 6 |
| GET /knowledge/documents/{doc_id} | api.ts:262；knowledge:58 | processing/ready/failed，步驟 6 |
| DELETE /knowledge/documents/{doc_id} | api.ts:267；knowledge:132 | 保留刪除，按 PostgreSQL transaction 與檔案清理重做，步驟 6 |

consumer 指令：`rg -n '<上述 helper 名稱>' source/frontend/src --glob '*.ts' --glob '*.tsx'`。JSON 列出 call 語法匹配，包含 getToken／clearToken／getQuizTaskStatus 等同檔依賴；不是 TypeScript compiler 的 symbol resolver。同步 generateQuiz 沒有 page 呼叫的證據是 JSON consumers 空陣列及該搜尋結果；不代表沒有外部使用者。

原題庫含 answer/explanation；AnswerRecord 含 client is_correct；ReportGenerateRequest 包含整包 questions 與 records。D6 已決後端逐題判分、提交後才揭露答案，報告統計由程式計算，因此不直接複製這三個對外 schema。保留題目種類、輸入長度 1–2000、題數 3–10、難度、generate_images/doc_id、image_notice、report 的文字欄位，門檻如改動需列明理由。share_quote 是原報告欄位，也納入步驟 3。

原七張表逐列改寫：users 改 Email／password hash；quiz_sessions、answer_records、reports 改伺服器權威與 D2 的訪客銜接；quiz_tasks 改 D5 的狀態／owner／復原；kb_documents 改 PostgreSQL 文件生命周期並新增 chunk/vector metadata；image_generation_logs 改 quota reservation／結果追蹤。不得複製 MySQL-specific schema。新 session、chunk、quota 結構在相關步驟設計時固定。

## 行為核對

- 訪客：quiz 與 report 使用 optional user；未登入不寫 quiz/history/xp。任務仍可建立；這與資料庫可空 user_id 的能力不同，不能以 schema 推定訪客歷史已保存。Email 登入後是否認領成果由 D2 決定。
- 私有文件：所有 knowledge route 強制登入，quiz_service.py:55–68 再檢查 owner 與 ready；vector_store_service.py:36、83 使用每人 collection + doc filter。**already protected**：登入、文件 owner/ready 與 doc 選擇有相應測試宣告；需在新 pgvector 重建同等行為，原完整測試尚未執行。
- 配圖：image_service.py:121 在訪客時返回提示；配圖、下載或轉存失敗返回 None，不阻斷題庫。**already protected**：test_image_service.py:53、134、163、176、193 已有對應案例；Web 重做保留降級。
- URL：search_service.py:77 使用 TavilyExtract，並非 FastAPI 自己直接抓任意 URL。換搜尋 provider 時需確認是否提供提取服務，不默認新增自建 crawler。
- 搜尋：basic/deep/extract 三工具，ReAct；120 秒逾時、5000 字摘要、recursion_limit=10；失敗返回空 context。這些是 code 現況，不是建議值。
- RAG：原版可用私有檢索並補聯網搜尋；60 秒逾時、3000 字摘要；失敗返回空 context，後續仍出題。現行 spec 明確允許此降級；D7 已由 Will 決定 Web 版文件模式保持文件邊界、失敗明確提示，搜尋模式可顯示降級。
- Task：DB 保存 status/result，但執行靠 asyncio.create_task；未見啟動時回復 pending/running 的 consumer。核對命令 `rg -n 'quiz_tasks|create_task|pending|running' source/backend/app --glob '*.py' --glob '!config.py'`，需要 D5 選擇重啟語意，不能把 DB row 當持久 worker。
- 前端輪詢：8 秒、100 次，名义最多約 800 秒；不是實際模型延遲數據。Web 版取消／重試／進度須按 D5 新契約。
- 歷史缺陷文件 docs/需要修复的 Bug.md 包含已修前端問題；不能当作目前仍有 17 個 bug。本機未跑小程序，視覺缺陷未重新驗證。

## 已重現的風險與處置

`offline_probes.py` 從固定來源 AST 提取原函式，注入 fake dependencies 執行。其範圍是 service 行為，不等於 HTTP、真实 Chroma／MySQL 或雲端驗證。

| ID | 證據與重現 | 處置與後續回歸測試 |
|---|---|---|
| B01 | scoring_service.py:6 只讀 client is_correct；假選項 + true 得 100%。前端 quiz:60–68 自判 | D6 已決修：server-owned 答案与每題提交；偽造正確 flag／非法選項測試在舊行為失敗 |
| B02 | task status route 無 auth；quiz_service:220、task_repository:55 只有 task_id；probe lookup 无 caller | 建議修：owner/session scope；雙帳號與訪客 session 越權測試。防護屬新 Web 私有邊界，不保留原缺口 |
| B03 | knowledge_service.py:72 在假 partial vector write 拋錯後只標 failed，不 cleanup | 建議修：向量與 chunk 同一 PG transaction，非交易性作業補恢復；注入中途 failure 不能留可檢索 partial vectors；也須符合原 OpenSpec「no partial vectors」 |
| B04 | image_service.py:123–153 先 count 再生成，semaphore 是每次呼叫；兩請求同看 0、每日限額 1 卻生成 2 | 建議修：原子 reservation、全 worker 配額與重試去重；並發額度回歸在舊行為失敗 |
| B05 | report_service.py:58 回傳模型 accuracy；probe computed 100%，model 7%，回傳 7% | D6 已決修：後端統計覆蓋 accuracy；相矛盾模型輸出不能改動統計 |

不宣稱上述情境「沒有測試」；已檢查的來源測試並未阻止離線重現，完整 suite 的覆蓋結果仍未知。B02–B04 是計畫作者建議處置，與細項計畫一起交使用者確認。

## 文件差異與 spike 結論

Archive search spec 寫 15 秒、3000 字、basic/deep 各 3/5 結果；目前 code 為 120 秒、5000 字、各 10 結果。這是 archived 文件與現況差異，不能當兩份現行 SSOT；D5/D3 重新設定，禁止默默照搬某個數字。

固定 pipeline、ReAct、同步、job polling、SSE 的實際品質、費用與延遲目前沒有量測。離線證據能證明上游機制與失敗路徑，不能證明 ReAct 必要或 SSE 比較快。技術 spike 保留為步驟 1b，先做 fake 有界 tool-loop 與 task lifecycle；真實測量需 providers、預算與授權後執行。

## 驗收基線

- `audit_source.py --self-test`：通過；去向清空與漏 model 的 mutation 被擋。
- `offline_probes.py`：五個 fake service 情境重現。
- 原 `test_prompt_contract.py`：4 passed；未安裝依賴，利用既有 pytest。命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<attachment>/source/backend python3 -m pytest -p no:cacheprovider <attachment>/source/backend/tests/test_prompt_contract.py -q`，log 在 prompt-tests.log。
- 原完整 pytest：未跑；本機缺 fastapi、pydantic-settings、LangChain/LangGraph、aiomysql、structlog 等依賴，未獲安裝授權。139 是靜態函式計數，不能寫成 139 passed。
- 新應用：仍無 code/scaffold，沒有可執行基線。
