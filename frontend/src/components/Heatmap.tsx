import type { HeatmapRow, Metric } from "../api";
import { metricOf } from "../format";

interface Cursor {
  clientX: number;
  clientY: number;
}

interface Props {
  rows: HeatmapRow[];
  hours: number[];
  metric: Metric;
  shortDay: (iso: string) => string;
  dayTitle: (iso: string) => string;
  weekend: (iso: string) => boolean;
  onHover: (text: string, cursor: Cursor) => void;
  onLeave: () => void;
}

// A green-through-red scale: free slots stay neutral, load ramps to warm.
function color(ratio: number): string {
  if (ratio <= 0) return "var(--heat-0)";
  const hue = 145 - ratio * 145; // 145 (green) -> 0 (red)
  const light = 68 - ratio * 20;
  return `hsl(${hue}, 72%, ${light}%)`;
}

export function Heatmap({ rows, hours, metric, shortDay, dayTitle, weekend, onHover, onLeave }: Props) {
  const cell = 22;
  const gap = 2;
  const labelW = 46;
  const topH = 16;
  const max = Math.max(1, ...rows.flatMap((r) => r.cells.map((c) => metricOf(c, metric))));
  const width = labelW + hours.length * (cell + gap);
  const height = topH + rows.length * (cell + gap);

  return (
    <div className="chart-scroll">
      <svg className="heatmap-svg" width={width} height={height} role="img">
        {hours.map((h, i) =>
          h % 3 === 0 ? (
            <text key={h} x={labelW + i * (cell + gap) + cell / 2} y={11} textAnchor="middle">
              {h}
            </text>
          ) : null,
        )}
        {rows.map((row, r) => {
          const y = topH + r * (cell + gap);
          return (
            <g key={row.date}>
              <text x={labelW - 8} y={y + cell / 2 + 3} textAnchor="end" fill={weekend(row.date) ? "var(--accent)" : undefined}>
                {shortDay(row.date)}
              </text>
              {row.cells.map((c, h) => {
                const value = metricOf(c, metric);
                return (
                  <rect
                    key={h}
                    x={labelW + h * (cell + gap)}
                    y={y}
                    width={cell}
                    height={cell}
                    rx={3}
                    fill={color(value / max)}
                    onMouseMove={(e) => onHover(`${dayTitle(row.date)}, ${String(h).padStart(2, "0")}:00 — ${value} ${metric}`, e)}
                    onMouseLeave={onLeave}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
