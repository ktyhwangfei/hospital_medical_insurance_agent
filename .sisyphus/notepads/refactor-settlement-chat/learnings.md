# Learnings: Refactor settlement-chat.tsx

## Summary
Refactored `settlement-chat.tsx` to integrate the new streaming infrastructure:
- `useChatStream` hook for SSE connection management
- `ExecutionTimeline` component for real-time execution steps
- `Typewriter` component for animated text display

## Changes Made

### Imports
- Replaced `sendChatStream` import with `useChatStream` from `@/lib/sse-hooks`
- Added `ExecutionTimeline` (default export from `./chat/execution-timeline`)
- Added `Typewriter` (named export from `./chat/typewriter`)
- Added `ConnectionStatus`, `StreamStepDisplay`, `ExecutionStep` type imports
- Removed `SseEvent` type import (no longer needed)

### State Management
- Removed `streamingContent` state (now managed by hook's return value)
- Added `streamingRequest` and `streamEnabled` states to control hook lifecycle
- Added reactive `useEffect` to reset streaming state when connection closes/errors

### Hook Integration
- Inserted `useChatStream` call with callbacks:
  - `onIntentTrace` — updates `intentTrace` state for stat bar display
  - `onFinal` — adds final message to `messages`, handles confirmation dialog, updates connection status, fallback detection
  - `onError` — displays error messages with ApiClientError handling for PERMISSION_DENIED

### Key Structural Changes
- `handleSend` simplified to just set request + enable hook (no manual SSE handling)
- Streaming content display uses `<Typewriter>` instead of raw `<span>` + cursor span
- Right sidebar replaced with `<ExecutionTimeline>` showing execution steps

### Preserved Functionality
- Mock fallback detection via `hasFallbackFlag()`
- Confirmation dialog flow for `waiting_human_confirmation`
- Role display, quick questions, intent stat bar, IntentTraceCard

## Edge Cases & Pitfalls
1. **StreamingContent before declaration**: The old `streamingContent` state was declared before the `useChatStream` hook destructuring. Caused "used before declaration" TS error. Fixed by removing the old state and moving the scroll `useEffect` after the hook.
2. **Import style**: `ExecutionTimeline` is a **default** export, not named. Used `import ExecutionTimeline from '...'`.
3. **TypeScript strict**: All compile checks pass (`npx tsc --noEmit`).
4. **Build successful**: `npx next build` passed with all 5 routes compiled.
