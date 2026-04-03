from fastapi import FastAPI, HTTPException, Response
import joblib
import os
import time
import pandas as pd
from contextlib import asynccontextmanager
from assembler import FeatureAssembler
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
DEFAULT_FEATURE_MAP = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
]

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
    model_dir = os.path.join(base_path, "models")
    configured_model_path = os.getenv("SAGE_MODEL_PATH")
    candidate_paths = []

    if configured_model_path:
        candidate_paths.append(configured_model_path)

    if os.path.isdir(model_dir):
        candidate_paths.extend(
            os.path.join(model_dir, filename)
            for filename in sorted(os.listdir(model_dir))
            if filename.endswith(".joblib") and "feature" not in filename.lower()
        )

    model_path = next((path for path in candidate_paths if os.path.exists(path)), None)

    if model_path:
        MODEL = joblib.load(model_path)
        FEATURE_MAP = DEFAULT_FEATURE_MAP
        print(f"[+] SAGE Engine ML Service Ready. Model loaded from {model_path}")
        print(f"[+] SAGE Engine ML Service Feature Order: {FEATURE_MAP}")
    else:
        MODEL = None
        FEATURE_MAP = None
        print(
            "WARNING: No .joblib model artifact found. "
            "Set SAGE_MODEL_PATH or place a .joblib file in inference_service/models/. "
            "Inference will return 503 until the model is available."
        )
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
        X_input = pd.DataFrame([input_vector], columns=FEATURE_MAP)

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
    return {
        "status": "operational" if MODEL is not None else "degraded",
        "model_loaded": MODEL is not None,
        "feature_map": FEATURE_MAP,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
