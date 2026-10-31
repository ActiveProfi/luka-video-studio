/**
 * Инструменты для ручной разметки аннотаций поверх видео в браузере.
 * Пока НЕ подключены к шагу «Аннотации» — только библиотеки Fabric.js / Konva.
 *
 * Fabric.js — рамки, стрелки, перетаскивание на canvas.
 * Konva + react-konva — то же для React-компонентов.
 */

export type NormRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

/** Нормализованные 0..1 координаты ↔ пиксели canvas. */
export function normToCanvas(
  rect: NormRect,
  canvasWidth: number,
  canvasHeight: number,
): { left: number; top: number; width: number; height: number } {
  return {
    left: rect.x * canvasWidth,
    top: rect.y * canvasHeight,
    width: rect.width * canvasWidth,
    height: rect.height * canvasHeight,
  };
}

export function canvasToNorm(
  left: number,
  top: number,
  width: number,
  height: number,
  canvasWidth: number,
  canvasHeight: number,
): NormRect {
  return {
    x: left / canvasWidth,
    y: top / canvasHeight,
    width: width / canvasWidth,
    height: height / canvasHeight,
  };
}

/** Ленивый импорт Fabric — не тянет canvas, пока не вызван. */
export async function loadFabricCanvas() {
  const { Canvas, Rect, Line } = await import("fabric");
  return { Canvas, Rect, Line };
}

/** Ленивый импорт Konva для React-редактора. */
export async function loadKonva() {
  const konva = await import("konva");
  const reactKonva = await import("react-konva");
  return { ...konva, ...reactKonva };
}
