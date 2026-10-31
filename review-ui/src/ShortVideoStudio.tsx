import { useEffect, useState } from "react";
import { API } from "./api";

type Draft = {target_platform?:"shorts"|"reels"|"vk"|null;kind:"excerpt"|"promo";title:string;start:number;end:number;cta:string;narration:string[]};
type Export = {filename:string;platform:string;created_at:string;duration_seconds:number;revision?:number;preview_available?:boolean;playback_speed?:number};
type Clip = {created_at?:string;id:string;status:string;draft:Draft;exports:Record<string,Export>;error?:string;revision?:number};
type Studio = {items:Clip[];state:{status:string;error?:string};platforms:Record<string,string>};
const platforms = {shorts:"YouTube Shorts",reels:"Reels",vk:"VK Клипы"};
const profileDescriptions = {vk:"Рабочая ситуация, действие и результат. Умеренные акценты. Ориентир: 20–35 секунд.",reels:"Одна выразительная мысль и динамичные акценты. Ориентир: 12–25 секунд.",shorts:"Конкретный вопрос и небольшой законченный ответ. Ориентир: 20–40 секунд."};

async function request(url:string, method="GET", body?:unknown) {
  const response = await fetch(url,{method,headers:body ? {"Content-Type":"application/json"}:undefined,body:body ? JSON.stringify(body):undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось выполнить действие");
  return data;
}

function ShortCard({clip,jobId,platform,disabled,onRefresh,onError}:{clip:Clip;jobId:string;platform:string;disabled:boolean;onRefresh:()=>void;onError:(message:string)=>void}) {
  const [draft,setDraft] = useState(clip.draft);
  const [saving,setSaving] = useState(false);
  const [dirty,setDirty] = useState(false);
  const base = `${API}/jobs/${jobId}/shorts/${clip.id}`;
  const output = clip.exports[platform];
  const preview = output ? [platform,output] as const : undefined;
  const update = (changes:Partial<Draft>) => { setDraft({...draft,...changes}); setDirty(true); };
  async function render() {
    setSaving(true);
    onError("");
    try {
      if (dirty) { await request(base,"PUT",draft); setDirty(false); }
      await request(`${base}/render`,"POST",{platform});
      onRefresh();
    } catch(e) { onError(e instanceof Error ? e.message : "Ошибка сборки"); }
    finally { setSaving(false); }
  }
  return <article className="short-card">
    <div className="short-card-heading"><strong>{clip.draft.kind === "promo" ? "Рекламный ролик" : "Полезный фрагмент"}</strong><span>{Math.round(draft.start)}–{Math.round(draft.end)} с исходного урока</span></div>
    <h3>{platforms[platform as keyof typeof platforms]} · {clip.draft.title}</h3><p className="hint">{draft.target_platform ? `Профиль: ${platforms[draft.target_platform]}` : "Общий вариант: одинаковый монтаж для всех площадок"}</p>
    <p className="hint">{clip.draft.kind === "promo" ? (draft.target_platform ? `${profileDescriptions[draft.target_platform]} Темп 1,2×.` : "Общий рекламный тизер с анимацией и субтитрами. Темп 1,2×.") : "Сохранённая озвучка и аннотации выбранного фрагмента. Крупные субтитры для вертикального кадра."}</p>
    <div className="short-export-actions">
      {!output && <button className="btn-primary" disabled={disabled || saving} onClick={()=>void render()}>{saving ? "Запускаем сборку…" : disabled ? "Идёт обработка…" : output ? "Пересобрать ролик" : "Создать ролик"}</button>}
      {output && <ApprovalButton url={`${base}/approve`} platform={platform} version={output.created_at} disabled={disabled || saving || dirty}/> }
      {output && <a className="btn-download" href={`${base}/${platform}.mp4?download=true`}>Скачать видео</a>}
    </div>
    {!output && <p className="hint">{disabled ? "Дождитесь завершения текущей обработки. Статус обновится автоматически." : "Сценарий готов. Нажмите «Создать ролик» — соберём видео, озвучку, анимацию и субтитры."}</p>}
    <details><summary>Изменить текст и пересобрать этот ролик</summary>
      <fieldset disabled={disabled || saving}>
        <label>Заголовок<input maxLength={110} value={draft.title} onChange={e=>update({title:e.target.value})}/></label>
        <div className="short-times"><label>С секунды<input type="number" min={0} step={.1} value={draft.start} onChange={e=>update({start:Number(e.target.value)})}/></label><label>По секунду<input type="number" step={.1} value={draft.end} onChange={e=>update({end:Number(e.target.value)})}/></label></div>
        <label>Призыв к действию<input maxLength={150} value={draft.cta} onChange={e=>update({cta:e.target.value})}/></label>
        {draft.kind === "promo" && <label>Рекламная озвучка — одна фраза в строке<textarea rows={6} value={draft.narration.join("\n")} onChange={e=>update({narration:e.target.value.split("\n")})}/></label>}
        {output && <button className="btn-primary" onClick={()=>void render()}>Пересобрать этот ролик</button>}
      </fieldset>
    </details>
    {clip.error && <p className="alert alert-error">{clip.error.includes("TTS") ? "Сервис озвучки не выдал звук. Сценарий сохранён; сборку можно повторить без нового сценария." : clip.error}</p>}
    {preview && <div className="short-output">
      {clip.error && <p className="hint">Ниже показана предыдущая сохранённая версия. Новая сборка не завершена.</p>}
      <p>Предпросмотр{preview[1].playback_speed === 1.2 ? " · темп рекламы 1,2×" : ""}</p>
      <video key={preview[1].created_at} controls playsInline preload="metadata"
        poster={preview[1].preview_available ? `${base}/preview/poster.jpg?v=${encodeURIComponent(preview[1].created_at)}` : undefined}
        src={preview[1].preview_available ? `${base}/preview/preview.webm?v=${encodeURIComponent(preview[1].created_at)}` : `${base}/${preview[0]}.mp4?v=${encodeURIComponent(preview[1].created_at)}`}/>
    </div>}
    {output && <div className="short-export-meta">
      <p><strong>{output.platform}</strong> · {output.duration_seconds.toFixed(1)} с · 1080 × 1920</p>
      {(output.revision ?? 1) !== (clip.revision ?? 1) && <p className="hint">Предыдущая сохранённая версия. Для новых правок пересоберите этот экспорт.</p>}
    </div>}
  </article>;
}

export default function ShortVideoStudio({jobId,ready,pipelineRunning}:{jobId:string;ready:boolean;pipelineRunning:boolean}) {
  const [studio,setStudio] = useState<Studio>({items:[],state:{status:"idle"},platforms});
  const [error,setError] = useState("");
  const [connectionError,setConnectionError] = useState("");
  const [viewPlatform,setViewPlatform] = useState("shorts");
  const [viewKind,setViewKind] = useState("promo");
  const [composerOpen,setComposerOpen] = useState(false);
  const [cta,setCta] = useState("Полный разбор — в основном видео");
  const [sending,setSending] = useState(false);

  const base = `${API}/jobs/${jobId}/shorts`;
  async function refresh() {
    if (!jobId) return;
    try { setStudio(await request(base)); setConnectionError(""); } catch {setConnectionError("Нет связи с сервером. Повторяем подключение…");}
  }
  useEffect(()=>{
    if (!jobId) return;
    const saved = localStorage.getItem(`shortPlatform:${jobId}`);
    setViewPlatform(saved && saved in platforms ? saved : "shorts");
    setComposerOpen(false);
  },[jobId]);
  useEffect(()=>{
    if (!jobId) return;
    let stopped = false;
    async function load() {try {const data=await request(base); if(!stopped){setStudio(data);setConnectionError("");}} catch {if(!stopped)setConnectionError("Нет связи с сервером. Повторяем подключение…");}}
    void load(); const timer=window.setInterval(()=>void load(),3000);
    return ()=>{stopped=true;window.clearInterval(timer);};
  },[base]);
  const working = studio.state.status === "running" || sending;
  async function generate(render = false) {
    if (!jobId || !ready || pipelineRunning) return;
    setSending(true);setError("");

    try {await request(`${base}/plan`,"POST",{kind:viewKind,cta,target_platform:viewPlatform,render});setComposerOpen(false);await refresh();}
    catch(e){setError(e instanceof Error ? e.message : "Не удалось создать варианты");}
    finally{setSending(false);}
  }
  const clips = [...studio.items].sort((a,b)=>(a.created_at || "").localeCompare(b.created_at || "") || a.id.localeCompare(b.id));
  const globalError = error || connectionError || (clips.some(clip=>clip.error === studio.state.error) ? "" : studio.state.error);
  return <section className="short-studio">
    <h2>Ролики из этого видеоурока</h2>
    <p className="hint">Каждый ролик остаётся здесь: просмотрите, утвердите и скачайте его, затем создайте следующий.</p>
    {clips.flatMap(clip=>{
      const targets = clip.draft.target_platform ? [clip.draft.target_platform] : Object.keys(clip.exports).length ? Object.keys(clip.exports) : ["shorts"];
      return targets.map(platform=><ShortCard key={`${clip.id}-${platform}`} clip={clip} platform={platform} jobId={jobId} disabled={working || pipelineRunning} onRefresh={()=>void refresh()} onError={setError}/>);
    })}
    <div className="short-card">
      {clips.length>0 && !composerOpen ? <button className="btn-primary" disabled={working || pipelineRunning || !ready} onClick={()=>setComposerOpen(true)}>Создать следующий ролик</button> : <>
        <h3>{clips.length ? "Следующий ролик из этого урока" : "Создать первый ролик из этого урока"}</h3>
        <fieldset disabled={working || pipelineRunning || !ready}>
          <div className="short-selector-row">
            <label>Тип ролика<select value={viewKind} onChange={e=>setViewKind(e.target.value)}><option value="promo">Рекламный ролик</option><option value="excerpt">Полезный фрагмент</option></select></label>
            <label>Площадка<select value={viewPlatform} onChange={e=>{setViewPlatform(e.target.value);localStorage.setItem(`shortPlatform:${jobId}`,e.target.value);}}>{Object.entries(platforms).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
          </div>
          <label>Куда пригласить зрителя<input maxLength={150} value={cta} onChange={e=>setCta(e.target.value)}/></label>
          <button className="btn-primary" onClick={()=>void generate(true)}>{working ? "Создаём ролик…" : "Создать ролик"}</button>
        </fieldset>
        <p className="hint">ИИ подберёт отрывки этого урока и соберёт отдельное видео. Готовые ролики выше сохранятся.</p>
      </>}
      {!ready && <p className="hint">Сначала завершите сборку основного урока.</p>}
      {working && <p role="status" className="alert alert-info">Создаём ролик… Готовые видео доступны выше.</p>}
      {globalError && <p role="alert" className="alert alert-error">{globalError}</p>}
    </div>
    {!jobId && <div className="short-card"><h3>Просмотр и скачивание роликов</h3><p className="hint">Здесь появятся готовые версии для выбранных площадок. Каждый ролик можно будет утвердить и скачать, затем создать следующий.</p></div>}
    {jobId && <details className="short-secondary"><summary>О форматах</summary><a href={`${base}/guide`} target="_blank" rel="noreferrer">Сравнение форматов и рекомендации</a></details>}
  </section>;
}

export function ApprovalButton({url,platform,version,disabled=false}:{url:string;platform?:string;version?:string;disabled?:boolean}) {
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{let stopped=false;setApproved(false);void request(`${url}${platform ? `?platform=${platform}` : ""}`).then(data=>{if(!stopped)setApproved(data.approved);}).catch(()=>{});return()=>{stopped=true;};},[url,platform,version]);
  async function approve(){setBusy(true);setError("");try{await request(url,"POST",platform?{platform}:{});setApproved(true);}catch(e){setError(e instanceof Error?e.message:"Не удалось сохранить утверждение");}finally{setBusy(false);}}
  return <><button className="btn-primary" disabled={disabled || busy || approved} onClick={()=>void approve()}>{approved?"✓ Утверждено":busy?"Сохраняем…":"Утвердить результат"}</button>{error && <p role="alert" className="alert alert-error">{error}</p>}</>;
}
