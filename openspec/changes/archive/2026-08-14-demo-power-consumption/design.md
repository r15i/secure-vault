## Context

See `proposal.md` for motivation. The ESP32 serves a web interface defined via the `DASHBOARD_HTML` string in `ESP32_Auth_PIO/src/dashboard.h`. The HTML relies on a JavaScript `fetch()` to `/api/energy` and updates the DOM elements.

## Goals / Non-Goals

**Goals:**
- Provide a clear graphical representation (like a bar chart or scaled progress bars) in the dashboard showing the absolute or relative power consumption differences.

**Non-Goals:**
- Overhauling the entire UI or adding heavy external JS libraries like Chart.js (which might be too large or complex to embed neatly inside an ESP32 raw string).

## Decisions

- **Decision 1:** Use simple HTML/CSS-based progress bars to render the comparison. 
  - *Rationale*: We can dynamically adjust the `width` of a colored `<div>` inside a container relative to the highest power-consuming algorithm (ECC). This requires zero external libraries and takes very little space inside the C++ string literal.
  - *Alternative*: Load a charting library via CDN. We reject this because we want the dashboard to work completely offline (local network).

## Risks / Trade-offs

- [Risk] Scaling differences between Classical/SV and ECC are immense (ECC uses ~200x more power). A linear bar chart will render Classical/SV as imperceptibly small lines.
  - *Mitigation*: We could use a logarithmic scale for the bars or simply state the multiplier explicitly next to the visual representation so users can interpret the small slivers correctly.
