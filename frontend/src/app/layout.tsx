import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "AI Learn · 學習練習", description: "用小練習確認理解" };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-Hant"><body>{children}</body></html>;
}
