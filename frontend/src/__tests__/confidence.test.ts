import { describe, expect, it } from "vitest";

import {
  CONFIDENCE_HIGH_MIN,
  CONFIDENCE_METHODOLOGY,
  CONFIDENCE_MODERATE_MIN,
  confidenceTier,
} from "@/lib/confidence";

describe("confidenceTier", () => {
  it("classifies the top of the low band", () => {
    expect(confidenceTier(CONFIDENCE_MODERATE_MIN - 1).tone).toBe("low");
  });

  it("classifies the bottom of the moderate band", () => {
    expect(confidenceTier(CONFIDENCE_MODERATE_MIN).tone).toBe("moderate");
  });

  it("classifies the top of the moderate band", () => {
    expect(confidenceTier(CONFIDENCE_HIGH_MIN - 1).tone).toBe("moderate");
  });

  it("classifies the bottom of the high band", () => {
    expect(confidenceTier(CONFIDENCE_HIGH_MIN).tone).toBe("high");
  });

  it("classifies a very high score", () => {
    expect(confidenceTier(100).tone).toBe("high");
  });

  it("classifies a very low score", () => {
    expect(confidenceTier(0).tone).toBe("low");
  });

  it("returns consistent metadata for the high tier", () => {
    const tier = confidenceTier(95);
    expect(tier.label).toBe("High confidence");
    expect(tier.color).toBe("emerald");
    expect(tier.bar).toContain("emerald");
    expect(tier.ring).toContain("emerald");
  });

  it("returns consistent metadata for the moderate tier", () => {
    const tier = confidenceTier(75);
    expect(tier.label).toBe("Moderate confidence");
    expect(tier.color).toBe("amber");
    expect(tier.bar).toContain("amber");
  });

  it("returns consistent metadata for the low tier", () => {
    const tier = confidenceTier(40);
    expect(tier.label).toBe("Low confidence");
    expect(tier.color).toBe("red");
    expect(tier.bar).toContain("red");
  });
});

describe("CONFIDENCE_METHODOLOGY", () => {
  it("references both thresholds so the tooltip can never drift", () => {
    expect(CONFIDENCE_METHODOLOGY).toContain(String(CONFIDENCE_HIGH_MIN));
    expect(CONFIDENCE_METHODOLOGY).toContain(String(CONFIDENCE_MODERATE_MIN));
  });

  it("reminds clinicians this is a decision aid, not a diagnosis", () => {
    expect(CONFIDENCE_METHODOLOGY.toLowerCase()).toContain("decision aid");
    expect(CONFIDENCE_METHODOLOGY.toLowerCase()).toContain("not a diagnosis");
  });

  it("uses ASCII only for hospital-browser compatibility", () => {
    // Reject any non-ASCII character so smart punctuation / math symbols can't sneak back in.
    expect(CONFIDENCE_METHODOLOGY).toMatch(/^[\x20-\x7e]+$/);
  });
});
