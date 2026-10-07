import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: 'var(--paper)',
        surface: 'var(--surface)',
        tint: 'var(--tint)',
        ink: 'var(--ink)',
        'ink-2': 'var(--ink-2)',
        'ink-3': 'var(--ink-3)',
        'ink-4': 'var(--ink-4)',
        brand: { DEFAULT: 'var(--brand)', hover: 'var(--brand-hover)', thin: 'var(--brand-thin)' },
        line: { DEFAULT: 'var(--line)', strong: 'var(--line-strong)' },
        ok: 'var(--ok)',
        danger: 'var(--danger)',
        warn: 'var(--warn)',
        /* shadcn 语义别名：全部指向同一套主题令牌，不引入新色值 */
        background: 'var(--surface)',
        foreground: 'var(--ink)',
        card: { DEFAULT: 'var(--surface)', foreground: 'var(--ink)' },
        popover: { DEFAULT: 'var(--surface)', foreground: 'var(--ink)' },
        primary: { DEFAULT: 'var(--brand)', foreground: 'var(--surface)', hover: 'var(--brand-hover)' },
        secondary: { DEFAULT: 'var(--tint)', foreground: 'var(--ink)' },
        muted: { DEFAULT: 'var(--tint)', foreground: 'var(--ink-3)' },
        accent: { DEFAULT: 'var(--brand-thin)', foreground: 'var(--brand)' },
        destructive: { DEFAULT: 'var(--danger)', foreground: 'var(--surface)' },
        border: 'var(--line)',
        input: 'var(--line)',
        ring: 'var(--brand-line)',
      },
      borderRadius: { sm: '6px', md: '8px', lg: '10px' },
      fontFamily: { mono: ['var(--font-mono)'] },
      boxShadow: { hover: 'var(--shadow-hover)' },
    },
  },
} satisfies Config
