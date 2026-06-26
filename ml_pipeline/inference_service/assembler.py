import redis
import numpy as np

class FeatureAssembler:
    def __init__(self, host="localhost", port=6379):
        self.r = redis.Redis(host=host, port=port, decode_responses=True)

    def assemble(self, user_id):
        key = f"user:features:{user_id}"
        data = self.r.hgetall(key)
        if not data:
            return np.array([[0.0] * 7])
        vector = [
            float(data.get("session_depth", 0.0)),
            float(data.get("temporal_variance", 0.0)),
            float(data.get("request_velocity", 0.0)),
            float(data.get("endpoint_diversity", 0.0)),
            float(data.get("endpoint_concentration", 0.0)),
            float(data.get("cart_ratio", 0.0)),
            float(data.get("asset_skip_ratio", 1.0))
        ]
        return np.array([vector])
