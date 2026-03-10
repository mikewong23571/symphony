import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{html,ts}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        line: "var(--color-line)",
        fg: "var(--color-fg)",
        muted: "var(--color-muted)",
        accent: "var(--color-accent)",
        danger: "var(--color-danger)",
        "danger-subtle": "var(--color-danger-subtle)"
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"]
      },
      fontSize: {
        body: ["var(--text-body)", { lineHeight: "var(--leading-body)" }],
        display: [
          "var(--text-display)",
          { lineHeight: "var(--leading-display)" }
        ]
      },
      letterSpacing: {
        ui: "var(--tracking-ui)"
      },
      borderRadius: {
        panel: "var(--radius-panel)"
      },
      boxShadow: {
        panel: "var(--shadow-panel)"
      },
      spacing: {
        "token-1": "var(--space-1)",
        "token-2": "var(--space-2)",
        "token-3": "var(--space-3)",
        "token-4": "var(--space-4)",
        "token-5": "var(--space-5)",
        "token-6": "var(--space-6)",
        "token-8": "var(--space-8)"
      },
      transitionDuration: {
        fast: "var(--motion-fast)",
        base: "var(--motion-base)"
      },
      transitionTimingFunction: {
        standard: "var(--ease-standard)"
      }
    }
  },
  plugins: []
} satisfies Config;
