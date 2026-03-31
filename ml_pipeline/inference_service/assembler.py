import redis
import numpy as np

class FeatureAssembler:
    def __init__(self, host='localhost', port=6379, db=0):
        """
        Initializes the connection to the Redis state store.
        Uses connection pooling to prevent opening/closing sockets on every request,
        which is crucial for maintaining our sub-10ms SLA.
        """
        self.redis_pool = redis.ConnectionPool(host=host, port=port, db=db, decode_responses=True)
        self.r = redis.Redis(connection_pool=self.redis_pool)

    def assemble(self, user_ip: str) -> np.ndarray:
        """
        Fetches the 4 core L7 proxy features for a given IP from Redis.
        Returns a 2D NumPy array perfectly formatted for the Random Forest model.
        """
        # We assume Java stores these metrics in a Redis Hash specific to the IP
        redis_key = f"sage:telemetry:{user_ip}"

        # O(1) lookup to grab all fields in the hash at once
        raw_data = self.r.hgetall(redis_key)

        # Feature Extraction with Safe Fallbacks
        # If an IP is brand new, it won't be in Redis yet. We provide safe defaults
        # that represent a "Benign" baseline to prevent crashing the model.

        # 1. Session Depth (Default: 1 packet)
        depth = float(raw_data.get("SAGE_Session_Depth", 1.0))

        # 2. Temporal Variance (Default: 0.0 - Needs at least 2 packets to have variance)
        variance = float(raw_data.get("SAGE_Temporal_Variance", 0.0))

        # 3. Request Velocity (Default: 1.0 pkts/s)
        velocity = float(raw_data.get("SAGE_Request_Velocity", 1.0))

        # 4. Behavioral Diversity (Default: High variance to simulate human behavior initially)
        # Using 100.0 as a baseline benign diversity score based on our CIC-IDS2018 EDA
        diversity = float(raw_data.get("SAGE_Behavioral_Diversity", 100.0))

        # Array Assembly
        # MUST be in the exact order the model was trained on:
        # [Depth, Variance, Velocity, Diversity]
        feature_vector = [depth, variance, velocity, diversity]

        # Scikit-Learn expects a 2D array: shape (1, 4)
        return np.array(feature_vector).reshape(1, -1)

    def is_connected(self) -> bool:
        """Utility method to check Redis health."""
        try:
            return self.r.ping()
        except redis.ConnectionError:
            return False