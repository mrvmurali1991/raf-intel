"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { CheckCircle2, AlertTriangle, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastType = "success" | "error" | "warning" | "info";

interface Toast {
  id: number;
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

let toastId = 0;

const icons: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const styles: Record<ToastType, string> = {
  success:
    "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100",
  error:
    "border-red-200 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100",
  warning:
    "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100",
  info: "border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100",
};

const iconStyles: Record<ToastType, string> = {
  success: "text-emerald-600 dark:text-emerald-400",
  error: "text-red-600 dark:text-red-400",
  warning: "text-amber-600 dark:text-amber-400",
  info: "text-blue-600 dark:text-blue-400",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (type: ToastType, title: string, message?: string) => {
      const id = ++toastId;
      setToasts((prev) => [...prev, { id, type, title, message }]);
      setTimeout(() => removeToast(id), 4000);
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
      {/* Toast container */}
      <div
        aria-live="polite"
        aria-label="Notifications"
        className="fixed bottom-4 right-4 z-[100] flex flex-col-reverse gap-2 pointer-events-none"
      >
        {toasts.map((t) => {
          const Icon = icons[t.type];
          return (
            <div
              key={t.id}
              className={cn(
                "pointer-events-auto flex items-start gap-3 rounded-xl border px-4 py-3 shadow-lg backdrop-blur-sm",
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
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
