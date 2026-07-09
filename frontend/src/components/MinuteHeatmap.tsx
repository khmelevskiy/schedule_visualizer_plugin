import { hhmm } from "../format";
import { heatColor } from "../heat";

interface Cursor {
  clientX: number;
  clientY: number;
}

interface Props {
  points: number[]; // value per minute-of-day, index 0..1439
  unit: string;
  onHover: (text: string, cursor: Cursor) => void;
  onLeave: () => void;
}

const HOURS = 24;
const MINUTES = 60;

// Hour (row) × minute (column) grid — surfaces the within-hour structure the
// day×hour heatmap averages away (e.g. everything piled onto :00).
export function MinuteHeatmap({ points, unit, onHover, onLeave }: Props) {
  const cell = 12;
  const gap = 1;
  const labelW = 28;
  const topH = 14;
  const max = Math.max(1, ...points);
  const width = labelW + MINUTES * (cell + gap);
  const height = topH + HOURS * (cell + gap);

  return (
    <div className="chart-scroll">
      <svg className="heatmap-svg" width={width} height={height} role="img">
        {Array.from({ length: 6 }, (_, i) => i * 10).map((m) => (
          <text key={m} x={labelW + m * (cell + gap) + cell / 2} y={11} textAnchor="middle">
            :{String(m).padStart(2, "0")}
          </text>
        ))}
        {Array.from({ length: HOURS }, (_, h) => {
          const y = topH + h * (cell + gap);
          return (
            <g key={h}>
              <text x={labelW - 6} y={y + cell / 2 + 3} textAnchor="end">
                {String(h).padStart(2, "0")}
              </text>
              {Array.from({ length: MINUTES }, (_, m) => {
                const value = points[h * MINUTES + m];
                return (
                  <rect
                    key={m}
                    x={labelW + m * (cell + gap)}
                    y={y}
                    width={cell}
                    height={cell}
                    rx={2}
                    fill={heatColor(value / max)}
                    onMouseMove={(e) => onHover(`${hhmm(h * MINUTES + m)} — ${value} ${unit}`, e)}
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
