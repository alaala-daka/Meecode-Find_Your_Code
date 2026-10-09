import * as React from "react";

import { getTraffic, type TrafficResponse, type YearSummary } from "@/api/traffic";
import { Button } from "@/components/ui/button";
import { Bar, CartesianGrid, ComposedChart, Line, Tooltip, XAxis, YAxis } from "recharts";

type View = "7d" | "30d" | "12m" | "year";

const VIEW_OPTIONS: { key: View; label: string }[] = [
  { key: "7d", label: "近 7 天" },
  { key: "30d", label: "近 30 天" },
  { key: "12m", label: "近 12 月" },
  { key: "year", label: "年度" },
];

const SUMMARY_CARDS: {
  key: "year_pv" | "daily_pv_avg" | "daily_uv_avg" | "new_users_year";
  label: string;
}[] = [
  { key: "year_pv", label: "年 PV 总量" },
  { key: "daily_pv_avg", label: "日均 PV" },
  { key: "daily_uv_avg", label: "日均 UV" },
  { key: "new_users_year", label: "年新增注册" },
];

export function TrafficPage() {
  const [view, setView] = React.useState<View>("7d");
  const [year, setYear] = React.useState(() => new Date().getFullYear());
  const [data, setData] = React.useState<TrafficResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    void getTraffic(view === "year" ? `year=${year}` : view)
      .then((resp) => {
        if (alive) setData(resp);
      })
      .catch((e: Error) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [view, year]);

  const days = data?.days;
  const months = data?.months;
  const summary: YearSummary | undefined = data?.summary;
  const chartData = days
    ? days.map((d) => ({ label: d.date.slice(5), pv: d.pv, uv: d.uv }))
    : (months ?? []).map((m) => ({ label: m.month, pv: m.pv, uv: m.uv_avg }));

  return (
    <section className="space-y-4">
      <header className="flex items-center gap-2">
        <h2 className="font-mono text-lg text-ink">站点流量</h2>
        <div className="ml-auto flex items-center gap-2">
          {view === "year" && (
            <>
              <Button type="button" variant="outline" size="sm" className="border-line"
                onClick={() => setYear((y) => y - 1)}>‹</Button>
              <span className="font-mono text-sm text-ink-2">{year}</span>
              <Button type="button" variant="outline" size="sm" className="border-line"
                onClick={() => setYear((y) => y + 1)}>›</Button>
            </>
          )}
          {VIEW_OPTIONS.map((o) => (
            <Button key={o.key} type="button" size="sm"
              variant={view === o.key ? "default" : "outline"}
              className={view === o.key ? "" : "border-line text-ink-2"}
              onClick={() => setView(o.key)}>
              {o.label}
            </Button>
          ))}
        </div>
      </header>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {loading && <p className="font-mono text-sm text-ink-3">加载中…</p>}

      {summary && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {SUMMARY_CARDS.map(({ key, label }) => (
            <div key={key} className="rounded-lg border border-line bg-surface p-5">
              <div className="text-sm text-ink-2">{label}</div>
              <div className="mt-2 font-mono text-2xl text-ink">{summary[key]}</div>
            </div>
          ))}
          <div className="rounded-lg border border-line bg-surface p-5">
            <div className="text-sm text-ink-2">峰值日</div>
            <div className="mt-2 font-mono text-2xl text-ink">
              {summary.peak_day
                ? `${summary.peak_day.date}（${summary.peak_day.pv}）`
                : "—"}
            </div>
          </div>
        </div>
      )}

      {chartData.length > 0 && (
        <div className="rounded-lg border border-line bg-surface p-5">
          <ComposedChart width={760} height={280} data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E7E2D8" />
            <XAxis dataKey="label" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip />
            <Bar dataKey="pv" name="PV" fill="#AE5139" />
            <Line type="monotone" dataKey="uv" name="UV" stroke="#313A45" />
          </ComposedChart>
        </div>
      )}
    </section>
  );
}

export default TrafficPage;
