export const GRID = 0.01;
export const MIN_WIDTH = 0.15;
export const MIN_HEIGHT = 0.1;

const round = (value) => Math.round(value / GRID) * GRID;
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

export function place(widget, action, dx, dy) {
  const next = { ...widget };
  if (action === "move") {
    next.x = clamp(round(widget.x + dx), 0, 1 - widget.w);
    next.y = clamp(round(widget.y + dy), 0, 1 - widget.h);
  } else {
    next.w = clamp(round(widget.w + dx), MIN_WIDTH, 1 - widget.x);
    next.h = clamp(round(widget.h + dy), MIN_HEIGHT, 1 - widget.y);
  }
  return next;
}

export function horizontalAlignment(widget) {
  const center = widget.x + widget.w / 2;
  if (center < 0.4) return "left";
  if (center > 0.6) return "right";
  return "center";
}
