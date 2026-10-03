---
title: 後端掌管學習權威與明確訪客認領
date: 2026-10-01
status: active
tags: [decision, auth, transaction]
---

# 後端掌管學習權威與明確訪客認領

## Context

來源前端持有答案並自行判分、報告信任 client 結果；Web 重做需重新決定身分、資料歸屬與結算權威。

- external：目前無公開部署承諾，不把正式認證營運需求算成本輪已完成。
- inherited：Email／密碼、訪客核心與私有文件／配圖限定登入由 Will 選定；仍成立，符合已確認 Web 範圍。
- inherited：七天匿名 session 與登入後明確認領仍成立，因為要練習資料銜接並限制匿名資料生命週期。

## Options Considered

**身分與紀錄**

- 基準／選用：opaque server session＋HttpOnly Cookie。可撤銷、輪替與逐資源授權；須保存、清理 session。[OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- 託管認證／OAuth：可降低部分認證營運負擔，託管認證也能支援 Email／密碼；代價是外部依賴與 identity 整合。
- 訪客僅存瀏覽器、不認領：實作較少，但無法保存本輪要求的 server-owned 可銜接紀錄。
- 登入自動合併／明確認領：前者少一步；後者讓資料移轉可見，代價是多一次操作。

**判分與報告**

- 基準／選用：server-owned quiz／submission。client 提交選項，後端判分及結算；新增提交 API 與冪等狀態。[OWASP Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- 前端持整包答案、自判後上傳：容易沿用來源，但提交前答案及統計依賴 client，不能提供相同權威邊界。

## Decision

- D2：匿名 session 保存七天；登入後以有效匿名與登入 session 明確認領，私有資源限定登入。
- D6：後端逐題判分，提交後才揭露答案；accuracy／XP 由程式計算，AI 只撰寫敘述。
- 認領移轉 owner，保留建立時 request namespace／key；同題提交與結算冪等。

## Rationale

選本機 server session，而非立即接託管認證，可在已選 stack 內練習到期、撤銷與所有權交易，減少本輪外部服務依賴；代價是自行維護密碼與 session，不代表公開服務時仍應維持同樣選型。

明確認領讓資料移轉由使用者發起，且必須證明兩種有效 session；相較只收 guest ID，可避免跨帳號轉移。建立時 namespace 與 owner 的生命週期不同，保留 namespace 而非改寫 key，才能維持原 client retry 識別；代價是 namespace 不作現存 principal FK。

後端判分增加持久 attempt 與提交往返，但移除 client／模型對統計事實的決定權。AI 敘述仍需 schema 驗證，不能覆寫已計算 accuracy／XP。不可變 quiz snapshot 適合本輪作答；需要跨 quiz 題庫編輯時才重評正規化。

## Expected Outcome

答案提前揭露、跨帳號存取、重複認領與重複 XP 可由正反例驗證；公開服務所需 Email 驗證／恢復不在本輪承諾。

## Followup

目前無新增執行項；公開服務或組織 identity 需求出現後才排認證營運與 provider 選擇。

## Revocation Triggers

- 對外開放、組織 identity 或第三方登入需求出現時重評認證。
- 跨 quiz 題庫編輯、版本關聯或分析需求出現時重評 snapshot 儲存；不因此移回 client 判分。

## Review Notes

兩份獨立草稿的託管認證與生命週期代價已納入；Email／密碼不被誤當託管認證不可行的理由。

## Related

- 本 ADR 記錄 2026-10-01 已決 D2／D6 與認領 namespace 設計。
- 無新增 Lessons Rule；不用單一選型建立跨專案硬規則。
