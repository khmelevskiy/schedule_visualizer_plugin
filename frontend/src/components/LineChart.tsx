import { hhmm } from "../format";

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

// viewBox coordinates; the SVG scales uniformly to the card width.
const W = 960;
const H = 220;
const PAD = { top: 12, right: 8, bottom: 22, left: 34 };

export function LineChart({ points, unit, onHover, onLeave }: Props) {
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const last = points.length - 1;
  const max = Math.max(1, ...points);
  const ticks = [0, 0.5, 1].map((t) => Math.round(max * t));
  const baseline = PAD.top + plotH;

  const x = (minute: number) => PAD.left + (minute / points.length) * plotW;
  const y = (value: number) => PAD.top + plotH - (value / max) * plotH;

  // One point per minute — even at sub-pixel spacing the polyline reads as a
  // continuous curve, so the fine structure (spikes at :00/:15/:30) stays visible.
  const line = points.map((v, m) => `${x(m).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${PAD.left},${baseline} ${line} ${x(last).toFixed(1)},${baseline}`;

  return (
    <div className="chart-scroll">
      <svg className="line-svg" viewBox={`0 0 ${W} ${H}`} role="img" style={{ width: "100%", height: "auto" }}>
        {ticks.map((t) => {
          const gy = y(t);
          return (
            <g key={t}>
              <line x1={PAD.left} y1={gy} x2={W - PAD.right} y2={gy} stroke="var(--grid)" />
              <text x={PAD.left - 6} y={gy + 3} textAnchor="end">
                {t}
              </text>
            </g>
          );
        })}
        {Array.from({ length: 9 }, (_, i) => i * 3).map((h) => (
          <text key={h} x={x(h * 60)} y={H - 8} textAnchor="middle">
            {h}
          </text>
        ))}
        <polygon points={area} fill="var(--accent)" fillOpacity={0.14} />
        <polyline points={line} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
        <rect
          x={PAD.left}
          y={PAD.top}
          width={plotW}
          height={plotH}
          fill="transparent"
          onMouseMove={(e) => {
            const box = e.currentTarget.getBoundingClientRect();
            const minute = Math.min(last, Math.max(0, Math.round(((e.clientX - box.left) / box.width) * last)));
            onHover(`${hhmm(minute)} — ${points[minute]} ${unit}`, e);
          }}
          onMouseLeave={onLeave}
        />
      </svg>
    </div>
  );
}
