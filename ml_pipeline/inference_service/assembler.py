import numpy as np
import redis

class FeatureAssembler:
    def __init__(self, host='localhost', port=6379):
        # We use decode_responses=True so Redis returns strings, not bytes
        self.r = redis.Redis(host=host, port=port, decode_responses=True)

        # must match the model's training order
        self.feature_keys = [
            'endpoint_diversity',
            'temporal_variance',
            'session_depth',
            'request_velocity'
        ]

    def assemble(self, user_id: str):
        # Fetch the hash map for this user
        # Hash Key format assumed: "user:features:{user_id}"
        raw_features = self.r.hgetall(f"user:features:{user_id}")

        vector = []
        for key in self.feature_keys:
            #Imputation (filling missing data)
            # If a feature doesn't exist yet, we default to 0.0
            val = raw_features.get(key, 0.0)
            vector.append(float(val))

        # Transform to NumPy array and reshape for the model (1 sample, 4 features)
        return np.array(vector).reshape(1, -1)