# 機制沿用盤點與本輪設計審查

本表是待驗證主張；完整功能尚未驗收，不代表完成。來源固定 d68cf0b77dd89cae1143abe8c300b239da79a6ea。

| 機制／來源做法 | 今天從零設計 | 本輪選擇與代價 | 核對／重新評估條件 |
|---|---|---|---|
| prefix＋截短 UUID，MySQL VARCHAR | PostgreSQL 原生 UUID，API string | UUIDv4 完整值、UUID(as_uuid=False)；不沿用 prefix。provider question ID 仍允許 opaque string；result_id 是多型 UUID、不設錯誤 FK | 0002 migration 在全新 PG17 跑通；有真實 ID migration 才重新評估轉換策略 |
| MySQL 題庫 JSON 與 client 判分 | server immutable quiz snapshot，relational ownership／submissions | 題庫 JSONB 經 schema 驗證、答案只在提交後揭露；Answer 唯一鍵，XP row lock。代價是分析題庫需 JSON 查詢 | 38 integration tests 已涵蓋 exact-set 判分與一次 XP；需要跨 quiz 題庫編輯／版本關聯時正規化 |
| 原微信登入／client local state | Email／密碼、opaque server session | Argon2id、hashed token、HttpOnly cookie、Origin gate、PG rate bucket，guest 7 天＋transaction claim。代價是自行維護登入生命週期 | 公開服務時重評 Email 驗證／恢復與營運邊界；未公開不引入 OAuth |
| create_task 與記憶體 task map | 單 PostgreSQL persistent queue 或 dedicated queue | pending／SKIP LOCKED、lease／heartbeat／version fence，明確 retry。代價為 polling、資料表清理 | 38 tests 有 expired worker fencing；lease recovery／expired finish與六workers claim regression通過；單worker容器重啟與smoke通過，超出單 worker需求才重評 queue |
| 外部呼叫 SDK async | adapter transport 負責 deadline，不以 thread 等待逾時替代取消 | Protocol monotonic deadline＋sanitized caller wrapper。fake 無網路；real adapter 尚未選，transport 不能忽略 deadline | deadline unit tests 已通過；real adapter 加入時必須測 connect/read/total timeout、不重試；非合作 local inference 用可終止 process |
| 獨立 Chroma、部分 chunk 寫入 | PostgreSQL vector 與 relational ownership 一次提交 | 外部 embedding 在 transaction 外，所有 chunks 單 transaction；model／dimension metadata、DB dimension CHECK、exact cosine | partial embedding failure integration 通過；目前 fake-hash-v1 64 維、0.15 僅 demo，真實模型 dataset／threshold 需另驗，不能拿 fake 分數作 production 決定 |
| 檔案與資料庫不同生命週期 | object storage 或本機檔案＋可恢復狀態 | 本機 generated UUID 路徑、delete tombstone/retry、image staging／replace、worker fencing。代價是 FS 與 DB 無法共用 commit | 正常失敗與刪除測試通過；actual image subprocess exit與advisory lock／GC regression通過，不以exception cleanup代替crash proof；公開／多 host 時重評 object storage |
| count-then-generate 配圖 quota | reservation＋charge ledger | User row lock，pending/running 預留，失敗释放；completed charged tombstone 防止刪圖補額度。自動圖片預留與 quiz 在同 transaction/savepoint，失敗可見但答題完成 | 38 tests 原子 quota／刪除保留 charge 已通過；auto reservation regression已通過 |
| SSE／client輪詢／同步入口混用 | 依 job 存續與部署需求選 polling/SSE | 统一202 job、同源 polling、localStorage僅保存jobID、explicit retry。代價是秒級延遲 | 不改生成入口；只有真實延遲／streaming UX 有需求才引入 SSE |

## Findings ledger

| ID | Finding | 處置 | 證據／尚需驗證 |
|---|---|---|---|
| D1 | UUID 仍用 String storage | 改，設計核對 fixed | native UUID model＋0002；PG17 fresh migrations／38 tests 通過，獨立 reviewer 核對 |
| D2 | daemon thread timeout 留下底層工作 | 改，設計核對 fixed | 移除 queue／thread semaphore adapter，deadline進Protocol；11 unit tests 通過，獨立 reviewer 核對，真實 transport 尚未選 |
| D3 | 缺作者盤點表 | 記，設計核對 fixed | 本表補各機制、依據、代價及重評條件；獨立 reviewer 核對 |

