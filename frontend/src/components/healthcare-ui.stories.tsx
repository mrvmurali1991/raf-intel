import type { Meta, StoryObj } from "@storybook/react";
import { StatCard, PageHeader, SectionHeader, EmptyState } from "./healthcare-ui";
import { Activity, Users, DollarSign, FileText } from "lucide-react";

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------

const statMeta: Meta<typeof StatCard> = {
  title: "Healthcare UI/StatCard",
  component: StatCard,
  tags: ["autodocs"],
};
export default statMeta;

type StatStory = StoryObj<typeof StatCard>;

export const Default: StatStory = {
  args: {
    label: "Total Patients",
    value: "1,234",
    subtitle: "+12% from last month",
    icon: <Users className="h-5 w-5" />,
    accentClassName: "text-primary bg-primary/10",
  },
};

export const WithTrend: StatStory = {
  args: {
    label: "Average RAF Score",
    value: "1.247",
    icon: <Activity className="h-5 w-5" />,
    trend: { value: 8.2, label: "vs last quarter" },
    accentClassName: "text-primary bg-primary/10",
  },
};

export const Loading: StatStory = {
  args: {
    label: "Revenue Opportunity",
    value: "$0",
    loading: true,
  },
};

export const WithLink: StatStory = {
  args: {
    label: "Open Documents",
    value: "42",
    icon: <FileText className="h-5 w-5" />,
    href: "/documents",
    accentClassName: "text-warning bg-warning/15",
  },
};

// ---------------------------------------------------------------------------
// PageHeader (separate file export for co-location)
// ---------------------------------------------------------------------------

export const PageHeaderStory: StoryObj<typeof PageHeader> = {
  name: "PageHeader",
  render: () => (
    <PageHeader
      title="Patient Dashboard"
      subtitle="Monitor risk scores and care gaps across your population"
      /* badge="Beta" — omitted; PageHeader does not have a badge prop */
    />
  ),
};

// ---------------------------------------------------------------------------
// SectionHeader
// ---------------------------------------------------------------------------

export const SectionHeaderStory: StoryObj<typeof SectionHeader> = {
  name: "SectionHeader",
  render: () => <SectionHeader title="Recent Activity" count={24} />,
};

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

export const EmptyStateStory: StoryObj<typeof EmptyState> = {
  name: "EmptyState",
  render: () => (
    <EmptyState
      icon={<FileText className="h-12 w-12" />}
      title="No documents yet"
      description="Upload clinical notes to begin HCC extraction and RAF scoring."
    />
  ),
};
