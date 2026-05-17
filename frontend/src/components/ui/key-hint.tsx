/**
 * KeyHint — renders a keyboard shortcut affordance badge inline with button labels.
 *
 * Usage:
 *   <Button size="sm">Accept <KeyHint>A</KeyHint></Button>
 *   <Button size="sm">Dismiss <KeyHint>D</KeyHint></Button>
 */

import React from "react";

export function KeyHint({ children }: { children: React.ReactNode }) {
  return (
    <kbd
      aria-label={`keyboard shortcut: ${children}`}
      style={{
        display: "inline-block",
        marginLeft: 5,
        padding: "1px 4px",
        fontSize: 10,
        fontFamily: "monospace",
        fontWeight: 600,
        lineHeight: 1.4,
        border: "1px solid rgba(0,0,0,0.18)",
        borderRadius: 3,
        background: "rgba(0,0,0,0.06)",
        color: "inherit",
        opacity: 0.75,
        verticalAlign: "middle",
      }}
    >
      {children}
    </kbd>
  );
}
