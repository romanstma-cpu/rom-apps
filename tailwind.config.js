export default {
  content: ['./index.html', './src/**/*.{ts,tsx,html}'],
  theme: {
    extend: {
      colors: {
        rom: {
          black: '#000000',
          void: '#0B1019',
          sidebar: '#0E1520',
          surface: '#121A26',
          surface2: '#192333',
          border: 'rgba(255,255,255,0.08)',
          borderHi: 'rgba(255,255,255,0.16)',
          muted: '#A4B1C4',
          dim: '#7E8DA3',

          indigo: '#1D4ED8',
          purple: '#6EA8FE',
          pink: '#38BDF8',
          win: '#40C9A2',
          loss: '#EF4444',
          warn: '#F59E0B',
        },
      },
      fontFamily: {
        sans: ['"Segoe UI"', 'Inter', 'system-ui', 'sans-serif'],
        pixel: ['"Segoe UI"', 'monospace'],
        mono: ['Consolas', 'Menlo', 'monospace'],
      },
      backgroundImage: {
        'rom-glow':
          'linear-gradient(90deg, #1D4ED8 0%, #6EA8FE 50%, #38BDF8 100%)',
        'rom-radial':
          'radial-gradient(700px circle at 15% 0%, rgba(59,130,246,0.035), transparent 60%)',
        'rom-radial-r':
          'radial-gradient(600px circle at 90% 0%, rgba(56,189,248,0.025), transparent 60%)',
      },
      boxShadow: {
        'rom-glow': '0 0 28px 0 rgba(59,130,246,0.35)',
        'rom-soft': '0 10px 40px -10px rgba(59,130,246,0.20)',
        'rom-strong': '0 0 60px -10px rgba(59,130,246,0.55)',
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'gradient-x': {
          '0%,100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
        'pulse-slow': {
          '0%,100%': { opacity: '0.4' },
          '50%': { opacity: '0.9' },
        },
      },
      animation: {
        'fade-in': 'fade-in 280ms ease-out',
        'gradient-x': 'gradient-x 6s ease infinite',
        'pulse-slow': 'pulse-slow 2.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
