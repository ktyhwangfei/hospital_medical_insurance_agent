from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE


class ModelRouter:
    def resolve(self, scene: str, model_type: str) -> tuple[str, list[str]]:
        key = (scene, model_type)
        model_name = ROUTING_TABLE.get(key)
        if model_name is None:
            model_name = ROUTING_TABLE.get(("default", model_type))
        fallbacks = FALLBACK_CHAINS.get(model_name, [])
        return model_name, list(fallbacks)

    def get_model_params(self, model_name: str) -> dict:
        default = {"temperature": 0.7, "max_tokens": 2048}
        return MODEL_PARAMS.get(model_name, default)
