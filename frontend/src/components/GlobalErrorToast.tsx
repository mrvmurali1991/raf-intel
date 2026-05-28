"use client";

import { useEffect, useState } from "react";

interface ToastMessage {
  id: number;
  message: string;
  type: "error" | "warning" | "info";
}

export function GlobalErrorToast() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => {
    let nextId = 0;

    const addToast = (message: string, type: "error" | "warning" | "info" = "error") => {
      const id = nextId++;
      setToasts(prev => [...prev, { id, message, type }]);
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, 5000);
    };

    const onApiError = (e: CustomEvent) => {
      addToast(e.detail?.message || "Something went wrong", "error");
    };

    const onSessionExpired = () => {
      addToast("Session expired. Logging you out...", "warning");
    };

    window.addEventListener("api-error", onApiError as EventListener);
    window.addEventListener("session-expired", onSessionExpired);
    return () => {
      window.removeEventListener("api-error", onApiError as EventListener);
      window.removeEventListener("session-expired", onSessionExpired);
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm">
      {toasts.map(t => (
        <div
          key={t.id}
          role="alert"
          className={`
            rounded-lg px-4 py-3 text-sm font-medium shadow-lg
            animate-in slide-in-from-bottom-2 fade-in duration-200
            ${t.type === "error" ? "bg-red-600 text-white" : ""}
            ${t.type === "warning" ? "bg-amber-500 text-white" : ""}
            ${t.type === "info" ? "bg-slate-800 text-white" : ""}
          `}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