官方基準：[PostgreSQL UUID](https://www.postgresql.org/docs/current/datatype-uuid.html)、[SELECT locking](https://www.postgresql.org/docs/current/sql-select.html)、[Python futures cancellation](https://docs.python.org/3/library/concurrent.futures.html)、[pgvector](https://github.com/pgvector/pgvector)。

## Correctness review 累積 ledger

| ID | Finding | 處置 | 驗證 |
|---|---|---|---|
| C1 | owner 切換後 guest job 無權輪詢，畫面鎖住；只有 pending job 時無 claim 按鈕 | 改：owner epoch、清空 view、401/404 停止、claimable_jobs、explicit claim 後恢復 pending | Backend regression 通過；9 Chromium E2E 通過；最新 document／asset polling epoch 修正獨立核對無新 finding |
| C2 | upload／image DB commit 前中斷留下私有檔案，partial staging 未清理 | 改：transaction advisory lock、aged orphan reconciliation、staging/final exception cleanup | actual subprocess crash／in-flight transaction／retained completed files regression 通過；獨立 review 已核對 fixed |
| C3 | 非法 UUID path 進 DB 成 500 | 改：ResourceId 422 boundary，body 外鍵同樣驗證 | malformed paths regression 通過；獨立 review 已核對 fixed |
| C4 | guest/user 合法使用相同 request key，claim unique collision | 改：固定 creation namespace 與 owner 分離，0003 backfill／unique migration | same-key pending claim regression 通過；獨立 review 已核對 fixed |

Creation namespace 不隨認領改變；不是現存 principal FK。User transfer 只改 owner，不重寫 key。GC 僅掃描自己的 UUID 檔案、不跟 symlink，取得 advisory transaction lock 才檢查 DB／刪除；預設 24 小時，不以 exception cleanup 宣稱 crash atomicity。

## Cloud adapter follow-up ledger

| ID | Finding | 處置與證據 |
|---|---|---|
| C5 | asyncio DNS timeout 不停止 default executor，run 關閉會等待 | 改：HTTP／DNS 真實 transport 一次性子程序，stdin 傳輸、不含秘密 env／argv，deadline kill＋communicate／drain／reap。慢速 socket resolver regression 證明同步 extract 返回且子程序 PID 已消失；21 cloud tests 通過，獨立 review 已核對 fixed |
| C6 | 可配置 image model 與預設 URL／base64 契約不符 | 改：AI_IMAGE_RESPONSE_FORMAT default／b64_json；request payload regression通過，預設格式能力寫入 README；獨立 review 已核對 fixed |
| C7 | smoke register 錯把201當200 | 改：expected201；完整 API lifecycle 與 backend502 negative mock smoke，2 tests通過 |

C1 延遲 initial restore regression已過；最新9 Chromium E2E全過。D1–D3及namespace／GC／Compose設計 follow-up無新增 finding。7 mutations被既有行為測試擋下（含 worker fence），不是 setup error。

子程序 guard 修正：父程序設定明確非秘密 guard flag，child 啟動安裝 socket guard；actual HTTP／DNS child sentinel 返回 blocked exit7，未連外。大量 stdout deadline 測試核對 drain／reap。最新完整後端103 tests passed；cloud／eval 的獨立設計 follow-up 無新 finding。

## Container reaper regression

新增 C8：CMD-SHELL healthcheck timeout 留下 exit2 orphan，PostgreSQL PID1 reaps 後誤判 backend crash。改 db init:true＋直接CMD pg_isready，保留資料volume。Dedicated空白before／after control採相同health-timeout：before實際server process exit2／recovery，after PostgreSQL PID6正常；logs health-control-before-result.log／health-control-after-result.log。獨立設計 follow-up：NO NEW DESIGN FINDINGS；actual完整container smoke通過，停止API負向回傳health500、make exit2，證明不假通過。此為process reaper邊界修正，不修改PostgreSQL recovery規則。
