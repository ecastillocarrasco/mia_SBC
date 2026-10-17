'use strict';
// Pure geometry used by the frameless chat window. All coordinates use Electron DIP.
function clamp(v, min, max) { return Math.max(min, Math.min(v, max)); }
function computeResizeBounds(bounds, area, dx, dy, edge, limits = {}) {
  const margin = 8;
  const minWidth = limits.minWidth || 390;
  const minHeight = limits.minHeight || 385;
  const maxWidth = Math.min(limits.maxWidth || 1000, Math.max(minWidth, area.width - 2 * margin));
  const maxHeight = Math.min(limits.maxHeight || 850, Math.max(minHeight, area.height - 2 * margin));
  const leftLimit = area.x + margin, topLimit = area.y + margin;
  const rightLimit = area.x + area.width - margin, bottomLimit = area.y + area.height - margin;
  let left = bounds.x, top = bounds.y;
  let right = bounds.x + bounds.width, bottom = bounds.y + bounds.height;
  if (edge.includes('w')) left = clamp(left + dx, Math.max(leftLimit, right - maxWidth), right - minWidth);
  if (edge.includes('e')) right = clamp(right + dx, left + minWidth, Math.min(rightLimit, left + maxWidth));
  if (edge.includes('n')) top = clamp(top + dy, Math.max(topLimit, bottom - maxHeight), bottom - minHeight);
  if (edge.includes('s')) bottom = clamp(bottom + dy, top + minHeight, Math.min(bottomLimit, top + maxHeight));
  return {
    x: Math.round(left), y: Math.round(top),
    width: Math.round(right - left), height: Math.round(bottom - top)
  };
}
module.exports = { computeResizeBounds };
