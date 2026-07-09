// Shared load color scale: free slots stay neutral, load ramps green → red.
// `ratio` is value / max, in [0, 1]. Used by both heatmaps (day×hour, hour×minute).
export function heatColor(ratio: number): string {
  if (ratio <= 0) return "var(--heat-0)";
  const hue = 145 - ratio * 145; // 145 (green) → 0 (red)
  const light = 68 - ratio * 20;
  return `hsl(${hue}, 72%, ${light}%)`;
}
