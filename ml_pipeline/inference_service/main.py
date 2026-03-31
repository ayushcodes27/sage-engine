from fastapi import FastAPI, HTTPException, Response
import joblib
import os
import time
import numpy as np
from contextlib import asynccontextmanager
from .assembler import FeatureAssembler
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field

#Observability: Prometheus Metrics
REQUESTS_TOTAL = Counter('sage_inference_requests_total', 'Total prediction requests received')
BOTS_DETECTED_TOTAL = Counter('sage_inference_bots_detected_total', 'Total requests classified as bots')
INFERENCE_LATENCY = Histogram('sage_inference_latency_seconds', 'Time spent processing the ML prediction')

# Global State
MODEL = None
FEATURE_MAP = None
assembler = FeatureAssembler(host='localhost', port=6379)

#Schemas
class GatewayTelemetry(BaseModel):
    session_id: str
    SAGE_Session_Depth: float = Field(..., description="Total Fwd + Bwd Packets")
    SAGE_Temporal_Variance: float = Field(..., description="Flow IAT Std / Mean")
    SAGE_Request_Velocity: float = Field(..., description="Flow Pkts/s")
    SAGE_Behavioral_Diversity: float = Field(..., description="Fwd Pkt Len Std")

class InferenceResult(BaseModel):
    session_id: str
    is_bot: bool
    bot_probability: float
    processing_time_ms: float

#Lifespan & Initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    global MODEL, FEATURE_MAP
    base_path = os.path.dirname(__file__)
    model_path = os.path.join(base_path, "models", "sage_rf_model_v1.joblib")
    features_path = os.path.join(base_path, "models", "sage_rf_features.joblib")

    if os.path.exists(model_path) and os.path.exists(features_path):
        MODEL = joblib.load(model_path)
        FEATURE_MAP = joblib.load(features_path)
        print(f"[+] SAGE Engine ML Service Ready. Tracking features: {FEATURE_MAP}")
    else:
        print(f"WARNING: Model artifacts not found at {model_path}. Inference will fail.")
    yield

app = FastAPI(lifespan=lifespan, title="SAGE ML Inference")

#Endpoints--

@app.post("/predict", response_model=InferenceResult)
def predict_anomaly(data: GatewayTelemetry):
    """
    Receives real-time telemetry from the Java Gateway.
    """
    if MODEL is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    start_time = time.perf_counter()
    REQUESTS_TOTAL.inc()

    try:
        # Extract features in the EXACT order the Random Forest expects
        input_vector = [getattr(data, feature_name) for feature_name in FEATURE_MAP]
        X_input = np.array(input_vector).reshape(1, -1)

        # Inference
        probabilities = MODEL.predict_proba(X_input)[0]
        bot_probability = float(probabilities[1])
        is_bot = bool(bot_probability > 0.5)

        if is_bot:
            BOTS_DETECTED_TOTAL.inc()

        # Latency Tracking
        processing_time_sec = time.perf_counter() - start_time
        INFERENCE_LATENCY.observe(processing_time_sec)

        return InferenceResult(
            session_id=data.session_id,
            is_bot=is_bot,
            bot_probability=round(bot_probability, 4),
            processing_time_ms=round(processing_time_sec * 1000, 3)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/predict/{user_id}")
async def predict_bot(user_id: str):
    """
    Pulls historical state from Redis via FeatureAssembler to make a prediction.
    """
    if MODEL is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    start_time = time.perf_counter()
    REQUESTS_TOTAL.inc()

    try:
        # Fetch the pre-assembled vector from Redis
        # NOTE: Ensure assembler.assemble() returns a 2D numpy array shaped (1, 4)
        # that matches the [Depth, Variance, Velocity, Diversity] order!
        vector = assembler.assemble(user_id)

        # Inference using Random Forest logic
        probabilities = MODEL.predict_proba(vector)[0]
        bot_probability = float(probabilities[1])
        is_bot = bool(bot_probability > 0.5)

        if is_bot:
            BOTS_DETECTED_TOTAL.inc()

        process_time_sec = time.perf_counter() - start_time
        INFERENCE_LATENCY.observe(process_time_sec)

        return {
            "user_id": user_id,
            "is_bot": is_bot,
            "bot_probability": round(bot_probability, 4),
            "processing_time_ms": round(process_time_sec * 1000, 3)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health")
def health_check():
    return {"status": "operational", "model": "RandomForest_v1"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)