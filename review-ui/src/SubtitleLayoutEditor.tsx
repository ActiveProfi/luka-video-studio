import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  mediaUrl,
  runSubtitleFinalVoiceover,
  saveSubtitleEdit,
  type PipelineStage,
  type SubtitleCue,
  type SubtitleEditData,
  type SubtitleLayout,
} from "./api";
import {
  boxesEqual,
  expandKeyframesToCueLayouts,
  getBoxForCue,
  keyframesFromCueLayouts,
  type BoxLayout,
  type LayoutKeyframe,
  upsertLayoutKeyframe,
} from "./subtitleLayoutKeyframes";
import { findCueByKey, getCueKey } from "./subtitleCueKey";

type Props = {
  jobId: string;
  data: SubtitleEditData;
  embedded?: boolean;
  /** На шаге 4 финальную озвучку не показываем — она на шаге 6 */
  allowFinalVoiceover?: boolean;
  pipelineRunning?: boolean;
  onUpdate: (stages?: PipelineStage[]) => void;
  onInfo: (msg: string) => void;
  onError: (msg: string) => void;
};

type DragMode = "move" | "resize" | null;

const FONT_MIN = 8;
const FONT_MAX = 14;

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
  { hex: "#713f12", label: "Коричневый" },
  { hex: "#facc15", label: "Жёлтый" },
];

