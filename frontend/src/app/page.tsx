"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import Image from "next/image";
import { api, ApiError, type Answer, type Asset, type Document, type Generation, type History, type Job, type Quiz, type Report, type Session, type Schema } from "../lib/api";

type Tab = "learn" | "history" | "documents" | "account";
const typeNames = { single: "單選", multiple: "多選", boolean: "判斷" };
const jobStorage = "ai-learn-active-job";
const guestJobStorage = "ai-learn-unclaimed-job";

export default function Home() {
  const [tab, setTab] = useState<Tab>("learn");
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [topic, setTopic] = useState("");
  const [source, setSource] = useState<Generation["source_mode"]>("text");
  const [url, setUrl] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [count, setCount] = useState(3);
  const [types, setTypes] = useState<NonNullable<Generation["question_types"]>>(["single", "multiple", "boolean"]);
  const [withImages, setWithImages] = useState(false);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [report, setReport] = useState<Report | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [history, setHistory] = useState<History | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [nickname, setNickname] = useState("");
  const [avatar, setAvatar] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const generationKey = useRef<string | null>(null);
  const quizStarted = useRef(0);
  const questionStarted = useRef<Record<string, number>>({});
  const ownerEpoch = useRef(0);
  const busyAction = useRef(false);

  function clearOwnerView() {
    ownerEpoch.current += 1;
    setJob(null); setQuiz(null); setReport(null); setAnswers({}); setSelected({});
    setAssets([]); setDocuments([]); setHistory(null); setWithImages(false);
    generationKey.current = null;
    localStorage.removeItem(jobStorage);
  }

  const refreshSession = useCallback(async () => {
    const epoch = ownerEpoch.current;
    const data = await api<Session>("/session");
    if (epoch !== ownerEpoch.current) return data;
    setSession(data);
    if (data.profile) { setNickname(data.profile.nickname); setAvatar(data.profile.avatar_url); }
    return data;
  }, []);

  const openQuiz = useCallback(async (id: string) => {
    const epoch = ownerEpoch.current;
    const data = await api<Quiz>(`/quiz/${encodeURIComponent(id)}`);
    if (epoch !== ownerEpoch.current) return;
    setQuiz(data); setReport(null); setAnswers({}); setSelected({}); setAssets([]); setTab("learn");
    quizStarted.current = Date.now();
    questionStarted.current = {};
    if (data.answered.length === data.questions.length) {
      const result = await api<Report>(`/quiz/${id}/report`, "POST", {});
      if (epoch !== ownerEpoch.current) return;
      setReport(result);
      setAnswers(Object.fromEntries(result.answers.map(answer => [answer.question_id, answer])));
    }
    if (data.image_ids.length) {
      const images = await Promise.all(data.image_ids.map(id => api<Asset>(`/assets/${id}`)));
      if (epoch === ownerEpoch.current) setAssets(images);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const epoch = ownerEpoch.current;
    api<Session>("/session").then(data => {
      if (!active || epoch !== ownerEpoch.current) return;
      setSession(data);
      if (data.profile) { setNickname(data.profile.nickname); setAvatar(data.profile.avatar_url); }
      const id = localStorage.getItem(jobStorage);
      if (id) return api<Job>(`/jobs/${encodeURIComponent(id)}`).then(async data => {
        if (!active || epoch !== ownerEpoch.current) return;
        setJob(data);
        if (data.status === "completed" && data.result_id) { localStorage.removeItem(jobStorage); await openQuiz(data.result_id); }
      });
    }).catch(err => {
      if (!active || epoch !== ownerEpoch.current) return;
      if (err instanceof ApiError && [401, 404].includes(err.status)) localStorage.removeItem(jobStorage);
      setError(err.message);
    });
    return () => { active = false; };
  }, [openQuiz]);

  useEffect(() => {
    if (!job || !["pending", "running"].includes(job.status)) return;
    let active = true;
    let polling = false;
    const epoch = ownerEpoch.current;
    const timer = setInterval(() => {
      if (polling) return;
      polling = true;
      api<Job>(`/jobs/${job.id}`).then(async data => {
        if (!active || epoch !== ownerEpoch.current) return;
        setJob(data);
        if (data.status === "completed" && data.result_id) {
          localStorage.removeItem(jobStorage);
          await openQuiz(data.result_id);
        }
      }).catch(err => {
        if (!active || epoch !== ownerEpoch.current) return;
        if (err instanceof ApiError && [401, 404].includes(err.status)) {
          setJob(null); localStorage.removeItem(jobStorage);
          setError("此任務已不可存取，請從學習紀錄或訪客認領接續");
        } else setError(`連線中斷，可重新整理以繼續查詢：${err.message}`);
      }).finally(() => { polling = false; });
    }, 1000);
    return () => { active = false; clearInterval(timer); };
  }, [job, openQuiz]);

  useEffect(() => {
    if (!session?.authenticated) return;
    if (tab === "documents" || source === "document") {
      let active = true;
      let polling = false;
      const epoch = ownerEpoch.current;
      const refresh = () => {
        if (polling) return;
        polling = true;
        return api<Document[]>("/documents").then(data => {
          if (active && epoch === ownerEpoch.current) setDocuments(data);
        }).catch(err => {
          if (active && epoch === ownerEpoch.current) setError(err.message);
        }).finally(() => { polling = false; });
      };
      void refresh();
      const timer = setInterval(refresh, 1500);
      return () => { active = false; clearInterval(timer); };
    }
  }, [tab, source, session?.authenticated]);

  useEffect(() => {
    if (!assets.some(asset => ["pending", "running"].includes(asset.status))) return;
    let active = true;
    let polling = false;
    const epoch = ownerEpoch.current;
    const timer = setInterval(() => {
      if (polling) return;
      polling = true;
      Promise.all(assets.map(asset => api<Asset>(`/assets/${asset.id}`))).then(data => {
        if (active && epoch === ownerEpoch.current) setAssets(data);
      }).catch(err => {
        if (active && epoch === ownerEpoch.current) setError(err.message);
      }).finally(() => { polling = false; });
    }, 1000);
    return () => { active = false; clearInterval(timer); };
  }, [assets]);

  async function act(action: () => Promise<void>) {
    if (busyAction.current) return;
    busyAction.current = true;
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : "操作失敗"); }
    finally { busyAction.current = false; setBusy(false); }
  }

  async function generate(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      generationKey.current ??= crypto.randomUUID();
      const payload: Generation = { topic, question_count: count, question_types: types, source_mode: source, include_images: withImages,
        ...(source === "url" ? { url } : {}), ...(source === "document" ? { document_id: documentId } : {}) };
      const data = await api<Job>("/quiz/generate", "POST", payload, generationKey.current);
      setJob(data); setQuiz(null); setReport(null); setAssets([]);
      localStorage.setItem(jobStorage, data.id);
      generationKey.current = null;
      if (data.status === "completed" && data.result_id) await openQuiz(data.result_id);
    });
  }

  async function answer(question: Quiz["questions"][number]) {
    if (!quiz) return;
    await act(async () => {
      const data = await api<Answer>(`/quiz/${quiz.id}/answers`, "POST", {
        question_id: question.id, selected_answers: selected[question.id] ?? [],
        duration_ms: Math.min(86400000, Date.now() - (questionStarted.current[question.id] ?? quizStarted.current)),
      });
      setAnswers(old => ({ ...old, [question.id]: data }));
      setQuiz(old => old ? { ...old, answered: [...new Set([...old.answered, question.id])] } : old);
      await refreshSession();
    });
  }

  async function loadHistory(page = 1) {
    setTab("history");
    await act(async () => setHistory(await api<History>(`/user/quizzes?page=${page}&page_size=10`)));
  }

  const locked = busy || !session || !!job && ["pending", "running"].includes(job.status);
  return <main>
    <header><Link className="brand" href="/">AI LEARN</Link><span className="badge">{session?.provider_mode === "fake" ? "示範模式・模擬 AI" : "AI 學習"}</span></header>
    <nav aria-label="主要導覽">
      <button className={tab === "learn" ? "active" : "secondary"} onClick={() => setTab("learn")}>開始學習</button>
      <button className={tab === "history" ? "active" : "secondary"} onClick={() => void loadHistory()}>學習紀錄</button>
      <button className={tab === "documents" ? "active" : "secondary"} onClick={() => setTab("documents")}>私有文件</button>
      <button className={tab === "account" ? "active" : "secondary"} onClick={() => setTab("account")}>{session?.profile?.nickname ?? "登入／註冊"}</button>
    </nav>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="result">{notice}</p>}
    {tab === "learn" && <>
      <section className="intro"><p className="eyebrow">從好奇開始，透過練習理解</p><h1>把想學的，<br/>變成真的學會。</h1><p>輸入主題或內容，選擇題型，逐題練習並取得學習復盤。</p></section>
      <section className="card"><form onSubmit={generate}>
        <label htmlFor="topic">學習主題或內容</label><textarea id="topic" value={topic} maxLength={12000} required placeholder="例如：Python 的 list 與 dictionary" onChange={e => { setTopic(e.target.value); generationKey.current = null; }}/>
        <div className="grid"><label>資料來源<select value={source} onChange={e => { setSource(e.target.value as Generation["source_mode"]); generationKey.current = null; }}>
          <option value="text">主題／文字</option><option value="search">搜尋補充</option><option value="url">公開網址</option><option value="document" disabled={!session?.authenticated}>私有文件（需登入）</option>
        </select></label><label>題數<input type="number" min={1} max={10} value={count} onChange={e => { setCount(Number(e.target.value)); generationKey.current = null; }}/></label></div>
        {source === "url" && <label>公開網址<input type="url" required value={url} onChange={e => { setUrl(e.target.value); generationKey.current = null; }}/></label>}
        {source === "document" && <label>指定文件<select value={documentId} required onChange={e => { setDocumentId(e.target.value); generationKey.current = null; }}><option value="">請選擇已完成處理的文件</option>{documents.filter(doc => doc.status === "ready").map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></label>}
        <fieldset><legend>題型</legend>{Object.entries(typeNames).map(([value, name]) => <label className="check" key={value}><input type="checkbox" checked={types.includes(value as typeof types[number])} onChange={e => {
          setTypes(old => e.target.checked ? [...old, value as typeof types[number]] : old.filter(type => type !== value)); generationKey.current = null;
        }}/>{name}</label>)}</fieldset>
        <label className="check"><input type="checkbox" checked={withImages} disabled={!session?.authenticated} onChange={e => { setWithImages(e.target.checked); generationKey.current = null; }}/>加入學習配圖（需登入）</label>
        <button disabled={locked || !types.length || !topic.trim()} type="submit">{locked ? "處理中…" : "產生練習"}</button>
      </form>
      {job && <section role="status" className="job"><p>任務狀態：{({ pending: "等待處理", running: "生成中", completed: "已完成", failed: "失敗" })[job.status]}</p>{job.error && <p>{job.error}</p>}{job.status === "failed" && <button disabled={busy} onClick={() => void act(async () => {
        const data = await api<Job>(`/jobs/${job.id}/retry`, "POST", {}, crypto.randomUUID()); setJob(data); localStorage.setItem(jobStorage, data.id);
      })}>明確重試</button>}</section>}
      </section>
      {quiz && <section className="card quiz"><h2>{quiz.topic}</h2>{quiz.source.degraded && <p role="status" className="warning">{quiz.source.message}</p>}
        {quiz.source.image_message && <p role="status" className="warning">{quiz.source.image_message}</p>}
        {quiz.source.citations.length > 0 && <details><summary>查看引用來源</summary><ul>{quiz.source.citations.map((citation, index) => <li key={index}>{citation.url ? <a href={citation.url} rel="noreferrer" target="_blank">{citation.title}</a> : citation.title}</li>)}</ul></details>}
        {quiz.questions.map((question, index) => {
          const result = answers[question.id]; const submitted = quiz.answered.includes(question.id);
          return <article className="question" key={question.id}><p className="eyebrow">第 {index + 1} 題・{typeNames[question.type]}</p><h3>{question.text}</h3>
            <fieldset disabled={submitted || busy}><legend>{question.type === "multiple" ? "選擇所有正確選項" : "選擇一個答案"}</legend>{question.options.map(option => <label className="option" key={option.id}>
              <input type={question.type === "multiple" ? "checkbox" : "radio"} name={question.id} checked={(selected[question.id] ?? result?.selected_answers ?? []).includes(option.id)} onChange={e => {
                questionStarted.current[question.id] ??= Date.now();
                setSelected(old => ({ ...old, [question.id]: question.type === "multiple" ? e.target.checked ? [...(old[question.id] ?? []), option.id] : (old[question.id] ?? []).filter(id => id !== option.id) : [option.id] }));
              }}/><span><strong>{option.id}</strong>{option.text}</span></label>)}</fieldset>
            {!submitted && <button disabled={busy || !selected[question.id]?.length} onClick={() => void answer(question)}>提交第 {index + 1} 題</button>}
            {result ? <div className="result"><h4>{result.is_correct ? "答對了" : "再理解一次"}</h4><p>正確答案：{result.correct_answers.join("、")}</p><p>{result.explanation}</p><p>知識點：{result.knowledge_points.join("、")}</p></div> : submitted && <p>此題已提交，完成全部題目後可查看完整復盤。</p>}
          </article>;
        })}
        {quiz.answered.length === quiz.questions.length && <button disabled={busy} onClick={() => void act(async () => { const data = await api<Report>(`/quiz/${quiz.id}/report`, "POST", {}); setReport(data); setAnswers(Object.fromEntries(data.answers.map(a => [a.question_id, a]))); })}>查看學習復盤</button>}
        {session?.authenticated && <section className="question"><h3>學習配圖</h3><button disabled={busy || assets.some(a => ["pending", "running"].includes(a.status))} onClick={() => void act(async () => {
          const asset = await api<Asset>("/assets", "POST", { quiz_id: quiz.id, prompt: quiz.topic.slice(0, 4000) }, crypto.randomUUID()); setAssets(old => [...old, asset]);
        })}>生成配圖</button>{assets.map(asset => <figure key={asset.id}>{asset.url && <Image unoptimized src={asset.url} alt={`${quiz.topic} 學習配圖`} width={640} height={360}/>}<figcaption>{asset.status === "completed" ? "配圖已完成" : asset.error ?? "配圖生成中"}</figcaption><button className="secondary" disabled={busy} onClick={() => void act(async () => { await api(`/assets/${asset.id}`, "DELETE", {}); setAssets(old => old.filter(a => a.id !== asset.id)); })}>刪除配圖</button></figure>)}</section>}
      </section>}
      {report && <section className="card report"><h2>學習復盤</h2><div className="stats"><p><strong>{report.accuracy}%</strong>正確率</p><p><strong>{report.correct}/{report.total}</strong>答對題數</p><p><strong>+{report.experience}</strong>經驗值</p><p><strong>{Math.round(report.duration_ms / 1000)} 秒</strong>答題時間</p></div><p>{report.narrative.summary}</p><h3>知識掌握</h3><dl>{Object.entries(report.narrative.mastery).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><h3>待加強</h3><ul>{report.narrative.weaknesses.map((text, i) => <li key={i}>{text}</li>)}</ul><h3>下一步建議</h3><ul>{report.narrative.suggestions.map((text, i) => <li key={i}>{text}</li>)}</ul><blockquote>{report.narrative.share_quote}</blockquote><button className="secondary" onClick={() => void act(async () => { await navigator.clipboard.writeText(`${quiz?.topic}\n${report.accuracy}%\n${report.narrative.share_quote}`); setNotice("復盤摘要已複製"); })}>複製分享摘要</button></section>}
    </>}
    {tab === "history" && <section className="card"><h1 className="section-title">學習紀錄</h1><p>{session?.authenticated ? `累積 ${session.profile?.experience ?? 0} XP・Level ${session.profile?.level ?? 1}` : "訪客紀錄保存 7 天，登入後可明確認領。"}</p>{history?.items.map(item => <article className="row" key={item.id}><div><h3>{item.topic}</h3><p>{item.answered}/{item.total} 題・{new Date(item.created_at).toLocaleString("zh-TW")}</p></div><button onClick={() => void act(() => openQuiz(item.id))}>繼續／復盤</button></article>)}{history?.total === 0 && <p>還沒有學習紀錄，先開始一份練習。</p>}{history && <div className="actions"><button disabled={busy || history.page <= 1} onClick={() => void loadHistory(history.page - 1)}>上一頁</button><span>第 {history.page} 頁，共 {history.total} 筆</span><button disabled={busy || history.page * history.page_size >= history.total} onClick={() => void loadHistory(history.page + 1)}>下一頁</button></div>}</section>}
    {tab === "documents" && <section className="card"><h1 className="section-title">私有文件</h1>{!session?.authenticated ? <p>請先登入，即可上傳 PDF、docx、Markdown 或 txt。</p> : <><p>文件處理完成後，可指定內容出題；找不到相關內容會明確失敗。</p><form onSubmit={e => { e.preventDefault(); const form = e.currentTarget; const data = new FormData(form); void act(async () => { await api<Document>("/documents", "POST", data); setDocuments(await api<Document[]>("/documents")); form.reset(); }); }}><label>上傳文件（最多 10 MB）<input type="file" name="file" accept=".pdf,.docx,.md,.txt" required/></label><button disabled={busy}>上傳並處理</button></form>{documents.map(doc => <article className="row" key={doc.id}><div><h3>{doc.filename}</h3><p>{doc.status}・{doc.chunk_count} 個區塊・{Math.ceil(doc.size / 1024)} KB</p>{doc.error && <p className="error">{doc.error}</p>}</div><div className="actions">{doc.status === "ready" && <button onClick={() => { setDocumentId(doc.id); setSource("document"); setTab("learn"); }}>用此文件出題</button>}{doc.status === "failed" && <button disabled={busy} onClick={() => void act(async () => { await api(`/documents/${doc.id}/retry`, "POST", {}); setDocuments(await api<Document[]>("/documents")); })}>重試處理</button>}<button className="secondary" disabled={busy} onClick={() => void act(async () => { await api(`/documents/${doc.id}`, "DELETE", {}); setDocuments(await api<Document[]>("/documents")); })}>刪除文件</button></div></article>)}</>}</section>}
    {tab === "account" && <section className="card"><h1 className="section-title">{session?.authenticated ? "個人資料" : "登入／註冊"}</h1>{session?.authenticated ? <>
      <p>{session.profile?.email}・Level {session.profile?.level}・{session.profile?.experience} XP</p><p>已完成 {session.profile?.completed_quizzes} 份測驗</p>
      <form onSubmit={e => { e.preventDefault(); void act(async () => { await api("/user/profile", "PUT", { nickname, avatar_url: avatar || null }); await refreshSession(); setNotice("個人資料已更新"); }); }}><label>暱稱<input required maxLength={80} value={nickname} onChange={e => setNickname(e.target.value)}/></label><label>頭像網址<input type="url" value={avatar} onChange={e => setAvatar(e.target.value)}/></label><button disabled={busy}>儲存資料</button></form>
      {!!(session.claimable_quizzes || session.claimable_jobs) && <div className="result"><p>此瀏覽器有 {session.claimable_quizzes} 份訪客紀錄與 {session.claimable_jobs ?? 0} 個訪客任務，可明確轉移到你的帳號。</p><button disabled={busy} onClick={() => void act(async () => { const result = await api<Schema["ClaimResponse"]>("/auth/claim", "POST", {}); await refreshSession(); const id = localStorage.getItem(guestJobStorage); localStorage.removeItem(guestJobStorage); if (id) { const restored = await api<Job>(`/jobs/${id}`); setJob(restored); if (["pending", "running"].includes(restored.status)) { localStorage.setItem(jobStorage, id); setTab("learn"); } } setNotice(`已認領 ${result.quizzes} 份紀錄，轉移 ${result.experience} XP`); })}>認領訪客紀錄</button></div>}
      <button className="secondary" disabled={busy} onClick={() => void act(async () => { await api("/auth/logout", "POST", {}); clearOwnerView(); await refreshSession(); })}>登出</button>
    </> : <><div className="actions"><button className={authMode === "login" ? "active" : "secondary"} onClick={() => setAuthMode("login")}>登入</button><button className={authMode === "register" ? "active" : "secondary"} onClick={() => setAuthMode("register")}>註冊</button></div><form onSubmit={e => { e.preventDefault(); void act(async () => { await api(`/auth/${authMode}`, "POST", { email, password, ...(authMode === "register" ? { nickname } : {}) }); setPassword(""); if (job && !session?.authenticated) localStorage.setItem(guestJobStorage, job.id); clearOwnerView(); await refreshSession(); setNotice("已登入，私有文件與配圖已開放"); }); }}><label>Email<input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)}/></label><label>密碼<input type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} minLength={authMode === "register" ? 12 : 1} maxLength={128} required value={password} onChange={e => setPassword(e.target.value)}/></label>{authMode === "register" && <label>暱稱<input required maxLength={80} value={nickname} onChange={e => setNickname(e.target.value)}/></label>}<button disabled={busy}>{authMode === "register" ? "建立帳號" : "登入帳號"}</button></form></>}</section>}
    <footer>答題結果與經驗值由後端計算。{session?.provider_mode === "fake" && "示範內容由 fake provider 產生，用於功能練習與驗證。"}</footer>
  </main>;
}
