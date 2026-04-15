"use client";

import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

type Theme = "light" | "dark";

const ThemeContext = createContext<{
  theme: Theme;
  toggle: () => void;
}>({ theme: "light", toggle: () => {} });

/**
 * Read the stored theme without causing a hydration mismatch.
 * On the server (and during hydration) we always return "light".
 * After hydration, useSyncExternalStore's client snapshot reads localStorage.
 */
function getServerSnapshot(): Theme {
  return "light";
}

function subscribe(cb: () => void) {
  // Re-sync if another tab changes the theme
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
}

function getClientSnapshot(): Theme {
  return (localStorage.getItem("raf-theme") as Theme) || "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const stored = useSyncExternalStore(subscribe, getClientSnapshot, getServerSnapshot);
  const [theme, setTheme] = useState<Theme>(stored);

  // Sync when stored value changes (e.g. another tab)
  useEffect(() => {
    setTheme(stored);
  }, [stored]);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    localStorage.setItem("raf-theme", theme);
  }, [theme]);

  const toggle = () => setTheme((t) => (t === "light" ? "dark" : "light"));

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
