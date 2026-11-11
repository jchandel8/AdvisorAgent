# AdvisorAgent design system (MASTER)

Source of truth for both portals. Page files in `pages/` override this file where they differ.
Built from two skills: `ui-ux-pro-max` (rules, accessibility, Angular and chart guidance) and
`frontend-design` (art direction). Owner decisions: Tailwind v4 + Angular CDK, Apache ECharts,
light theme by default with a dark toggle.

## Subject, audience, job

- **Subject:** private wealth accounts, and *who is allowed to see which account*. The permission model is
  the product's point, and the demo shows it by putting the advisor and client portals side by side.
- **Audience:** a financial advisor at work (dense, fast scanning, many clients) and their client at home
  (calm, few numbers, plain words). Viewers of the portfolio demo are engineers and hiring managers.
- **Primary job:** answer "what is in these accounts and how are they doing" with numbers people can trust,
  and make the same account recognizable in both windows.

## The one bold idea: account swatches

Every account gets a stable identity: a colored ledger tab (swatch) plus its short name, derived from the
account ID. The same account shows the same swatch in the advisor portal, the client portal and the
assistant's answers. In a side-by-side demo the viewer can match an account across windows at a glance,
and see that an advisor has only some of a client's swatches. Everything else stays quiet.

## Color tokens

Light (default). Defined as CSS variables in `styles/tokens.css`; components use tokens, never raw hex.

| Token | Hex | Use |
|---|---|---|
| `--paper` | `#F6F7F5` | App background (cool grey-green, not cream) |
| `--surface` | `#FFFFFF` | Panels, tables |
| `--ink` | `#17201D` | Primary text (green-black ink) |
| `--ink-muted` | `#55625D` | Secondary text (≥ 4.5:1 on paper and surface) |
| `--rule` | `#DCE1DE` | Dividers and table rules |
| `--advisor` | `#0E5A4A` | Advisor portal identity (deep evergreen) |
| `--client` | `#2E3A8C` | Client portal identity (statement ink blue) |
| `--gain` | `#17663F` | Gains, always with ▲ and a + sign |
| `--loss` | `#A3261B` | Losses, always with ▼ and a − sign |
| `--focus` | `#1D5FD1` | Focus ring, 2px, offset 2px |

Dark: same names, re-derived (paper `#111816`, surface `#18211E`, ink `#E6ECE9`, muted `#A3B0AB`,
rule `#2C3833`, advisor `#5FBFA6`, client `#9FAAF5`, gain `#5CC38C`, loss `#F08A7E`). All text pairs ≥ 4.5:1.

Account swatches and chart series: the `dataviz` skill's validated 8-hue categorical palette, re-validated
against our surfaces (`validate_palette.js`): all checks pass in both modes. Light has a contrast WARN on
aqua, yellow and pink, so swatches always carry the account name and charts always have a table view.
Slot = account ID mod 8, so an account keeps its color everywhere (color follows the entity, never rank).

