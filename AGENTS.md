# AI Learn Web

這是完整重做 yu-ai-learn 的學習專案。前端採 Next.js + TypeScript，後端採 FastAPI，資料層採 PostgreSQL + pgvector；Email／密碼登入取代微信登入，保留訪客體驗。

- 開工先讀 `docs/plans/2026-10-01-full-rebuild.md` 與附件；依步驟的阻擋條件執行。
- `make check`、`make e2e`、`make inventory-check` 是本機驗收入口；API schema 修改後執行 `make schema`，一併 review generated TypeScript types。
- PostgreSQL 是持久資料來源；Alembic 管 schema，背景生成使用持久 jobs 與獨立 worker。測試建立獨立 database，不能 truncate 開發或其他專案資料。
- 產品業務與 AI orchestration 放在 FastAPI；前端不得持有 provider secrets。後端逐題判分，提交後才揭露答案與解析；正確率和經驗值由程式計算，不能接受 client 的 is_correct 或讓 AI 覆寫統計。
- 未決的範圍、資料模型、對外契約與費用選擇不得默認成已決。
- 測試使用 fake providers；真實外部服務驗證須單獨執行，不能由一般測試觸發。
- 決策紀錄（ADR）：`docs/adr/`。
