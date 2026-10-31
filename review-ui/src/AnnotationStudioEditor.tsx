import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  approveAnnotationEdit,
  artifactDownloadUrl,
  mediaUrl,
  saveAnnotationStudio,
  type AnnotationEditData,
  type AnnotationPlacementItem,
  type AnnotationStudioItem,
  type SubtitleCue,
  type SubtitleLayout,
} from "./api";

type Props = {
  jobId: string;
  data: AnnotationEditData;
  embedded?: boolean;
  onUpdate: () => void;
  onInfo: (msg: string) => void;
  onError: (msg: string) => void;
};

type Tool = "select" | "frame" | "arrow";
type ArrowDirection = "top" | "bottom" | "left" | "right";

type StudioAnn = {
  localId: string;
  annotation_id?: string;
  type: "highlight_rect" | "arrow";
  text: string;
  target_start: number;
  target_end: number;
  x: number;
  y: number;
  width: number;
  height: number;
  arrow_direction: ArrowDirection;
  arrow_length_ratio: number;
};

type BoxLayout = { x: number; y: number; width: number; height: number };

const DEFAULT_DURATION = 3;
const MIN_DURATION = 0.5;
const DURATION_STEP = 0.5;

function formatTime(sec: number): string {
  const m = Math.floor(Math.max(0, sec) / 60);
  const s = Math.floor(Math.max(0, sec) % 60);
  const ms = Math.floor((Math.max(0, sec) % 1) * 10);
  return `${m}:${s.toString().padStart(2, "0")}.${ms}`;
}

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

/** Сдвинуть блок целиком, длина не меняется. */
function slideRange(
  start: number,
  end: number,
  total: number,
): { target_start: number; target_end: number } {
  const len = Math.max(MIN_DURATION, end - start);
  let s = Math.max(0, Math.min(start, Math.max(0, total - len)));
  let e = s + len;
  if (e > total) {
    e = total;
    s = Math.max(0, e - len);
  }
  return { target_start: s, target_end: e };
}

/** Задать длительность от фиксированного начала (конец двигается). */
function durationFromStart(
  start: number,
  lengthSec: number,
  total: number,
): { target_start: number; target_end: number } {
  const s = Math.max(0, Math.min(start, Math.max(0, total - MIN_DURATION)));
  const len = Math.max(MIN_DURATION, lengthSec);
  let e = s + len;
  if (e > total) e = total;
  if (e - s < MIN_DURATION) {
    e = Math.min(total, s + MIN_DURATION);
  }
  return { target_start: s, target_end: e };
}

function directionFromDelta(dx: number, dy: number): ArrowDirection {
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? "right" : "left";
  return dy >= 0 ? "bottom" : "top";
}

function hexToRgba(hex: string, opacity: number): string {
  const raw = (hex || "#000000").replace("#", "");
  const full =
    raw.length === 3
      ? raw
          .split("")
          .map((ch) => ch + ch)
          .join("")
      : raw.padEnd(6, "0").slice(0, 6);
  const r = parseInt(full.slice(0, 2), 16) || 0;
  const g = parseInt(full.slice(2, 4), 16) || 0;
  const b = parseInt(full.slice(4, 6), 16) || 0;
  return `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, opacity))})`;
}

function defaultSubtitleLayout(): SubtitleLayout {
  return {
    x: 0.06,
    y: 0.82,
    width: 0.88,
    height: 0.12,
    font_size_px: 12,
    alignment: "center",
    font_color: "#ffffff",
    background_color: "#000000",
    background_opacity: 0.72,
    font_bold: false,
    font_italic: false,
    cue_layouts: {},
  };
}

function cueBox(cue: SubtitleCue, layout: SubtitleLayout): BoxLayout {
  const overrides = layout.cue_layouts || {};
  const override =
    overrides[cue.cue_id] ||
    (cue.source_segment_id ? overrides[cue.source_segment_id] : undefined);
  return {
    x: override?.x ?? layout.x,
    y: override?.y ?? layout.y,
    width: override?.width ?? layout.width,
    height: override?.height ?? layout.height,
  };
}

