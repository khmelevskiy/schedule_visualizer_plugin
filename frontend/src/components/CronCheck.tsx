import { useEffect, useState } from "react";
import { type Assessment, fetchAssess, type Metric } from "../api";
import { fmtNum } from "../format";

interface Props {
  metric: Metric;
  teams: string[];
  includePaused: boolean;
  timezone: string;
  cron: string;
  onCron: (cron: string) => void;
}

// 0 = red (busiest), 100 = green (empty).
const scoreColor = (score: number) => `hsl(${Math.round(score * 1.2)}, 65%, 42%)`;

// meta.timezone is always a valid zone name (currently "UTC").
const runLabel = (iso: string, timezone: string): string =>
  new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));

export function CronCheck({ metric, teams, includePaused, timezone, cron, onCron }: Props) {
  const [draft, setDraft] = useState(cron);
  const [result, setResult] = useState<Assessment | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [retry, setRetry] = useState(0);
  const normalized = draft.trim();
  const isAlias = normalized.startsWith("@");

  const updateDraft = (value: string) => {
    const nextNormalized = value.trim();
    setDraft(value);
    // A cosmetic trailing space is the same cron and keeps the current result.
    // A real edit invalidates stale output immediately; only the request waits
    // for the debounce below.
    if (nextNormalized !== normalized) {
      setResult(null);
      setStatus(nextNormalized ? "loading" : "idle");
    }
  };

  // The parent owns only the debounced/shareable URL value. Keystrokes stay
  // local so typing here cannot rerender charts or the 1440-slot table.
  useEffect(() => setDraft(cron), [cron]);

  // Debounced fetch: grade while typing without a request per keystroke.
  useEffect(() => {
    if (!normalized) {
      setResult(null);
      setStatus("idle");
      onCron("");
      return;
    }
    const controller = new AbortController();
    const t = setTimeout(() => {
      onCron(normalized);
      setStatus("loading");
      setResult(null);
      fetchAssess(normalized, { teams, metric, includePaused }, controller.signal)
        .then((assessment) => {
          setResult(assessment);
          setStatus("success");
        })
        .catch((error: unknown) => {
          if ((error as { name?: string }).name === "AbortError") return;
          setResult(null);
          setStatus("error");
        });
    }, 350);
    return () => {
      clearTimeout(t);
      controller.abort();
    };
  }, [normalized, teams, metric, includePaused, retry, onCron]);

  return (
    <div className="cron-check">
      <span className="control-label">Check a cron</span>
      <input
        type="text"
        value={draft}
        onChange={(e) => updateDraft(e.target.value)}
        placeholder={`e.g. 0 3 * * * (${timezone})`}
        spellCheck={false}
      />
      {isAlias && (
        <span className="cron-alias-hint">
          @-aliases fire at midnight / on the hour, right where load piles up — prefer an explicit cron with an offset
        </span>
      )}
      {normalized && status === "loading" && <span className="cron-status">checking…</span>}
      {normalized && status === "error" && (
        <span className="cron-error" role="alert">
          check failed
          <button
            type="button"
            onClick={() => {
              setStatus("loading");
              setRetry((value) => value + 1);
            }}
          >
            retry
          </button>
        </span>
      )}
      {normalized && status === "success" && result && !result.valid && (
        <span className="cron-invalid">not a valid cron (or never fires in the window)</span>
      )}
      {normalized && status === "success" && result?.valid && (
        <span className="cron-result">
          <span className="score" style={{ background: scoreColor(result.score) }}>
            {result.score}
          </span>
          {result.peak > 0
            ? `worst firing overlaps ~${fmtNum(result.peak)} ${metric} (${result.peak_label})`
            : "every firing lands on a free minute"}
          {" · fires "}
          {fmtNum(result.firings_per_week)}×/week
          {result.next_runs.length > 0 && (
            <span className="cron-next" tabIndex={0}>
              next runs
              <span className="cron-next-list" role="tooltip">
                {result.next_runs.map((iso) => (
                  <span key={iso}>{runLabel(iso, timezone)}</span>
                ))}
              </span>
            </span>
          )}
        </span>
      )}
    </div>
  );
}
