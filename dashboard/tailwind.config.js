/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bgPrimary: "var(--bg-primary)",
        bgSecondary: "var(--bg-secondary)",
        bgCard: "var(--bg-card)",
        borderStrong: "var(--border)",
        textPrimary: "var(--text-primary)",
        textMuted: "var(--text-muted)",
        amber: "var(--amber)",
        emerald: "var(--emerald)",
        rose: "var(--rose)",
        blue: "var(--blue)",
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "Inter", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        rowSlide: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        glowPulse: {
          "0%, 100%": { boxShadow: "0 0 0 rgba(245,158,11,0)" },
          "50%": { boxShadow: "0 0 20px rgba(245,158,11,0.2)" },
        },
      },
      animation: {
        fadeIn: "fadeIn 200ms ease-out",
        rowSlide: "rowSlide 320ms ease-out forwards",
        glowPulse: "glowPulse 1.4s ease-in-out 1",
      },
    },
  },
  plugins: [],
};

