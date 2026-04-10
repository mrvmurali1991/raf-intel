"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { CheckCircle2, AlertTriangle, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastType = "success" | "error" | "warning" | "info";

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
}

interface ToastContextValue {
  toast: (type: ToastType, title: string, message?: string) => void;
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  warning: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
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

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Ref Map tracks pending auto-dismiss timers keyed by toast id so they can
  // be cleared immediately when a toast is manually dismissed.
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const removeToast = useCallback((id: string) => {
    // Clear any pending timer to prevent double-removal attempts.
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (type: ToastType, title: string, message?: string) => {
      const id = crypto.randomUUID();
      setToasts((prev) => [...prev, { id, type, title, message }]);
      const timer = setTimeout(() => removeToast(id), 4000);
      timers.current.set(id, timer);
    },
    [removeToast]
  );

  const value: ToastContextValue = {
    toast: addToast,
    success: (title, message) => addToast("success", title, message),
    error: (title, message) => addToast("error", title, message),
    warning: (title, message) => addToast("warning", title, message),
    info: (title, message) => addToast("info", title, message),
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Error toast container — assertive so screen readers interrupt immediately */}
      <div
        aria-live="assertive"
        aria-label="Error notifications"
        className="fixed bottom-4 right-4 z-[100] flex flex-col-reverse gap-2 pointer-events-none"
      >
        {toasts.filter((t) => t.type === "error").map((t) => {
          const Icon = icons[t.type];
          return (
            <div
              key={t.id}
              className={cn(
                "pointer-events-auto flex items-start gap-3 rounded-xl border px-4 py-3 backdrop-blur-sm premium-shadow animate-slide-up",
                "animate-in slide-in-from-right-5 fade-in duration-300",
                "min-w-[320px] max-w-[420px]",
                styles[t.type]
              )}
              role="alert"
            >
              <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", iconStyles[t.type])} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold">{t.title}</p>
                {t.message && (
                  <p className="mt-0.5 text-xs opacity-80">{t.message}</p>
                )}
              </div>
              <button
                onClick={() => removeToast(t.id)}
                className="shrink-0 rounded-md p-0.5 opacity-60 hover:opacity-100 transition-opacity"
                aria-label="Dismiss notification"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
      {/* Non-error toast container — polite so screen readers finish current speech */}
      <div
        aria-live="polite"
        aria-label="Notifications"
        className="fixed bottom-4 right-4 z-[100] flex flex-col-reverse gap-2 pointer-events-none"
      >
        {toasts.filter((t) => t.type !== "error").map((t) => {
          const Icon = icons[t.type];
          return (
            <div
              key={t.id}
              className={cn(
                "pointer-events-auto flex items-start gap-3 rounded-xl border px-4 py-3 backdrop-blur-sm premium-shadow animate-slide-up",
                "animate-in slide-in-from-right-5 fade-in duration-300",
                "min-w-[320px] max-w-[420px]",
                styles[t.type]
              )}
              role="status"
            >
              <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", iconStyles[t.type])} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold">{t.title}</p>
                {t.message && (
                  <p className="mt-0.5 text-xs opacity-80">{t.message}</p>
                )}
              </div>
              <button
                onClick={() => removeToast(t.id)}
                className="shrink-0 rounded-md p-0.5 opacity-60 hover:opacity-100 transition-opacity"
                aria-label="Dismiss notification"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
