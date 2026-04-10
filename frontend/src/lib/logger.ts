type LogLevel = "debug" | "info" | "warn" | "error";

const LEVEL_PRIORITY: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

const LEVEL_STYLES: Record<LogLevel, string> = {
  debug: "color: #8b5cf6; font-weight: bold;",
  info: "color: #0ea5e9; font-weight: bold;",
  warn: "color: #f59e0b; font-weight: bold;",
  error: "color: #ef4444; font-weight: bold;",
};

const MIN_LEVEL: LogLevel =
  (process.env.NEXT_PUBLIC_LOG_LEVEL as LogLevel) || "debug";

function shouldLog(level: LogLevel): boolean {
  return LEVEL_PRIORITY[level] >= LEVEL_PRIORITY[MIN_LEVEL];
}

function formatTimestamp(): string {
  return new Date().toISOString().slice(11, 23);
}

function log(level: LogLevel, context: string, message: string, data?: unknown) {
  if (!shouldLog(level)) return;

  const ts = formatTimestamp();
  const prefix = `%c[${level.toUpperCase()}]%c ${ts} [${context}]`;
  const style1 = LEVEL_STYLES[level];
  const style2 = "color: inherit;";

  if (data !== undefined) {
    console[level === "debug" ? "log" : level](prefix, style1, style2, message, data);
  } else {
    console[level === "debug" ? "log" : level](prefix, style1, style2, message);
  }
}

export const logger = {
  debug: (context: string, message: string, data?: unknown) =>
    log("debug", context, message, data),
  info: (context: string, message: string, data?: unknown) =>
    log("info", context, message, data),
  warn: (context: string, message: string, data?: unknown) =>
    log("warn", context, message, data),
  error: (context: string, message: string, data?: unknown) =>
    log("error", context, message, data),

  /** Log an API request/response pair */
  api: (method: string, url: string, status?: number, duration?: number) => {
    const statusStr = status ? ` -> ${status}` : "";
    const durationStr = duration ? ` (${duration}ms)` : "";
    const level: LogLevel = status && status >= 400 ? "error" : "info";
    log(level, "API", `${method.toUpperCase()} ${url}${statusStr}${durationStr}`);
  },
};

export default logger;