| Slot | Light (on #FFFFFF) | Dark (on #18211E) |
|---|---|---|
| 1 blue | `#2a78d6` | `#3987e5` |
| 2 orange | `#eb6834` | `#d95926` |
| 3 aqua | `#1baf7a` | `#199e70` |
| 4 yellow | `#eda100` | `#c98500` |
| 5 pink | `#e87ba4` | `#d55181` |
| 6 green | `#008300` | `#008300` |
| 7 violet | `#6250d6` | `#9085e9` |
| 8 red | `#e34948` | `#e66767` |

Gain/loss: the green/red text pair FAILED colour-blind separation (deutan ΔE 3.0 in dark), so chart bars
use the validated blue↔red diverging pair (light `#2a78d6`/`#e34948`, dark `#3987e5`/`#e66767`, all checks
pass). The green/red `--gain`/`--loss` tokens are only for text, always with ▲/▼ and a +/− sign.

## Typography

- **Instrument Sans** (variable weight and width), self-hosted via Fontsource. One family for everything.
- Numbers: `font-variant-numeric: tabular-nums` everywhere money or percentages appear; right-aligned in tables.
- Scale (rem): 0.8125 caption · 0.875 table · 1 body · 1.25 section · 1.75 page sentence · 2.5 statement figure.
- Headlines are sentences, semibold at normal width (`font-stretch: 100%`). Money tables set condensed (`88%`) so long figures fit; the font's width axis runs 75–100%.
- Body line length under 75 characters. Line height 1.5 body, 1.25 headlines.

## Layout

```
Desktop (≥1024px)                                  Phone (<768px)
┌────────┬───────────────────────────────────┐     ┌──────────────────────┐
│ ▌Portal│  Statement sentence + date         │     │ Portal band + user   │
│  band  │  ───────────────────────────────── │     │ Statement sentence   │
│        │  Primary content (table or chart)  │     │ Content, one column  │
│ Nav    │                                    │     │                      │
│ (4-5)  │  Secondary content                 │     ├──────────────────────┤
│        │                                    │     │ Bottom tabs (≤5)     │
│ User   │                                    │     └──────────────────────┘
└────────┴───────────────────────────────────┘
```

- Left aligned throughout. Content max width 1200px.
- Left rail carries the portal identity band (advisor evergreen, client ink blue) and the signed-in person,
  so the two demo windows are distinguishable from across the room.
- Each page opens with a statement sentence, not a hero metric:
  "Your 2 accounts are worth $793,944.18 as of November 11, 2026."
- Panels: two radii only (12px page panels, 6px controls). Hairline rules separate rows; no shadows except
  overlays. No gradient washes.
- Spacing scale 4/8/12/16/24/32/48.

## Charts (ECharts)

- Growth: area line (time-weighted growth of 100) with market value on hover; data table toggle.
- Top 10 holdings: horizontal bars sorted by value, labeled directly with value and % (not a donut).
- Allocation: 100% stacked bar by asset class (≤ 3 categories), labeled.
- Gain/loss: realized by month as signed bars (gain/loss tokens + ▲▼ in labels); unrealized by holding as
  diverging horizontal bars. Every chart has a text summary and a "Show as table" alternative.
- Respect `prefers-reduced-motion` (animation off).

## Motion

- Nothing moves on page load. Motion answers actions only: panel open/close 180ms, chat message arrival
  120ms fade, swatch hover highlights matching rows. All disabled under reduced motion.

## Words

- Sentence case everywhere. No all-caps labels, no "→" in buttons, no middle-dot meta strings.
- Buttons name the action ("Ask", "Switch user", "Show as table").
- Empty and error states say what happened and what to do: "No transactions in this account yet."
  / "We couldn't load holdings. Check the API is running, then try again."

## Accessibility floor (from ui-ux-pro-max priorities 1–6)

- Contrast ≥ 4.5:1 text, ≥ 3:1 UI; visible focus on every control; keyboard reachable everything.
- Touch targets ≥ 44px on phone; responsive at 375, 768, 1024, 1440 with no horizontal page scroll
  (wide tables scroll inside their own container).
- Gains and losses never by color alone; charts have text alternatives.
- SVG icons only (Lucide), `aria-hidden` when decorative, labels on icon-only buttons.

## Angular implementation rules (ui-ux-pro-max, angular 22.x)

- Standalone components, signals for state, zoneless change detection, `provideRouter` / `provideHttpClient`.
- New control flow (`@if`, `@for` with `track`), `OnPush`-style signal inputs, lazy-loaded portal routes.

## Design review notes (pass 2 critique)

- Rejected: navy + gold IBM Plex banking palette (the database's top match): it is the default finance look.
- Rejected: dark OLED + green accent from the dashboard style match: one of the common generated looks,
  and the owner chose light by default.
- Rejected: big total + small label + gradient hero: replaced with a statement sentence.
- Rejected: uniform rounded card grid: replaced with ruled ledger panels at two radii.
- Kept from the data: tabular numbers, gain/loss with icons not color alone, chart-type choices, Angular rules.
