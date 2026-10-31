/** Временные «шаги» для сопоставления текста и тайм-блока озвучки. */

export type TimelineEntry = {
  char: string;
  type: "char" | "gap";
  start: number;
  end: number;
};

export type WordTimingGroup = {
  word: string;
  charSteps: number;
};

export type TimingStepsModel = {
  words: WordTimingGroup[];
  gapSteps: number[];
  totalSteps: number;
  budgetSteps: number;
  slotSeconds: number;
  secondsPerStep: number;
  budgetExceeded: boolean;
  stepsDelta: number;
  timingMismatch: boolean;
};

export function tokenizeWords(text: string): string[] {
  return String(text || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

/** Один шаг на символ + один шаг на паузу между словами. */
export function countTimingSteps(text: string): number {
  const words = tokenizeWords(text);
  if (!words.length) return 0;
  const chars = words.reduce((sum, word) => sum + word.length, 0);
  return chars + Math.max(0, words.length - 1);
}

export function buildSpeechTimeline(text: string, start: number, end: number): TimelineEntry[] {
  const words = tokenizeWords(text);
  if (!words.length) return [];

  const totalSteps = countTimingSteps(text);
  const stepDuration = (end - start) / totalSteps;
  let cursor = start;
  const entries: TimelineEntry[] = [];

  words.forEach((word, wordIndex) => {
    for (const char of word) {
      entries.push({
        char,
        type: "char",
        start: cursor,
        end: cursor + stepDuration,
      });
      cursor += stepDuration;
    }
    if (wordIndex < words.length - 1) {
      entries.push({
        char: " ",
        type: "gap",
        start: cursor,
        end: cursor + stepDuration,
      });
      cursor += stepDuration;
    }
  });

  return entries;
}

export function buildTimingStepsModel(
  text: string,
  originalText: string,
  slotSeconds: number,
): TimingStepsModel {
  const words = tokenizeWords(text);
  const reference = String(originalText || text || "").trim();
  const budgetSteps = Math.max(1, countTimingSteps(reference || text));
  const totalSteps = countTimingSteps(text);
  const wordGroups = words.map((word) => ({ word, charSteps: word.length }));
  const gapSteps = Array(Math.max(0, words.length - 1)).fill(1);
  const stepsDelta = totalSteps - budgetSteps;

  return {
    words: wordGroups,
    gapSteps,
    totalSteps,
    budgetSteps,
    slotSeconds,
    secondsPerStep: slotSeconds / budgetSteps,
    budgetExceeded: totalSteps > budgetSteps,
    stepsDelta,
    timingMismatch: stepsDelta !== 0,
  };
}

function formatSeconds(value: number): string {
  if (value < 10) return value.toFixed(2);
  return value.toFixed(1);
}

export function formatStepDuration(seconds: number): string {
  return formatSeconds(seconds);
}
