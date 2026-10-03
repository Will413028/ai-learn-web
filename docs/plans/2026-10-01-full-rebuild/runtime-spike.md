# 離線 runtime spike（2026-10-01）

目的：測試停止條件與任務契約，供 D5 決策；不建立產品服務。

## 可重跑驗收

在本附件目錄執行 `python3 runtime_spike.py`：13 tests 通過。分别執行 `python3 runtime_spike.py --mutation tool-budget`、`--mutation restart-recovery`、`--mutation fencing`：三者皆 exit 1，故意破壞停止上限、重啟轉態與過期 worker 寫入保護會被測試擋住。

所有 provider 都是 fake；socket 連線被禁止。SQLite 只建立在本附件內的臨時目錄並清除。

## 觀察與限制

| 情境 | 觀察 | 未證明的部分 |
|---|---|---|
| 固定 pipeline | 一次工具呼叫 | 真實搜尋品質與延遲 |
| bounded ReAct 模型 | 兩次工具、三輪 planner；工具上限與空轉輪數分別受限 | 真實模型遵循程度；正式上限尚未決定 |
| job | owner 隔離、idempotency、lease、heartbeat、過期 token 禁止提交 | PostgreSQL locking、真正併發 worker 與效能 |
| 重啟 | 子 process 在 provider 呼叫後、提交前受控退出；可標失敗或有限重試 | OS hard crash、部署與磁碟持久性 |
| 自動重試 | fake provider 可被呼叫兩次，最終只提交一份結果 | 外部服務 exactly-once；資料庫去重不等於供應商呼叫去重 |
| polling／重連 | 虛擬完成時間 13 秒、2 秒 polling 在 14 秒觀察到；可重讀 owner 的持久結果 | 實際 HTTP、SSE event replay、斷線取消與延遲 |

## D5 可選做法

搜尋編排：固定 pipeline 最可控；bounded ReAct 可練習自主工具選擇，但需工具與 planner 雙重停止上限。以完整重做與學習為目標，建議 bounded ReAct；fake 的呼叫數不能當品質結論。

任務入口：同步最容易，但工作依附請求；持久 job + polling 可分離工作與瀏覽器連線，建議先採這個。SSE 可後續接在同一 job 上，需事件重播與重連契約，不能取代持久 job。

中斷處理：標記失敗並讓使用者明確重試，操作與費用較可控，建議先採這個；有限自動重試較連續，但外部呼叫可能重複。Will 於 2026-10-01 確認按上述建議；實作契約以主計畫 D5 為準。

選定後在步驟 5 實作 PostgreSQL transaction、lease 與 fencing，並以 PostgreSQL integration tests 驗收。若任務被更早的功能使用，必須同步提前其基礎設施，不可拿本 spike 當產品實作。