function fromServerItem(item: AnnotationPlacementItem): StudioAnn | null {
  if (item.skipped || !item.placement_confirmed || !item.anchor) return null;
  const type = item.suggested_type === "arrow" ? "arrow" : "highlight_rect";
  return {
    localId: item.annotation_id,
    annotation_id: item.annotation_id,
    type,
    text: item.text || "",
    target_start: item.target_start,
    target_end: Math.max(item.target_start + MIN_DURATION, item.target_end),
    x: item.anchor.x ?? 0.4,
    y: item.anchor.y ?? 0.4,
    width: Math.max(0.005, item.anchor.width ?? 0.18),
    height: Math.max(0.005, item.anchor.height ?? 0.1),
    arrow_direction: (item.arrow_direction as ArrowDirection) || "left",
    arrow_length_ratio: item.arrow_length_ratio || 0.08,
  };
}

function toStudioPayload(items: StudioAnn[]): AnnotationStudioItem[] {
  return items.map((item) => ({
    annotation_id: item.annotation_id,
    type: item.type,
    text: item.text,
    target_start: item.target_start,
    target_end: item.target_end,
    x: item.x,
    y: item.y,
    width: item.width,
    height: item.height,
    arrow_direction: item.arrow_direction,
    arrow_length_ratio: item.arrow_length_ratio,
    skipped: false,
  }));
}