function normalizeHex(hex: string): string {
  const h = hex.trim().toLowerCase();
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
  const current = normalizeHex(value);
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

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function findCueAtTime(cues: SubtitleCue[], time: number): SubtitleCue | null {
  if (!cues.length) return null;
  // Только реальный интервал блока. В паузе между cues — null (НЕ первый блок).
  return cues.find((c) => time >= c.start && time < c.end) ?? null;
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatDuration(start: number, end: number): string {
  const sec = Math.max(1, Math.round(end - start));
  return `${sec} с`;
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  if (h.length !== 6) return `rgba(0, 0, 0, ${alpha})`;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function withStyleDefaults(layout: SubtitleLayout): SubtitleLayout {
  return {
    ...layout,
    font_size_px: Math.min(FONT_MAX, Math.max(FONT_MIN, layout.font_size_px || 12)),
    font_color: layout.font_color || "#ffffff",
    background_color: layout.background_color || "#000000",
    background_opacity: layout.background_opacity ?? 0.72,
    font_bold: Boolean(layout.font_bold),
    font_italic: Boolean(layout.font_italic),
  };
}

function extractBox(layout: SubtitleLayout): BoxLayout {
  return { x: layout.x, y: layout.y, width: layout.width, height: layout.height };
}

export function SubtitleLayoutEditor({
  jobId,
  data,
  embedded,
  allowFinalVoiceover = true,
  pipelineRunning = false,
  onUpdate,
  onInfo,
  onError,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const timelineListRef = useRef<HTMLDivElement>(null);
  const initialCuesRef = useRef<SubtitleCue[]>(data.cues);
  const initialKeyframesRef = useRef<LayoutKeyframe[]>(
    keyframesFromCueLayouts(data.layout.cue_layouts ?? {}, data.cues, extractBox(withStyleDefaults(data.layout))),
  );
  const defaultBoxRef = useRef<BoxLayout>(extractBox(withStyleDefaults(data.layout)));
  const layoutRef = useRef<SubtitleLayout>(withStyleDefaults(data.layout));
  const layoutKeyframesRef = useRef<LayoutKeyframe[]>(initialKeyframesRef.current);
  const cuesRef = useRef<SubtitleCue[]>(data.cues);
  const displayedCueKeyRef = useRef<string | null>(null);
  const textEditCueKeyRef = useRef<string | null>(null);
  const isComposingRef = useRef(false);

  const [layout, setLayout] = useState<SubtitleLayout>(() => withStyleDefaults(data.layout));
  const [cues, setCues] = useState<SubtitleCue[]>(data.cues);
  const [layoutKeyframes, setLayoutKeyframes] = useState<LayoutKeyframe[]>(() =>
    keyframesFromCueLayouts(data.layout.cue_layouts ?? {}, data.cues, extractBox(withStyleDefaults(data.layout))),
  );
  const [videoTime, setVideoTime] = useState(0);
  const [textEditCueKey, setTextEditCueKey] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [finalVoiceBusy, setFinalVoiceBusy] = useState(false);
  const [rememberedMsg, setRememberedMsg] = useState<string | null>(null);
  const [isFrameFullscreen, setIsFrameFullscreen] = useState(false);
  const sawFinalVoiceRunningRef = useRef(false);
  const dragRef = useRef<{
    mode: DragMode;
    startX: number;
    startY: number;
    origin: SubtitleLayout;
    moved: boolean;
  } | null>(null);

  layoutRef.current = layout;
  layoutKeyframesRef.current = layoutKeyframes;
  cuesRef.current = cues;
  textEditCueKeyRef.current = textEditCueKey;

  useEffect(() => {
    const normalized = withStyleDefaults(data.layout);
    const defaultBox = extractBox(normalized);
    const keyframes = keyframesFromCueLayouts(data.layout.cue_layouts ?? {}, data.cues, defaultBox);
    initialCuesRef.current = data.cues;
    initialKeyframesRef.current = keyframes;
    defaultBoxRef.current = defaultBox;
    layoutKeyframesRef.current = keyframes;
    setLayout(normalized);
    setCues(data.cues);
    setLayoutKeyframes(keyframes);
    setRememberedMsg(null);
    displayedCueKeyRef.current = null;
    setTextEditCueKey(null);
  }, [data.layout, data.cues, data.last_saved_at]);

  const videoActiveCue = useMemo(() => findCueAtTime(cues, videoTime), [cues, videoTime]);
  const displayCueKey = textEditCueKey ?? (videoActiveCue ? getCueKey(videoActiveCue) : null);
  const displayCue = useMemo(
    () => (displayCueKey ? findCueByKey(cues, displayCueKey) : null),
    [cues, displayCueKey],
  );

  const recordLayoutKeyframe = useCallback((cueKey: string, box: BoxLayout) => {
    setLayoutKeyframes((prev) => {
      const next = upsertLayoutKeyframe(prev, cueKey, box, defaultBoxRef.current);
      layoutKeyframesRef.current = next;
      return next;
    });
  }, []);

  const applyBoxForCue = useCallback(
    (cueKey: string) => {
      const box = getBoxForCue(cueKey, layoutKeyframesRef.current, cuesRef.current, defaultBoxRef.current);
      setLayout((prev) => ({ ...prev, ...box }));
    },
    [],
  );

  const syncVideoClock = useCallback(() => {
    const video = videoRef.current;
    if (!video || isComposingRef.current || textEditCueKeyRef.current) return;
    setVideoTime(video.currentTime);
  }, []);

  useEffect(() => {
    if (textEditCueKey || dragRef.current) return;
    const cue = findCueAtTime(cuesRef.current, videoTime);
    if (!cue) {
      // Пауза между блоками: не переключать на чужой cue, сбросить «активный» ключ.
      if (displayedCueKeyRef.current !== null) {
        displayedCueKeyRef.current = null;
      }
      return;
    }

    const cueKey = getCueKey(cue);
    const prevKey = displayedCueKeyRef.current;
    if (prevKey === cueKey) return;

    displayedCueKeyRef.current = cueKey;
    applyBoxForCue(cueKey);
  }, [videoTime, textEditCueKey, applyBoxForCue]);

  useEffect(() => {
    if (textEditCueKey) return;
    const cue = findCueAtTime(cuesRef.current, videoTime);
    const cueKey = cue ? getCueKey(cue) : null;
    if (!cueKey || !timelineListRef.current) return;
    const block = timelineListRef.current.querySelector<HTMLElement>(
      `[data-cue-key="${cueKey}"]`,
    );
    block?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [videoTime, textEditCueKey]);

  const handlePause = useCallback(() => {
    syncVideoClock();
    setRememberedMsg(
      "Изменения запомнены. Нажмите «Сохранить субтитры» в конце, чтобы записать в файл.",
    );
  }, [syncVideoClock]);

  const jumpToCueFromTimeline = useCallback((cue: SubtitleCue) => {
    const cueKey = getCueKey(cue);
    setTextEditCueKey(null);
    displayedCueKeyRef.current = cueKey;
    applyBoxForCue(cueKey);
    const video = videoRef.current;
    if (!video) return;
    if (!video.paused) video.pause();
    const t = cue.start + 0.02;
    video.currentTime = t;
    setVideoTime(t);
  }, [applyBoxForCue]);

  const addBlockAtPlayhead = useCallback(() => {
    const video = videoRef.current;
    if (video && !video.paused) video.pause();
    syncVideoClock();
    const time = videoRef.current?.currentTime ?? videoTime;
    const minPart = 0.4;
    setCues((prev) => {
      const idx = prev.findIndex((c) => time >= c.start && time < c.end);
      if (idx < 0) {
        onInfo("Сейчас нет блока под курсором — перемотайте чуть внутрь нужного фрагмента.");
        return prev;
      }
      const cue = prev[idx];
      if (time - cue.start < minPart || cue.end - time < minPart) {
        onInfo("Слишком близко к краю блока. Перемотайте внутрь или просто впишите текст в пустой блок.");
        return prev;
      }
      const left: SubtitleCue = {
        ...cue,
        end: Number(time.toFixed(3)),
      };
      const right: SubtitleCue = {
        cue_id: `cue_new_${Date.now()}`,
        source_segment_id: "",
        start: Number(time.toFixed(3)),
        end: cue.end,
        text: "",
      };
      const next = [...prev.slice(0, idx), left, right, ...prev.slice(idx + 1)];
      cuesRef.current = next;
      const rightKey = getCueKey(right);
      displayedCueKeyRef.current = rightKey;
      setTextEditCueKey(rightKey);
      onInfo("Добавлен пустой блок. Впишите текст (можно взять часть из соседнего).");
      return next;
    });
    setRememberedMsg("Не забудьте «Сохранить субтитры» в конце.");
  }, [videoTime, syncVideoClock, onInfo]);

  const handlePlay = useCallback(() => {
    setTextEditCueKey(null);
    setRememberedMsg(null);
  }, []);

  useEffect(() => {
    const syncFullscreenState = () => {
      const frame = frameRef.current;
      const doc = document as Document & { webkitFullscreenElement?: Element | null };
      const active =
        document.fullscreenElement === frame || doc.webkitFullscreenElement === frame;
      setIsFrameFullscreen(Boolean(active));
    };
    document.addEventListener("fullscreenchange", syncFullscreenState);
    document.addEventListener("webkitfullscreenchange", syncFullscreenState);
    return () => {
      document.removeEventListener("fullscreenchange", syncFullscreenState);
      document.removeEventListener("webkitfullscreenchange", syncFullscreenState);
    };
  }, []);

  const toggleFrameFullscreen = useCallback(async () => {
    const frame = frameRef.current as
      | (HTMLDivElement & { webkitRequestFullscreen?: () => Promise<void> | void })
      | null;
    if (!frame) return;
    const doc = document as Document & {
      webkitFullscreenElement?: Element | null;
      webkitExitFullscreen?: () => Promise<void> | void;
    };
    try {
      const active =
        document.fullscreenElement === frame || doc.webkitFullscreenElement === frame;
      if (active) {
        if (document.exitFullscreen) await document.exitFullscreen();
        else if (doc.webkitExitFullscreen) await doc.webkitExitFullscreen();
      } else if (frame.requestFullscreen) {
        await frame.requestFullscreen();
      } else if (frame.webkitRequestFullscreen) {
        await frame.webkitRequestFullscreen();
      } else {
        onError("Этот браузер не поддерживает полный экран для рамки с субтитрами.");
      }
    } catch {
      onError("Не удалось переключить полный экран.");
    }
  }, [onError]);

  const pointerMove = useCallback((event: PointerEvent) => {
    const drag = dragRef.current;
    const frame = frameRef.current;
    if (!drag || !frame) return;
    const rect = frame.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const dx = (event.clientX - drag.startX) / rect.width;
    const dy = (event.clientY - drag.startY) / rect.height;
    if (Math.abs(event.clientX - drag.startX) > 4 || Math.abs(event.clientY - drag.startY) > 4) {
      drag.moved = true;
    }
    const origin = drag.origin;
    if (drag.mode === "move") {
      setLayout({
        ...origin,
        x: clamp01(origin.x + dx),
        y: clamp01(origin.y + dy),
      });
    } else if (drag.mode === "resize") {
      setLayout({
        ...origin,
        width: clamp01(Math.max(0.12, origin.width + dx)),
        height: clamp01(Math.max(0.06, origin.height + dy)),
      });
    }
  }, []);

  const pointerUp = useCallback(() => {
    const drag = dragRef.current;
    if (drag?.moved && displayedCueKeyRef.current) {
      const cueKey = displayedCueKeyRef.current;
      const box = extractBox(layoutRef.current);
      recordLayoutKeyframe(cueKey, box);
      setRememberedMsg(
        "Положение запомнено с этого блока и дальше, пока не измените снова.",
      );
    }
    dragRef.current = null;
    window.removeEventListener("pointermove", pointerMove);
    window.removeEventListener("pointerup", pointerUp);
  }, [pointerMove, recordLayoutKeyframe]);

  const startDrag = (mode: DragMode) => (event: React.PointerEvent) => {
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = {
      mode,
      startX: event.clientX,
      startY: event.clientY,
      origin: layoutRef.current,
      moved: false,
    };
    window.addEventListener("pointermove", pointerMove);
    window.addEventListener("pointerup", pointerUp);
  };

  useEffect(() => {
    return () => {
      window.removeEventListener("pointermove", pointerMove);
      window.removeEventListener("pointerup", pointerUp);
    };
  }, [pointerMove, pointerUp]);

  const updateActiveCueText = (text: string) => {
    const cueKey = textEditCueKeyRef.current ?? displayedCueKeyRef.current;
    if (!cueKey) return;
    setCues((prev) => prev.map((c) => (getCueKey(c) === cueKey ? { ...c, text } : c)));
  };

  const handleTextFocus = () => {
    const cue = displayCue ?? videoActiveCue;
    if (cue) {
      const cueKey = getCueKey(cue);
      setTextEditCueKey(cueKey);
      displayedCueKeyRef.current = cueKey;
    }
    const video = videoRef.current;
    if (video && !video.paused) video.pause();
  };

  const handleTextBlur = () => {
    setTextEditCueKey(null);
  };

  const isCueEdited = useCallback(
    (cue: SubtitleCue): boolean => {
      const cueKey = getCueKey(cue);
      const orig = initialCuesRef.current.find((c) => getCueKey(c) === cueKey);
      if (!orig) return true; // новый блок (после «Добавить блок здесь»)
      const textChanged = orig.text !== cue.text;
      const initialBox = getBoxForCue(
        cueKey,
        initialKeyframesRef.current,
        cuesRef.current,
        defaultBoxRef.current,
      );
      const currentBox = getBoxForCue(
        cueKey,
        layoutKeyframes,
        cues,
        defaultBoxRef.current,
      );
      const layoutChanged = !boxesEqual(initialBox, currentBox);
      return textChanged || layoutChanged;
    },
    [layoutKeyframes, cues],
  );

  const pendingCount = useMemo(() => cues.filter(isCueEdited).length, [cues, isCueEdited]);

  const handleSave = async () => {
    setSaving(true);
    onError("");
    try {
      const cueLayouts = expandKeyframesToCueLayouts(
        layoutKeyframesRef.current,
        cues,
        defaultBoxRef.current,
      );
      const res = await saveSubtitleEdit(jobId, {
        layout: {
          ...withStyleDefaults(layoutRef.current),
          cue_layouts: cueLayouts,
        },
        cues,
      });
      initialCuesRef.current = cues;
      initialKeyframesRef.current = [...layoutKeyframesRef.current];
      setRememberedMsg(null);
      onInfo(res.message ?? "Субтитры сохранены. Озвучка не изменена.");
      onUpdate();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (!finalVoiceBusy) return;
    if (pipelineRunning) {
      sawFinalVoiceRunningRef.current = true;
      return;
    }
    if (sawFinalVoiceRunningRef.current) {
      sawFinalVoiceRunningRef.current = false;
      setFinalVoiceBusy(false);
      onUpdate();
    }
  }, [pipelineRunning, finalVoiceBusy, onUpdate]);

  const handleFinalVoiceover = async () => {
    if (pendingCount > 0) {
      onError("Сначала нажмите «Сохранить субтитры», затем запускайте 6.1.");
      return;
    }
    setFinalVoiceBusy(true);
    sawFinalVoiceRunningRef.current = false;
    onError("");
    try {
      const res = await runSubtitleFinalVoiceover(jobId);
      onInfo(res.message ?? "Подшаг 6.1 запущен: финальная озвучка по блокам субтитров.");
      onUpdate(res.stages);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка запуска финальной озвучки");
      setFinalVoiceBusy(false);
      sawFinalVoiceRunningRef.current = false;
    }
  };

  const bgRgba = hexToRgba(layout.background_color, layout.background_opacity);
  const textStyle = {
    fontSize: `${layout.font_size_px}px`,
    fontWeight: layout.font_bold ? 700 : 400,
    fontStyle: layout.font_italic ? ("italic" as const) : ("normal" as const),
    color: layout.font_color,
  };

  return (
    <div className={`subtitle-editor ${embedded ? "subtitle-editor-embedded" : ""}`}>
      {!embedded && <h3>Субтитры на видео</h3>}
      <p className="hint">
        <strong>Шаг 1.</strong> Нажмите Play — в рамке на видео появится текст текущей фразы.
        <strong> Шаг 2.</strong> Не нравится слово — Pause, поправьте текст прямо в рамке, снова Play.
        <strong> Шаг 3.</strong> Паузы закрыты пустыми блоками — кликните по ним в списке и впишите текст
        (можно перенести часть фразы из соседнего блока).
        <strong> Шаг 4.</strong> «Добавить блок здесь» — разрезать текущий блок в позиции Playhead.
        <strong> Шаг 5.</strong> «Полный экран» и в конце — «Сохранить субтитры». Озвучка не меняется.
      </p>

      {rememberedMsg && <p className="subtitle-remembered-msg">{rememberedMsg}</p>}

      <div className="subtitle-video-frame" ref={frameRef}>
        <video
          ref={videoRef}
          controls
          controlsList="nofullscreen"
          disablePictureInPicture
          src={mediaUrl(
            data.video_version
              ? `${data.video_url}${data.video_url.includes("?") ? "&" : "?"}v=${encodeURIComponent(data.video_version)}`
              : data.video_url,
          )}
          onTimeUpdate={syncVideoClock}
          onSeeked={syncVideoClock}
          onLoadedMetadata={syncVideoClock}
          onPause={handlePause}
          onPlay={handlePlay}
        />
        <button
          type="button"
          className="btn-secondary btn-fullscreen subtitle-fs-toggle"
          onClick={() => void toggleFrameFullscreen()}
          title="Полный экран рамки вместе с субтитрами"
        >
          {isFrameFullscreen ? "Выйти из полного экрана" : "Полный экран"}
        </button>
        <div
          className="subtitle-overlay-box selected"
          style={{
            left: `${layout.x * 100}%`,
            top: `${layout.y * 100}%`,
            width: `${layout.width * 100}%`,
            height: `${layout.height * 100}%`,
            background: bgRgba,
            textAlign: layout.alignment as "left" | "center" | "right",
          }}
        >
          <div
            className="subtitle-overlay-drag-bar"
            onPointerDown={startDrag("move")}
            title="Перетащить область (применится к этому и следующим блокам)"
          />
          <textarea
            className="subtitle-overlay-text subtitle-overlay-edit"
            style={textStyle}
            rows={3}
            placeholder={
              videoActiveCue
                ? "Запустите видео — здесь появится текст. На паузе можно править."
                : "Пауза между фразами — следующий блок появится по времени."
            }
            value={displayCue?.text ?? ""}
            readOnly={!displayCue}
            onFocus={handleTextFocus}
            onBlur={handleTextBlur}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={(e) => {
              isComposingRef.current = false;
              updateActiveCueText(e.currentTarget.value);
            }}
            onChange={(e) => updateActiveCueText(e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
          />
          <span
            className="subtitle-resize-handle"
            onPointerDown={startDrag("resize")}
            title="Изменить размер (применится к этому и следующим блокам)"
          />
        </div>
      </div>

      <div className="subtitle-timeline">
        <div className="subtitle-timeline-header">
          <span>Фрагменты субтитров по времени</span>
          <span className="subtitle-timeline-meta">
            {cues.length} блоков · {formatTime(data.total_duration_seconds)}
            {displayCue ? ` · сейчас ${formatTime(displayCue.start)}` : ""}
          </span>
        </div>
        <div className="subtitle-timeline-actions">
          <button type="button" className="btn-secondary" onClick={addBlockAtPlayhead}>
            Добавить блок здесь
          </button>
          <span className="hint" style={{ margin: 0 }}>
            Пустые блоки = бывшие паузы. Клик → вписать текст.
          </span>
        </div>
        <div className="subtitle-timeline-list" ref={timelineListRef} role="list">
          {cues.map((cue) => {
            const cueKey = getCueKey(cue);
            const active = displayCueKey === cueKey;
            const edited = isCueEdited(cue);
            const isEmpty = !cue.text.trim();
            const hasLayout = !boxesEqual(
              getBoxForCue(cueKey, layoutKeyframes, cues, defaultBoxRef.current),
              defaultBoxRef.current,
            );
            return (
              <button
                key={cueKey}
                type="button"
                role="listitem"
                data-cue-key={cueKey}
                className={`subtitle-timeline-block ${active ? "active" : ""} ${edited ? "edited" : ""} ${isEmpty ? "empty" : ""}`}
                onClick={() => jumpToCueFromTimeline(cue)}
                title="Перейти к этому моменту видео"
              >
                <span className="subtitle-timeline-time">
                  {formatTime(cue.start)} – {formatTime(cue.end)}
                  <span className="subtitle-timeline-duration">{formatDuration(cue.start, cue.end)}</span>
                </span>
                <span className="subtitle-timeline-text">
                  {isEmpty ? "Пустой блок — введите текст" : cue.text}
                </span>
                {edited && (
                  <span className="subtitle-timeline-badges">
                    {cue.text !== initialCuesRef.current.find((c) => getCueKey(c) === cueKey)?.text && (
                      <span className="subtitle-badge">текст</span>
                    )}
                    {hasLayout && <span className="subtitle-badge">область</span>}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <details className="subtitle-style-details">
        <summary>Оформление шрифта и фона (для всех субтитров)</summary>
        <div className="subtitle-style-panel">
          <div className="subtitle-style-grid">
            <label className="subtitle-style-field">
              <span>Размер шрифта</span>
              <select
                value={layout.font_size_px}
                onChange={(e) =>
                  setLayout((prev) => ({ ...prev, font_size_px: Number(e.target.value) }))
                }
              >
                {Array.from({ length: FONT_MAX - FONT_MIN + 1 }, (_, i) => FONT_MIN + i).map(
                  (size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ),
                )}
              </select>
            </label>

            <div className="subtitle-style-field">
              <span>Начертание</span>
              <div className="subtitle-font-style-row">
                <button
                  type="button"
                  className={`subtitle-font-toggle ${layout.font_bold ? "active" : ""}`}
                  title="Жирный"
                  onClick={() => setLayout((prev) => ({ ...prev, font_bold: !prev.font_bold }))}
                >
                  <strong>Ж</strong>
                </button>
                <button
                  type="button"
                  className={`subtitle-font-toggle ${layout.font_italic ? "active" : ""}`}
                  title="Курсив"
                  onClick={() =>
                    setLayout((prev) => ({ ...prev, font_italic: !prev.font_italic }))
                  }
                >
                  <em>К</em>
                </button>
              </div>
            </div>

            <div className="subtitle-style-field subtitle-color-field">
              <span>Цвет шрифта</span>
              <ColorSwatches
                value={layout.font_color}
                options={FONT_COLOR_OPTIONS}
                onChange={(hex) => setLayout((prev) => ({ ...prev, font_color: hex }))}
              />
            </div>

            <div className="subtitle-style-field subtitle-color-field">
              <span>Цвет фона</span>
              <ColorSwatches
                value={layout.background_color}
                options={BACKGROUND_COLOR_OPTIONS}
                onChange={(hex) => setLayout((prev) => ({ ...prev, background_color: hex }))}
              />
            </div>

            <label className="subtitle-style-field">
              <span>
                Прозрачность фона: <strong>{Math.round(layout.background_opacity * 100)}%</strong>
              </span>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round(layout.background_opacity * 100)}
                onChange={(e) =>
                  setLayout((prev) => ({
                    ...prev,
                    background_opacity: Number(e.target.value) / 100,
                  }))
                }
              />
            </label>
          </div>
        </div>
      </details>

      <div className="subtitle-editor-controls">
        <button className="btn-primary" type="button" disabled={saving || finalVoiceBusy} onClick={handleSave}>
          {saving
            ? "Сохранение…"
            : pendingCount > 0
              ? `Сохранить субтитры (${pendingCount} измен.)`
              : "Сохранить субтитры"}
        </button>
      </div>

      {allowFinalVoiceover && (
      <div className="subtitle-final-voiceover" style={{ marginTop: 16 }}>
        <strong>6.1 Финальная AI-озвучка</strong>
        <p className="hint" style={{ margin: "6px 0 10px" }}>
          Берёт текст из блоков субтитров (шаг 6) и озвучивает каждый блок в его тайминге.
          Затем обновляет видео новой озвучкой. Результат слушайте в видео выше (Play).
          Сначала сохраните субтитры.
        </p>
        <button
          type="button"
          className="btn-primary"
          disabled={saving || finalVoiceBusy || pendingCount > 0}
          onClick={() => void handleFinalVoiceover()}
        >
          {finalVoiceBusy ? "Озвучка идёт…" : "Запустить 6.1 — финальная озвучка"}
        </button>
        {data.final_voiceover?.ok && !finalVoiceBusy && (
          <div className="subtitle-final-voiceover-result" style={{ marginTop: 10 }}>
            <p style={{ margin: 0, color: "#166534" }}>
              Готово
              {data.final_voiceover.segment_count != null
                ? `: ${data.final_voiceover.segment_count} блоков озвучено. `
                : ". "}
              Нажмите Play на видео выше — там новая озвучка.
            </p>
            {(data.final_voiceover.warnings?.length ?? 0) > 0 && (
              <p className="hint" style={{ margin: "6px 0 0" }}>
                Внимание: у {data.final_voiceover.warnings!.length} блоков озвучка длиннее слота
                субтитров (речь может наезжать на следующий блок).
              </p>
            )}
          </div>
        )}
        {data.final_voiceover && data.final_voiceover.ok === false && !finalVoiceBusy && (
          <p style={{ marginTop: 10, color: "#b91c1c" }}>
            Ошибка 6.1: {data.final_voiceover.message || "не удалось создать озвучку"}
          </p>
        )}
      </div>
      )}
    </div>
  );
}
