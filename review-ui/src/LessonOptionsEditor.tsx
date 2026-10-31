import { useEffect, useRef, useState } from "react";
import { API, LessonOptions, VoiceChoice } from "./api";
import BrandingReferences from './BrandingReferences';

export const defaultLessonOptions: LessonOptions = {
  provider: "yandex", voice: "alena", speed: 1, automatic: true,
  title: "", intro: true, outro: true, company_name: "", company_description: "",
  intro_seconds: 6, outro_seconds: 4,
  topic_context: "", terminology: "", content_profile: "general",
};

export function LessonOptionsEditor({ value, onChange, disabled = false, logoFile, onLogoChange, onLogoRemove }: {
  value: LessonOptions; onChange: (value: LessonOptions) => void; disabled?: boolean;
  logoFile?: File | null; onLogoChange?: (file: File | null) => void; onLogoRemove?: () => void;
}) {
  const [voices, setVoices] = useState<VoiceChoice[]>([]);
  const [vision, setVision] = useState<boolean | null>(null);
  const [sample, setSample] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sampleRef = useRef("");
  const logoInputRef = useRef<HTMLInputElement>(null);
  const [localLogo, setLocalLogo] = useState("");
  useEffect(() => {
    if (!logoFile) { setLocalLogo(""); return; }
    const url = URL.createObjectURL(logoFile); setLocalLogo(url);
    return () => URL.revokeObjectURL(url);
  }, [logoFile]);
  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/voices`).then(r => { if (!r.ok) throw new Error("Нет связи с сервером"); return r.json(); })
      .then(data => { if (!cancelled) { setVoices(data.voices); setVision(data.screen_analysis_available); } })
      .catch(() => { if (!cancelled) setError("Не удалось загрузить список голосов."); });
    return () => { cancelled = true; if (sampleRef.current) URL.revokeObjectURL(sampleRef.current); };
  }, []);
  useEffect(() => { setSample(""); if (sampleRef.current) URL.revokeObjectURL(sampleRef.current); sampleRef.current = ""; }, [value.provider, value.voice, value.speed]);
  async function preview() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API}/voices/preview`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(value) });
      if (!response.ok) { const data = await response.json(); throw new Error(data.detail || "Не удалось прослушать голос"); }
      if (sampleRef.current) URL.revokeObjectURL(sampleRef.current);
      sampleRef.current = URL.createObjectURL(await response.blob());
      setSample(sampleRef.current);
    } catch (err) { setError(err instanceof Error ? err.message : "Ошибка прослушивания"); }
    finally { setBusy(false); }
  }
  const selected = voices.find(v => v.provider === value.provider && v.id === value.voice);
  return <fieldset className="lesson-options" disabled={disabled || busy}>
    <legend className="visually-hidden">Настройки видео</legend>
    <div className="options-title-field">
      <label className="brand-wide">Название видео<textarea rows={1} maxLength={160} placeholder="Например: Как оформить презентацию или решить уравнение" value={value.title} onChange={e => onChange({...value, title: e.target.value})} /><span className="hint">Название для заставки. Пустое поле — ИИ предложит своё.</span></label>
    </div>
    <div className="options-sections">
      <details className="options-section">
        <summary><span><strong>Автор и оформление</strong><small>{value.company_name || "Добавьте фирменное оформление"}{(localLogo || value.logo_url) ? " · логотип добавлен" : ""}</small></span></summary>
        <div className="options-section-body lesson-options-grid">
      <label>Название канала или компании<input maxLength={100} placeholder="Актив Профи" value={value.company_name} onChange={e => onChange({...value, company_name: e.target.value})} /></label>
      <label>Логотип компании<input ref={logoInputRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={e => {
        const file = e.target.files?.[0] || null;
        if (file && file.size > 5 * 1024 * 1024) { setError("Размер логотипа — до 5 МБ"); e.target.value=""; return; }
        setError(""); onLogoChange?.(file);
      }} /><span className="hint">PNG, JPEG или WebP, до 5 МБ. Лучше PNG с прозрачным фоном.</span></label>
      {(localLogo || value.logo_url) && <div className="brand-logo-preview"><img src={localLogo || `${API}${value.logo_url}`} alt="Логотип компании" /><button type="button" className="btn-secondary" onClick={() => { onLogoChange?.(null); onLogoRemove?.(); if (logoInputRef.current) logoInputRef.current.value=""; }}>Убрать логотип</button></div>}
      <label className="brand-wide">О чём ваш канал или проект<textarea rows={2} maxLength={1200} placeholder="Кратко: сфера деятельности, услуги и для кого создано видео" value={value.company_description} onChange={e => onChange({...value, company_description: e.target.value})} /><span className="hint">Контекст для ИИ: поможет подобрать оформление и поясняющую строку. Полное описание не выводится на заставке.</span></label>
        </div>
      </details>
      <details className="options-section">
        <summary><span><strong>Голос и темп</strong><small>{selected?.label || value.voice} · {value.speed.toFixed(2)}× · {{yandex:"Yandex SpeechKit",openai:"OpenAI",elevenlabs:"ElevenLabs",edge:"Edge TTS"}[value.provider]}</small></span></summary>
        <div className="options-section-body">
          <div className="lesson-options-grid">
      <label>Сервис озвучки<select value={value.provider} onChange={e => onChange({...value, provider: e.target.value as LessonOptions["provider"], voice: e.target.value === "yandex" ? "alena" : e.target.value === "openai" ? "nova" : voices.find(v=>v.provider === e.target.value)?.id || ""})}>
        <option value="edge">Edge TTS — мужские голоса</option><option value="yandex">Yandex SpeechKit</option><option value="openai">OpenAI</option>
        <option value="elevenlabs" disabled={!voices.some(v=>v.provider === "elevenlabs" && v.available)}>ElevenLabs{!voices.some(v=>v.provider === "elevenlabs" && v.available) ? " — не настроен" : ""}</option>
      </select></label>
      <label>Голос<select value={value.voice} onChange={e => onChange({...value, voice: e.target.value})}>
        {voices.filter(v => v.provider === value.provider).map(v => <option key={v.id} value={v.id}>{v.label}{!v.available ? " — сервис не настроен" : ""}</option>)}
        {!voices.length && <option value={value.voice}>{value.voice}</option>}
      </select></label>
      <label>Темп речи: {value.speed.toFixed(2)}×<input type="range" min="0.8" max="1.2" step="0.05" value={value.speed} onChange={e => onChange({...value, speed: Number(e.target.value)})} /></label>
          </div>
    <div className="actions-row">
      <button type="button" className="btn-secondary" disabled={selected?.available === false} onClick={() => void preview()}>{busy ? "Подготовка образца…" : "Прослушать голос"}</button>
      {sample && <audio controls autoPlay src={sample} />}
    </div>
        </div>
      </details>
      <details className="options-section">
        <summary><span><strong>Заставки</strong><small>{value.intro ? `В начале · ${value.intro_seconds} с` : "Без начальной"} / {value.outro ? `в конце · ${value.outro_seconds} с` : "без финальной"}</small></span></summary>
        <div className="options-section-body">
          <div className="lesson-option-checks">
            <label><input type="checkbox" checked={value.intro} onChange={e => onChange({...value, intro: e.target.checked})} /> В начале видео</label>
            <label><input type="checkbox" checked={value.outro} onChange={e => onChange({...value, outro: e.target.checked})} /> В конце видео</label>
          </div>
          <div className="lesson-options-grid">
      <label>Начальная заставка, секунд<input type="number" min={4} max={15} step={1} value={value.intro_seconds} onChange={e => onChange({...value, intro_seconds: Number(e.target.value)})} /><span className="hint">Для длинного названия время чтения увеличится автоматически.</span></label>
      <label>Финальная заставка, секунд<input type="number" min={3} max={10} step={1} value={value.outro_seconds} onChange={e => onChange({...value, outro_seconds: Number(e.target.value)})} /></label>
          </div>
          <BrandingReferences value={value} onChange={onChange}/>
        </div>
      </details>
      <details className="options-section">
        <summary><span><strong>Контекст для ИИ</strong><small>{value.content_profile === "accounting" ? "1С и бухгалтерия" : "Любая тема"} · тема, термины и обработка</small></span></summary>
        <div className="options-section-body lesson-options-grid">
    <label>Тематика<select value={value.content_profile} onChange={e => onChange({...value, content_profile: e.target.value as "general" | "accounting"})}><option value="general">Любая тема</option><option value="accounting">1С и бухгалтерия</option></select></label>
    <label className="brand-wide">О чём видео<textarea rows={2} maxLength={2000} value={value.topic_context} placeholder="Тема, приложение и аудитория — помогут точнее распознать речь" onChange={e => onChange({...value, topic_context:e.target.value})} /></label>
    <label className="brand-wide">Термины и названия<input maxLength={1500} value={value.terminology} placeholder="Названия продуктов и специальные термины через запятую" onChange={e => onChange({...value, terminology:e.target.value})} /></label>
          <div className="lesson-option-checks brand-wide"><label><input type="checkbox" checked={value.automatic} onChange={e => onChange({...value, automatic: e.target.checked})} /> Автоматический конвейер с проверкой спорных мест</label></div>
        </div>
      </details>
    </div>
    {selected?.available === false && <p className="hint">Выбранный сервис озвучки пока не настроен на сервере.</p>}
    {vision === false && <p className="hint">Анализ кадров для автоматических рамок и стрелок пока недоступен. Аннотации потребуют проверки.</p>}
    {error && <p className="alert alert-error">{error}</p>}
  </fieldset>;
}

