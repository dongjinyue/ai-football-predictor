---
version: alpha
name: "AI Football Predictor"
description: "A calm, evidence-led match analysis workspace inspired by the structure of a coach's match board."
colors:
  primary: "#176B45"
  ink: "#14221B"
  muted: "#617068"
  canvas: "#F4F7F2"
  surface: "#FFFFFF"
  line: "#DDE6DF"
  pitch: "#176B45"
  signal: "#D8FF63"
  warning: "#9A5A13"
typography:
  display:
    fontFamily: "Georgia, 'Noto Serif SC', serif"
  sans:
    fontFamily: "Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif"
  mono:
    fontFamily: "'SFMono-Regular', Consolas, monospace"
rounded:
  DEFAULT: "0.875rem"
  sm: "0.5rem"
  lg: "1.5rem"
spacing:
  unit: "0.25rem"
  page: "1.5rem"
  section: "2rem"
components:
  navigation: {}
  status-card: {}
  notice: {}
---

# AI Football Predictor Design System

## Overview

### Creative North Star

The interface should feel like a coach's match board translated into a research tool: a pale working surface, strong pitch-green structure, precise ruled divisions, and one high-visibility signal color used only for live status or primary emphasis.

### Product context and register

- **Audience and primary job:** Chinese football-analysis users need to inspect fixtures, model evidence, backtests, and data quality without mistaking research output for certainty.
- **Target market and evidence:** The design specification targets Chinese sports-lottery fixtures and Chinese-language workflows.
- **Locale and language policy:** The initial interface is Simplified Chinese. Technical terms remain secondary to plain Chinese labels.
- **Usage scene:** Desktop-first daily analysis with a usable narrow-screen overview; future data screens may be dense.
- **Register:** Product interface. Clarity and traceability lead over promotional expression.
- **Memorable signature:** A pitch-line motif frames the page status and active navigation.
- **Restraint:** Tables, filters, probability data, and warnings must remain quiet and highly legible.
- **Anti-references:** Avoid betting-app neon, casino imagery, generic blue SaaS gradients, and claims of guaranteed accuracy.
- **Token ownership/runtime mapping:** `DESIGN.md` records accepted values. The hand-maintained `frontend/src/index.css` Tailwind v4 theme is the runtime source and mirrors these values.

## Colors

`pitch` establishes navigation and focus. `signal` is a scarce status accent. `canvas`, `surface`, and `line` build low-glare analytical layers. `warning` is reserved for cautionary content. Text uses `ink` and `muted`; color never carries status alone.

## Typography

Display headings use the restrained serif stack to suggest match reports rather than marketing. Controls and body copy use the locale-capable sans stack. Future scores, timestamps, and model versions may use the mono stack for stable numeric rhythm.

## Layout

The application uses a fixed-width desktop navigation rail and fluid content area. Narrow screens move navigation above content and allow horizontal navigation without hiding destinations. Content spacing follows the `unit`, `page`, and `section` values.

## Elevation & Depth

Hierarchy comes from tonal layers, borders, and controlled overlap. Static cards use shallow shadows only to separate white surfaces from the pale canvas; no glass effects or decorative blur.

## Shapes

Primary surfaces use the `lg` radius, compact status items use `sm`, and standard controls use `DEFAULT`. Pitch-line details remain squared or lightly rounded so the interface does not become pill-heavy.

## Components

### Foundational visual states

Links expose hover, active, and visible keyboard-focus states. Disabled or unavailable features include a text explanation. Reduced-motion mode removes nonessential transitions.

### Buttons and actions

Future primary actions use pitch green with clear verb labels. Destructive actions remain visually and spatially separate. No icon-only action is introduced without an accessible name.

### Navigation and data display

Navigation uses real links and `aria-current` for the active destination. Future data tables must preserve comparison on narrow screens through explicit horizontal overflow, not silent field removal.

### Forms and overlays

Not included in the foundation module. Future implementations must use owned validation, accessible labels, and application dialogs instead of browser alerts.

### Iconography

Lucide supplies consistent 1.75px outline icons. Text labels remain visible for primary navigation.

### Motion

Transitions are limited to 160ms color and position feedback. Motion communicates interaction only and is removed under `prefers-reduced-motion`.

### Content and data visualization

Copy is factual and cautious. Status, update time, data grade, and model confidence will be explicit when real data is introduced. Charts must retain text alternatives and must not imply guaranteed outcomes.

## Do's and Don'ts

- **Do:** Use pitch-board structure to orient users and clarify system status.
- **Do:** Pair every quality or confidence color with a text label.
- **Don't:** Use casino, odds-ticket, flashing, or guaranteed-win visual language.
- **Don't:** fill every surface with cards or bright accent colors.
