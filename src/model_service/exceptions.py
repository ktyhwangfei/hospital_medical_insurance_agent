class ModelError(Exception):
    def __init__(self, message: str, model_name: str = ""):
        super().__init__(message)
        self.model_name = model_name


class ModelTimeoutError(ModelError):
    pass


class ModelRateLimitError(ModelError):
    pass


class ModelAuthError(ModelError):
    pass


class ModelServerError(ModelError):
    pass


class ModelExhaustedError(ModelError):
    def __init__(self, message: str, failures: list[dict]):
        super().__init__(message)
        self.failures = failures
