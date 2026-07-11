import { useEffect, useMemo, useState } from "react";
import { fetchSchedule, type Metric, type Schedule } from "./api";
import { BarChart } from "./components/BarChart";
import { type Aggregation, Controls } from "./components/Controls";
import { CronCheck } from "./components/CronCheck";
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

// View state lives in the URL (replaceState, no history spam) so a specific
// view — team, tab, slot resolution, even a cron being checked — is shareable.
const URL_DEFAULTS = { tab: "heatmap", metric: "tasks", values: "avg", heat: "day", hour: "hour", cadence: "daily" };

function fromUrl<T extends string>(key: keyof typeof URL_DEFAULTS, allowed: readonly T[]): T {
  const v = new URLSearchParams(window.location.search).get(key);
  return allowed.includes(v as T) ? (v as T) : (URL_DEFAULTS[key] as T);
}

export function App() {
  const [metric, setMetric] = useState<Metric>(() => fromUrl("metric", ["tasks", "dags"] as const));
  const [aggregation, setAggregation] = useState<Aggregation>(() => fromUrl("values", ["avg", "sum"] as const));
  const [selected, setSelected] = useState<string[]>(() => new URLSearchParams(window.location.search).getAll("team"));
  const [includePaused, setIncludePaused] = useState(() => new URLSearchParams(window.location.search).get("paused") === "1");
  const [tab, setTab] = useState<Tab>(() => fromUrl("tab", ["heatmap", "trends", "tables"] as const));
  const [heatRes, setHeatRes] = useState<"day" | "minute">(() => fromUrl("heat", ["day", "minute"] as const));
  const [hourRes, setHourRes] = useState<"hour" | "minute">(() => fromUrl("hour", ["hour", "minute"] as const));
  const [cadence, setCadence] = useState<string>(
    () => new URLSearchParams(window.location.search).get("cadence") ?? URL_DEFAULTS.cadence,
  );
  const [cron, setCron] = useState<string>(() => new URLSearchParams(window.location.search).get("cron") ?? "");
  const [data, setData] = useState<Schedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);

  const showTip = (text: string, cursor: { clientX: number; clientY: number }) =>
    setTip({ text, x: cursor.clientX, y: cursor.clientY });
  const hideTip = () => setTip(null);

  useEffect(() => {
    const q = new URLSearchParams();
    if (tab !== URL_DEFAULTS.tab) q.set("tab", tab);
    if (metric !== URL_DEFAULTS.metric) q.set("metric", metric);
    if (aggregation !== URL_DEFAULTS.values) q.set("values", aggregation);
    if (includePaused) q.set("paused", "1");
    for (const team of selected) q.append("team", team);
    if (heatRes !== URL_DEFAULTS.heat) q.set("heat", heatRes);
    if (hourRes !== URL_DEFAULTS.hour) q.set("hour", hourRes);
    if (cadence !== URL_DEFAULTS.cadence) q.set("cadence", cadence);
    if (cron.trim()) q.set("cron", cron.trim());
    const qs = q.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [tab, metric, aggregation, includePaused, selected, heatRes, hourRes, cadence, cron]);

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
  // Time-of-day series sum the whole window; "avg" rescales them to one
  // average day so the numbers match intuition ("18 tasks at 09:00", not
  // "558 tasks over 31 days"). Day-keyed views are real calendar days and
  // are never rescaled.
  const windowDays = data?.meta.window_days ?? 1;
  const scale = (v: number) => (aggregation === "avg" ? Math.round((v / windowDays) * 10) / 10 : v);
  const hourBars = useMemo(
    () =>
      data?.hours.map((h) => ({
        label: String(h.hour),
        title: `${String(h.hour).padStart(2, "0")}:00`,
        value: scale(metricOf(h, metric)),
      })) ?? [],
    [data, metric, aggregation],
  );
  // One value per minute-of-day (slots is all 1440, minute-ordered) — reused by
  // the minute line and the hour×minute heatmap.
  const minutePoints = useMemo(
    () => data?.slots.map((s) => scale(metricOf(s, metric))) ?? [],
    [data, metric, aggregation],
  );

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
        aggregation={aggregation}
        onAggregation={setAggregation}
        windowDays={data.meta.window_days}
        teams={data.meta.teams}
        selected={selected}
        onToggleTeam={toggleTeam}
        onClearTeams={() => setSelected([])}
        includePaused={includePaused}
        onIncludePaused={setIncludePaused}
      />

      <Suggest
        suggestions={data.suggestions}
        metric={metric}
        timezone={data.meta.timezone}
        cadence={cadence}
        onCadence={setCadence}
      >
        <CronCheck
          metric={metric}
          teams={selected}
          includePaused={includePaused}
          timezone={data.meta.timezone}
          cron={cron}
          onCron={setCron}
        />
      </Suggest>

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
              : `Rows are hours, columns minutes. Warmer = busier. ${
                  aggregation === "avg"
                    ? `Average day (${data.meta.timezone}).`
                    : `Summed over ${data.meta.window_days} days (${data.meta.timezone}).`
                }`}
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
                ? aggregation === "avg"
                  ? `Average day, per hour (${data.meta.timezone}).`
                  : `Totals per hour across the ${data.meta.window_days}-day window (${data.meta.timezone}).`
                : aggregation === "avg"
                  ? `Average day, per minute (${data.meta.timezone}) — spikes on round minutes stand out.`
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
            hint="Every day — quietest first. Actual per-day totals, so the Avg/Sum toggle does not apply here. Click a header to re-sort."
            colHeader="Day"
            metric={metric}
            rows={data.days.map((d, i) => ({ key: d.date, label: dayLabel(d.date), order: i, dags: d.dags, tasks: d.tasks }))}
          />
          <SortableTable
            title="Time slots"
            hint={`Every minute of the day (${data.meta.timezone}), ${
              aggregation === "avg" ? "average day" : `summed over ${data.meta.window_days} days`
            } — quietest first. Click a header to re-sort.`}
            colHeader="Time"
            metric={metric}
            rows={data.slots.map((s) => ({
              key: s.label,
              label: s.label,
              order: s.minute,
              dags: scale(s.dags),
              tasks: scale(s.tasks),
            }))}
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
