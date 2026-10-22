'use strict';

// Geometry-only helpers: Electron cursor coordinates and BrowserWindow bounds are
// both in display-independent pixels (DIP), including multi-monitor setups.
function isInWindow(point, bounds) {
  if (!point || !bounds) return false;
  if (![point.x, point.y, bounds.x, bounds.y, bounds.width, bounds.height].every(Number.isFinite)) return false;
  return point.x >= bounds.x && point.x < bounds.x + bounds.width &&
    point.y >= bounds.y && point.y < bounds.y + bounds.height;
}

function toLocalPoint(point, bounds) {
  return { x: point.x - bounds.x, y: point.y - bounds.y };
}

// Ignore-transparent behavior must never turn on while a drag is active.
function shouldIgnoreMouse({ dragging, inside, hit }) {
  return !dragging && (!inside || !hit);
}

function nextDragPosition(start, cursorAtStart, cursorNow, area) {
  const clamp = (x, low, high) => Math.max(low, Math.min(high, x));
  return {
    x: Math.round(clamp(start.x + cursorNow.x - cursorAtStart.x, area.x,
      area.x + Math.max(0, area.width - start.width))),
    y: Math.round(clamp(start.y + cursorNow.y - cursorAtStart.y, area.y,
      area.y + Math.max(0, area.height - start.height)))
  };
}

module.exports = { isInWindow, toLocalPoint, shouldIgnoreMouse, nextDragPosition };
