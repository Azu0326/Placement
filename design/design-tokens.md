# DNC Content Platform — design tokens

Paste these into Figma as **variables** (Local variables → create collection "DNC") so the
imported HTML layers can be re-bound to real styles.

## Colour

| Token | Hex | Use |
|---|---|---|
| `primary/500` | `#4F46E5` | Primary buttons, active nav, links |
| `primary/600` | `#4338CA` | Primary hover |
| `primary/50` | `#EEF0FF` | Primary tint backgrounds |
| `accent/500` | `#2E7CF6` | Focus rings, running state, secondary emphasis |
| `accent/50` | `#EFF6FF` | Accent tint |
| `canvas` | `#F6F7FA` | App background |
| `surface` | `#FFFFFF` | Cards, tables, panels |
| `rail` | `#141A2E` | Sidebar |
| `rail/deep` | `#0E1322` | Code viewers, logs |
| `rail/line` | `#242C45` | Sidebar dividers |
| `rail/text` | `#A9B2CA` | Sidebar idle label |
| `ink` | `#0F172A` | Primary text |
| `ink/soft` | `#334155` | Body text |
| `ink/mute` | `#64748B` | Secondary text |
| `ink/faint` | `#94A3B8` | Meta, placeholder |
| `ok/500` | `#10B981` | COMPLETED, connected |
| `warn/500` | `#F59E0B` | Attention, review status |
| `err/500` | `#F87171` | FAILED (soft red) |
| `err/700` | `#B91C1C` | Error text on tint |
| `queued/500` | `#8B5CF6` | QUEUED, scheduled |

Status pills use a three-part recipe: `{tone}/700` text on `{tone}/50` fill with a
`{tone}/500` border at 20–25% opacity.

## Type — Inter

| Role | Size / weight / tracking |
|---|---|
| Page title | 27px · 600 · −0.02em |
| Dashboard greeting | 30px · 600 · −0.02em |
| KPI metric | 30px · 600 · tabular |
| Card title | 14.5px · 600 |
| Section heading | 15px · 600 |
| Body | 13.5px · 400 |
| Editor body | 15.5px · 400 · 1.75 line-height |
| Table cell | 13px · 400 |
| Table header | 11.5px · 500 · uppercase · 0.05em |
| Meta / caption | 12px · 400 |
| Status badge | 11px · 600 · uppercase · 0.02em |

All numeric columns (job IDs, counts, durations, timestamps) use tabular figures.

## Layout

- Sidebar 260px, collapsed 72px, mobile off-canvas
- Header 64px, sticky
- Content max-width 1440px, padding 32px desktop / 16px mobile
- Card radius 14px, control radius 12px, pill radius 8px
- Border `#E2E8F0` at 80% opacity
- Shadow *soft*: `0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06)`
- Shadow *lift*: `0 4px 12px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.04)`
- Shadow *pop* (modals): `0 12px 32px rgba(15,23,42,.12)`

## Control heights

| Element | Desktop | Mobile |
|---|---|---|
| Primary button | 40px | 44px |
| Small button | 36px | 44px |
| Input / select | 40px | 44px |
| Table row | 48px | card |
| Icon button | 36–40px | 44px |

## Component states

Every interactive component needs: default, hover, focus (2px `accent/500` ring at 2px offset),
active, disabled (40% opacity), and where relevant loading and error.

## Job status vocabulary

`QUEUED` `RUNNING` `COMPLETED` `FAILED` — these are the application's own states and are the
only status source shown to users. Queue and worker internals appear solely in
**Scraper → Execution** and the job detail Execution tab.
