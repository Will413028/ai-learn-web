import type { components } from "./generated/api";

export type Schema = components["schemas"];
export type Quiz = Schema["QuizResponse"];
export type Answer = Schema["AnswerResponse"];
export type Generation = Schema["GenerateRequest"];
export type Job = Schema["JobResponse"];
export type Session = Schema["SessionResponse"];
export type Report = Schema["ReportResponse"];
export type Document = Schema["DocumentResponse"];
export type Asset = Schema["AssetResponse"];
export type History = Schema["HistoryResponse"];

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function api<T>(path: string, method = "GET", body?: unknown, key?: string): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;
  const response = await fetch(`/api/v1${path}`, {
    method, headers, credentials: "same-origin", cache: "no-store",
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(typeof data?.detail === "string" ? data.detail : "請求失敗，請檢查輸入後重試", response.status);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
