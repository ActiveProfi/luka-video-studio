/** Подсветка правок, которые меняют «размер» текста (число шагов озвучки). */

import { countTimingSteps } from "./timingSteps";

export type DiffToken = {
  text: string;
  lengthChanged: boolean;
};

export type TextRange = {
  start: number;
  end: number;
};

function tokenizeWords(text: string): string[] {
  return String(text || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

/** Word-level LCS → токены текста «после» с флагом lengthChanged. */
export function buildLengthChangeTokens(before: string, after: string): DiffToken[] {
  const a = tokenizeWords(before);
  const b = tokenizeWords(after);
  if (!b.length) return [];
  if (!a.length) {
    return b.map((text) => ({ text, lengthChanged: true }));
  }

  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  type Op =
    | { type: "equal"; after: string }
    | { type: "insert"; after: string }
    | { type: "delete"; before: string }
    | { type: "replace"; before: string; after: string };

  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: "equal", after: b[j] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: "delete", before: a[i] });
      i += 1;
    } else {
      ops.push({ type: "insert", after: b[j] });
      j += 1;
    }
  }
  while (i < n) {
    ops.push({ type: "delete", before: a[i] });
    i += 1;
  }
  while (j < m) {
    ops.push({ type: "insert", after: b[j] });
    j += 1;
  }

  const merged: Op[] = [];
  for (let k = 0; k < ops.length; k += 1) {
    const cur = ops[k];
    const next = ops[k + 1];
    if (cur.type === "delete" && next?.type === "insert") {
      merged.push({ type: "replace", before: cur.before, after: next.after });
      k += 1;
    } else if (cur.type === "insert" && next?.type === "delete") {
      merged.push({ type: "replace", before: next.before, after: cur.after });
      k += 1;
    } else {
      merged.push(cur);
    }
  }

  const tokens: DiffToken[] = [];
  for (const op of merged) {
    if (op.type === "equal") {
      tokens.push({ text: op.after, lengthChanged: false });
    } else if (op.type === "insert") {
      tokens.push({ text: op.after, lengthChanged: true });
    } else if (op.type === "replace") {
      const beforeSteps = countTimingSteps(op.before);
      const afterSteps = countTimingSteps(op.after);
      tokens.push({
        text: op.after,
        lengthChanged: beforeSteps !== afterSteps || op.before !== op.after,
      });
    }
  }
  return tokens;
}

/** Диапазоны символов в тексте «после», которые нужно подчеркнуть. */
export function findLengthChangeRanges(before: string, after: string): TextRange[] {
  const tokens = buildLengthChangeTokens(before, after);
  const ranges: TextRange[] = [];
  let pos = 0;
  for (const token of tokens) {
    if (!token.text) continue;
    const idx = after.indexOf(token.text, pos);
    if (idx < 0) continue;
    if (token.lengthChanged) {
      ranges.push({ start: idx, end: idx + token.text.length });
    }
    pos = idx + token.text.length;
  }
  return ranges;
}

export function hasLengthChangingEdits(before: string, after: string): boolean {
  if (!before.trim() || !after.trim()) return false;
  if (before.trim() === after.trim()) return false;
  return findLengthChangeRanges(before, after).length > 0;
}

/** Разбить строку на фрагменты plain / underlined для отрисовки. */
export function splitByLengthChangeRanges(
  text: string,
  ranges: TextRange[],
): Array<{ text: string; underlined: boolean }> {
  if (!ranges.length) return [{ text, underlined: false }];
  const sorted = [...ranges].sort((a, b) => a.start - b.start);
  const parts: Array<{ text: string; underlined: boolean }> = [];
  let cursor = 0;
  for (const range of sorted) {
    const start = Math.max(0, Math.min(text.length, range.start));
    const end = Math.max(start, Math.min(text.length, range.end));
    if (start > cursor) {
      parts.push({ text: text.slice(cursor, start), underlined: false });
    }
    if (end > start) {
      parts.push({ text: text.slice(start, end), underlined: true });
    }
    cursor = Math.max(cursor, end);
  }
  if (cursor < text.length) {
    parts.push({ text: text.slice(cursor), underlined: false });
  }
  return parts;
}
