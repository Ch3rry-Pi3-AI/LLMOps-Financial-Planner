# 🎨 **Global Stylesheet — Theme, Animations & Brand Identity**

The **`frontend/styles/global.css`** file defines all **global styling primitives**, theme colours, animations, and cross-application UI behaviours for the Alex AI Financial Advisor frontend.

It is loaded once at the root of the Next.js app and governs:

* Tailwind CSS theme extension
* Brand colour palette for UI consistency
* Global background/foreground defaults
* Custom animations used throughout the app (agent pulses, glows, toast transitions)
* Light-mode-only aesthetic for a clean, enterprise-grade look

This stylesheet forms the foundation for the entire UI layer.

## 🎨 **Brand Theme & Tailwind Integration**

```css
@import "tailwindcss";
```

Imports the full Tailwind CSS engine.
All custom colours and variables declared below become available as **Tailwind tokens** via the `@theme inline` block.

### 🧩 Theme Tokens

```css
@theme inline {
  --color-primary: #209DD7;
  --color-ai-accent: #753991;
  --color-accent: #FFB707;
  --color-dark: #062147;
  --color-success: #10b981;
  --color-error: #ef4444;
```

These define the **core Alex AI brand palette**:

| Token               | Purpose                                    |
| ------------------- | ------------------------------------------ |
| `--color-primary`   | Main action colour (buttons, headers)      |
| `--color-ai-accent` | Used to highlight AI/agent components      |
| `--color-accent`    | Gold/yellow highlight for KPIs and CTAs    |
| `--color-dark`      | Deep navy used for headings & footers      |
| `--color-success`   | Positive state (saves, successful actions) |
| `--color-error`     | Alerts, validation errors, failures        |

The theme also preserves Tailwind defaults for:

```css
--color-background
--color-foreground
--font-sans
--font-mono
```

Fonts map to the **Geist** family supplied by Next.js.


## ☀️ **Global Light Mode Styling**

```css
body {
  background: var(--background);
  color: var(--foreground);
  font-family: system-ui, -apple-system, sans-serif;
}
```

The app intentionally ships in **light mode only**, aligning with the professional financial tooling aesthetic.

* No dark-mode media queries
* Neutral white canvas
* Clean, readable system fonts for dashboard-style interfaces

## ✨ **Custom Animations**

These animations are used throughout the UI to show **agent activity**, **loading states**, and **toast notifications**.

### 🔵 **Strong Pulse** — Agent Alive / Processing Indicator

```css
@keyframes strong-pulse { ... }
.animate-strong-pulse { animation: strong-pulse 1.5s ... }
```

Used on:

* AI agent status dots
* Animated workflow cards
* Progress indicators

Produces a clear breathing effect: scale + opacity transitions.

### 💜 **Glow Pulse** — Active Agent Highlight

```css
@keyframes glow-pulse { ... }
.animate-glow-pulse { animation: glow-pulse 1.5s ... }
```

This provides a more intense glow effect with purple shadows, creating an animated “AI is thinking” aesthetic.

Perfect for:

* Advisor Team active agent tiles
* Analysis cards
* Important callouts during multi-step workflows

### 🟨 **Toast Slide-In** — Notification Animations

```css
@keyframes slide-in { ... }
.animate-slide-in { animation: slide-in 0.3s ease-out; }
```

Smooth animate-in from the right edge.

Used by the `Toast` component for:

* Success messages (e.g., “Settings saved!”)
* Errors
* Warnings and info messages

## 🚀 **Summary**

The `global.css` file provides:

* A unified **brand theme** for colours, typography, and background/foreground defaults
* Tailwind-integrated colour tokens for consistent design
* Application-wide **animations** that bring the AI assistants to life
* A deliberate **light-mode enterprise aesthetic**
* Foundational styles relied upon by every page and component

This stylesheet ensures the entire Alex AI frontend feels cohesive, responsive, and aligned with its professional financial identity.
