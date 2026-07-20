import { axisGutter, fmtAxis } from "../format";

export interface Bar {
  label: string;
  value: number;
  title?: string;
  muted?: boolean;
}

interface Cursor {
  clientX: number;
  clientY: number;
}

interface Props {
  bars: Bar[];
  height?: number;
  barWidth?: number;
  labelEvery?: number;
  unit: string;
  onHover: (text: string, cursor: Cursor) => void;
  onLeave: () => void;
}

export function BarChart({ bars, height = 200, barWidth = 22, labelEvery = 1, unit, onHover, onLeave }: Props) {
  const gap = 6;
  const max = Math.max(1, ...bars.map((b) => b.value));
  const ticks = [0, 0.5, 1].map((t) => Math.round(max * t));
  const tickLabels = ticks.map(fmtAxis);
  const pad = { top: 12, right: 8, bottom: 22, left: axisGutter(tickLabels) };
  const plotH = height - pad.top - pad.bottom;
  const width = pad.left + pad.right + bars.length * (barWidth + gap);

  return (
    <div className="chart-scroll">
      <svg className="bar-svg" width={width} height={height} role="img">
        {ticks.map((t, index) => {
          const y = pad.top + plotH - (t / max) * plotH;
          return (
            <g key={t}>
              <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} stroke="var(--grid)" />
              <text x={pad.left - 6} y={y + 3} textAnchor="end">
                {tickLabels[index]}
              </text>
            </g>
          );
        })}
        {bars.map((b, i) => {
          const h = (b.value / max) * plotH;
          const x = pad.left + i * (barWidth + gap);
          const y = pad.top + plotH - h;
          return (
            <g key={i}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={Math.max(h, b.value > 0 ? 1 : 0)}
                rx={3}
                fill={b.muted ? "var(--bar-muted)" : "var(--accent)"}
                onMouseMove={(e) => onHover(`${b.title ?? b.label}: ${b.value} ${unit}`, e)}
                onMouseLeave={onLeave}
              />
              {i % labelEvery === 0 && (
                <text x={x + barWidth / 2} y={height - 8} textAnchor="middle">
                  {b.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
