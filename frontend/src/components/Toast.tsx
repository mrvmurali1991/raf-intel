"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  type ReactNode,
} from "react";
import { CheckCircle2, AlertTriangle, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastType = "success" | "error" | "warning" | "info";

interface ToastAction {
  label: string;
  onClick: () => void;
}

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  action?: ToastAction;
  createdAt: number;
  duration: number;
}

interface ToastContextValue {
  toast: (type: ToastType, title: string, message?: string, action?: ToastAction) => void;
  success: (title: string, message?: string, action?: ToastAction) => void;
  error: (title: string, message?: string, action?: ToastAction) => void;
  warning: (title: string, message?: string, action?: ToastAction) => void;
  info: (title: string, message?: string, action?: ToastAction) => void;
}

const ToastContext = createContext<ToastContextValue>({
  toast: () => {},
  success: () => {},
  error: () => {},
  warning: () => {},
  info: () => {},
});

const icons: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const styles: Record<ToastType, string> = {
  success:
    "border-l-4 border-l-emerald-500 border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-l-emerald-400 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100",
  error:
    "border-l-4 border-l-red-500 border-red-200 bg-red-50 text-red-900 dark:border-l-red-400 dark:border-red-800 dark:bg-red-950 dark:text-red-100",
  warning:
    "border-l-4 border-l-amber-500 border-amber-200 bg-amber-50 text-amber-900 dark:border-l-amber-400 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100",
  info: "border-l-4 border-l-blue-500 border-blue-200 bg-blue-50 text-blue-900 dark:border-l-blue-400 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100",
};

const iconStyles: Record<ToastType, string> = {
  success: "text-emerald-600 dark:text-emerald-400",
  error: "text-red-600 dark:text-red-400",
  warning: "text-amber-600 dark:text-amber-400",
  info: "text-blue-600 dark:text-blue-400",
};

const progressBarColors: Record<ToastType, string> = {
  success: "bg-emerald-500 dark:bg-emerald-400",
  error: "bg-red-500 dark:bg-red-400",
  warning: "bg-amber-500 dark:bg-amber-400",
  info: "bg-blue-500 dark:bg-blue-400",
};

const DURATION_DEFAULT = 4000;
const DURATION_ERROR = 6000;
const MAX_VISIBLE = 3;

/* ---------- Individual toast with pause-on-hover + progress bar ---------- */

function ToastItem({
  t,
  onDismiss,
}: {
  t: Toast;
  onDismiss: (id: string) => void;
}) {
  const Icon = icons[t.type];
  const [progress, setProgress] = useState(100);
  const startRef = useRef(t.createdAt);
  const remainingRef = useRef(t.duration);
  const pausedRef = useRef(false);
  const rafRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const tick = () => {
      if (pausedRef.current) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }
      const elapsed = Date.now() - startRef.current;
      const pct = Math.max(0, 100 - (elapsed / t.duration) * 100);
      setProgress(pct);
      if (pct <= 0) {
        onDismiss(t.id);
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [t.id, t.duration, onDismiss]);

  // Also keep a setTimeout as a fallback for exact dismissal
  useEffect(() => {
    timerRef.current = setTimeout(() => onDismiss(t.id), remainingRef.current);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [t.id, onDismiss]);

  const handleMouseEnter = () => {
    pausedRef.current = true;
    // Clear the fallback timer
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    remainingRef.current = (progress / 100) * t.duration;
  };

  const handleMouseLeave = () => {
    pausedRef.current = false;
    startRef.current = Date.now() - ((100 - progress) / 100) * t.duration;
    // Restart fallback timer with remaining time
    timerRef.current = setTimeout(() => onDismiss(t.id), remainingRef.current);
  };

  return (
    <div
      className={cn(
        "pointer-events-auto flex flex-col rounded-xl border backdrop-blur-sm premium-shadow animate-slide-up overflow-hidden",
        "animate-in slide-in-from-right-5 fade-in duration-300",
        "min-w-[320px] max-w-[420px]",
        styles[t.type]
      )}
      role={t.type === "error" ? "alert" : "status"}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div className="flex items-start gap-3 px-4 py-3">
        <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", iconStyles[t.type])} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold">{t.title}</p>
          {t.message && (
            <p className="mt-0.5 text-xs opacity-80">{t.message}</p>
          )}
        </div>
        {t.action && (
          <button
            onClick={() => {
              t.action!.onClick();
              onDismiss(t.id);
            }}
            className="shrink-0 text-xs font-semibold px-2 py-1 rounded-md hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
            aria-label={t.action.label}
          >
            {t.action.label}
          </button>
        )}
        <button
          onClick={() => onDismiss(t.id)}
          className="shrink-0 rounded-md p-0.5 opacity-60 hover:opacity-100 transition-opacity"
          aria-label="Dismiss notification"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      {/* Progress bar */}
      <div className="h-[3px] w-full bg-black/5 dark:bg-white/5">
        <div
          className={cn("h-full transition-none", progressBarColors[t.type])}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (type: ToastType, title: string, message?: string, action?: ToastAction) => {
      const id = crypto.randomUUID();
      const duration = type === "error" ? DURATION_ERROR : DURATION_DEFAULT;
      setToasts((prev) => {
        const next = [...prev, { id, type, title, message, action, createdAt: Date.now(), duration }];
        // Enforce max visible — drop oldest when exceeding limit
        if (next.length > MAX_VISIBLE) {
          return next.slice(next.length - MAX_VISIBLE);
        }
        return next;
      });
    },
    []
  );

  const value: ToastContextValue = {
    toast: addToast,
    success: (title, message, action) => addToast("success", title, message, action),
    error: (title, message, action) => addToast("error", title, message, action),
    warning: (title, message, action) => addToast("warning", title, message, action),
    info: (title, message, action) => addToast("info", title, message, action),
  };

  const errorToasts = toasts.filter((t) => t.type === "error");
  const otherToasts = toasts.filter((t) => t.type !== "error");

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Error toast container — assertive so screen readers interrupt immediately */}
      <div
        aria-live="assertive"
        aria-label="Error notifications"
        className="fixed bottom-4 right-4 z-[100] flex flex-col-reverse gap-2 pointer-events-none"
      >
        {errorToasts.map((t) => (
          <ToastItem key={t.id} t={t} onDismiss={removeToast} />
        ))}
      </div>
      {/* Non-error toast container — polite so screen readers finish current speech */}
      <div
        aria-live="polite"
        aria-label="Notifications"
        className="fixed bottom-4 right-4 z-[100] flex flex-col-reverse gap-2 pointer-events-none"
      >
        {otherToasts.map((t) => (
          <ToastItem key={t.id} t={t} onDismiss={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
