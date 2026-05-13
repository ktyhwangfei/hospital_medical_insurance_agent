# SSE Refactor — Architecture Decisions

## 1. sendChatStream signature change
- **Decision**: Changed return type from `Promise<void>` to `Promise<{ cancel: () => void; retryCount: number }>`
- **Rationale**: Callers that `await` the promise without assigning are fully backward compatible (the new return value is simply unused by existing callers).
- **Third parameter**: Added optional `signal?: AbortSignal` for parent-driven cancellation.

## 2. AbortController strategy
- **Decision**: Always create an internal `AbortController`. If an external `AbortSignal` is provided, forward its abort to the internal controller via `forwardAbortSignal()`.
- **Rationale**: Guarantees `cancel()` always works regardless of whether an external signal is provided. The fetch always uses the internal controller's signal, so all abort sources converge cleanly.

## 3. Retry policy
- **Decision**: Retry ONLY on `TypeError` (network errors). Do NOT retry on HTTP 4xx/5xx (thrown as `ApiClientError`) or abort errors.
- **Backoff**: `Math.min(1000 * Math.pow(3, attempt-1), 10000) * (0.8 + Math.random() * 0.4)` — exponential with jitter.
- **Max attempts**: 3 (configurable via `maxRetries` in `useSSEConnection`, hardcoded in `sendChatStream`).

## 4. Keepalive in readSseStream
- **Decision**: Timer fires after 15s of inactivity. Emits a synthetic `stream:step` event with `{ step: 'keepalive', message: '等待服务器响应...' }`. Timer re-arms after each emission and resets on every data arrival.
- **Rationale**: Keepalive is a transparent addition that doesn't change `readSseStream`'s signature. The synthetic event uses the existing SSE event pipeline.

## 5. useSSEConnection vs useChatStream separation
- **Decision**: `useSSEConnection` is generic (uses `fetch` + `readSseStream` directly), `useChatStream` is chat-specific (uses `sendChatStream`).
- **Rationale**: `useSSEConnection` takes a `url` parameter which is only meaningful if it actually fetches that URL. Using `sendChatStream` (which has a hardcoded `/chat/stream` URL) would make the `url` parameter pointless.
- **Note**: The spec originally stated `useSSEConnection` calls `sendChatStream`, but this conflicts with the `url` parameter. Our implementation is architecturally consistent.

## 6. Event naming backward compatibility
- **Decision**: `useChatStream` normalizes event names by stripping the `stream:` prefix for switch dispatch. The `token` event is handled alongside `delta`/`stream:delta` in the content extraction path.
- **Rationale**: Supports both old (`delta`, `final`, `start`) and new (`stream:delta`, `stream:final`, `stream:start`) naming conventions transparently.

## 7. Ref pattern for callback freshness
- **Decision**: All optional callbacks (`onMessage`, `onError`, etc.) are stored in refs and accessed via `xxxRef.current` inside event handlers.
- **Rationale**: Avoids stale closures in the SSE event handler without re-creating it on every render.
