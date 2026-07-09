import { useEffect, useMemo, useState } from "react";
import { fetchSchedule, type Metric, type Schedule } from "./api";
import { BarChart } from "./components/BarChart";
import { Controls } from "./components/Controls";
import { Heatmap } from "./components/Heatmap";
import { LineChart } from "./components/LineChart";
import { MinuteHeatmap } from "./components/MinuteHeatmap";
import { SortableTable } from "./components/SortableTable";
import { Suggest } from "./components/Suggest";
import { dayLabel, isWeekend, metricOf, shortDay, timeAgo, untilLabel } from "./format";

type Tab = "heatmap" | "trends" | "tables";
const TABS: { key: Tab; label: string }[] = [
  { key: "heatmap", label: "Heatmap" },
  { key: "trends", label: "Trends" },
  { key: "tables", label: "Tables" },
];

export function App() {
  const [metric, setMetric] = useState<Metric>("tasks");
  const [selected, setSelected] = useState<string[]>([]);
  const [includePaused, setIncludePaused] = useState(false);
  const [tab, setTab] = useState<Tab>("heatmap");
  const [heatRes, setHeatRes] = useState<"day" | "minute">("day");
  const [hourRes, setHourRes] = useState<"hour" | "minute">("hour");
  const [data, setData] = useState<Schedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);

  const showTip = (text: string, cursor: { clientX: number; clientY: number }) =>
    setTip({ text, x: cursor.clientX, y: cursor.clientY });
  const hideTip = () => setTip(null);

  useEffect(() => {
    let live = true;
    setError(null);
    fetchSchedule({ teams: selected, metric, includePaused })
      .then((d) => live && setData(d))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [metric, selected, includePaused]);

  const toggleTeam = (team: string) =>
    setSelected((cur) => (cur.includes(team) ? cur.filter((t) => t !== team) : [...cur, team]));

  const dayBars = useMemo(
    () =>
      data?.days.map((d) => ({
        label: shortDay(d.date),
        title: dayLabel(d.date),
        value: metricOf(d, metric),
        muted: isWeekend(d.date),
      })) ?? [],
    [data, metric],
  );
  const hourBars = useMemo(
    () => data?.hours.map((h) => ({ label: String(h.hour), title: `${String(h.hour).padStart(2, "0")}:00`, value: metricOf(h, metric) })) ?? [],
    [data, metric],
  );
  // One value per minute-of-day (slots is all 1440, minute-ordered) — reused by
  // the minute line and the hour×minute heatmap.
  const minutePoints = useMemo(() => data?.slots.map((s) => metricOf(s, metric)) ?? [], [data, metric]);

  if (error) return <div className="app"><div className="state">Failed to load: {error}</div></div>;
  if (!data) return <div className="app"><div className="state">Loading…</div></div>;

  const dayLabelEvery = data.days.length > 20 ? 2 : 1;

  return (
    <div className="app">
      <div className="header">
        <h1>Schedule Visualizer</h1>
        <span className="freshness">
          Updated {timeAgo(data.meta.updated_at)} · refreshes {untilLabel(data.meta.next_refresh)}
        </span>
      </div>
      <p className="subtitle">
        Planned load across {data.days.length} days — find the quietest days and time slots to place new work.
      </p>

      <Controls
        metric={metric}
        onMetric={setMetric}
        teams={data.meta.teams}
        selected={selected}
        onToggleTeam={toggleTeam}
        onClearTeams={() => setSelected([])}
        includePaused={includePaused}
        onIncludePaused={setIncludePaused}
      />

      <Suggest suggestions={data.suggestions} metric={metric} timezone={data.meta.timezone} windowDays={data.meta.window_days} />

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "heatmap" && (
        <div className="card">
          <div className="card-head">
            <h2>{heatRes === "day" ? "Load by day & hour" : "Load by hour & minute"}</h2>
            <div className="toggle">
              <button className={heatRes === "day" ? "active" : ""} onClick={() => setHeatRes("day")}>
                Day × Hour
              </button>
              <button className={heatRes === "minute" ? "active" : ""} onClick={() => setHeatRes("minute")}>
                Hour × Minute
              </button>
            </div>
          </div>
          <p className="hint">
            {heatRes === "day"
              ? `Darker/warmer = busier. Cool cells are open slots. Hours in ${data.meta.timezone}.`
              : `Rows are hours, columns minutes. Warmer = busier. Summed over ${data.meta.window_days} days (${data.meta.timezone}).`}
          </p>
          {heatRes === "day" ? (
            <Heatmap
              rows={data.heatmap.rows}
              hours={data.heatmap.hours}
              metric={metric}
              shortDay={shortDay}
              dayTitle={dayLabel}
              weekend={isWeekend}
              onHover={showTip}
              onLeave={hideTip}
            />
          ) : (
            <MinuteHeatmap points={minutePoints} unit={metric} onHover={showTip} onLeave={hideTip} />
          )}
          <div className="legend">
            <span className="swatch" style={{ background: "var(--heat-0)" }} />
            free
            <span className="swatch" style={{ background: "hsl(72,72%,58%)" }} />
            <span className="swatch" style={{ background: "hsl(0,72%,48%)" }} />
            busy
          </div>
        </div>
      )}

      {tab === "trends" && (
        <div className="stack">
          <div className="card">
            <h2>Load by day</h2>
            <p className="hint">{metric === "tasks" ? "Task" : "DAG"} runs planned per day (weekends muted).</p>
            <BarChart bars={dayBars} labelEvery={dayLabelEvery} unit={metric} onHover={showTip} onLeave={hideTip} />
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Load by time of day</h2>
              <div className="toggle">
                <button className={hourRes === "hour" ? "active" : ""} onClick={() => setHourRes("hour")}>
                  Hour
                </button>
                <button className={hourRes === "minute" ? "active" : ""} onClick={() => setHourRes("minute")}>
                  Minutes
                </button>
              </div>
            </div>
            <p className="hint">
              {hourRes === "hour"
                ? `Totals per hour across the ${data.meta.window_days}-day window (${data.meta.timezone}).`
                : `Totals per minute of the day across the ${data.meta.window_days}-day window (${data.meta.timezone}) — spikes on round minutes stand out.`}
            </p>
            {hourRes === "hour" ? (
              <BarChart bars={hourBars} unit={metric} onHover={showTip} onLeave={hideTip} />
            ) : (
              <LineChart points={minutePoints} unit={metric} onHover={showTip} onLeave={hideTip} />
            )}
          </div>
        </div>
      )}

      {tab === "tables" && (
        <div className="grid">
          <SortableTable
            title="Days"
            hint="Every day — quietest first. Click a header to re-sort."
            colHeader="Day"
            metric={metric}
            rows={data.days.map((d, i) => ({ key: d.date, label: dayLabel(d.date), order: i, dags: d.dags, tasks: d.tasks }))}
          />
          <SortableTable
            title="Time slots"
            hint={`Every minute of the day (${data.meta.timezone}), summed over ${data.meta.window_days} days — quietest first. Click a header to re-sort.`}
            colHeader="Time"
            metric={metric}
            rows={data.slots.map((s) => ({ key: s.label, label: s.label, order: s.minute, dags: s.dags, tasks: s.tasks }))}
          />
        </div>
      )}

      {tip && (
        <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
          {tip.text}
        </div>
      )}
    </div>
  );
}
