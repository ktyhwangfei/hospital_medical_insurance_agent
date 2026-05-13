---
## 2026-05-13: Typewriter Component (T12)

- Created src/apps/portal/src/components/chat/typewriter.tsx
- Used functional updater pattern with setInterval + useRef
- No external animation libraries - injected CSS @keyframes via a one-time useEffect
- Cursor: cyan-400 (#22d3ee) per dark theme chat accent
- Animation cycle: 530ms step-end for cursor blink, 1.4s for tool-call pulse
- Acceleration: batches 3 chars when >50 behind, 2 when >20 behind, 1 otherwise
- Import path: @/components/chat/typewriter
