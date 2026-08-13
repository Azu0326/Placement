/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './design/dnc-content-platform.html',
    // Classes toggled from JS must be scanned too, or they are purged.
    './static/js/*.js',
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: '#0F172A',
          soft: '#334155',
          mute: '#64748B',
          faint: '#94A3B8',
        },
        primary: {
          50: '#EEF0FF',
          100: '#E0E4FF',
          200: '#C7CDFE',
          500: '#4F46E5',
          600: '#4338CA',
          700: '#3730A3',
        },
        accent: {
          50: '#EFF6FF',
          100: '#DBEAFE',
          500: '#2E7CF6',
          600: '#1D63D2',
        },
        canvas: '#F6F7FA',
        surface: '#FFFFFF',
        rail: {
          DEFAULT: '#141A2E',
          deep: '#0E1322',
          line: '#242C45',
          text: '#A9B2CA',
        },
        ok: {
          50: '#ECFDF5',
          500: '#10B981',
          700: '#047857',
        },
        warn: {
          50: '#FFFBEB',
          500: '#F59E0B',
          700: '#B45309',
        },
        err: {
          50: '#FEF2F2',
          500: '#F87171',
          700: '#B91C1C',
        },
        queued: {
          50: '#F5F3FF',
          500: '#8B5CF6',
          700: '#6D28D9',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        card: '14px',
        xl2: '16px',
        control: '12px',
        pill: '8px',
      },
      boxShadow: {
        soft: '0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06)',
        lift: '0 4px 12px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.04)',
        pop: '0 12px 32px rgba(15,23,42,.12), 0 2px 8px rgba(15,23,42,.06)',
      },
      maxWidth: {
        content: '1440px',
      },
      spacing: {
        rail: '260px',
        'rail-collapsed': '72px',
        header: '64px',
      },
    },
  },
  plugins: [],
};
