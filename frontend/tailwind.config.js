/** Design tokens live in src/index.css as CSS variables (RGB channels) so Light and Dark
 *  themes swap in one place; Tailwind colors reference them by role. */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
                    mono: ["JetBrains Mono", "Consolas", "ui-monospace", "monospace"] },
      colors: {
        bg: token("bg"), surface: token("surface"), "surface-2": token("surface-2"), "surface-3": token("surface-3"),
        line: token("border"), "line-strong": token("border-strong"),
        ink: token("text"), muted: token("text-muted"), subtle: token("text-subtle"),
        accent: token("accent"), "accent-ink": token("accent-text"), "accent-soft": token("accent-soft"),
        "on-accent": token("on-accent"),
        sidebar: token("sidebar"), "sidebar-ink": token("sidebar-text"), "sidebar-hover": token("sidebar-hover"),
        success: token("success"), "success-soft": token("success-soft"),
        warning: token("warning"), "warning-soft": token("warning-soft"),
        danger: token("danger"), "danger-soft": token("danger-soft"),
        info: token("info"), "info-soft": token("info-soft"),
      },
      fontSize: { "2xs": ["0.6875rem", { lineHeight: "1rem" }] },
      borderRadius: { xl: "0.75rem" },
      boxShadow: { card: "0 1px 2px rgb(var(--shadow) / 0.06), 0 1px 3px rgb(var(--shadow) / 0.04)",
                   pop: "0 10px 30px rgb(var(--shadow) / 0.18)" },
      transitionDuration: { DEFAULT: "180ms" },
    },
  },
  plugins: [],
};
