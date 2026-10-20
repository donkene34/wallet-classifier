"use client";

import { useEffect, useState } from "react";

export const THEME_KEY = "wc_theme";

function apply(t: "light" | "dark") {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem(THEME_KEY, t);
  } catch {}
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  }, []);
  const pick = (t: "light" | "dark") => {
    setTheme(t);
    apply(t);
  };
  const base = "grid h-7 w-8 place-items-center rounded-full transition-colors";
  return (
    <div role="group" aria-label="Thème" className="flex gap-0.5 rounded-full border border-grid bg-surface2 p-0.5">
      <button
        type="button"
        aria-label="Thème clair"
        aria-pressed={theme === "light"}
        onClick={() => pick("light")}
        className={`${base} ${theme === "light" ? "bg-page text-ink" : "text-muted"}`}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      </button>
      <button
        type="button"
        aria-label="Thème sombre"
        aria-pressed={theme === "dark"}
        onClick={() => pick("dark")}
        className={`${base} ${theme === "dark" ? "bg-page text-ink" : "text-muted"}`}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      </button>
    </div>
  );
}
