import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { applyTheme, readPref, resolveTheme, writePref, type ThemePref } from "../lib/theme";

interface ThemeState {
  pref: ThemePref;
  theme: "light" | "dark";
  setPref: (p: ThemePref) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeState | null>(null);
const media = () => (typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null);
const safeStorage = () => {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
};

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(() => readPref(safeStorage()));
  const [systemDark, setSystemDark] = useState<boolean>(() => media()?.matches ?? false);
  const theme = resolveTheme(pref, systemDark);

  useEffect(() => {
    const mq = media();
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // index.html applied the initial theme before React rendered; later changes animate briefly.
  const [first, setFirst] = useState(true);
  useEffect(() => {
    applyTheme(document.documentElement, theme, !first);
    setFirst(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  const setPref = useCallback((p: ThemePref) => {
    writePref(safeStorage(), p);
    setPrefState(p);
  }, []);
  const toggle = useCallback(() => setPref(theme === "dark" ? "light" : "dark"), [setPref, theme]);

  const value = useMemo(() => ({ pref, theme, setPref, toggle }), [pref, theme, setPref, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}
