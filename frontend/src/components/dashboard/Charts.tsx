import { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TrendPoint } from "../../types";

const PIE_COLORS = ["#1e9e57", "#e30613", "#c07800"];

function formatDuration(sec: number): string {
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h}h ${m.toString().padStart(2, "0")}m`;
  return `${m}m ${(s % 60).toString().padStart(2, "0")}s`;
}

export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits > 0 ? Math.min(digits, 1) : 0,
  });
}

export function fmtSec(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return formatDuration(n);
}

export function KpiCard({
  label,
  value,
  hint,
  tone,
  trend,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "ok" | "warn" | "bad" | "neutral";
  trend?: TrendPoint | null;
}) {
  const display =
    value === null || value === undefined || value === "" ? "—" : value;
  return (
    <div className={`dash-kpi lift ${tone || "neutral"}`}>
      <div className="dash-kpi-label">{label}</div>
      <div className="dash-kpi-value">{display}</div>
      {hint && <div className="dash-kpi-hint muted small">{hint}</div>}
      {trend && <TrendBadge trend={trend} />}
    </div>
  );
}

export function TrendBadge({ trend }: { trend: TrendPoint }) {
  const arrow =
    trend.direction === "improving" ? "↑" : trend.direction === "declining" ? "↓" : "→";
  const cls =
    trend.direction === "improving" ? "ok" : trend.direction === "declining" ? "bad" : "off";
  return (
    <span className={`chip ${cls} dash-trend`}>
      {arrow}{" "}
      {trend.delta === null || trend.delta === undefined
        ? trend.direction
        : `${trend.delta > 0 ? "+" : ""}${fmtNum(trend.delta, 1)}`}
    </span>
  );
}

export function ProgressRing({ percent, size = 88 }: { percent: number; size?: number }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, percent));
  const offset = c - (pct / 100) * c;
  return (
    <svg className="dash-ring" width={size} height={size} viewBox="0 0 80 80">
      <circle cx="40" cy="40" r={r} className="dash-ring-bg" />
      <circle
        cx="40"
        cy="40"
        r={r}
        className="dash-ring-fg"
        strokeDasharray={c}
        strokeDashoffset={offset}
      />
      <text x="40" y="44" textAnchor="middle" className="dash-ring-text">
        {Math.round(pct)}%
      </text>
    </svg>
  );
}

export function Section({
  title,
  subtitle,
  children,
  actions,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="dash-section panel fade-in">
      <div className="row spread dash-section-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p className="muted small">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function InsightBadges({
  items,
}: {
  items: { level: string; message: string; code?: string }[];
}) {
  return (
    <div className="dash-insight-row">
      {items.map((i) => (
        <span key={i.code || i.message} className={`chip dash-insight ${i.level === "success" ? "ok" : i.level === "warn" ? "warn" : "accent"}`}>
          {i.message}
        </span>
      ))}
    </div>
  );
}

export function AchievementGrid({
  items,
}: {
  items: { icon: string; title: string; earned: boolean; detail?: string }[];
}) {
  return (
    <div className="dash-achieve-grid">
      {items.map((a) => (
        <div key={a.title} className={`dash-achieve ${a.earned ? "earned" : "locked"}`}>
          <span className="dash-achieve-icon">{a.icon}</span>
          <div>
            <div className="dash-achieve-title">{a.title}</div>
            {a.detail && <div className="muted small">{a.detail}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="dash-chart-card">
      <h3>{title}</h3>
      <div className="dash-chart-body">{children}</div>
    </div>
  );
}

export function DailyLineChart({ data }: { data: { date: string; count: number }[] }) {
  if (!data.length) return <EmptyChart />;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={24} />
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
        <Tooltip />
        <Line type="monotone" dataKey="count" stroke="var(--accent)" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function WeeklyBarChart({ data }: { data: { week: string; count: number }[] }) {
  if (!data.length) return <EmptyChart />;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="week" tick={{ fontSize: 11 }} minTickGap={16} />
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
        <Tooltip />
        <Bar dataKey="count" fill="var(--accent)" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function StatusPieChart({
  data,
}: {
  data: { accepted: number; rejected: number; pending: number };
}) {
  const rows = [
    { name: "Accepted", value: data.accepted },
    { name: "Rejected", value: data.rejected },
    { name: "Pending", value: data.pending },
  ].filter((r) => r.value > 0);
  if (!rows.length) return <EmptyChart />;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie data={rows} dataKey="value" nameKey="name" innerRadius={48} outerRadius={78} paddingAngle={2}>
          {rows.map((_, i) => (
            <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function QcLineChart({ data }: { data: { date: string; avg_qc_score: number }[] }) {
  if (!data.length) return <EmptyChart />;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={24} />
        <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} width={32} />
        <Tooltip />
        <Line type="monotone" dataKey="avg_qc_score" stroke="#1e9e57" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function DurationHistChart({ data }: { data: { bucket: string; count: number }[] }) {
  if (!data.some((d) => d.count > 0)) return <EmptyChart />;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
        <Tooltip />
        <Bar dataKey="count" fill="#c07800" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function DomainBarChart({ data }: { data: { domain: string; count: number }[] }) {
  if (!data.length) return <EmptyChart />;
  const rows = data.map((d) => ({ ...d, domain: d.domain.replace(/_/g, " ") }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
        <YAxis type="category" dataKey="domain" width={100} tick={{ fontSize: 11 }} />
        <Tooltip />
        <Bar dataKey="count" fill="var(--accent)" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ActivityCalendar({ data }: { data: { date: string; count: number }[] }) {
  if (!data.length) return <EmptyChart />;
  const max = Math.max(...data.map((d) => d.count), 1);
  const byDate = new Map(data.map((d) => [d.date, d.count]));
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 119);
  const days: { date: string; count: number }[] = [];
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const key = d.toISOString().slice(0, 10);
    days.push({ date: key, count: byDate.get(key) || 0 });
  }
  return (
    <div className="dash-calendar" title="Recording activity (last ~17 weeks)">
      {days.map((d) => {
        const level = d.count === 0 ? 0 : Math.min(4, Math.ceil((d.count / max) * 4));
        return (
          <span
            key={d.date}
            className={`dash-cal-cell l${level}`}
            title={`${d.date}: ${d.count}`}
          />
        );
      })}
    </div>
  );
}

export function HourHeatmap({
  data,
}: {
  data: { weekday: number; hour: number; count: number }[];
}) {
  if (!data.length) return <EmptyChart />;
  const max = Math.max(...data.map((d) => d.count), 1);
  const map = new Map(data.map((d) => [`${d.weekday}-${d.hour}`, d.count]));
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div className="dash-heatmap">
      <div className="dash-heatmap-spacer" />
      {Array.from({ length: 24 }, (_, h) => (
        <div key={h} className="dash-heatmap-hlabel">
          {h % 6 === 0 ? h : ""}
        </div>
      ))}
      {days.map((label, dow) => (
        <div key={label} className="dash-heatmap-row">
          <div className="dash-heatmap-dlabel">{label}</div>
          {Array.from({ length: 24 }, (_, hour) => {
            const count = map.get(`${dow}-${hour}`) || 0;
            const level = count === 0 ? 0 : Math.min(4, Math.ceil((count / max) * 4));
            return (
              <span
                key={hour}
                className={`dash-heat-cell l${level}`}
                title={`${label} ${hour}:00 — ${count}`}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

function EmptyChart() {
  return <div className="dash-empty muted small">No data yet for this chart.</div>;
}
