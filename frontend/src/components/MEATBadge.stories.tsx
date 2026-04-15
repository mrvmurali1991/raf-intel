import type { Meta, StoryObj } from "@storybook/react";
import { MEATBadge } from "./MEATBadge";
import { TooltipProvider } from "@/components/ui/tooltip";

const meta: Meta<typeof MEATBadge> = {
  title: "Healthcare UI/MEATBadge",
  component: MEATBadge,
  tags: ["autodocs"],
  decorators: [
    (Story: React.ComponentType) => (
      <TooltipProvider>
        <Story />
      </TooltipProvider>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof MEATBadge>;

export const AllPresent: Story = {
  args: {
    evidence: {
      monitor: "Blood pressure tracked weekly",
      evaluate: "Labs reviewed and compared to baseline",
      assess: "Condition stable, no progression",
      treat: "Continued metformin 500mg BID",
    },
  },
};

export const Partial: Story = {
  args: {
    evidence: {
      monitor: "Weight monitored",
      evaluate: null,
      assess: "Obesity class II",
      treat: null,
    },
  },
};

export const NoEvidence: Story = {
  args: {
    evidence: undefined,
  },
};
