---
title: 同庫 relational／vector 與單一 FastAPI 權威
date: 2026-10-01
status: active
tags: [decision, postgresql, pgvector]
---

# 同庫 relational／vector 與單一 FastAPI 權威

## Context

原 yu-ai-learn 的 MySQL＋Chroma 與小程序只作行為參考；這是無既有正式部署或資料的獨立學習重做。

- external：沒有資料遷移或相容性窗口；本輪用途為本機學習，無公開部署承諾。
- inherited：Will 已選 Next.js／FastAPI 與資料庫整合練習；仍成立，因為這是本輪學習目標，不是舊框架限制。
- inherited：完整保留 R01–R12 對應 Web 行為；仍成立，因為「完整重做」是已確認範圍，不要求照搬 schema。

## Options Considered

**資料層**

- 基準／選用：PostgreSQL＋pgvector。資料與向量同庫，可共用 relational transaction；仍須設計 schema／檢索。[pgvector 官方文件](https://github.com/pgvector/pgvector)
- MySQL＋Chroma：貼近來源，但要協調兩種儲存的寫入、刪除與恢復。
- PostgreSQL＋獨立向量服務：可獨立擴展、調校，但增加服務管理與跨系統一致性。

**入口**

- 基準／選用：同源代理 FastAPI。瀏覽器單一入口，FastAPI 管認證與業務權威；需協調代理部署。[Next.js rewrites](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites)
- 跨域直連 FastAPI：部署更獨立，代價是 CORS／Cookie／環境配置。
- Next.js BFF：可聚合前端資料與認證；代價是新增 session、授權與契約層。

## Decision

- D-DB：選 PostgreSQL＋pgvector，而非保留 MySQL＋Chroma。
- D4：同源 /api/v1/* 保留原路徑代理 FastAPI，不新增 BFF 權威。
- D0 的 Next.js／FastAPI 是已決學習需求，本 ADR 不補造框架比較理由。

## Rationale

同庫符合 Will 明確要求的資料整合練習，且沒有正式資料逼迫保留雙庫。相較來源雙庫，chunks 與 ownership 可同次提交；代價是重設 schema。先以 exact cosine 建立小規模基線，未有負載證據就不引入獨立向量服務。外部 embedding 與本機檔案仍不能共用 DB transaction，須另行恢復。

同源代理降低本機登入與 Cookie 配置負擔；相較 BFF，單一 FastAPI 權威少一套授權與 schema 同步。代價是前後端入口需要共同部署配置，並非禁止未來跨域或 BFF。

## Expected Outcome

同庫 ownership、atomic chunks 與 model／dimension 隔離可由 integration tests 驗證；瀏覽器只消費同源生成契約。這不承諾真實檢索品質或多主機檔案一致性。

## Followup

目前無新增執行項；公開部署、獨立向量服務與檔案儲存重設，等 Revocation Triggers 觸發再排入範圍。

## Revocation Triggers

- 出現正式資料遷移需求，或實測 vector 容量／延遲需要獨立服務。
- 出現多 host、跨域獨立部署或具體 BFF 聚合需求。

## Review Notes

初版由兩份獨立草稿比較約束與拒絕理由；已決方向對草稿可見，意見一致不當作選型正確證據。

## Related

- 本 ADR 記錄 2026-10-01 Will 與 coding agent 的選擇。
- 來源固定 [yu-ai-learn d68cf0b](https://github.com/liyupi/yu-ai-learn/tree/d68cf0b77dd89cae1143abe8c300b239da79a6ea)。
- 無 Lessons Rule 新增；資料與 API 選型是本專案決策，不抽成跨專案硬規則。
