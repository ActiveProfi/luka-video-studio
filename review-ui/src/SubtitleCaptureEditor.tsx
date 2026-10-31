import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CaptureBlock,
  CaptureData,
  PipelineStage,
  SubtitleLayout,
  finalizeCapture,
  mediaUrl,
  mergeCaptureBlock,
  rebuildCaptureBlocks,
  saveCaptureDraft,
  saveCaptureLayout,
  splitCaptureBlock,
} from "./api";

/** Этап 2: пользователь пишет субтитры прямо в кадре. Других окон правки текста нет. */

const MAX_LINE_CHARS = 42;
const MAX_LINES = 2;
const FONT_MIN = 8;
const FONT_MAX = 28;

const FONT_COLOR_OPTIONS = [
  { hex: "#ffffff", label: "Белый" },
  { hex: "#000000", label: "Чёрный" },
  { hex: "#ffff00", label: "Жёлтый" },
  { hex: "#ff0000", label: "Красный" },
  { hex: "#00ff00", label: "Зелёный" },
  { hex: "#00bfff", label: "Голубой" },
  { hex: "#ff8c00", label: "Оранжевый" },
  { hex: "#e879f9", label: "Розовый" },
];

const BACKGROUND_COLOR_OPTIONS = [
  { hex: "#000000", label: "Чёрный" },
  { hex: "#1e293b", label: "Тёмно-серый" },
  { hex: "#ffffff", label: "Белый" },
  { hex: "#1e3a8a", label: "Синий" },
  { hex: "#14532d", label: "Зелёный" },
  { hex: "#7f1d1d", label: "Бордовый" },
];

function normalizeHex(hex: string): string {
  const h = (hex || "").trim().toLowerCase();
  return h.startsWith("#") ? h : `#${h}`;
}

