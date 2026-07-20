export type Metric = "dags" | "tasks";

export interface Counts {
  dags: number;
  tasks: number;
}

export interface DayCounts extends Counts {
  date: string;
}

export interface HourCounts extends Counts {
  hour: number;
}

export interface SlotCounts extends Counts {
  minute: number;
  label: string;
}

export interface HeatmapRow {
  date: string;
  cells: Counts[];
}

export interface SuggestionOption extends Counts {
  label: string;
  cron: string;
  /** How many times this slot fires within the window (divide sums by it for per-firing load). */
  occurrences: number;
}

export interface CadenceSuggestions {
  cadence: string;
  label: string;
  options: SuggestionOption[];
}

export interface Schedule {
  window: { start: string; end: string };
  meta: {
    updated_at: string;
    next_refresh: string;
    teams: (string | null)[];
    timezone: string;
    window_days: number;
  };
  selected_teams: string[] | null;
  metric: Metric;
  days: DayCounts[];
  hours: HourCounts[];
  slots: SlotCounts[];
  heatmap: { hours: number[]; rows: HeatmapRow[] };
  suggestions: CadenceSuggestions[];
  suggestions_by_metric: Record<Metric, CadenceSuggestions[]>;
}

export type Assessment =
  | { valid: false }
  | {
      valid: true;
      score: number; // 0 busiest .. 100 empty
      peak: number;
      peak_label: string;
      average: number;
      firings_per_week: number;
      /** ISO instants of the next five firings, from "now". */
      next_runs: string[];
    };

function query(params: { teams: string[]; metric: Metric; includePaused: boolean }): URLSearchParams {
  const q = new URLSearchParams();
  q.set("metric", params.metric);
  if (params.includePaused) q.set("include_paused", "true");
  for (const team of params.teams) q.append("team", team);
  return q;
}

// Relative paths so they resolve under any mount prefix.
export async function fetchSchedule(
  params: { teams: string[]; metric: Metric; includePaused: boolean },
  signal?: AbortSignal,
): Promise<Schedule> {
  const res = await fetch(`api/schedule?${query(params).toString()}`, { signal });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

export async function fetchAssess(
  cron: string,
  params: { teams: string[]; metric: Metric; includePaused: boolean },
  signal?: AbortSignal,
): Promise<Assessment> {
  const q = query(params);
  q.set("cron", cron);
  const res = await fetch(`api/assess?${q.toString()}`, { signal });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}
