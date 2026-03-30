from fastapi import FastAPI, HTTPException, Response
import joblib
import os
import time
from contextlib import asynccontextmanager
from .assembler import FeatureAssembler
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST


# Counters only go up. for counting total requests and bots.
REQUESTS_TOTAL = Counter('sage_inference_requests_total', 'Total prediction requests received')
BOTS_DETECTED_TOTAL = Counter('sage_inference_bots_detected_total', 'Total requests classified as bots')

# Histograms measure duration/sizes
INFERENCE_LATENCY = Histogram('sage_inference_latency_seconds', 'Time spent processing the ML prediction')

# Global State & Lifespan
model = None
assembler = FeatureAssembler(host='localhost', port=6379)

from pydantic import BaseModel

class GatewayTelemetry(BaseModel):
    session_id: str
    endpoint_diversity: float
    temporal_variance: float
    session_depth: int
    request_velocity: float

class InferenceResult(BaseModel):
    session_id: str
    is_bot: bool
    bot_probability: float
    processing_time_ms: float

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    base_path = os.path.dirname(__file__)
    model_path = os.path.join(base_path, "isolation_forest.pkl")
    if os.path.exists(model_path):
        model = joblib.load(model_path)
        print("Model loaded successfully.")
    yield

app = FastAPI(lifespan=lifespan, title="SAGE ML Inference")

@app.post("/predict", response_model=InferenceResult)
def predict_anomaly(data: GatewayTelemetry):
    """
    Receives real-time telemetry from the Java Gateway,
    processes features, and returns a bot risk score.
    """
    start_time = time.perf_counter()
    REQUEST_COUNT.inc()

    try:
        # Assemble and Scale (using the logic in assembler.py)
        # Note: data.dict() converts the Pydantic model to a Python dictionary
        model_input = assembler.process(data.dict())

        # Inference: predict_proba returns [prob_human, prob_bot]
        probabilities = rf_model.predict_proba(model_input)[0]
        bot_probability = float(probabilities[1])

        # Decision Logic (Standard 0.5 threshold)
        is_bot = bool(bot_probability > 0.5)

        if is_bot:
            BOT_DETECTED_COUNT.inc()

        # Latency Calculation
        processing_time_sec = time.perf_counter() - start_time
        INFERENCE_LATENCY.observe(processing_time_sec)

        return InferenceResult(
            session_id=data.session_id,
            is_bot=is_bot,
            bot_probability=round(bot_probability, 4),
            processing_time_ms=round(processing_time_sec * 1000, 2)
        )

    except Exception as e:
        # 500 Internal Server Error if the ML logic fails
        raise HTTPException(status_code=500, detail=str(e))



# API Endpoints
@app.get("/predict/{user_id}")
async def predict_bot(user_id: str):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # Start the stopwatch for latency tracking
    start_time = time.time()
    REQUESTS_TOTAL.inc() # Increment total requests by 1

    try:
        vector = assembler.assemble(user_id)
        prediction = model.predict(vector)
        score = model.decision_function(vector)

        is_bot = bool(prediction[0] == -1)

        # If it's a bot, increment the bot counter
        if is_bot:
            BOTS_DETECTED_TOTAL.inc()

        # Stop the stopwatch and record the latency
        process_time = time.time() - start_time
        INFERENCE_LATENCY.observe(process_time)

        return {
            "user_id": user_id,
            "is_bot": is_bot,
            "anomaly_score": float(score[0]),
            "processing_time_ms": round(process_time * 1000, 2) # Adding to response for easy debugging
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# This is the endpoint Prometheus will constantly check to pull the data
@app.get("/metrics")
async def get_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health")
def health_check():
    return {"status": "operational", "model": "RandomForestClassifier"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)