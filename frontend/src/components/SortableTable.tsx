import { useEffect, useState } from "react";
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

export function SortableTable({ title, hint, colHeader, rows, metric }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>(metric);
  const [asc, setAsc] = useState(true);

  // Follow the metric toggle while sorting by a metric column (quietest first).
  useEffect(() => {
    setSortKey((cur) => (cur === "order" ? cur : metric));
  }, [metric]);

  const valueOf = (r: SortRow) => (sortKey === "dags" ? r.dags : sortKey === "tasks" ? r.tasks : r.order);
  const sorted = [...rows].sort((a, b) => {
    const cmp = valueOf(a) - valueOf(b) || a.order - b.order; // stable tiebreak by natural order
    return asc ? cmp : -cmp;
  });

  const onHeader = (key: SortKey) => {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(true);
    }
  };
  const arrow = (key: SortKey) => (key === sortKey ? (asc ? " ▲" : " ▼") : "");
  const bold = (key: Metric) => (metric === key ? { fontWeight: 600 } : undefined);

  return (
    <div className="card">
      <h2>{title}</h2>
      <p className="hint">{hint}</p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="sortable" onClick={() => onHeader("order")}>
                {colHeader}
                {arrow("order")}
              </th>
              <th className="sortable num" onClick={() => onHeader("dags")}>
                DAGs{arrow("dags")}
              </th>
              <th className="sortable num" onClick={() => onHeader("tasks")}>
                Tasks{arrow("tasks")}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td className="num" style={bold("dags")}>
                  {row.dags}
                </td>
                <td className="num" style={bold("tasks")}>
                  {row.tasks}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
