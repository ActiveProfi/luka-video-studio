import type { SubtitleCue } from "./api";

/** Уникальный ключ блока: source_segment_id + cue_id или тайминг. */
export function getCueKey(cue: SubtitleCue): string {
  if (cue.source_segment_id) {
    return `${cue.source_segment_id}:${cue.cue_id}`;
  }
  return `${cue.cue_id}@${cue.start.toFixed(3)}-${cue.end.toFixed(3)}`;
}

export function findCueByKey(cues: SubtitleCue[], key: string): SubtitleCue | null {
  return cues.find((cue) => getCueKey(cue) === key) ?? null;
}

export function findCueIndexByKey(cues: SubtitleCue[], key: string): number {
  return cues.findIndex((cue) => getCueKey(cue) === key);
}
