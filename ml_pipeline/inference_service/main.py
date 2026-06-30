from fastapi import FastAPI, HTTPException, Response
import joblib
import os
import time
import numpy as np
import pandas as pd
from contextlib import asynccontextmanager
from assembler import FeatureAssembler
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field

# Observability: Prometheus Metrics
REQUESTS_TOTAL = Counter('sage_inference_requests_total', 'Total prediction requests received')
THREATS_DETECTED_TOTAL = Counter('sage_inference_threats_detected_total', 'Total requests classified as malicious')
INFERENCE_LATENCY = Histogram('sage_inference_latency_seconds', 'Time spent processing the ML prediction')

import pickle

# Global State
MODEL = None
CLASSES = []
FEATURE_MAP = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration",
    "SAGE_Cart_Ratio",
    "SAGE_Asset_Skip_Ratio",
]
import os
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
assembler = FeatureAssembler(host=REDIS_HOST, port=REDIS_PORT)

# Schemas
class GatewayTelemetry(BaseModel):
    session_id: str
    SAGE_Session_Depth: float = Field(..., description="Total Fwd + Bwd Packets")
    SAGE_Temporal_Variance: float = Field(..., description="Flow IAT Std / Mean")
    SAGE_Request_Velocity: float = Field(..., description="Flow Pkts/s")
    SAGE_Behavioral_Diversity: float = Field(..., description="Fwd Pkt Len Std")
    SAGE_Endpoint_Concentration: float = Field(..., description="Price+inventory+product hits / total hits")
    SAGE_Cart_Ratio: float = Field(..., description="Cart+checkout hits / total hits")
    SAGE_Asset_Skip_Ratio: float = Field(..., description="1 - (static hits / total hits)")

class InferenceResult(BaseModel):
    session_id: str
    is_bot: bool
    bot_probability: float
    threat_class: str       #  "Benign", "Bot", "Flood", or "Infiltration"
    confidence: float       # Confidence score of the specific threat class
    processing_time_ms: float

# Lifespan & Initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    global MODEL, CLASSES
    base_path = os.path.dirname(__file__)
    model_dir = os.path.abspath(os.path.join(base_path, "..", "models"))
    model_path = os.path.join(model_dir, "sage_model.pkl")

    if os.path.exists(model_path):
        with open(model_path, "rb") as f:
            model_data = pickle.load(f)
        MODEL = model_data["model"]
        CLASSES = model_data["classes"]
        print(f"[+] SAGE Engine ML Service Ready.")
        print(f"[+] Master Brain Loaded: {model_path}")
        print(f"[+] Classes Detected: {CLASSES}")
    else:
        print(
            f"WARNING: Missing {model_path} in models/ directory. "
            "Inference will return 503 until models are available."
        )
    yield

app = FastAPI(lifespan=lifespan, title="SAGE ML Inference (Multiclass)")

# Endpoints
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

        # Multiclass Inference
        probabilities = MODEL.predict_proba(X_input)[0]
        max_prob_idx = int(np.argmax(probabilities))
        confidence = float(probabilities[max_prob_idx])
        predicted_class = CLASSES[max_prob_idx]

        # SAGE Enforcement Logic: Require confidence threshold for automated action
        CONFIDENCE_THRESHOLD = 0.75
        if predicted_class == "human" or confidence < CONFIDENCE_THRESHOLD:
            is_malicious = False
            threat_class = "Benign"
        else:
            is_malicious = True
            threat_class = predicted_class

        if is_malicious:
            THREATS_DETECTED_TOTAL.inc()

        # Latency Tracking
        processing_time_sec = time.perf_counter() - start_time
        INFERENCE_LATENCY.observe(processing_time_sec)

        return InferenceResult(
            session_id=data.session_id,
            is_bot=is_malicious,
            bot_probability=float(confidence if is_malicious else (1.0 - confidence)),
            threat_class=threat_class,
            confidence=round(confidence, 4),
            processing_time_ms=round(processing_time_sec * 1000, 3)
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
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
        vector = assembler.assemble(user_id)

        probabilities = MODEL.predict_proba(vector)[0]
        max_prob_idx = int(np.argmax(probabilities))
        confidence = float(probabilities[max_prob_idx])
        predicted_class = CLASSES[max_prob_idx]

        CONFIDENCE_THRESHOLD = 0.75
        if predicted_class == "human" or confidence < CONFIDENCE_THRESHOLD:
            is_malicious = False
            threat_class = "Benign"
        else:
            is_malicious = True
            threat_class = predicted_class

        if is_malicious:
            THREATS_DETECTED_TOTAL.inc()

        process_time_sec = time.perf_counter() - start_time
        INFERENCE_LATENCY.observe(process_time_sec)

        return {
            "user_id": user_id,
            "is_bot": is_malicious,
            "bot_probability": confidence,
            "threat_class": threat_class,
            "confidence": round(confidence, 4),
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
        "classes": CLASSES if MODEL is not None else [],
        "feature_map": FEATURE_MAP,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
