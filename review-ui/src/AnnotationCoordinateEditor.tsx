import { useCallback, useEffect, useRef, useState } from "react";
import {
  approveAnnotationEdit,
  mediaUrl,
  saveAnnotationPlacement,
  type AnnotationEditData,
  type AnnotationPlacementItem,
} from "./api";

type Props = {
  jobId: string;
  data: AnnotationEditData;
  onUpdate: () => void;
  onInfo: (msg: string) => void;
  onError: (msg: string) => void;
};

type ArrowDirection = "top" | "bottom" | "left" | "right";

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function isRectType(type: string): boolean {
  return type === "highlight_rect" || type === "frame" || type === "zoom";
}

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

export function AnnotationCoordinateEditor({ jobId, data, onUpdate, onInfo, onError }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [arrowDirection, setArrowDirection] = useState<ArrowDirection>("left");
  const [draft, setDraft] = useState<{
    x: number;
    y: number;
    width?: number;
    height?: number;
  } | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const pending = data.items.filter(item => !item.placement_confirmed && !item.skipped);

  const activeItem = data.items.find((i) => i.annotation_id === activeId) ?? null;

  useEffect(() => {
    setActiveId(null);
    setDraft(null);
  }, [data.last_saved_at, data.approved_at, jobId]);

  useEffect(() => {
    if (!activeItem) return;
    setArrowDirection((activeItem.arrow_direction as ArrowDirection) || "left");
    if (activeItem.placement_confirmed && activeItem.anchor) {
      setDraft({
        x: activeItem.anchor.x,
        y: activeItem.anchor.y,
        width: activeItem.anchor.width,
        height: activeItem.anchor.height,
      });
    } else {
      setDraft(null);
    }
  }, [activeItem?.annotation_id, activeItem?.placement_confirmed]);

  const relCoords = useCallback((clientX: number, clientY: number) => {
    const frame = frameRef.current;
    if (!frame) return null;
    const rect = frame.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return {
      x: clamp01((clientX - rect.left) / rect.width),
      y: clamp01((clientY - rect.top) / rect.height),
    };
  }, []);

  const onFramePointerDown = (e: React.PointerEvent) => {
    if (!activeItem || activeItem.skipped) return;
    const pt = relCoords(e.clientX, e.clientY);
    if (!pt) return;
    e.preventDefault();

    if (activeItem.suggested_type === "arrow") {
      setDraft({ x: pt.x, y: pt.y });
      return;
    }
    setDragStart(pt);
    setDraft({ x: pt.x, y: pt.y, width: 0.02, height: 0.02 });
  };

  const onFramePointerMove = (e: React.PointerEvent) => {
    if (!dragStart || !activeItem || activeItem.suggested_type === "arrow") return;
    const pt = relCoords(e.clientX, e.clientY);
    if (!pt) return;
    const x = clamp01(Math.min(dragStart.x, pt.x));
    const y = clamp01(Math.min(dragStart.y, pt.y));
    const width = clamp01(Math.abs(pt.x - dragStart.x));
    const height = clamp01(Math.abs(pt.y - dragStart.y));
    setDraft({ x, y, width: Math.max(0.02, width), height: Math.max(0.02, height) });
  };

  const onFramePointerUp = () => setDragStart(null);

  const handleSavePlacement = async (item: AnnotationPlacementItem, skipped = false) => {
    setSaving(true);
    onError("");
    try {
      if (skipped) {
        await saveAnnotationPlacement(jobId, item.annotation_id, { type: item.suggested_type, skipped: true });
        onInfo("Аннотация пропущена.");
      } else if (item.suggested_type === "arrow") {
        if (!draft) {
          onError("Кликните по объекту на кадре — куда должна указывать стрелка.");
          return;
        }
        await saveAnnotationPlacement(jobId, item.annotation_id, {
          type: "arrow",
          x: draft.x,
          y: draft.y,
          arrow_direction: arrowDirection,
        });
        onInfo("Стрелка сохранена. Превью видео обновлено.");
      } else if (draft && draft.width && draft.height) {
        await saveAnnotationPlacement(jobId, item.annotation_id, {
          type: item.suggested_type,
          x: draft.x,
          y: draft.y,
          width: draft.width,
          height: draft.height,
        });
        onInfo("Область сохранена. Превью видео обновлено.");
      } else {
        onError("Выделите прямоугольник мышью на кадре.");
        return;
      }
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
      const res = await approveAnnotationEdit(jobId);
      onInfo(res.message ?? "Аннотации подтверждены.");
      onUpdate();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Ошибка подтверждения");
    } finally {
      setApproving(false);
    }
  };

  const seekTo = (start: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, start);
    void video.play().catch(() => undefined);
  };

  if (data.review_status === "approved") {
    return null;
  }

  return (
    <div className="cleanup-editor annotation-editor">
      <h3>Проверка спорных выделений</h3>
      <p className="hint">
        Автоматически размещено: <strong>{data.confirmed_count}</strong>.
        Осталось проверить: <strong>{pending.length}</strong>. Для спорного выделения
        укажите объект на кадре или нажмите «Пропустить». Исходное видео сохранится.
      </p>

      <div className="annotation-preview-video">
        <video
          ref={videoRef}
          controls
          src={mediaUrl(`${data.preview_video_url}?t=${data.last_saved_at ?? ""}`)}
          onError={e => {
            const fallback = data.studio_video_url;
            if (fallback && !e.currentTarget.src.includes(fallback)) {
              e.currentTarget.src = mediaUrl(fallback);
            }
          }}
        />
      </div>

      <label><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} /> Показать все выделения</label>
      {pending.length === 0 && <p>Спорных выделений не осталось. Можно подтвердить результат и собрать урок.</p>}
      <div className="annotation-items-list">
        {(showAll ? data.items : pending).map((item) => {
          const isActive = activeId === item.annotation_id;
          const statusKey = item.skipped ? "skipped" : item.placement_confirmed ? "ready" : "pending";
          const statusLabel = item.skipped ? "пропущено" : item.placement_confirmed ? "готово" : "нужно указать";
          return (
            <div
              key={item.annotation_id}
              className={`annotation-item-card ${isActive ? "active" : ""} status-${statusKey}`}
            >
              <div className="annotation-item-head">
                <span className="transcript-time">{formatTime(item.target_start)}</span>
                <span className="annotation-type-badge">{item.type_label || item.suggested_type}</span>
                <span className={`annotation-status-badge badge-${statusKey}`}>{statusLabel}</span>
              </div>
              <p className="annotation-item-text">{item.text}</p>
              <div className="annotation-item-actions">
                <button
                  type="button"
                  className="btn-secondary btn-seek"
                  onClick={() => seekTo(item.target_start)}
                >
                  На видео
                </button>
                <button
                  type="button"
                  className={isActive ? "btn-primary" : "btn-secondary"}
                  onClick={() => {
                    setActiveId(item.annotation_id);
                    setDraft(null);
                  }}
                  disabled={item.skipped}
                >
                  {isRectType(item.suggested_type) ? "Указать область" : "Добавить стрелку"}
                </button>
                {!item.placement_confirmed && !item.skipped && (
                  <button
                    type="button"
                    className="btn-rerun"
                    disabled={saving}
                    onClick={() => handleSavePlacement(item, true)}
                  >
                    Пропустить
                  </button>
                )}
              </div>

              {isActive && item.frame_url && (
                <div className="annotation-frame-editor">
                  <p className="hint">
                    {item.suggested_type === "arrow"
                      ? "Кликните по объекту на кадре — здесь будет кончик стрелки. Выберите направление."
                      : "Зажмите мышь и выделите прямоугольник на элементе."}
                  </p>
                  {item.suggested_type === "arrow" && (
                    <div className="arrow-direction-picker">
                      {(["left", "right", "top", "bottom"] as ArrowDirection[]).map((dir) => (
                        <button
                          key={dir}
                          type="button"
                          className={arrowDirection === dir ? "btn-primary" : "btn-secondary"}
                          onClick={() => setArrowDirection(dir)}
                        >
                          {dir === "left" && "← слева"}
                          {dir === "right" && "справа →"}
                          {dir === "top" && "↑ сверху"}
                          {dir === "bottom" && "снизу ↓"}
                        </button>
                      ))}
                    </div>
                  )}
                  <div
                    className="annotation-frame-wrap"
                    ref={frameRef}
                    onPointerDown={onFramePointerDown}
                    onPointerMove={onFramePointerMove}
                    onPointerUp={onFramePointerUp}
                    onPointerLeave={onFramePointerUp}
                  >
                    <img src={mediaUrl(item.frame_url)} alt="Стоп-кадр" draggable={false} />
                    {draft && item.suggested_type === "arrow" && (
                      <span
                        className="annotation-draft-arrow"
                        style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%` }}
                      />
                    )}
                    {draft && isRectType(item.suggested_type) && draft.width && draft.height && (
                      <div
                        className="annotation-draft-rect"
                        style={{
                          left: `${draft.x * 100}%`,
                          top: `${draft.y * 100}%`,
                          width: `${draft.width * 100}%`,
                          height: `${draft.height * 100}%`,
                        }}
                      />
                    )}
                  </div>
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={saving}
                    onClick={() => handleSavePlacement(item)}
                  >
                    {saving ? "Сохранение…" : "Сохранить координаты"}
                  </button>
                </div>
              )}
              {isActive && !item.frame_url && (
                <p className="annotation-empty">Стоп-кадр не найден. Пропустите это выделение или повторите этап «Аннотации».</p>
              )}
            </div>
          );
        })}
      </div>

      <div className="cleanup-actions">
        <button
          className="btn-primary"
          type="button"
          disabled={saving || approving || pending.length > 0}
          onClick={handleApprove}
        >
          {approving
            ? "Подтверждение…"
            : "Подтвердить и собрать готовый урок"}
        </button>
      </div>
    </div>
  );
}
