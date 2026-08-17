import { PerformanceDashboard } from "../../types";
import {
  ActivityCalendar,
  ChartCard,
  DailyLineChart,
  DomainBarChart,
  fmtNum,
  fmtSec,
  HourHeatmap,
  KpiCard,
  ProgressRing,
  Section,
  StatusPieChart,
  WeeklyBarChart,
} from "./Charts";

/** Lean dashboard: assignment progress + essentials + charts only. */
export default function PerformanceDashboardView({
  data,
  compact = false,
}: {
  data: PerformanceDashboard;
  compact?: boolean;
}) {
  const { progress, quality, charts, profile } = data;
  const skipped = progress.skipped ?? data.kpis.skipped ?? 0;

  return (
    <div className={`dash-root ${compact ? "compact" : ""}`}>
      <Section title="Progress" subtitle={profile.dataset_name || "Assigned dataset"}>
        <div className="dash-progress-row">
          <ProgressRing percent={progress.percent} />
          <div className="dash-kpi-grid">
            <KpiCard label="Dataset" value={profile.dataset_name || "—"} />
            <KpiCard label="Assigned scripts" value={fmtNum(progress.assigned)} />
            <KpiCard label="Finished" value={fmtNum(progress.completed)} tone="ok" />
            <KpiCard label="Remaining" value={fmtNum(progress.remaining)} tone="warn" />
            <KpiCard label="Skipped / deleted" value={fmtNum(skipped)} tone="bad" />
            <KpiCard
              label="Est. time left"
              value={fmtSec(progress.estimated_remaining_sec)}
              hint={`${fmtNum(progress.percent, 0)}% complete`}
            />
          </div>
        </div>
      </Section>

      <Section title="Recording status">
        <div className="dash-kpi-grid">
          <KpiCard label="Accepted clips" value={fmtNum(quality.accepted)} tone="ok" />
          <KpiCard label="Pending review" value={fmtNum(quality.pending)} tone="warn" />
          <KpiCard label="Rejected" value={fmtNum(quality.rejected)} tone="bad" />
          <KpiCard label="Total takes" value={fmtNum(quality.total)} />
          <KpiCard label="Acceptance %" value={`${fmtNum(quality.acceptance_rate, 1)}%`} />
          <KpiCard
            label="Time recorded"
            value={(() => {
              const rawHours = Number(data?.productivity?.hours_recorded) || 0;
              const totalSec = Math.round(rawHours * 3600);
              const mins = Math.floor(totalSec / 60);
              const secs = totalSec % 60;
              return `${mins}m ${secs.toString().padStart(2, "0")}s`;
            })()}
          />
        </div>
      </Section>

      {!compact && (
        <Section title="Charts">
          <div className="dash-chart-grid">
            <ChartCard title="Daily recordings">
              <DailyLineChart data={charts.daily_recordings} />
            </ChartCard>
            <ChartCard title="Weekly productivity">
              <WeeklyBarChart data={charts.weekly_productivity} />
            </ChartCard>
            <ChartCard title="Accepted vs rejected">
              <StatusPieChart data={charts.accepted_vs_rejected} />
            </ChartCard>
            <ChartCard title="Contribution by domain">
              <DomainBarChart data={charts.dataset_contribution} />
            </ChartCard>
            <ChartCard title="Activity calendar">
              <ActivityCalendar data={charts.activity_calendar} />
            </ChartCard>
            <ChartCard title="Recording by hour">
              <HourHeatmap data={charts.hour_heatmap} />
            </ChartCard>
          </div>
        </Section>
      )}
    </div>
  );
}
