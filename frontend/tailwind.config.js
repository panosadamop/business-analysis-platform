/** @type {import('tailwindcss').Config} */

/** A colour read from the theme tokens in src/theme.css. */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`
const scale = (family, shades) =>
  Object.fromEntries(shades.map((shade) => [shade, token(`${family}-${shade}`)]))
const FULL = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: scale('ink', FULL),
        brand: { ...scale('brand', FULL), hover: token('brand-hover') },
        // Status families define only the shades in use; add a shade to
        // src/theme.css (light and dark) before using it.
        amber: scale('amber', [50, 200, 700, 800, 900]),
        red: scale('red', [50, 200, 300, 700, 800, 900]),
        emerald: scale('emerald', [50, 200, 700, 800]),
        surface: token('surface'),
        code: { DEFAULT: token('code'), text: token('code-text') },
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
