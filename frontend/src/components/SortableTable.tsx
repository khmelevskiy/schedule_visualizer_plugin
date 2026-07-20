import { useEffect, useMemo, useRef, useState } from "react";
import type { Metric } from "../api";

export interface SortRow {
  key: string;
  label: string;
  order: number; // natural order of the first column (day index / minute-of-day)
  dags: number;
  tasks: number;
}

type SortKey = "order" | "dags" | "tasks";

interface Props {
  title: string;
  hint: string;
  colHeader: string;
  rows: SortRow[];
  metric: Metric;
}

const ROW_HEIGHT = 33;
const MAX_BODY_HEIGHT = 306;
const OVERSCAN = 5;

export function SortableTable({ title, hint, colHeader, rows, metric }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>(metric);
  const [asc, setAsc] = useState(true);
  const [scrollTop, setScrollTop] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);

  // Follow the metric toggle while sorting by a metric column (quietest first).
  useEffect(() => {
    setSortKey((cur) => (cur === "order" ? cur : metric));
  }, [metric]);

  const sorted = useMemo(() => {
    const valueOf = (row: SortRow) => (sortKey === "dags" ? row.dags : sortKey === "tasks" ? row.tasks : row.order);
    return [...rows].sort((a, b) => {
      const cmp = valueOf(a) - valueOf(b) || a.order - b.order; // stable tiebreak by natural order
      return asc ? cmp : -cmp;
    });
  }, [rows, sortKey, asc]);

  useEffect(() => {
    setScrollTop(0);
    scroller.current?.scrollTo({ top: 0 });
  }, [sortKey, asc]);

  const onHeader = (key: SortKey) => {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(true);
    }
  };
  const arrow = (key: SortKey) => (key === sortKey ? (asc ? " ▲" : " ▼") : "");
  const bodyHeight = Math.min(MAX_BODY_HEIGHT, sorted.length * ROW_HEIGHT);
  const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const visibleCount = Math.ceil(bodyHeight / ROW_HEIGHT) + OVERSCAN * 2;
  const visible = sorted.slice(start, start + visibleCount);

  return (
    <div className="card">
      <h2>{title}</h2>
      <p className="hint">{hint}</p>
      <div className="virtual-table" role="table" aria-rowcount={sorted.length + 1}>
        <div className="virtual-table-head" role="row">
          <button className="sortable" role="columnheader" onClick={() => onHeader("order")}>
            {colHeader}{arrow("order")}
          </button>
          <button className="sortable num" role="columnheader" onClick={() => onHeader("dags")}>
            DAGs{arrow("dags")}
          </button>
          <button className="sortable num" role="columnheader" onClick={() => onHeader("tasks")}>
            Tasks{arrow("tasks")}
          </button>
        </div>
        <div
          className="table-scroll"
          ref={scroller}
          style={{ height: bodyHeight }}
          onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        >
          <div className="virtual-table-spacer" role="rowgroup" style={{ height: sorted.length * ROW_HEIGHT }}>
            {visible.map((row, index) => (
              <div
                className="virtual-table-row"
                role="row"
                aria-rowindex={start + index + 2}
                key={row.key}
                style={{ transform: `translateY(${(start + index) * ROW_HEIGHT}px)` }}
              >
                <span role="cell">{row.label}</span>
                <span className={`num ${metric === "dags" ? "selected" : ""}`} role="cell">{row.dags}</span>
                <span className={`num ${metric === "tasks" ? "selected" : ""}`} role="cell">{row.tasks}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
