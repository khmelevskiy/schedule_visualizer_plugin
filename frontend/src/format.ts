import type { Counts, Metric } from "./api";

export const metricOf = (c: Counts, metric: Metric): number => (metric === "tasks" ? c.tasks : c.dags);

const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Dates from the API are plain calendar days (YYYY-MM-DD) — parse as UTC to
// avoid a local-timezone shift moving them to the previous day.
const parseDay = (iso: string): Date => new Date(`${iso}T00:00:00Z`);

export function dayLabel(iso: string): string {
  const d = parseDay(iso);
  return `${WEEKDAY[d.getUTCDay()]} ${d.getUTCDate()} ${MONTH[d.getUTCMonth()]}`;
}

export function shortDay(iso: string): string {
  const d = parseDay(iso);
  return `${d.getUTCDate()}`;
}

export function isWeekend(iso: string): boolean {
  const day = parseDay(iso).getUTCDay();
  return day === 0 || day === 6;
}

export function timeAgo(iso: string, now: Date = new Date()): string {
  const diff = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  return `${Math.floor(diff / 3600)} h ago`;
}

export function untilLabel(iso: string, now: Date = new Date()): string {
  const diff = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  if (diff <= 0) return "due";
  if (diff < 3600) return `in ${Math.ceil(diff / 60)} min`;
  return `in ${Math.floor(diff / 3600)} h`;
}

export const teamLabel = (team: string | null): string => team ?? "untagged";

// Minute-of-day (0..1439) → "HH:MM".
export const hhmm = (minute: number): string =>
  `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;

// Averages can be fractional: keep one decimal while it matters, drop it once
// the integer part dominates ("0.3", "7.5", but "18" and "120").
export function fmtNum(value: number): string {
  if (Number.isInteger(value)) return String(value);
  return value < 10 ? value.toFixed(1) : String(Math.round(value));
}
