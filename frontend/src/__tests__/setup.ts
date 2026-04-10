/// <reference types="vitest/globals" />
import "@testing-library/jest-dom";

// Suppress noisy console errors from components that call real APIs
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    const msg = args[0];
    if (
      typeof msg === "string" &&
      (msg.includes("Warning:") ||
        msg.includes("ReactDOM.render") ||
        msg.includes("act("))
    ) {
      return;
    }
    originalError(...args);
  };
});
afterAll(() => {
  console.error = originalError;
});
