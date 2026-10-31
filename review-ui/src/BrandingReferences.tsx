import { useEffect, useRef, useState } from 'react';
import { API, LessonOptions } from './api';

type Reference = { id: string; name: string; duration: number; url: string };
export default function BrandingReferences({value, onChange}: {value: LessonOptions; onChange: (value: LessonOptions) => void}) {
  const [references, setReferences] = useState<Reference[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const current = useRef(value); current.current = value;
  const mounted = useRef(true);
  const ids = value.branding_reference_ids || [];
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let cancelled = false;
    Promise.all(ids.map(async id => {
      const response = await fetch(`${API}/branding/references/${id}`);
      if (!response.ok) throw new Error('Не удалось загрузить референсы. Попробуйте обновить страницу.');
      return await response.json() as Reference;
    })).then(data => { if (!cancelled) setReferences(data); }).catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [ids.join(',')]);
  async function upload(files: File[]) {
    if (files.length + ids.length > 3) { setError('Можно добавить до трёх референсов.'); return; }
    if (files.some(file => file.size > 100 * 1024 * 1024 || !/\.(mp4|mov|webm)$/i.test(file.name))) { setError('Выберите MP4, MOV или WebM, каждый до 100 МБ.'); return; }
    setBusy(true); setError('');
    try {
      for (const file of files) {
        const form = new FormData(); form.append('video', file);
        const response = await fetch(`${API}/branding/references`, {method:'POST', body:form});
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось загрузить референс.');
        if (!mounted.current) return;
        const updated = {...current.current, branding_reference_ids:[...(current.current.branding_reference_ids || []), data.id]};
        current.current = updated; onChange(updated);
      }
    } catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : 'Ошибка загрузки.'); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <div className="branding-references">
    <label>Видеореференсы заставок<input type="file" multiple accept=".mp4,.mov,.webm" disabled={busy || ids.length >= 3} onChange={e => { const files = Array.from(e.target.files || []); e.target.value = ''; if (files.length) void upload(files); }}/><span className="hint">До 3 видео · MP4, MOV, WebM · до 60 секунд и 100 МБ каждое.</span></label>
    {busy && <p role="status">Загружаем видео и подготавливаем предпросмотр… Дождитесь завершения перед сохранением настроек.</p>}
    {references.length > 0 && <div className="branding-reference-grid">{references.map(ref => <figure key={ref.id}><video controls preload="metadata" playsInline src={`${API}${ref.url}`} aria-label={`Референс: ${ref.name}`}/><figcaption>{ref.name} · {ref.duration} с</figcaption><button type="button" className="btn-secondary" disabled={busy} onClick={() => onChange({...value, branding_reference_ids:ids.filter(id => id !== ref.id)})}>Убрать из заставок</button></figure>)}</div>}
    <label>Что взять из референсов<textarea rows={2} maxLength={1500} placeholder="Например: фиолетовый фон, крупное название, плавное появление логотипа" value={value.branding_reference_notes || ''} onChange={e => onChange({...value, branding_reference_notes:e.target.value})}/></label>
    <details className="options-help"><summary>Как используются референсы</summary><p className="hint">Примеры сохраняются локально и привязываются к уроку при сохранении настроек. Сейчас ИИ учитывает палитру кадров и ваши пожелания; движения из примера пока не воспроизводятся. Исходные видео сохраняются для дальнейшей работы над заставками.</p></details>
    {error && <p className="alert alert-error" role="alert">{error}</p>}
  </div>;
}
