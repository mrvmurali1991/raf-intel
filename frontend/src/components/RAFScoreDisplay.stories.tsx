import type { Meta, StoryObj } from "@storybook/react";
import { RAFScoreDisplay } from "./RAFScoreDisplay";

const meta: Meta<typeof RAFScoreDisplay> = {
  title: "Healthcare UI/RAFScoreDisplay",
  component: RAFScoreDisplay,
  tags: ["autodocs"],
};
export default meta;

type Story = StoryObj<typeof RAFScoreDisplay>;

export const LowRisk: Story = {
  args: { score: 0.543, size: "lg" },
};

export const MediumRisk: Story = {
  args: { score: 1.247, size: "lg" },
};

export const HighRisk: Story = {
  args: { score: 2.891, size: "lg" },
};

export const SmallVariant: Story = {
  args: { score: 1.123, size: "sm" },
};
