/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        warm: {
          yellow: 'rgb(var(--color-accent-rgb) / <alpha-value>)',
          amber: 'rgb(var(--color-accent-rgb) / <alpha-value>)',
        },
        surface: {
          dark: 'rgb(var(--color-bg-rgb) / <alpha-value>)',
          card: 'rgb(var(--color-surface-rgb) / <alpha-value>)',
          input: 'rgb(var(--color-input-rgb) / <alpha-value>)',
        },
        brand: {
          amber: 'rgb(var(--color-accent-rgb) / <alpha-value>)',
          accent: 'rgb(var(--color-accent-rgb) / <alpha-value>)',
        },
      },
      fontFamily: {
        // sans: ['"Noto Sans SC"', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
        sans: ['"Segoe UI"', '"Terminal Symbol"', '"Twemoji Mozilla"', 'sans-serif'],
        // mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
        mono: ['"JetBrains Mono"', '"Terminal Symbol"', '"Twemoji Mozilla"', 'monospace'],
      },
      animation: {
        'pulse-dot': 'pulse-dot 1.4s ease-in-out infinite',
        'slide-up': 'slide-up 0.3s ease-out',
        'fade-in': 'fade-in 0.25s ease-out',
      },
      keyframes: {
        'pulse-dot': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
