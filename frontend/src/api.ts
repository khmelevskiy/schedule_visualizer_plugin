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
}

// Relative path so it resolves under any mount prefix.
export async function fetchSchedule(params: { teams: string[]; metric: Metric; includePaused: boolean }): Promise<Schedule> {
  const query = new URLSearchParams();
  query.set("metric", params.metric);
  if (params.includePaused) query.set("include_paused", "true");
  for (const team of params.teams) query.append("team", team);
  const res = await fetch(`api/schedule?${query.toString()}`);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}
