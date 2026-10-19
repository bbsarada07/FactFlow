/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./pages/**/*.{js,jsx}", "./components/**/*.{js,jsx}", "./lib/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        base: "var(--bg-base)",
        surface: "var(--bg-surface)",
        card: "var(--bg-card)",
        hover: "var(--bg-hover)",
        subtle: "var(--border-subtle)",
        active: "var(--border-active)",
        red: "var(--accent-red)",
        green: "var(--accent-green)",
        orange: "var(--accent-orange)",
        blue: "var(--accent-blue)",
        purple: "var(--accent-purple)",
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        muted: "var(--text-muted)",
        whatsapp: "#25D366",
      },
      fontFamily: {
        display: ["var(--font-display)"],
        body: ["var(--font-body)"],
        mono: ["var(--font-mono)"],
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },
      boxShadow: {
        "glow-red": "var(--glow-red)",
        "glow-green": "var(--glow-green)",
      },
    },
  },
  plugins: [],
};
