# Walking skeleton 驗收紀錄

## 實作

Next.js → 同源 `/api/v1/*` rewrite → FastAPI；fake provider 一題，答案在內部模型，首次提交由後端判分。匿名 cookie＋owner／CSRF 邊界、strict schema、生成 OpenAPI types、loading／錯誤重試已實作。根 Git main 已初始化，無 commit／remote。

## 已驗收

- `make check` exit 0：OpenAPI drift、ruff、mypy、19 pytest cases、ESLint、TypeScript、Python／Node／browser guards、proxy contract、production build。
- `make inventory-check` exit 0：14 routes／24 models 等固定來源盤點與兩個盤點 mutation，五項原缺陷離線 probes。
- `make mutation-check` exit 0：provider-schema、network-guard、csrf、answer-secrecy、proxy-destination、browser-network-guard 六項故意破壞皆被擋；僅用附件臨時副本，底層 sentinel／mock 防止真的對外連線。
- 獨立 design review：NO DESIGN FINDINGS。獨立 code review S1 connect_ex／S2 browser 假通過均修正，reviewer 唯讀核對已修，主 agent 重跑驗收。
- `make e2e` exit 0：5 Chromium E2E 全通過，正確／錯誤判分、生成錯誤後重試、匿名越權與外部阻擋。錯誤定位限定答題 region，避免匹配 Next.js 自带 route announcer。已視覺核對 quiz-result.png，未見文字截斷或操作遮擋。

## 工具鏈調整

TypeScript 7 與 openapi-typescript 的 compiler API 不相容；使用 peer 範圍內的 5.9.3。ESLint 10 與 eslint-plugin-react API 不相容；使用 9.x。實際版本固定在 manifests／lockfiles；`pnpm peers check` 無未滿足 peers。pnpm 明列 unrs-resolver 可執行 script。

## 限制與下一步

目前只單選示範題；記憶體紀錄重啟清除。步驟 3 擴三題型與復盤；4 接 PostgreSQL、Email／密碼、七天保存清理與認領；5 把同步入口統一為持久 job。真實 AI、搜尋、RAG、配圖尚未驗收，不能宣稱完整重做已完成。

原 prompt suite 4 passed 的既有基線保留；原完整 suite 缺依賴尚未跑，不屬這次新 skeleton 安裝清單。
