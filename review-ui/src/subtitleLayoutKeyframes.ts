import type { SubtitleCue } from "./api";
import { findCueIndexByKey, getCueKey } from "./subtitleCueKey";

export type BoxLayout = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type LayoutKeyframe = {
  cueId: string;
  box: BoxLayout;
};

export function boxesEqual(a: BoxLayout, b: BoxLayout): boolean {
  return (
    Math.abs(a.x - b.x) < 0.001 &&
    Math.abs(a.y - b.y) < 0.001 &&
    Math.abs(a.width - b.width) < 0.001 &&
    Math.abs(a.height - b.height) < 0.001
  );
}

function cueIndex(cues: SubtitleCue[], cueKey: string): number {
  return findCueIndexByKey(cues, cueKey);
}

function layoutBoxForCue(
  cueLayouts: Record<string, BoxLayout>,
  cue: SubtitleCue,
  fallback: BoxLayout,
): BoxLayout {
  return cueLayouts[getCueKey(cue)] ?? cueLayouts[cue.cue_id] ?? fallback;
}

export function sortKeyframes(keyframes: LayoutKeyframe[], cues: SubtitleCue[]): LayoutKeyframe[] {
  return [...keyframes].sort(
    (a, b) => cueIndex(cues, a.cueId) - cueIndex(cues, b.cueId),
  );
}

/** Из сохранённых per-cue layout собрать ключевые точки (где положение менялось). */
export function keyframesFromCueLayouts(
  cueLayouts: Record<string, BoxLayout>,
  cues: SubtitleCue[],
  defaultBox: BoxLayout,
): LayoutKeyframe[] {
  const keyframes: LayoutKeyframe[] = [];
  let last = defaultBox;
  for (const cue of cues) {
    const box = layoutBoxForCue(cueLayouts, cue, last);
    if (!boxesEqual(box, last)) {
      keyframes.push({ cueId: getCueKey(cue), box: { ...box } });
      last = box;
    }
  }
  return keyframes;
}

/** Положение для фрагмента: последняя ручная настройка на этом или предыдущем блоке. */
export function getBoxForCue(
  cueKey: string,
  keyframes: LayoutKeyframe[],
  cues: SubtitleCue[],
  defaultBox: BoxLayout,
): BoxLayout {
  const idx = cueIndex(cues, cueKey);
  if (idx < 0) return defaultBox;
  let active = defaultBox;
  for (const kf of sortKeyframes(keyframes, cues)) {
    const kfIdx = cueIndex(cues, kf.cueId);
    if (kfIdx >= 0 && kfIdx <= idx) active = kf.box;
  }
  return active;
}

/** Развернуть ключевые точки в cue_layouts для сохранения на сервер. */
export function expandKeyframesToCueLayouts(
  keyframes: LayoutKeyframe[],
  cues: SubtitleCue[],
  defaultBox: BoxLayout,
): Record<string, BoxLayout> {
  const sorted = sortKeyframes(keyframes, cues);
  const result: Record<string, BoxLayout> = {};
  let active = defaultBox;
  let kfIndex = 0;

  for (const cue of cues) {
    const cueKey = getCueKey(cue);
    const idx = cueIndex(cues, cueKey);
    while (kfIndex < sorted.length && cueIndex(cues, sorted[kfIndex].cueId) <= idx) {
      active = sorted[kfIndex].box;
      kfIndex += 1;
    }
    if (!boxesEqual(active, defaultBox)) {
      result[cueKey] = { ...active };
    }
  }
  return result;
}

export function upsertLayoutKeyframe(
  keyframes: LayoutKeyframe[],
  cueKey: string,
  box: BoxLayout,
  defaultBox: BoxLayout,
): LayoutKeyframe[] {
  const withoutCurrent = keyframes.filter((kf) => kf.cueId !== cueKey);
  if (boxesEqual(box, defaultBox)) {
    return withoutCurrent;
  }
  return [...withoutCurrent, { cueId: cueKey, box: { ...box } }];
}
