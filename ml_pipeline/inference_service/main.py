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

# Global State
MODEL = None
LABEL_ENCODER = None
FEATURE_MAP = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
]
# NOTE: Gateway now sends 7 features. The 3 new scraper-focused features are accepted
# by the request schema but intentionally not used for inference until model retraining.
assembler = FeatureAssembler(host='localhost', port=6379)

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
    global MODEL, LABEL_ENCODER
    base_path = os.path.dirname(__file__)
    model_dir = os.path.abspath(os.path.join(base_path, "..", "models"))
    fallback_model_dir = os.path.join(base_path, "models")

    model_path = os.path.join(model_dir, "sage_model.pkl")
    encoder_path = os.path.join(model_dir, "sage_label_encoder.pkl")
    if not os.path.exists(encoder_path):
        encoder_path = os.path.join(fallback_model_dir, "sage_label_encoder.pkl")

    if os.path.exists(model_path) and os.path.exists(encoder_path):
        MODEL = joblib.load(model_path)
        LABEL_ENCODER = joblib.load(encoder_path)
        print(f"[+] SAGE Engine ML Service Ready.")
        print(f"[+] Master Brain Loaded: {model_path}")
        print(f"[+] Classes Detected: {LABEL_ENCODER.classes_}")
    else:
        print(
            "WARNING: Missing sage_model.pkl or sage_label_encoder.pkl in models/ directory. "
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
    if MODEL is None or LABEL_ENCODER is None:
        raise HTTPException(status_code=503, detail="Model or Encoder not loaded")

    start_time = time.perf_counter()
    REQUESTS_TOTAL.inc()

    try:
        # Extract features in the EXACT order the Random Forest expects
        input_vector = [getattr(data, feature_name) for feature_name in FEATURE_MAP]
        X_input = pd.DataFrame([input_vector], columns=FEATURE_MAP)

        # Multiclass Inference
        probabilities = MODEL.predict_proba(X_input)[0]
        predicted_idx = int(np.argmax(probabilities))
        confidence = float(probabilities[predicted_idx])

        # Decode the integer prediction back to a string ("Benign", "Bot", etc.)
        threat_class = str(LABEL_ENCODER.inverse_transform([predicted_idx])[0])

        # SAGE Enforcement Logic: Anything not 'Benign' triggers the Java Ban
        is_malicious = threat_class != "Benign"

        if is_malicious:
            THREATS_DETECTED_TOTAL.inc()

        # Latency Tracking
        processing_time_sec = time.perf_counter() - start_time
        INFERENCE_LATENCY.observe(processing_time_sec)

        return InferenceResult(
            session_id=data.session_id,
            is_bot=is_malicious,
            bot_probability=confidence,
            threat_class=threat_class,
            confidence=round(confidence, 4),
            processing_time_ms=round(processing_time_sec * 1000, 3)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/predict/{user_id}")
async def predict_bot(user_id: str):
    """
    Pulls historical state from Redis via FeatureAssembler to make a prediction.
    """
    if MODEL is None or LABEL_ENCODER is None:
        raise HTTPException(status_code=503, detail="Model or Encoder not loaded")

    start_time = time.perf_counter()
    REQUESTS_TOTAL.inc()

    try:
        vector = assembler.assemble(user_id)

        probabilities = MODEL.predict_proba(vector)[0]
        predicted_idx = int(np.argmax(probabilities))
        confidence = float(probabilities[predicted_idx])

        threat_class = str(LABEL_ENCODER.inverse_transform([predicted_idx])[0])
        is_malicious = threat_class != "Benign"

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
        "classes": LABEL_ENCODER.classes_.tolist() if LABEL_ENCODER else [],
        "feature_map": FEATURE_MAP,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)