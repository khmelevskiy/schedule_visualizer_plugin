// Theme sync. Airflow (Chakra/next-themes) sets `light`/`dark` on its <html> as a
// class or a data-theme attribute, and does NOT touch the OS `prefers-color-scheme`.
// The plugin is embedded as a same-origin iframe, so when framed we mirror the
// parent's theme (and follow its changes); standalone, we use the OS preference.

type Theme = "light" | "dark";

function parentTheme(): Theme | null {
  try {
    if (window.parent === window) return null; // not framed → standalone
    const el = window.parent.document.documentElement;
    if (el.classList.contains("dark") || el.dataset.theme === "dark") return "dark";
    if (el.classList.contains("light") || el.dataset.theme === "light") return "light";
  } catch {
    // cross-origin parent — can't read it
  }
  return null;
}

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(): void {
  document.documentElement.dataset.theme = parentTheme() ?? systemTheme();
}

export function initTheme(): void {
  apply();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", apply);
  try {
    if (window.parent !== window) {
      new MutationObserver(apply).observe(window.parent.document.documentElement, {
        attributes: true,
        attributeFilter: ["class", "data-theme"],
      });
    }
  } catch {
    // cross-origin parent — no live sync, apply() fallback already ran
  }
}
