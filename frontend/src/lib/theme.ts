/** Pure theme logic (unit-tested in theme.test.ts). */
export type ThemePref = "light" | "dark" | "system";
export const THEME_KEY = "riq-theme";

export function parsePref(value: unknown): ThemePref {
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

export function resolveTheme(pref: ThemePref, systemDark: boolean): "light" | "dark" {
  return pref === "system" ? (systemDark ? "dark" : "light") : pref;
}

export function readPref(storage: Pick<Storage, "getItem"> | undefined): ThemePref {
  try {
    return parsePref(storage?.getItem(THEME_KEY));
  } catch {
    return "system";
  }
}

export function writePref(storage: Pick<Storage, "setItem"> | undefined, pref: ThemePref): void {
  try {
    storage?.setItem(THEME_KEY, pref);
  } catch {
    /* storage unavailable (private mode): the theme still applies for this session */
  }
}

export function applyTheme(root: HTMLElement, theme: "light" | "dark", animate: boolean): void {
  if (animate) {
    root.classList.add("theme-transition");
    window.setTimeout(() => root.classList.remove("theme-transition"), 200);
  }
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
}