export function ExistingLessonOptions({ jobId, busy, onUpdate, onInfo, onError }: {
  jobId: string; busy: boolean; onUpdate: () => void; onInfo: (message: string) => void; onError: (message: string) => void;
}) {
  const [value, setValue] = useState<LessonOptions>(defaultLessonOptions);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [removeLogo, setRemoveLogo] = useState(false);
  const [cards, setCards] = useState<{intro_url: string; outro_url: string} | null>(null);
  useEffect(() => {
    let cancelled = false; setLoaded(false);
    fetch(`${API}/jobs/${jobId}/options`).then(r => { if (!r.ok) throw new Error("Не удалось загрузить настройки"); return r.json(); })
      .then(data => { if (!cancelled) { setValue({...defaultLessonOptions,...data}); setLoaded(true); if (data.intro_preview_url) setCards({intro_url:data.intro_preview_url,outro_url:data.outro_preview_url}); } })
      .catch(err => { if (!cancelled) onError(err.message); });
    return () => { cancelled = true; };
  }, [jobId]);
  async function save(start: boolean) {
    setSaving(true);
    try {
      let logoUrl = value.logo_url;
      if (logoFile || removeLogo) {
        const form = new FormData(); if (logoFile) form.append("logo",logoFile);
        const uploaded = await fetch(`${API}/jobs/${jobId}/logo`, {method:logoFile ? "POST" : "DELETE",body:logoFile ? form : undefined});
        const data = await uploaded.json(); if (!uploaded.ok) throw new Error(data.detail || "Не удалось сохранить логотип");
        logoUrl = data.logo_url; setLogoFile(null); setRemoveLogo(false);
      }
      const response = await fetch(`${API}/jobs/${jobId}/options`, {
        method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(value),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Не удалось сохранить настройки");
      setValue({...value, logo_url:logoUrl});
      const preview = await fetch(`${API}/jobs/${jobId}/branding/preview`, {method:"POST"});
      const design = await preview.json(); if (!preview.ok) throw new Error(design.detail || "Не удалось создать заставку");
      setCards(design);
      if (start) {
        const started = await fetch(`${API}/jobs/${jobId}/automatic`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...value, automatic:true})});
        const result = await started.json(); if (!started.ok) throw new Error(result.detail || "Не удалось запустить сборку");
        setValue({...value,logo_url:logoUrl,automatic:true});
      }
      onInfo(design.warning || (start ? "Заставка создана. Собираем видео с сохранённой озвучкой и аннотациями." : "Заставка создана. Нажмите «Сохранить и собрать видео», чтобы включить её в готовый ролик."));
      onUpdate();
    } catch (err) { onError(err instanceof Error ? err.message : "Ошибка настроек"); }
    finally { setSaving(false); }
  }
  return <section className="card brand-editor"><h2>Оформление текущего видео</h2><p className="options-intro">Название на заставке, фирменный стиль и голос — в одном месте.</p>
    <LessonOptionsEditor value={value} onChange={v => {setValue(v); setCards(null);}} disabled={busy || saving || !loaded}
      logoFile={logoFile} onLogoChange={file => {setLogoFile(file); if(file) setRemoveLogo(false); setCards(null);}}
      onLogoRemove={() => {setRemoveLogo(true); setValue({...value,logo_url:null}); setCards(null);}} />
    <div className="actions-row options-save-actions"><button className="btn-secondary" disabled={busy || saving || !loaded} onClick={() => void save(false)}>{saving ? "Создаём оформление…" : "Создать заставку с ИИ"}</button>
      <button className="btn-primary" disabled={busy || saving || !loaded} onClick={() => void save(true)}>Сохранить и собрать видео</button></div>
    {cards && <details className="options-preview"><summary>Посмотреть заставки</summary><div className="brand-card-previews"><figure><img src={`${API}${cards.intro_url}`} alt="Предпросмотр начальной заставки" /><figcaption>Начальная заставка</figcaption></figure><figure><img src={`${API}${cards.outro_url}`} alt="Предпросмотр финальной заставки" /><figcaption>Финальная заставка</figcaption></figure></div></details>}
  </section>;
}
