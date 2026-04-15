/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0f14",
        surface: "#121820",
        border: "#1f2a36",
        accent: "#00d4aa",
        danger: "#ef4444",
        warn: "#f59e0b",
        muted: "#6b7b8c",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
