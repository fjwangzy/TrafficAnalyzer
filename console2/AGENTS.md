# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## Durable design direction

- This prototype is the next-generation TrafficAnalyzer console, kept separate from `traffic-fly-console`.
- Visual target: dark, cinematic command-center UI with an aerial road scene as the primary canvas, translucent metric panels, a right-side live-event stream, and a bottom replay timeline.
- Product target: help traffic commanders assess intersection state, detect risk, confirm UAV health, and technically review AI events without duplicating the parent smart-traffic platform's dispatch workflow.
- Use realistic PRD concepts and vocabulary: congestion index, queues, GCJ02 alignment, TTC/PET, lane changes, accident survey, truck restriction clues, evidence references, and technical/business review.
- The main canvas defaults to the full detector-output video view, not a GIS map or inset video panel.
- The right-top secondary viewport defaults to BEV trajectory projection. Detector output and BEV must swap primary/secondary roles through a clear `切为主视图` action.
- Flight attitude data stays visible in the top intersection context bar: altitude, heading, pitch, roll, and gimbal state.
