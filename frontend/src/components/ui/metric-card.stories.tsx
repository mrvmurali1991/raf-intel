import type { Meta, StoryObj } from "@storybook/react";
import { Activity, DollarSign, Users, TrendingUp, AlertTriangle } from "lucide-react";
import { MetricCard } from "./metric-card";

const meta: Meta<typeof MetricCard> = {
  title: "UI/MetricCard",
  component: MetricCard,
  tags: ["autodocs"],
  parameters: {
    layout: "padded",
    docs: {
      description: {
        component:
          "Single KPI card primitive. Replaces StatCard, KpiCard (RecaptureVelocityKpis), KpiCard (heatmap), and inline tiles in AdminDashboard.",
      },
    },
  },
  argTypes: {
    intent: {
      control: "select",
      options: ["default", "success", "warning", "danger"],
    },
    delta: { control: { type: "number", step: 0.1 } },
    loading: { control: "boolean" },
  },
};

export default meta;
type Story = StoryObj<typeof MetricCard>;

// ---------------------------------------------------------------------------
// Default / baseline
// ---------------------------------------------------------------------------

export const Default: Story = {
  args: {
    label: "Total Members",
    value: "2,847",
    subtitle: "Patients in system",
    icon: <Users size={20} />,
    intent: "default",
  },
};

// ---------------------------------------------------------------------------
// Intent variants — all four states side-by-side in docs
// ---------------------------------------------------------------------------

export const Intents: Story = {
  render: () => (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <MetricCard label="Default" value="1,024" subtitle="Baseline state" icon={<Activity size={18} />} intent="default" />
      <MetricCard label="Success" value="89%" subtitle="Coverage rate" icon={<TrendingUp size={18} />} intent="success" delta={5.3} />
      <MetricCard label="Warning" value="1.42" subtitle="Avg RAF score" icon={<AlertTriangle size={18} />} intent="warning" delta={-1.2} />
      <MetricCard label="Danger" value="412" subtitle="Overdue gaps" icon={<AlertTriangle size={18} />} intent="danger" delta={-8.7} />
    </div>
  ),
};

// ---------------------------------------------------------------------------
// With positive delta badge
// ---------------------------------------------------------------------------

export const PositiveDelta: Story = {
  args: {
    label: "Patients Analyzed",
    value: "1,203",
    subtitle: "vs prior 30d",
    icon: <Activity size={20} />,
    intent: "success",
    delta: 12.4,
  },
};

// ---------------------------------------------------------------------------
// With negative delta badge
// ---------------------------------------------------------------------------

export const NegativeDelta: Story = {
  args: {
    label: "Average RAF Score",
    value: "1.247",
    subtitle: "Moderate acuity",
    icon: <TrendingUp size={20} />,
    intent: "warning",
    delta: -3.1,
  },
};

// ---------------------------------------------------------------------------
// With inline sparkline
// ---------------------------------------------------------------------------

export const WithSparkline: Story = {
  args: {
    label: "Avg Days to Close",
    value: "18.4 days",
    subtitle: "Median 14.0 · 72% closed ≤30d",
    intent: "default",
    trend: [22, 20, 25, 18, 21, 17, 19, 15, 18, 14, 16, 18],
  },
};

// ---------------------------------------------------------------------------
// Revenue — hero-sized variant (controlled by parent grid span)
// ---------------------------------------------------------------------------

export const Revenue: Story = {
  args: {
    label: "Revenue Opportunity",
    value: "$4.2M",
    subtitle: "Estimated annual capture",
    icon: <DollarSign size={20} />,
    intent: "success",
    delta: 8.1,
    trend: [3.1, 3.4, 3.8, 4.0, 3.9, 4.2],
  },
};

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

export const Loading: Story = {
  args: {
    label: "Revenue Opportunity",
    value: "$0",
    loading: true,
  },
};

// ---------------------------------------------------------------------------
// Clickable (drill-down)
// ---------------------------------------------------------------------------

export const Clickable: Story = {
  args: {
    label: "Open Gaps",
    value: "412",
    subtitle: "Across 3 care programs",
    icon: <AlertTriangle size={20} />,
    intent: "danger",
    delta: -5.0,
    onClick: () => alert("Drill down triggered"),
  },
};

// ---------------------------------------------------------------------------
// All variants in a realistic 4-column KPI strip
// ---------------------------------------------------------------------------

export const KpiStrip: Story = {
  render: () => (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <MetricCard
        label="Revenue Opportunity"
        value="$4.2M"
        subtitle="Estimated annual capture"
        icon={<DollarSign size={20} />}
        intent="success"
        delta={8.1}
        trend={[3.1, 3.4, 3.8, 4.0, 3.9, 4.2]}
        href="/reports"
      />
      <MetricCard
        label="Total Members"
        value="2,847"
        subtitle="Patients in system"
        icon={<Users size={20} />}
        intent="default"
        href="/patients"
      />
      <MetricCard
        label="Patients Analyzed"
        value="2,203"
        subtitle="77% coverage"
        icon={<Activity size={20} />}
        intent="success"
        delta={12.4}
        href="/analysis"
      />
      <MetricCard
        label="Average RAF Score"
        value="1.247"
        subtitle="Moderate acuity"
        icon={<TrendingUp size={20} />}
        intent="warning"
        delta={-2.1}
        href="/reports?tab=raf-distribution"
      />
    </div>
  ),
};
