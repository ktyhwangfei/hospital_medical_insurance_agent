# SSE Refactor — Learnings

## Working with `AbortSignal` and `AbortController`

- `AbortController.abort()` is idempotent — safe to call multiple times.
- When a fetch is aborted, the `ReadableStream` errors and `reader.read()` throws. The error propagates as a `DOMException` with `name === 'AbortError'`.
- In catch blocks, check `controller.signal.aborted` rather than matching error names for robustness.
- `AbortSignal.any()` exists in modern environments but manual forwarding via `addEventListener('abort', ...)` is more portable.

## sendChatStream backward compatibility

The key insight is that changing `Promise<void>` to `Promise<{ cancel, retryCount }>` is safe because:
- Callers that `await` the promise without assigning (like `settlement-chat.tsx:388`) simply discard the return value.
- TypeScript doesn't flag this because discarding return values is allowed.

## Retry loop gotchas

- Recursive `attempt()` calls with `return attempt()` work if each invocation is truly independent.
- Must check `controller.signal.aborted` BEFORE the fetch AND inside the catch block to avoid retrying after cancellation.
- The `sleepAbortable` helper needs to resolve (not reject) on abort to prevent unhandled promise rejections.

## Keepalive implementation

- The keepalive timer in `readSseStream` runs alongside the `reader.read()` loop.
- Timer fires while `reader.read()` is blocking (waiting for server data) — this is the intended behavior.
- Must clear the timer in the `finally` block to prevent firing after stream closure.
