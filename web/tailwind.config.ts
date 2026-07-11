import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        panel: '#f8fafc',
        ink: '#172033',
      },
      boxShadow: {
        focus: '0 0 0 3px rgba(37, 99, 235, 0.16)',
      },
    },
  },
  plugins: [],
} satisfies Config;
