class ModelError(Exception):
    def __init__(self, message: str, model_name: str = ""):
        super().__init__(message)
        self.model_name = model_name


class ModelConfigError(ModelError):
    """模型服务未配置（无 MODEL_BASE_URL/MODEL_API_KEY 且无已发布治理路由）。"""


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
