import { describe, expect, it } from "vitest";
import { parsePref, readPref, resolveTheme, writePref, THEME_KEY } from "./theme";

function memoryStorage(initial: Record<string, string> = {}) {
  const data: Record<string, string> = { ...initial };
  return {
    getItem: (k: string) => (k in data ? data[k] : null),
    setItem: (k: string, v: string) => { data[k] = v; },
  };
}

describe("theme", () => {
  it("falls back to system for missing or invalid values", () => {
    expect(parsePref(null)).toBe("system");
    expect(parsePref("purple")).toBe("system");
    expect(readPref(memoryStorage({ [THEME_KEY]: "bogus" }))).toBe("system");
  });
  it("resolves the system preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
  it("persists and reads back", () => {
    const s = memoryStorage();
    writePref(s, "dark");
    expect(readPref(s)).toBe("dark");
  });
  it("survives storage that throws", () => {
    const broken = {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
    };
    expect(readPref(broken)).toBe("system");
    expect(() => writePref(broken, "light")).not.toThrow();
  });
});
