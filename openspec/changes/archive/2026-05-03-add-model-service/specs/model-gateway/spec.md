## ADDED Requirements

### Requirement: ModelGateway provides unified model invocation

The ModelGateway SHALL provide a single entry point for all model invocations, abstracting the underlying model provider details.

#### Scenario: Invoke LLM model

- **WHEN** caller invokes `generate(messages, model_type=ModelType.LLM, scene="settlement_exception_guidance")`
- **THEN** ModelGateway returns a `ModelResponse` with `content`, `model_name`, `usage`, `finish_reason` fields

#### Scenario: Invoke Embedding model

- **WHEN** caller invokes `generate(messages, model_type=ModelType.EMBEDDING)`
- **THEN** ModelGateway returns a `ModelResponse` with `content` containing the embedding as JSON-serialized float list

### Requirement: ModelGateway supports streaming responses

The ModelGateway SHALL support streaming via synchronous Generator.

#### Scenario: Stream LLM response

- **WHEN** caller invokes `generate_stream(messages, model_type=ModelType.LLM, scene="settlement_exception_guidance")`
- **THEN** ModelGateway returns an `Iterator[StreamChunk]` where each chunk has `content` (incremental tokens), `finish_reason`, and `usage`

#### Scenario: Stream connection interrupted

- **WHEN** stream connection is interrupted mid-response
- **THEN** ModelGateway catches the exception and returns the chunks received so far, logging the partial failure

### Requirement: ModelGateway handles timeouts and retries

The ModelGateway SHALL enforce timeout limits and retry on transient failures.

#### Scenario: Request timeout

- **WHEN** model call exceeds configured timeout (default 30s)
- **THEN** ModelGateway retries up to `max_retries` times, then raises `ModelTimeoutError`

#### Scenario: Transient failure retry (5xx)

- **WHEN** model call fails with a server error (5xx)
- **THEN** ModelGateway retries immediately up to `max_retries` times before raising `ModelServerError`

#### Scenario: Rate limit retry (429)

- **WHEN** model call returns 429 rate limit
- **THEN** ModelGateway waits 10s (fixed delay) then retries up to `max_retries` times before raising `ModelRateLimitError`

#### Scenario: Auth failure (401/403)

- **WHEN** model call returns 401 or 403
- **THEN** ModelGateway raises `ModelAuthError` immediately without retry or fallback

### Requirement: ModelGateway logs all invocations

The ModelGateway SHALL log every model invocation for observability.

#### Scenario: Successful invocation logged

- **WHEN** a model call succeeds
- **THEN** ModelGateway logs `model_name`, `scene`, `latency_ms`, `token_usage`

#### Scenario: Failed invocation logged

- **WHEN** a model call fails
- **THEN** ModelGateway logs `model_name`, `scene`, `error_type`, `error_message`

#### Scenario: Stream invocation logged

- **WHEN** a streaming call completes
- **THEN** ModelGateway logs `model_name`, `scene`, `total_chunks`, `latency_ms`, `token_usage`
