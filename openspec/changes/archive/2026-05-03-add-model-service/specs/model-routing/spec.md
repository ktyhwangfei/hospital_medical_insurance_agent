## ADDED Requirements

### Requirement: ModelRouter selects model by scene and type

The ModelRouter SHALL select the appropriate model based on business scene and model type.

#### Scenario: Route by scene

- **WHEN** caller requests model for scene="settlement_exception_guidance" and type=LLM
- **THEN** ModelRouter returns the configured model name for that scene

#### Scenario: Default model for unknown scene

- **WHEN** caller requests model for an unconfigured scene
- **THEN** ModelRouter returns the default model for that model type

### Requirement: ModelRouter supports fallback chain

The ModelRouter SHALL provide a fallback chain when the primary model fails.

#### Scenario: Primary model fails, fallback succeeds

- **WHEN** primary model raises a retriable `ModelError` (Timeout, RateLimit, Server) and retries are exhausted
- **THEN** ModelRouter automatically tries the next model in the fallback chain

#### Scenario: Auth error stops immediately

- **WHEN** primary model raises `ModelAuthError`
- **THEN** ModelRouter raises `ModelAuthError` immediately without trying fallback models

#### Scenario: All models in chain fail

- **WHEN** all models in the fallback chain have been tried and failed
- **THEN** ModelRouter raises `ModelExhaustedError` with details of all failures

### Requirement: Model configuration is centralized

Model routing configuration SHALL be defined in a single configuration module.

#### Scenario: Configuration structure

- **WHEN** system starts
- **THEN** ModelRouter loads routing config mapping `(scene, model_type)` to `(primary_model, fallback_models)`

#### Scenario: No fallback configured

- **WHEN** a scene has no fallback models configured
- **THEN** ModelRouter treats it as a single-model chain (no fallback)

### Requirement: Model parameters are configurable per model

Each model SHALL have configurable default parameters (temperature, max_tokens).

#### Scenario: Model-specific parameters

- **WHEN** a model is selected for a request
- **THEN** ModelGateway applies the model's configured `temperature` and `max_tokens` defaults unless overridden in the request

#### Scenario: No parameters configured

- **WHEN** a model has no specific parameters configured
- **THEN** ModelGateway uses system defaults (temperature=0.7, max_tokens=2048)
