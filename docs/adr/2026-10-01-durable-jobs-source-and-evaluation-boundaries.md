---
title: 持久任務、明確來源與獨立真實評測
date: 2026-10-01
status: active
tags: [decision, postgresql, ai]
---

# 持久任務、明確來源與獨立真實評測

## Context

來源 process 內 task 不能提供重啟後任務契約；外部生成不可交易且可能付費，指定文件亦不可悄悄改成常識來源。

- external：真實服務、預算、資料集與品質門檻未定，不能把 fake 分數當真實品質／成本。
- inherited：單 worker 本機部署仍成立，沒有容量證據需要額外 queue；不代表禁止未來多 worker。
- inherited：Will 已選明確 retry、文件 strict failure、搜尋可見降級；仍成立，維持呼叫控制與來源語意。
- inherited：最新完成範圍為 fake 功能、可配置 adapters／opt-in eval；仍成立，服務與費用已明確延後。

## Options Considered

**任務與連線**

- 基準／選用：小型部署 PostgreSQL 持久 queue＋polling。共用現有 DB，需 lease／fencing／清理。[PostgreSQL locking](https://www.postgresql.org/docs/current/sql-select.html)
- 獨立 queue／workflow engine：調度與擴展能力完整；多一套服務與恢復契約。[FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- 記憶體 task／同步 HTTP：適合薄原型，但不能維持重啟、斷線重讀與明確失敗。
- polling／SSE：前者可重讀、入口簡單；後者改善 streaming UX，增加連線恢復成本。
- 明確 retry／自動 retry：前者成本可見但多一步；後者較順暢，需提供外部冪等或承擔重複呼叫。

**來源與驗收**

- 基準／選用：指定文件 fail-closed、一般搜尋明示降級；犧牲文件可用性以保留來源語意。
- 文件失敗改用常識：流程不中斷，卻不能保證依指定文件出題。
- 基準／選用：fake／mock 契約＋獨立 opt-in 真實 eval；可重跑，真實品質需另測。
- 真實 provider 先行：較早取得品質證據，但先決定服務、預算，且一般驗收受外部波動影響。

## Decision

- D5：PostgreSQL jobs、獨立 worker、polling；ReAct 工具次數與 planner 輪數均有限制。
- D5：中斷轉失敗，使用者建立新 retry job；外部呼叫不在長 DB transaction 內。
- D7：文件不足明確失敗，不補常識／聯網；搜尋降級須在 response 與 UI 明示。
- D1／D3a：先完成可配置 text／embedding／base64 image、search／extract adapters 與 opt-in eval；不代替選供應商。

## Rationale

持久 queue 相較記憶體 task，可重讀建立後任務；相較獨立 queue，目前少一套服務。代價是 polling 延遲、lease／heartbeat、version fencing 與清理。claim 競爭與遲到提交是不同故障；每次結果寫入都核執行權。

明確 retry 保持中斷後成本可見，代價是使用者主動恢復。此設計不保證外部 exactly-once；即使本機 fencing 阻止寫入，先前 provider 可能已執行。

strict 文件失敗降低可用性，換取來源語意不被改寫；搜尋的通用能力才允許可見降級。相容協定不等於所有 provider 能力相同，image 回應格式與 embedding model／dimension 需顯式設定。

fake 契約驗產品行為，真實 eval 驗品質。相較一般測試直接連外，本輪可驗故障與授權邊界，但對真實準確性、相關性、費用與延遲仍無結論。

## Expected Outcome

重啟、expired worker、owner 隔離、重複建立與來源失敗均有可測行為；一般測試不連真實 AI。公開 fixtures 的 eval harness pass 不等於品質 pass。

## Followup

- D3b：選定服務、總預算、每局限制、評測資料集／門檻後執行 opt-in 品質評測；回流既有 project Pending，不新增重複項。

## Revocation Triggers

- 真實容量／workflow 複雜度超出本機單 worker，或有 streaming UX 需求時重評 queue／SSE。
- Provider 能力／deadline 不符協定時重評 adapter；文件來源語意只有需求改變才重決 fallback。

## Lessons

- R1：Rule: claim 排他與結果提交權分開核對；在同次 transaction 檢查當前 status／lease／version，不用 task cancellation 或一次 claim 代替遲到回寫防護。

## Review Notes

兩份獨立草稿的專用 queue、SSE、外部重複成本與實際能力差異均納入；不把並發 claim 測試當成已決多 worker 架構。

## Related

- 本 ADR 記錄 2026-10-01 D1／D3a／D5／D7。
- R1 另收錄為跨專案 PostgreSQL transaction／lease 知識。