export function AnnotationStudioEditor({ jobId, data, embedded, onUpdate, onInfo, onError }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [anns, setAnns] = useState<StudioAnn[]>(() =>
    data.items.map(fromServerItem).filter((x): x is StudioAnn => Boolean(x)),
  );
  const [tool, setTool] = useState<Tool>("select");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [pendingPlacement, setPendingPlacement] = useState<AnnotationPlacementItem | null>(null);
  const [skippedSuggestions, setSkippedSuggestions] = useState<string[]>([]);
  const [videoTime, setVideoTime] = useState(0);
  const [duration, setDuration] = useState(Math.max(1, data.video_duration_seconds || 1));
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [isShellFullscreen, setIsShellFullscreen] = useState(false);
  const [dragMode, setDragMode] = useState<
    "draw" | "move" | "resize" | "trim-start" | "trim-end" | "slide" | null
  >(null);
  const dragRef = useRef<{
    mode: "draw" | "move" | "resize" | "trim-start" | "trim-end" | "slide";
    localId: string | null;
    startX: number;
    startY: number;
    origin?: StudioAnn;
    originTime?: number;
    pointerId?: number;
  } | null>(null);
  const clipboardRef = useRef<StudioAnn | null>(null);
  const [clipboardReady, setClipboardReady] = useState(false);
  const lastDurationRef = useRef(DEFAULT_DURATION);

  // Видео уже с прожитыми субтитрами — не подменяем на «голое» edited_video
  const videoSrc = useMemo(() => {
    const base = data.studio_video_url || data.preview_video_url;
    const url = mediaUrl(base);
    return data.video_version
      ? `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(data.video_version)}`
      : url;
  }, [data.studio_video_url, data.preview_video_url, data.video_version]);
  const subtitlesBurned = Boolean(data.studio_subtitles_burned);
  const subtitleLayout = useMemo(
    () => ({ ...defaultSubtitleLayout(), ...(data.subtitle_layout || {}) }),
    [data.subtitle_layout],
  );
  const subtitleCues = data.subtitle_cues || [];
  const active = anns.find((a) => a.localId === activeId) ?? null;

  const activeSubtitle = useMemo(() => {
    return subtitleCues.find((cue) => cue.start <= videoTime && videoTime <= cue.end) ?? null;
  }, [subtitleCues, videoTime]);

  const subtitleBox = useMemo(() => {
    if (!activeSubtitle) return null;
    return cueBox(activeSubtitle, subtitleLayout);
  }, [activeSubtitle, subtitleLayout]);

  useEffect(() => {
    setAnns(data.items.map(fromServerItem).filter((x): x is StudioAnn => Boolean(x)));
  }, [jobId, data.last_saved_at, data.approved_at]);

  useEffect(() => {
    const syncFullscreenState = () => {
      const shell = shellRef.current;
      const doc = document as Document & { webkitFullscreenElement?: Element | null };
      const on =
        document.fullscreenElement === shell || doc.webkitFullscreenElement === shell;
      setIsShellFullscreen(Boolean(on));
    };
    document.addEventListener("fullscreenchange", syncFullscreenState);
    document.addEventListener("webkitfullscreenchange", syncFullscreenState);
    return () => {
      document.removeEventListener("fullscreenchange", syncFullscreenState);
      document.removeEventListener("webkitfullscreenchange", syncFullscreenState);
    };
  }, []);

  const toggleShellFullscreen = useCallback(async () => {
    const shell = shellRef.current as
      | (HTMLDivElement & { webkitRequestFullscreen?: () => Promise<void> | void })
      | null;
    if (!shell) return;
    const doc = document as Document & {
      webkitFullscreenElement?: Element | null;
      webkitExitFullscreen?: () => Promise<void> | void;
    };
    try {
      const activeFs =
        document.fullscreenElement === shell || doc.webkitFullscreenElement === shell;
      if (activeFs) {
        if (document.exitFullscreen) await document.exitFullscreen();
        else if (doc.webkitExitFullscreen) await doc.webkitExitFullscreen();
      } else if (shell.requestFullscreen) {
        await shell.requestFullscreen();
      } else if (shell.webkitRequestFullscreen) {
        await shell.webkitRequestFullscreen();
      }
    } catch {
      onError("Не удалось переключить полный экран");
    }
  }, [onError]);

  const visibleAnns = useMemo(
    () => anns.filter((a) => a.target_start <= videoTime && videoTime <= a.target_end),
    [anns, videoTime],
  );

  const relPoint = useCallback((clientX: number, clientY: number) => {
    const el = stageRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return {
      x: clamp01((clientX - rect.left) / rect.width),
      y: clamp01((clientY - rect.top) / rect.height),
    };
  }, []);

  const syncTime = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    setVideoTime(video.currentTime);
    if (video.duration && Number.isFinite(video.duration)) {
      setDuration(video.duration);
    }
  }, []);

  const pauseVideo = () => {
    const video = videoRef.current;
    if (video && !video.paused) video.pause();
  };

  const createAtTime = (type: "highlight_rect" | "arrow", pt: { x: number; y: number }) => {
    const start = videoTime;
    const clipLen = Math.max(MIN_DURATION, lastDurationRef.current || DEFAULT_DURATION);
    const range = durationFromStart(start, clipLen, duration);
    const localId = `local_${Date.now()}`;
    const item: StudioAnn = {
      localId,
      annotation_id: pendingPlacement?.annotation_id,
      type,
      text: pendingPlacement?.text || (type === "arrow" ? "Стрелка" : "Рамка"),
      target_start: pendingPlacement?.target_start ?? range.target_start,
      target_end: pendingPlacement?.target_end ?? range.target_end,
      x: type === "arrow" ? pt.x : clamp01(pt.x - 0.05),
      y: type === "arrow" ? pt.y : clamp01(pt.y - 0.03),
      width: 0.12,
      height: 0.08,
      arrow_direction: "left",
      arrow_length_ratio: 0.08,
    };
    setAnns((prev) => [...prev, item]);
    setActiveId(localId);
    setPendingPlacement(null);
    return item;
  };

  const onStagePointerDown = (e: React.PointerEvent) => {
    const pt = relPoint(e.clientX, e.clientY);
    if (!pt) return;
    pauseVideo();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);

    if (tool === "frame" || tool === "arrow") {
      const item = createAtTime(tool === "frame" ? "highlight_rect" : "arrow", pt);
      dragRef.current = {
        mode: "draw",
        localId: item.localId,
        startX: pt.x,
        startY: pt.y,
        origin: item,
        pointerId: e.pointerId,
      };
      setDragMode("draw");
      return;
    }

    for (let i = visibleAnns.length - 1; i >= 0; i -= 1) {
      const ann = visibleAnns[i];
      if (ann.type === "arrow") {
        const near =
          Math.hypot(pt.x - ann.x, pt.y - ann.y) < 0.045 ||
          (pt.x >= ann.x - 0.03 &&
            pt.x <= ann.x + 0.03 &&
            pt.y >= ann.y - 0.03 &&
            pt.y <= ann.y + 0.03);
        if (!near) continue;
        setActiveId(ann.localId);
        dragRef.current = {
          mode: "move",
          localId: ann.localId,
          startX: pt.x,
          startY: pt.y,
          origin: { ...ann },
        };
        setDragMode("move");
        return;
      }
      const inBox =
        pt.x >= ann.x &&
        pt.x <= ann.x + ann.width &&
        pt.y >= ann.y &&
        pt.y <= ann.y + ann.height;
      if (!inBox) continue;
      const nearCorner =
        Math.hypot(pt.x - (ann.x + ann.width), pt.y - (ann.y + ann.height)) < 0.035;
      setActiveId(ann.localId);
      dragRef.current = {
        mode: nearCorner ? "resize" : "move",
        localId: ann.localId,
        startX: pt.x,
        startY: pt.y,
        origin: { ...ann },
      };
      setDragMode(nearCorner ? "resize" : "move");
      return;
    }
    setActiveId(null);
  };

  const onStagePointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || !drag.localId) return;
    const pt = relPoint(e.clientX, e.clientY);
    const origin = drag.origin;
    if (!pt || !origin) return;

    setAnns((prev) =>
      prev.map((ann) => {
        if (ann.localId !== drag.localId) return ann;
        if (drag.mode === "draw" && ann.type === "highlight_rect") {
          const x = Math.min(drag.startX, pt.x);
          const y = Math.min(drag.startY, pt.y);
          return {
            ...ann,
            x,
            y,
            width: Math.max(0.04, Math.abs(pt.x - drag.startX)),
            height: Math.max(0.04, Math.abs(pt.y - drag.startY)),
          };
        }
        if (drag.mode === "draw" && ann.type === "arrow") {
          const dx = pt.x - drag.startX;
          const dy = pt.y - drag.startY;
          const len = Math.min(0.25, Math.max(0.04, Math.hypot(dx, dy)));
          return {
            ...ann,
            x: pt.x,
            y: pt.y,
            arrow_direction: directionFromDelta(dx, dy),
            arrow_length_ratio: len,
          };
        }
        if (drag.mode === "move") {
          const dx = pt.x - drag.startX;
          const dy = pt.y - drag.startY;
          return {
            ...ann,
            x: clamp01(origin.x + dx),
            y: clamp01(origin.y + dy),
          };
        }
        if (drag.mode === "resize" && ann.type === "highlight_rect") {
          return {
            ...ann,
            width: Math.max(0.04, clamp01(origin.width + (pt.x - drag.startX))),
            height: Math.max(0.04, clamp01(origin.height + (pt.y - drag.startY))),
          };
        }
        return ann;
      }),
    );
  };

  const onStagePointerUp = () => {
    dragRef.current = null;
    setDragMode(null);
    if (tool !== "select") setTool("select");
  };

  const seekRatio = (clientX: number) => {
    const track = trackRef.current;
    if (!track || duration <= 0) return 0;
    const rect = track.getBoundingClientRect();
    return clamp01((clientX - rect.left) / rect.width) * duration;
  };

  const endTimelineDrag = useCallback(() => {
    const drag = dragRef.current;
    if (drag?.localId && (drag.mode === "trim-start" || drag.mode === "trim-end")) {
      setAnns((prev) => {
        const ann = prev.find((a) => a.localId === drag.localId);
        if (ann) {
          lastDurationRef.current = Math.max(MIN_DURATION, ann.target_end - ann.target_start);
        }
        return prev;
      });
    }
    dragRef.current = null;
    setDragMode(null);
  }, []);

  const onTimelineDragMove = useCallback(
    (clientX: number) => {
      const drag = dragRef.current;
      if (!drag || !drag.origin || !drag.localId) return;
      if (drag.mode !== "trim-start" && drag.mode !== "trim-end" && drag.mode !== "slide") return;
      const track = trackRef.current;
      if (!track || duration <= 0) return;
      const rect = track.getBoundingClientRect();
      const t = clamp01((clientX - rect.left) / rect.width) * duration;
      setAnns((prev) =>
        prev.map((ann) => {
          if (ann.localId !== drag.localId || !drag.origin) return ann;
          if (drag.mode === "trim-start") {
            const start = Math.min(Math.max(0, t), drag.origin.target_end - MIN_DURATION);
            return { ...ann, target_start: start, target_end: drag.origin.target_end };
          }
          if (drag.mode === "trim-end") {
            const end = Math.max(Math.min(duration, t), drag.origin.target_start + MIN_DURATION);
            return { ...ann, target_start: drag.origin.target_start, target_end: end };
          }
          const len = drag.origin.target_end - drag.origin.target_start;
          const delta = t - (drag.originTime ?? drag.origin.target_start);
          return {
            ...ann,
            ...slideRange(
              drag.origin.target_start + delta,
              drag.origin.target_start + delta + len,
              duration,
            ),
          };
        }),
      );
    },
    [duration],
  );

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      if (drag.mode !== "trim-start" && drag.mode !== "trim-end" && drag.mode !== "slide") return;
      onTimelineDragMove(e.clientX);
    };
    const onUp = () => {
      const drag = dragRef.current;
      if (!drag) return;
      if (drag.mode !== "trim-start" && drag.mode !== "trim-end" && drag.mode !== "slide") return;
      endTimelineDrag();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [endTimelineDrag, onTimelineDragMove]);

  const onPlayheadPointerDown = (e: React.PointerEvent) => {
    if (dragRef.current) return;
    const t = seekRatio(e.clientX);
    const video = videoRef.current;
    if (video) {
      video.currentTime = t;
      video.pause();
    }
    setVideoTime(t);
  };

  const beginTimelineEdit =
    (localId: string, mode: "trim-start" | "trim-end" | "slide") => (e: React.PointerEvent) => {
      e.stopPropagation();
      e.preventDefault();
      pauseVideo();
      const ann = anns.find((a) => a.localId === localId);
      if (!ann) return;
      dragRef.current = {
        mode,
        localId,
        startX: e.clientX,
        startY: e.clientY,
        origin: { ...ann },
        originTime: seekRatio(e.clientX),
      };
      setDragMode(mode);
      setActiveId(localId);
    };

  const deleteActive = () => {
    if (!activeId) return;
    setAnns((prev) => prev.filter((a) => a.localId !== activeId));
    setActiveId(null);
  };

  const setActiveDurationSeconds = (lengthSec: number) => {
    if (!activeId) return;
    const len = Math.max(MIN_DURATION, Number(lengthSec) || MIN_DURATION);
    lastDurationRef.current = len;
    setAnns((prev) =>
      prev.map((ann) => {
        if (ann.localId !== activeId) return ann;
        const next = durationFromStart(ann.target_start, len, duration);
        return { ...ann, ...next };
      }),
    );
  };

  const nudgeDuration = (delta: number) => {
    if (!active) return;
    const currentLen = Math.max(MIN_DURATION, active.target_end - active.target_start);
    setActiveDurationSeconds(currentLen + delta);
  };

  const copyActive = () => {
    if (!active) return;
    clipboardRef.current = { ...active };
    setClipboardReady(true);
    onInfo("Блок скопирован. Поставьте ползунок в нужное место и нажмите «Вставить».");
  };

  const pasteAtPlayhead = () => {
    const src = clipboardRef.current;
    if (!src) {
      onError("Сначала скопируйте блок на дорожке.");
      return;
    }
    pauseVideo();
    const len = Math.max(MIN_DURATION, src.target_end - src.target_start);
    lastDurationRef.current = len;
    const range = durationFromStart(videoTime, len, duration);
    const localId = `local_${Date.now()}`;
    const item: StudioAnn = {
      ...src,
      localId,
      annotation_id: undefined,
      target_start: range.target_start,
      target_end: range.target_end,
    };
    setAnns((prev) => [...prev, item]);
    setActiveId(localId);
    onInfo(`Вставлено с ${formatTime(range.target_start)} по ${formatTime(range.target_end)}.`);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c" && active) {
        e.preventDefault();
        clipboardRef.current = { ...active };
        setClipboardReady(true);
        onInfo("Блок скопирован. Поставьте ползунок в нужное место и нажмите «Вставить».");
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v" && clipboardRef.current) {
        e.preventDefault();
        const src = clipboardRef.current;
        const len = Math.max(MIN_DURATION, src.target_end - src.target_start);
        lastDurationRef.current = len;
        const range = durationFromStart(videoTime, len, duration);
        const localId = `local_${Date.now()}`;
        setAnns((prev) => [
          ...prev,
          {
            ...src,
            localId,
            annotation_id: undefined,
            target_start: range.target_start,
            target_end: range.target_end,
          },
        ]);
        setActiveId(localId);
        onInfo(`Вставлено с ${formatTime(range.target_start)} по ${formatTime(range.target_end)}.`);
      }
      if ((e.key === "Delete" || e.key === "Backspace") && activeId) {
        e.preventDefault();
        setAnns((prev) => prev.filter((a) => a.localId !== activeId));
        setActiveId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, activeId, videoTime, duration, onInfo]);

  const handleSave = async () => {
    setSaving(true);
    onError("");
    try {
      const res = await saveAnnotationStudio(jobId, studioPayload(), true);
      onInfo(res.message ?? "Аннотации сохранены.");
      onUpdate();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  const handleApprove = async () => {
    setApproving(true);
    onError("");
    try {
      onInfo("Подтверждаю аннотации и собираю готовый файл… Обычно 1–3 минуты.");
      await saveAnnotationStudio(jobId, studioPayload(), true);
      const res = await approveAnnotationEdit(jobId);
      onInfo(res.message ?? "Аннотации подтверждены.");
      if (res.download_url || res.final_ready) {
        const a = document.createElement("a");
        a.href = artifactDownloadUrl(jobId, "final_lesson.mp4");
        a.download = `${jobId}_lesson.mp4`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
      onUpdate();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Ошибка подтверждения");
    } finally {
      setApproving(false);
    }
  };

  if (data.review_status === "approved") {
    const finalUrl = mediaUrl(`/jobs/${encodeURIComponent(jobId)}/artifacts/final_lesson.mp4`);
    const approvedSrc = data.video_version
      ? `${finalUrl}${finalUrl.includes("?") ? "&" : "?"}v=${encodeURIComponent(data.video_version)}`
      : finalUrl;
    return (
      <div className={`cleanup-editor annotation-studio ${embedded ? "cleanup-editor-embedded" : ""}`}>
        <p className="stage-summary">✓ Аннотации подтверждены. Готовый урок можно скачать.</p>
        <div className="annotation-studio-shell">
          <div className="annotation-studio-stage">
            <video
              controls
              playsInline
              src={approvedSrc}
              style={{ width: "100%", maxHeight: "70vh", background: "#000" }}
            />
          </div>
        </div>
        <div className="stage-download">
          <a
            className="btn-download"
            href={artifactDownloadUrl(jobId, "final_lesson.mp4")}
            download={`${jobId}_lesson.mp4`}
          >
            Скачать готовый урок (MP4)
          </a>
          <p className="hint stage-download-hint">
            В файле: озвучка + ваши субтитры (цвет и размер рамки как на шаге 2) + аннотации.
          </p>
        </div>
      </div>
    );
  }

  const bgRgba = hexToRgba(subtitleLayout.background_color, subtitleLayout.background_opacity);
  const textStyle = {
    fontSize: `${subtitleLayout.font_size_px}px`,
    fontWeight: subtitleLayout.font_bold ? 700 : 400,
    fontStyle: subtitleLayout.font_italic ? ("italic" as const) : ("normal" as const),
    color: subtitleLayout.font_color,
  };

  function studioPayload() {
    return [...toStudioPayload(anns), ...data.items.filter(item => skippedSuggestions.includes(item.annotation_id)).map(item => ({
      annotation_id: item.annotation_id, type: item.suggested_type, target_start: item.target_start,
      target_end: item.target_end, x: 0, y: 0, skipped: true,
    }))];
  }

  return (
    <div className={`cleanup-editor annotation-studio ${embedded ? "cleanup-editor-embedded" : ""}`}>
      {!embedded && <h3>Аннотации — студия (шаг 7)</h3>}
      <p className="hint">
        Play → Pause → «Рамка» или «Стрелка» → нарисуйте на видео. Длительность выбранного знака
        меняйте полем «Длительность, сек» или краями блока на дорожке (не фиксирована). Середина
        блока — перенос по времени. Ctrl+C / Ctrl+V — копировать и вставить. Затем «Сохранить».
      </p>

      {data.items.some(item => !item.placement_confirmed && !item.skipped) && <div className="script-review">
        <strong>Проверьте объекты, которые не удалось определить автоматически</strong>
        {data.items.filter(item => !item.placement_confirmed && !item.skipped
          && !anns.some(ann => ann.annotation_id === item.annotation_id) && !skippedSuggestions.includes(item.annotation_id))
          .map(item => <div key={item.annotation_id} className="script-review-item">
            <p>{formatTime(item.target_start)} · {item.text}</p>
            {item.anchor && <button type="button" className="btn-secondary" onClick={() => {
              const proposed = fromServerItem({...item, placement_confirmed: true});
              if (proposed) { setAnns(prev => [...prev, proposed]); setActiveId(proposed.localId); }
              if (videoRef.current) { videoRef.current.currentTime = item.target_start; videoRef.current.pause(); }
              setVideoTime(item.target_start);
            }}>Использовать предложенную область</button>}{" "}
            <button type="button" className="btn-secondary" onClick={() => {
              if (videoRef.current) { videoRef.current.currentTime = item.target_start; videoRef.current.pause(); }
              setVideoTime(item.target_start); setPendingPlacement(item);
              setTool(item.suggested_type === "arrow" ? "arrow" : "frame");
              onInfo("Укажите объект на кадре: кликните для стрелки или протяните рамку.");
            }}>Указать объект на кадре</button>{" "}
            <button type="button" className="btn-secondary" onClick={() => setSkippedSuggestions(prev => [...prev, item.annotation_id])}>Пропустить</button>
          </div>)}
        {pendingPlacement && <p>Сейчас размещается: {pendingPlacement.text}</p>}
      </div>}

      <div className="annotation-studio-shell" ref={shellRef}>
        <div
          className="annotation-studio-stage"
          ref={stageRef}
          onPointerDown={onStagePointerDown}
          onPointerMove={onStagePointerMove}
          onPointerUp={onStagePointerUp}
          onPointerCancel={onStagePointerUp}
        >
          <video
            ref={videoRef}
            src={videoSrc}
            controls
            controlsList="nofullscreen"
            disablePictureInPicture
            onTimeUpdate={syncTime}
            onLoadedMetadata={syncTime}
            onSeeked={syncTime}
          />
          {subtitleBox && activeSubtitle && !subtitlesBurned && (
            <div
              className="annotation-subtitle-overlay"
              style={{
                left: `${subtitleBox.x * 100}%`,
                top: `${subtitleBox.y * 100}%`,
                width: `${subtitleBox.width * 100}%`,
                height: `${subtitleBox.height * 100}%`,
                background: bgRgba,
                textAlign: (subtitleLayout.alignment as "left" | "center" | "right") || "center",
              }}
              aria-hidden="true"
            >
              <div className="annotation-subtitle-text" style={textStyle}>
                {activeSubtitle.text}
              </div>
            </div>
          )}
          <div className="annotation-studio-overlay" aria-hidden="true">
            {visibleAnns.map((ann) =>
              ann.type === "arrow" ? (
                <div
                  key={ann.localId}
                  className={`annotation-arrow-mark ${activeId === ann.localId ? "active" : ""}`}
                  style={{ left: `${ann.x * 100}%`, top: `${ann.y * 100}%` }}
                  title="Стрелка"
                >
                  <span className={`annotation-arrow-glyph dir-${ann.arrow_direction}`}>➤</span>
                </div>
              ) : (
                <div
                  key={ann.localId}
                  className={`annotation-frame-mark ${activeId === ann.localId ? "active" : ""}`}
                  style={{
                    left: `${ann.x * 100}%`,
                    top: `${ann.y * 100}%`,
                    width: `${ann.width * 100}%`,
                    height: `${ann.height * 100}%`,
                  }}
                >
                  <span className="annotation-frame-handle" />
                </div>
              ),
            )}
          </div>
          <button
            type="button"
            className="btn-secondary btn-fullscreen annotation-fs-toggle"
            onClick={() => void toggleShellFullscreen()}
            title="Полный экран: видео + панель инструментов"
          >
            {isShellFullscreen ? "Выйти из полного экрана" : "Полный экран"}
          </button>
        </div>

        <div className="annotation-studio-toolbar">
          <button
            type="button"
            className={`annotation-tool-btn ${tool === "select" ? "active" : ""}`}
            onClick={() => setTool("select")}
          >
            Выбор
          </button>
          <button
            type="button"
            className={`annotation-tool-btn ${tool === "frame" ? "active" : ""}`}
            onClick={() => {
              pauseVideo();
              setTool("frame");
            }}
          >
            Рамка
          </button>
          <button
            type="button"
            className={`annotation-tool-btn ${tool === "arrow" ? "active" : ""}`}
            onClick={() => {
              pauseVideo();
              setTool("arrow");
            }}
          >
            Стрелка
          </button>
          <button type="button" className="btn-secondary" disabled={!activeId} onClick={deleteActive}>
            Удалить
          </button>
          <button type="button" className="btn-secondary" disabled={!activeId} onClick={copyActive}>
            Копировать
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={!clipboardReady}
            onClick={pasteAtPlayhead}
          >
            Вставить сюда
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={!activeId}
            onClick={() => nudgeDuration(-DURATION_STEP)}
            title={`Короче на ${DURATION_STEP} с`}
          >
            −{DURATION_STEP}с
          </button>
          <label className="annotation-duration-field" title="Длительность выбранного знака в секундах">
            <span>Длительность, сек</span>
            <input
              type="number"
              min={MIN_DURATION}
              step={0.1}
              disabled={!active}
              value={
                active
                  ? Number((active.target_end - active.target_start).toFixed(1))
                  : ""
              }
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (!Number.isFinite(v)) return;
                setActiveDurationSeconds(v);
              }}
            />
          </label>
          <button
            type="button"
            className="btn-secondary"
            disabled={!activeId}
            onClick={() => nudgeDuration(DURATION_STEP)}
            title={`Длиннее на ${DURATION_STEP} с`}
          >
            +{DURATION_STEP}с
          </button>
          <span className="annotation-studio-time">
            {formatTime(videoTime)} / {formatTime(duration)}
            {active
              ? ` · блок ${formatTime(active.target_start)}–${formatTime(active.target_end)} (${(
                  active.target_end - active.target_start
                ).toFixed(1)} с)`
              : ""}
          </span>
        </div>

        <div className="annotation-timeline">
          <div className="annotation-timeline-label">
            Дорожка: края — длина, середина — перенос по времени
          </div>
          <div
            className="annotation-timeline-track"
            ref={trackRef}
            onPointerDown={onPlayheadPointerDown}
          >
            <div
              className="annotation-timeline-playhead"
              style={{ left: `${duration > 0 ? (videoTime / duration) * 100 : 0}%` }}
            />
            {anns.map((ann) => {
              const left = duration > 0 ? (ann.target_start / duration) * 100 : 0;
              const width =
                duration > 0
                  ? (Math.max(MIN_DURATION, ann.target_end - ann.target_start) / duration) * 100
                  : 2;
              return (
                <div
                  key={ann.localId}
                  className={`annotation-timeline-block ${ann.type} ${activeId === ann.localId ? "active" : ""} ${
                    dragMode === "slide" && activeId === ann.localId ? "sliding" : ""
                  }`}
                  style={{ left: `${left}%`, width: `${Math.max(1.8, width)}%` }}
                  title={`${ann.type === "arrow" ? "Стрелка" : "Рамка"} ${formatTime(ann.target_start)}–${formatTime(ann.target_end)} · тяните середину чтобы сдвинуть`}
                  onPointerDown={(e) => {
                    beginTimelineEdit(ann.localId, "slide")(e);
                    const video = videoRef.current;
                    if (video) {
                      video.pause();
                      video.currentTime = ann.target_start + 0.05;
                    }
                    setVideoTime(ann.target_start + 0.05);
                  }}
                >
                  <span
                    className="annotation-timeline-handle start"
                    title="Изменить начало"
                    onPointerDown={beginTimelineEdit(ann.localId, "trim-start")}
                  />
                  <span className="annotation-timeline-block-label">
                    {ann.type === "arrow" ? "→" : "▭"}
                  </span>
                  <span
                    className="annotation-timeline-handle end"
                    title="Изменить конец"
                    onPointerDown={beginTimelineEdit(ann.localId, "trim-end")}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="cleanup-actions">
        <button className="btn-secondary" type="button" disabled={saving || approving} onClick={handleSave}>
          {saving ? "Сохранение…" : "Сохранить аннотации"}
        </button>
        <button className="btn-primary" type="button" disabled={saving || approving} onClick={handleApprove}>
          {approving ? "Подтверждение…" : "Подтвердить аннотации"}
        </button>
      </div>
      {dragMode && <span className="sr-only">Режим: {dragMode}</span>}
    </div>
  );
}
