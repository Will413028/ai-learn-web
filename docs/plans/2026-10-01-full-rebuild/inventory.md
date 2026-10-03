# 功能與來源盤點

核對日期：2026-10-01。固定版本的 API、models、tables、prompts、tests 與前端 consumer 已盤點；詳見 [原始碼盤點](source-review.md) 與 [逐項清單](source-inventory.json)。完整 runtime 基線與技術 spike 尚未完成。

## 來源與重查方法

- S1：[README](https://github.com/liyupi/yu-ai-learn)：八項核心能力、技術選型、執行與測試說明。
- S2：[方案設計](https://github.com/liyupi/yu-ai-learn/blob/main/docs/方案设计文档.md)：早期 MVP，不能用它刪除後續擴展。
- S3：[docs 目錄](https://github.com/liyupi/yu-ai-learn/tree/main/docs)：包含需求、使用者系統需求與設計、作廢文件。
- S4：[services 目錄](https://github.com/liyupi/yu-ai-learn/tree/main/backend/app/services)：出題、判分、報告、搜尋、文件解析、RAG、向量庫、圖片、COS、歷史與使用者 service。
- S5：[tests 目錄](https://github.com/liyupi/yu-ai-learn/tree/main/backend/tests)：已靜態列出測試函式、閱讀相關模型／文件／配圖測試，原 prompt contract 4 tests 通過；完整 suite 未跑。
- S6：[提交歷史](https://github.com/liyupi/yu-ai-learn/commits/main/)：下載後 `git rev-parse HEAD` 確認為 d68cf0b77dd89cae1143abe8c300b239da79a6ea。
- S7：使用者已選學習用途、Next.js + FastAPI、personal/ 下 ai-learn-web、Email／密碼登入、PostgreSQL + pgvector，AI 另選；已授權建立目錄、計畫與下載原碼，未授權費用、憑證或依賴下載。

原始網頁抓取後已依授權 clone 到附件 `source/`。盤點指令為 `git -C <source-absolute-path> rev-parse HEAD`、`git -C <source-absolute-path> ls-files`、`python3 <attachment>/audit_source.py` 及 [原始碼盤點](source-review.md) 的 consumer 搜尋；未讀憑證設定，未啟動來源 app。不得把未讀到當成不存在。

## 功能去向

此表有 12 個需求組，只是本表分組數，不是原 repo 的功能數。各組的 route/schema/consumer 對照與缺陷見 source-review.md；所有 API schema 是否完全保持相容不是本學習重做的要求，變更需有決定依據。

| ID | 需求與來源 | Web 版去向 | 步驟 | 原始碼狀態 |
|---|---|---|---|---|
| R01 | 主題／一句話／長文本出題；S1 | 保留，Next.js 輸入 + FastAPI 生成 | 3 | models/quiz.py:32、quiz_service.py:78 已核對 |
| R02 | 單選、多選、判斷；S1 | 保留三題型；依已決 D6 後端逐題判分 | 3 | models/quiz.py:12；前端 quiz:60 已核對 |
| R03 | 即時正確答案、解析與知識點；S1 | 保留；依 D6 提交後揭露答案／解析 | 3 | models/quiz.py:17、前端 quiz:185 已核對 |
| R04 | 復盤、掌握度、薄弱點、总结、建議、share_quote；S1、code | 保留文字欄位；D6 統計由程式計算，AI 只生成文字 | 3 | models/report.py:14、report_service.py:16 已核對 |
| R05 | 可選微信登入、nickname/avatar 資料與編輯；S1、S7、code | 改 Email／密碼，保留個人資料與訪客核心；紀錄銜接 D2 | 4 | routes/user.py:15、models/user.py:24、前端 profile 已核對 |
| R06 | 歷史、報告回看、經驗值；S1 | 保留，持久化及冪等結算 | 4 | history_service.py:9、report_service.py:51 已核對 |
| R07 | 聯網搜尋／ReAct、輪詢任務；S1、S6 | 保留搜尋能力；編排與任務先 spike 再決定 | 5 | search_service.py:17、quiz_service.py:133 已核對 |
| R08 | 網址輸入；S1 | 保留，原版由搜尋 provider 提取 URL | 5 | search_service.py:77 已核對 |
| R09 | PDF、docx、Markdown、txt 私有文件；S1、spec | 保留登入限定上傳、解析、狀態與刪除 | 6 | routes/knowledge.py:15、knowledge_service.py:115 已核對；刪除是原功能 |
| R10 | 分塊、Embedding、向量檢索、依文件出題；S1 | PostgreSQL/pgvector 重做；依已決 D7 保持文件邊界，失敗明確提示 | 6 | vector_store_service.py:83、rag_service.py:95 已核對 |
| R11 | AI 配圖、持久資源、每日額度、併發限制；S1 | 保留登入限定及失敗降級；quota 改原子預留 | 7 | image_service.py:108 已核對 |
| R12 | 小程序發布／微信雲托管；S1、S7 | 改 Web 本機容器驗收；公開部署延後 | 8 | backend/Dockerfile 存在；未 build 原鏡像 |

沒有來源證據支持的密碼重設、Email 驗證、付費、排行榜與多人 PK 不放入本輪完成定義；公開部署前再決定帳號恢復及 Email 驗證需求。

## 非功能需求與外部介面

- 一般測試零外部請求、零付費；provider secrets 只留後端。真實模型品質、延遲與每局費用：未決，步驟 1 spike 後設定門檻。
- 私有文件、歷史、任務與圖片按使用者或訪客 session 隔離。D2 已決：匿名 session 保存 7 天，登入後明確認領，過期清理、防重複與跨帳號認領均在步驟 4 驗收。
- 暫定本機 HTTP 可開發；公開環境必須 HTTPS。密碼採 Argon2id，參數至少依 [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)；登入使用 HttpOnly session cookie、CSRF 防護、登出撤銷、登入速率限制。登入 session 期限預設 24 小時（可推翻）；匿名 session 期限依 D2 為 7 天，不得把 session token 放 localStorage。此為安全預設，不代表既有實作。
- 模型輸出必須 schema 驗證；壞格式、超時、重複提交、資源不存在、跨帳號存取有明確失敗狀態。
- 文件大小、每位使用者文件數上限、chunk 數、題數、搜尋次數、生成逾時、圖片額度與 retry 上限：未決，由步驟 1b/D3 決定，必須在付費调用前落实。文件數上限是來源現行需求，不得因 provider 未選而漏移植；原 spec 預設 10 不代表新系統已選 10。
- 版本與工具鏈於步驟 2 依 [Next.js](https://nextjs.org/docs/app)、[FastAPI](https://fastapi.tiangolo.com/) 與本機可用工具核對，固定 lockfile，不在本文件猜版本。
- 資料庫／向量庫：Will 已選 PostgreSQL + pgvector，取代 MySQL + Chroma，增加資料庫整合練習。AI providers：D1 未決。選定後補官方 API、限制、價格查詢日期與 adapter contract，不把原 repo 品牌當必要約束。
- 資料層官方來源（2026-10-01）：[PostgreSQL tutorial](https://www.postgresql.org/docs/current/tutorial.html)、[pgvector](https://github.com/pgvector/pgvector)。精確檢索與 HNSW／IVFFlat 有不同的速度、召回與索引成本；步驟 6 先量測預計資料量，建立精確查詢基線，再決定索引。Embedding 模型、維度與距離 metric 必須一起固定；更換模型時不得混用舊向量，需版本化與重新 embedding。
- 學習用途不需要先驗證市場或付費意願；產品需求為 Will 自用學習。每步驗收包含可操作 demo、資料流解釋與一個故障案例。

## 缺陷與盤點限制

已在 source-review.md 記錄五項離線重現 B01–B05，D6 已決修正 B01/B05，其餘為建議處置；它們是 fake service 證據，不是完整 API／雲端驗證。現行 RAG spec 允許 fallback，Will 已在 D7 選擇 Web 版文件模式明確失敗；archive 搜尋數字與 code 差異另列，不能把 archived 文檔升為現行 SSOT。

## 新版功能驗證對照

後端完整 suite 103 passed；瀏覽器 `frontend/tests/quiz.spec.ts` 覆蓋全流程。真實模型品質依最新 D1／D3a 延後；本表的通過只指 fake／mock contract。

| 需求 | 新版實作 | 行為驗證 |
|---|---|---|
| R01–R04 | schemas.py、services.py、worker.py、page.tsx | test_learning.py／test_validation.py／test_contracts.py；三題型、提交後答案、正錯判分、報告／分享 browser flow |
| R05–R06 | auth.py、main.py、db.py、page.tsx | 登入、profile、7日 session、明確認領、XP 冪等、歷史；test_learning.py／test_review_regressions.py／browser flow |
| R07–R08 | worker.py、providers.py、cloud_provider.py | bounded tools、持久 jobs／lease fencing、retry、URL guard、可見降級；test_resources.py／test_cloud_provider.py／browser flow |
| R09–R10 | files.py、resources.py、db.py | 四格式7 parser fixtures、owner／document／model／dimension 隔離、embedding atomic failure、strict RAG；test_parsers.py／test_resources.py／browser upload-delete |
| R11 | resources.py、worker.py、main.py | 原子 quota、charge tombstone、私有圖片、crash GC；test_resources.py／test_review_regressions.py／browser image |
| R12 | compose.yaml、backend/Dockerfile、frontend/Dockerfile | 完整Web容器smoke通過；停止API負向非零、恢復後再次通過；upstream微信部署不沿用 |

Opt-in eval：eval_provider.py；4 eval gates、21 cloud contracts 與 fake9calls harness 已通過。7 mutants 均由行為 assertions 捕獲，不是 setup errors。