function ColorSwatches({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { hex: string; label: string }[];
  onChange: (hex: string) => void;
}) {
  const current = normalizeHex(value || "#ffffff");
  return (
    <div className="subtitle-color-swatches" role="listbox" aria-label="Выбор цвета">
      {options.map((opt) => {
        const hex = normalizeHex(opt.hex);
        const selected = current === hex;
        return (
          <button
            key={hex}
            type="button"
            role="option"
            aria-selected={selected}
            className={`subtitle-swatch ${selected ? "selected" : ""}`}
            style={{ backgroundColor: hex }}
            title={opt.label}
            onClick={() => onChange(hex)}
          >
            <span className="sr-only">{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function formatTime(seconds: number) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function hexToRgba(hex: string, opacity: number) {
  const clean = (hex || "#000000").replace("#", "");
  const value = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
  const r = parseInt(value.slice(0, 2), 16) || 0;
  const g = parseInt(value.slice(2, 4), 16) || 0;
  const b = parseInt(value.slice(4, 6), 16) || 0;
  const alpha = Math.min(1, Math.max(0, opacity ?? 0.72));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Сколько строк займёт текст в кадре — чтобы сразу видеть, помещается ли субтитр */
function estimateLines(text: string) {
  const parts = String(text || "").split("\n");
  let lines = 0;
  for (const part of parts) {
    lines += Math.max(1, Math.ceil(part.trim().length / MAX_LINE_CHARS));
  }
  return lines;
}

export default function SubtitleCaptureEditor({
  jobId,
  data,
  onUpdate,
  onInfo,
  onError,
  pipelineRunning = false,
}: {
  jobId: string;
  data: CaptureData;
  onUpdate: (stages?: PipelineStage[]) => void;
  onInfo: (message: string) => void;
  onError: (message: string) => void;
  pipelineRunning?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const saveTimer = useRef<number | null>(null);
  const dirtyRef = useRef(false);
  const layoutDirtyRef = useRef(false);
  const [layoutDirty, setLayoutDirty] = useState(false);

  const [blocks, setBlocks] = useState<CaptureBlock[]>(data.blocks);
  const [layout, setLayout] = useState<SubtitleLayout>(data.layout);
  const [currentTime, setCurrentTime] = useState(0);
  const [savedAt, setSavedAt] = useState<string | null>(data.saved_at ?? null);
  const [busy, setBusy] = useState(false);
  const [draftMsg, setDraftMsg] = useState("");

  useEffect(() => {
    // Не затираем то, что человек печатает прямо сейчас
    if (dirtyRef.current) return;
    setBlocks(data.blocks);
    if (!layoutDirtyRef.current) setLayout(data.layout);
    setSavedAt(data.saved_at ?? null);
  }, [data]);

  const videoSrc = useMemo(() => {
    const url = data.video_url;
    const versioned = data.video_version
      ? `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(data.video_version)}`
      : url;
    return mediaUrl(versioned);
  }, [data.video_url, data.video_version]);

  const activeBlock = useMemo(() => {
    const found = blocks.find((b) => currentTime >= b.start && currentTime < b.end);
    return found ?? blocks[0] ?? null;
  }, [blocks, currentTime]);

  const filledCount = blocks.filter((b) => b.subtitle.trim()).length;

  const queueDraftSave = useCallback(
    (next: CaptureBlock[]) => {
      dirtyRef.current = true;
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(async () => {
        try {
          await saveCaptureDraft(
            jobId,
            next.map((b) => ({ id: b.id, subtitle: b.subtitle })),
          );
          dirtyRef.current = false;
          setDraftMsg(`Черновик сохранён в ${new Date().toLocaleTimeString()}`);
        } catch {
          setDraftMsg("Черновик не сохранился — проверьте связь с сервером");
        }
      }, 1200);
    },
    [jobId],
  );

  useEffect(() => {
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, []);

  const updateActiveText = (text: string) => {
    if (!activeBlock) return;
    const next = blocks.map((b) => (b.id === activeBlock.id ? { ...b, subtitle: text } : b));
    setBlocks(next);
    setSavedAt(null);
    queueDraftSave(next);
  };

  const goToBlock = (block: CaptureBlock) => {
    const video = videoRef.current;
    if (video) {
      video.pause();
      video.currentTime = block.start + 0.05;
    }
    setCurrentTime(block.start + 0.05);
    // Клик по блоку = перемотка + фокус поля субтитра на видео
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const syncClock = () => {
    const video = videoRef.current;
    if (video) setCurrentTime(video.currentTime);
  };

  const applyCapture = (capture: CaptureData) => {
    setBlocks(capture.blocks);
    if (!layoutDirtyRef.current) setLayout(capture.layout);
    setSavedAt(capture.saved_at ?? null);
  };

  const handleSplit = async () => {
    if (!activeBlock) return;
    setBusy(true);
    try {
      const at = Math.max(activeBlock.start + 0.5, Math.min(currentTime, activeBlock.end - 0.5));
      const res = await splitCaptureBlock(jobId, activeBlock.id, Number(at.toFixed(2)));
      applyCapture(res.capture);
      onInfo(res.message ?? "Блок разделён");
    } catch (e) {
      onError(e instanceof Error ? e.message : "Не удалось разделить блок");
    } finally {
      setBusy(false);
    }
  };

  const handleMerge = async () => {
    if (!activeBlock) return;
    setBusy(true);
    try {
      const res = await mergeCaptureBlock(jobId, activeBlock.id);
      applyCapture(res.capture);
      onInfo(res.message ?? "Блоки склеены");
    } catch (e) {
      onError(e instanceof Error ? e.message : "Не удалось склеить блоки");
    } finally {
      setBusy(false);
    }
  };

  const handleRebuild = async () => {
    setBusy(true);
    try {
      const res = await rebuildCaptureBlocks(jobId);
      applyCapture(res.capture);
      onInfo(res.message ?? "Разбивка пересобрана");
    } catch (e) {
      onError(e instanceof Error ? e.message : "Не удалось пересобрать разбивку");
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    setBusy(true);
    try {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      const res = await finalizeCapture(
        jobId,
        blocks.map((b) => ({ id: b.id, subtitle: b.subtitle })),
      );
      applyCapture(res.capture);
      dirtyRef.current = false;
      setDraftMsg("");
      onInfo(res.message ?? "Субтитры сохранены");
      onUpdate(res.stages);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Не удалось сохранить субтитры");
    } finally {
      setBusy(false);
    }
  };

  const persistLayout = async (next: SubtitleLayout) => {
    setLayout(next);
    layoutDirtyRef.current = true;
    setLayoutDirty(true);
  };

  const handleLayoutSave = async () => {
    setBusy(true);
    try {
      const res = await saveCaptureLayout(jobId, layout);
      layoutDirtyRef.current = false;
      setLayoutDirty(false);
      onInfo(res.message ?? "Оформление сохранено");
      onUpdate(res.stages);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Не удалось сохранить оформление");
    } finally {
      setBusy(false);
    }
  };

  const lines = estimateLines(activeBlock?.subtitle ?? "");
  const tooLong = lines > MAX_LINES;

  return (
    <div className="capture-editor">
      <p className="hint">
        Проверьте сценарий, подготовленный из речи автора. Текст можно исправить прямо на кадре.
        Под видео — список тайм-блоков (не шкала времени): клик перематывает и открывает нужное поле.
      </p>

      {data.script_review && <details className="script-review">
        <summary>Результат ИИ-корректировки — {data.script_review.segments.filter(s => s.text !== s.original_text).length} изменённых фраз</summary>
        {data.script_review.segments.filter(s => s.text !== s.original_text).map(s =>
          <div key={s.segment_id} className="script-review-item">
            <p><strong>Распознано:</strong> {s.original_text}</p>
            <p><strong>После корректировки:</strong> {s.text}</p>
          </div>)}
      </details>}

      {data.script_review?.status === "needs_review" && <div className="script-review">
        <strong>Спорные фрагменты сценария</strong>
        {data.script_review.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
        {data.script_review.segments.filter(segment => segment.needs_review).map(segment => <div className="script-review-item" key={segment.segment_id}>
          <button type="button" className="btn-secondary" onClick={() => {
            const block = blocks.find(b => b.start >= segment.start - 0.01 && b.start < segment.end);
            if (block) goToBlock(block);
          }}>{formatTime(segment.start)} — проверить на кадре</button>
          <p><strong>Автор:</strong> {segment.original_text}</p>
          <p><strong>Сценарий:</strong> {segment.text}</p>
          {segment.suggested_text && segment.suggested_text !== segment.text &&
            <p><strong>Предложение ИИ для проверки:</strong> {segment.suggested_text}</p>}
          <p>{segment.review_reason}</p>
        </div>)}
        <p className="hint">После проверки нажмите «Сохранить»: озвучка продолжится автоматически.</p>
      </div>}

      <div className="subtitle-video-frame">
        <video
          ref={videoRef}
          controls
          controlsList="nofullscreen"
          disablePictureInPicture
          src={videoSrc}
          onTimeUpdate={syncClock}
          onSeeked={syncClock}
          onLoadedMetadata={syncClock}
        />
        <div
          className="subtitle-overlay-box selected"
          style={{
            left: `${layout.x * 100}%`,
            top: `${layout.y * 100}%`,
            width: `${layout.width * 100}%`,
            height: `${layout.height * 100}%`,
            background: hexToRgba(layout.background_color, layout.background_opacity),
            textAlign: layout.alignment as "left" | "center" | "right",
          }}
        >
          <textarea
            ref={textareaRef}
            className="subtitle-overlay-text subtitle-overlay-edit"
            style={{
              fontSize: `${layout.font_size_px}px`,
              fontWeight: layout.font_bold ? 700 : 400,
              fontStyle: layout.font_italic ? "italic" : "normal",
              color: layout.font_color,
            }}
            rows={2}
            placeholder="Впишите субтитр для этого блока"
            value={activeBlock?.subtitle ?? ""}
            readOnly={!activeBlock}
            onFocus={() => videoRef.current?.pause()}
            onChange={(e) => updateActiveText(e.target.value)}
          />
        </div>
      </div>

      <div className="capture-toolbar">
        <span className="capture-active">
          {activeBlock
            ? `Блок ${activeBlock.id} · ${formatTime(activeBlock.start)}–${formatTime(activeBlock.end)}`
            : "Блоков нет"}
        </span>
        <span className={tooLong ? "capture-warn" : "capture-ok"}>
          {tooLong
            ? `Длинно: ${lines} строки. Сократите текст или разделите блок.`
            : `Строк в кадре: ${lines} из ${MAX_LINES}`}
        </span>
        <button type="button" className="btn-secondary" disabled={busy} onClick={handleSplit}>
          Разделить блок здесь
        </button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={handleMerge}>
          Склеить со следующим
        </button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={handleRebuild}>
          Пересобрать разбивку
        </button>
      </div>

      <fieldset disabled={busy || pipelineRunning} className="subtitle-style-panel capture-style-panel" aria-label="Панель инструментов субтитров">
        <h4>Оформление субтитра</h4>
        <div className="subtitle-style-grid">
          <label className="subtitle-style-field">
            <span>Размер шрифта</span>
            <select
              value={layout.font_size_px}
              onChange={(e) =>
                void persistLayout({
                  ...layout,
                  font_size_px: Math.min(FONT_MAX, Math.max(FONT_MIN, Number(e.target.value))),
                })
              }
            >
              {Array.from({ length: FONT_MAX - FONT_MIN + 1 }, (_, i) => FONT_MIN + i).map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>

          <div className="subtitle-style-field">
            <span>Начертание</span>
            <div className="subtitle-font-style-row">
              <button
                type="button"
                className={`subtitle-font-toggle ${layout.font_bold ? "active" : ""}`}
                title="Жирный"
                onClick={() => void persistLayout({ ...layout, font_bold: !layout.font_bold })}
              >
                <strong>Ж</strong>
              </button>
              <button
                type="button"
                className={`subtitle-font-toggle ${layout.font_italic ? "active" : ""}`}
                title="Курсив"
                onClick={() => void persistLayout({ ...layout, font_italic: !layout.font_italic })}
              >
                <em>К</em>
              </button>
            </div>
          </div>

          <div className="subtitle-style-field subtitle-color-field">
            <span>Цвет текста</span>
            <ColorSwatches
              value={layout.font_color || "#ffffff"}
              options={FONT_COLOR_OPTIONS}
              onChange={(hex) => void persistLayout({ ...layout, font_color: hex })}
            />
          </div>

          <div className="subtitle-style-field subtitle-color-field">
            <span>Цвет фона</span>
            <ColorSwatches
              value={layout.background_color || "#000000"}
              options={BACKGROUND_COLOR_OPTIONS}
              onChange={(hex) => void persistLayout({ ...layout, background_color: hex })}
            />
          </div>

          <label className="subtitle-style-field">
            <span>
              Прозрачность фона:{" "}
              <strong>{Math.round((layout.background_opacity ?? 0.72) * 100)}%</strong>
            </span>
            <input
              type="range"
              min={0}
              max={100}
              value={Math.round((layout.background_opacity ?? 0.72) * 100)}
              onChange={(e) =>
                void persistLayout({ ...layout, background_opacity: Number(e.target.value) / 100 })
              }
            />
          </label>

          <label className="subtitle-style-field">
            <span>Высота от верха</span>
            <input
              type="range"
              min={0}
              max={95}
              value={Math.round(layout.y * 100)}
              onChange={(e) => void persistLayout({ ...layout, y: Number(e.target.value) / 100 })}
            />
          </label>

          <label className="subtitle-style-field">
            <span>Ширина поля</span>
            <input
              type="range"
              min={30}
              max={100}
              value={Math.round(layout.width * 100)}
              onChange={(e) => {
                const width = Number(e.target.value) / 100;
                void persistLayout({
                  ...layout,
                  width,
                  x: Math.min(layout.x, 1 - width),
                });
              }}
            />
          </label>
        </div>
      </fieldset>

      <div className="capture-blocks" ref={listRef}>
        <div className="capture-blocks-head">
          <span>
            Список блоков: {filledCount} из {blocks.length} с текстом
          </span>
          <span className="hint" style={{ margin: 0 }}>
            {draftMsg ||
              (savedAt
                ? "Сохранено — дальше озвучка идёт автоматически"
                : "Черновик сохраняется сам, пока вы печатаете")}
          </span>
        </div>
        <div className="capture-blocks-list" role="list">
          {blocks.map((block) => (
            <button
              key={block.id}
              type="button"
              role="listitem"
              className={`capture-block ${activeBlock?.id === block.id ? "active" : ""} ${
                block.subtitle.trim() ? "filled" : "empty"
              }`}
              onClick={() => goToBlock(block)}
            >
              <span className="capture-block-title">Блок {block.id}{block.needs_review ? " · проверьте" : ""}</span>
              <span className="capture-block-time">
                {formatTime(block.start)}–{formatTime(block.end)}
              </span>
              <span className="capture-block-text">
                {block.subtitle.trim() || "— текста нет —"}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="capture-actions">
        <button type="button" className="btn-primary" disabled={busy || pipelineRunning || !layoutDirty}
          onClick={() => void handleLayoutSave()}>
          Применить оформление к видео
        </button>
        <span className="hint">Цвет, размер и положение субтитров меняются без повторной озвучки и создания аннотаций.</span>
      </div>
      <div className="capture-actions">
        <button
          type="button"
          className="btn-primary"
          disabled={busy || pipelineRunning || filledCount === 0 || Boolean(savedAt)}
          onClick={handleSave}
        >
          {busy ? "Сохраняем…" : "Сохранить изменения текста"}
        </button>
        <span className="hint" style={{ margin: 0 }}>
          При изменении текста обновятся озвучка и связанные с ней аннотации. Для смены внешнего вида используйте «Применить оформление к видео».
        </span>
      </div>
    </div>
  );
}
