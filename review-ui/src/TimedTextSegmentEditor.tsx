import { useMemo, useRef } from "react";
import type { CleanupSegmentEdit } from "./api";
import {
  buildSpeechTimeline,
  buildTimingStepsModel,
  formatStepDuration,
} from "./timingSteps";
import {
  findLengthChangeRanges,
  hasLengthChangingEdits,
  splitByLengthChangeRanges,
} from "./textDiffHighlight";

type Props = {
  segment: CleanupSegmentEdit;
  value: string;
  textareaId: string;
  rows?: number;
  /** Если передан — можно подсветить правки длины. Без него подсветка выключена (ручное редактирование). */
  compareWith?: string;
  /** Сетка шагов по символам. Для длинного текста урока лучше выключить. */
  showTimeline?: boolean;
  onChange: (value: string) => void;
  onCompositionStart?: () => void;
  onCompositionEnd?: (value: string) => void;
};

export function TimedTextSegmentEditor({
  segment,
  value,
  textareaId,
  rows = 4,
  compareWith,
  showTimeline = true,
  onChange,
  onCompositionStart,
  onCompositionEnd,
}: Props) {
  const highlightRef = useRef<HTMLDivElement>(null);
  const slot = segment.slot_seconds ?? segment.end - segment.start;
  const reference = segment.original_text ?? value;
  // Подсветку включаем ТОЛЬКО при явном compareWith — иначе ломается ручной ввод.
  const baseline = (compareWith ?? "").trim();
  const model = useMemo(
    () => buildTimingStepsModel(value, reference, slot),
    [value, reference, slot],
  );
  const stepsDelta = model.totalSteps - model.budgetSteps;
  const timingMismatch = stepsDelta !== 0;
  const timeline = useMemo(() => {
    if (!showTimeline) return [];
    return buildSpeechTimeline(value, segment.start, segment.end);
  }, [showTimeline, value, segment.start, segment.end]);
  const showLengthHighlight =
    Boolean(compareWith?.trim()) && Boolean(baseline) && hasLengthChangingEdits(baseline, value);
  const highlightParts = useMemo(() => {
    if (!showLengthHighlight) return [];
    const ranges = findLengthChangeRanges(baseline, value);
    return splitByLengthChangeRanges(value, ranges);
  }, [showLengthHighlight, baseline, value]);
  const underlinedCount = highlightParts.filter((p) => p.underlined).length;

  const syncHighlightScroll = (scrollTop: number, scrollLeft: number) => {
    if (highlightRef.current) {
      highlightRef.current.scrollTop = scrollTop;
      highlightRef.current.scrollLeft = scrollLeft;
    }
  };

  return (
    <div className={`timed-text-field ${timingMismatch ? "timed-text-over" : ""}`}>
      {showLengthHighlight && (
        <div className="timed-text-diff-banner" role="status">
          Подчёркнуты места, где правка изменила размер текста относительно исходника
          {underlinedCount > 0 ? ` (${underlinedCount})` : ""}.
        </div>
      )}
      <div className={`timed-text-editor-stack ${showLengthHighlight ? "has-diff-highlight" : ""}`}>
        {showLengthHighlight && (
          <div className="timed-text-highlight-layer" ref={highlightRef} aria-hidden="true">
            {highlightParts.map((part, index) =>
              part.underlined ? (
                <span key={index} className="timed-text-length-change">
                  {part.text}
                </span>
              ) : (
                <span key={index}>{part.text}</span>
              ),
            )}
          </div>
        )}
        <textarea
          id={textareaId}
          className={`timed-text-input ${showLengthHighlight ? "timed-text-input-over-highlight" : ""}`}
          rows={rows}
          value={value}
          autoComplete="off"
          spellCheck={true}
          onScroll={(e) =>
            syncHighlightScroll(e.currentTarget.scrollTop, e.currentTarget.scrollLeft)
          }
          onCompositionStart={onCompositionStart}
          onCompositionEnd={(e) => onCompositionEnd?.(e.currentTarget.value)}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
      {showTimeline && (
        <div className="timed-text-steps" aria-hidden="true">
          {timeline.length === 0 ? (
            <span className="timed-text-steps-empty">Временные шаги появятся вместе с текстом</span>
          ) : (
            timeline.map((entry, index) => (
              <span
                key={`${entry.type}-${index}-${entry.start}`}
                className={`timed-step-cell ${entry.type === "gap" ? "is-gap" : "is-char"}`}
                title={`${entry.start.toFixed(2)}–${entry.end.toFixed(2)} с · 1 шаг ≈ ${formatStepDuration(model.secondsPerStep)} с`}
              >
                <span className="timed-step-char">{entry.type === "gap" ? "·" : entry.char}</span>
                <span className="timed-step-dot" />
              </span>
            ))
          )}
        </div>
      )}
      <p className="timed-text-legend">
        В блоке <strong>{model.budgetSteps}</strong> шагов · сейчас <strong>{model.totalSteps}</strong> · 1
        шаг ≈ <strong>{formatStepDuration(model.secondsPerStep)}</strong> с
        {timingMismatch && (
          <span className="timed-text-warn">
            {" "}
            — {stepsDelta > 0 ? "текста больше" : "текста меньше"}, чем нужно для тайм-блока (
            {stepsDelta > 0 ? "+" : ""}
            {stepsDelta} шагов). Будет рассинхрон с видео
          </span>
        )}
      </p>
    </div>
  );
}
