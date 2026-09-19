from fastapi import FastAPI, HTTPException, Response
import joblib
import os
import time
import numpy as np
import pandas as pd
from contextlib import asynccontextmanager
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import pickle
import json
import hashlib

# Observability: Prometheus Metrics
REQUESTS_TOTAL = Counter('sage_inference_requests_total', 'Total prediction requests received')
THREATS_DETECTED_TOTAL = Counter('sage_inference_threats_detected_total', 'Total requests classified as malicious')
INFERENCE_LATENCY = Histogram('sage_inference_latency_seconds', 'Time spent processing the ML prediction')

# Global State
PROD_MODEL = None
SHADOW_MODEL = None
CLASSES = []
CONTRACT_HASH = "unknown"

PROD_FEATURE_MAP: List[str] = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration",
    "SAGE_Cart_Ratio",
    "SAGE_Asset_Skip_Ratio",
]

SHADOW_FEATURE_MAP: List[str] = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration",
    "SAGE_Cart_Ratio",
    "SAGE_NonStatic_Navigation_Gap",
    "SAGE_NonStatic_Long_Gap_Ratio",
]

PROD_MODEL_META: Dict[str, Any] = {
    "version": "sage_binary_v1",
    "contract_version": "1.0",
    "contract_hash": "unknown",
    "threshold": 0.50,
    "features": PROD_FEATURE_MAP,
}

SHADOW_MODEL_META: Dict[str, Any] = {
    "version": "timing-v1",
    "contract_version": "1.0-timing",
    "contract_hash": "unknown",
    "threshold": 0.35,
    "features": SHADOW_FEATURE_MAP,
}

# Schemas
class GatewayTelemetry(BaseModel):
    session_id: str
    gateway_timestamp_ms: float = 0.0
    SAGE_Session_Depth: float = Field(..., description="Total non-static requests")
    SAGE_Temporal_Variance: float = Field(..., description="Flow IAT Std / Mean")
    SAGE_Request_Velocity: float = Field(..., description="Flow Pkts/s")
    SAGE_Behavioral_Diversity: float = Field(..., description="Path Shannon Entropy")
    SAGE_Endpoint_Concentration: float = Field(..., description="Top endpoint visits / total non-static")
    SAGE_Cart_Ratio: float = Field(..., description="Cart+checkout hits / total hits")
    SAGE_Asset_Skip_Ratio: float = Field(1.0, description="1 - (static hits / total hits)")
    SAGE_NonStatic_Navigation_Gap: float = Field(0.0, description="Median gap between non-static requests")
    SAGE_NonStatic_Long_Gap_Ratio: float = Field(0.0, description="Ratio of non-static gaps >= 500ms")

class InferenceResult(BaseModel):
    session_id: str
    is_bot: bool
    bot_probability: float
    threat_class: str       #  "Benign", "Bot", "Flood", or "Infiltration"
    confidence: float       # Confidence score of the specific threat class
    production_processing_time_ms: float
    
    # Shadow Fields
    shadow_status: str
    shadow_is_bot: Optional[bool] = None
    shadow_bot_probability: Optional[float] = None
    shadow_threat_class: Optional[str] = None
    shadow_processing_time_ms: Optional[float] = None
    
    # Metadata & Cryptographic Identity
    contract_hash: str
    model_version: str
    shadow_threshold: Optional[float] = 0.35
    prod_model_sha256: Optional[str] = None
    shadow_model_sha256: Optional[str] = None
    shadow_contract_hash: Optional[str] = None
    shadow_feature_list_hash: Optional[str] = None

# Lifespan & Initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    global PROD_MODEL, SHADOW_MODEL, CLASSES, CONTRACT_HASH
    global PROD_FEATURE_MAP, SHADOW_FEATURE_MAP, PROD_MODEL_META, SHADOW_MODEL_META
    base_path = os.path.dirname(__file__)
    model_dir = os.path.abspath(os.path.join(base_path, "..", "models"))
    
    # 1. Load and hash feature contract for Gateway production contract verification
    contract_path = os.path.join(model_dir, "contracts", "contract_prod_7feat.json")
    if not os.path.exists(contract_path):
        contract_path = os.path.join(model_dir, "feature_contract.json")
    try:
        with open(contract_path, "rb") as f:
            c_bytes = f.read()
        CONTRACT_HASH = hashlib.sha256(c_bytes).hexdigest()
        PROD_MODEL_META["contract_hash"] = CONTRACT_HASH
        print(f"[+] Production Contract Hash: {CONTRACT_HASH}")
    except Exception as e:
        print(f"[-] Failed to load contract hash: {e}")

    # Load frozen manifest if present for startup assertions
    manifest_path = os.path.join(model_dir, "frozen_models_manifest.json")
    manifest = None
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            print(f"[-] Warning: Failed to parse frozen manifest: {e}")
        
    # 2. Load Production Model (7 features) with hash-before-unpickle
    prod_path = os.path.join(model_dir, "sage_binary_model.pkl")
    if os.path.exists(prod_path):
        with open(prod_path, "rb") as f:
            prod_bytes = f.read()
        prod_sha256 = hashlib.sha256(prod_bytes).hexdigest()
        PROD_MODEL_META["sha256"] = prod_sha256
        
        if manifest and "models" in manifest:
            expected_sha = None
            if "sage_binary_model" in manifest["models"]:
                expected_sha = manifest["models"]["sage_binary_model"]["sha256"]
            elif "production_7feat" in manifest["models"]:
                expected_sha = manifest["models"]["production_7feat"].get("model_sha256") or manifest["models"]["production_7feat"].get("sha256")
            if expected_sha and prod_sha256 != expected_sha:
                raise RuntimeError(
                    f"PROD model hash mismatch! Expected {expected_sha}, got {prod_sha256}"
                )

        model_data = pickle.loads(prod_bytes)
        PROD_MODEL = model_data["model"]
        if hasattr(PROD_MODEL, 'n_jobs'):
            PROD_MODEL.n_jobs = 1
        CLASSES = model_data.get("classes", ["Benign", "Bot"])
        PROD_FEATURE_MAP = model_data.get("features", PROD_FEATURE_MAP)
        PROD_MODEL_META["features"] = PROD_FEATURE_MAP
        PROD_MODEL_META["feature_list_hash"] = hashlib.sha256(
            json.dumps(PROD_FEATURE_MAP, separators=(',', ':')).encode("utf-8")
        ).hexdigest()
        PROD_MODEL_META["version"] = model_data.get("model_version", "sage_binary_v1")
        PROD_MODEL_META["threshold"] = float(model_data.get("threshold", 0.50))
        print(f"[+] PROD Brain Loaded: {prod_path} (SHA-256: {prod_sha256[:12]}..., {len(PROD_FEATURE_MAP)} features)")
    else:
        print(f"WARNING: Missing PROD model {prod_path}")
        
    # 3. Load Shadow Model with hash-before-unpickle
    shadow_target = os.getenv("SHADOW_MODEL_FILE", "eclog_timing_binary_model.pkl")
    shadow_path = os.path.join(model_dir, shadow_target)
    if not os.path.exists(shadow_path):
        fallback_path = os.path.join(model_dir, "eclog_timing_binary_model.pkl")
        if os.path.exists(fallback_path):
            shadow_path = fallback_path

    if os.path.exists(shadow_path):
        try:
            with open(shadow_path, "rb") as f:
                shadow_bytes = f.read()
            shadow_sha256 = hashlib.sha256(shadow_bytes).hexdigest()
            SHADOW_MODEL_META["sha256"] = shadow_sha256
            
            # Check against manifest if available
            shadow_key = os.path.splitext(os.path.basename(shadow_path))[0]
            if manifest and "models" in manifest:
                expected_sha = None
                if shadow_key in manifest["models"]:
                    expected_sha = manifest["models"][shadow_key]["sha256"]
                elif "timing" in shadow_target and "eclog_timing_8feat" in manifest["models"]:
                    expected_sha = manifest["models"]["eclog_timing_8feat"].get("model_sha256") or manifest["models"]["eclog_timing_8feat"].get("sha256")
                elif "eclog_weak_7feat" in manifest["models"]:
                    expected_sha = manifest["models"]["eclog_weak_7feat"].get("model_sha256") or manifest["models"]["eclog_weak_7feat"].get("sha256")
                if expected_sha and shadow_sha256 != expected_sha:
                    raise RuntimeError(
                        f"SHADOW model hash mismatch! Expected {expected_sha}, got {shadow_sha256}"
                    )

            s_data = pickle.loads(shadow_bytes)
            SHADOW_MODEL = s_data["model"]
            if hasattr(SHADOW_MODEL, 'n_jobs'):
                SHADOW_MODEL.n_jobs = 1
            if "features" in s_data:
                SHADOW_FEATURE_MAP = s_data["features"]
            SHADOW_MODEL_META["features"] = SHADOW_FEATURE_MAP
            SHADOW_MODEL_META["feature_list_hash"] = hashlib.sha256(
                json.dumps(SHADOW_FEATURE_MAP, separators=(',', ':')).encode("utf-8")
            ).hexdigest()

            # Resolve contract hash based on feature count
            if len(SHADOW_FEATURE_MAP) == 7:
                c_path = os.path.join(model_dir, "contracts", "contract_prod_7feat.json")
            elif len(SHADOW_FEATURE_MAP) == 6:
                c_path = os.path.join(model_dir, "contracts", "contract_eclog_6feat.json")
            elif len(SHADOW_FEATURE_MAP) == 8:
                c_path = os.path.join(model_dir, "contracts", "contract_eclog_timing_8feat.json")
            else:
                c_path = None

            if c_path and os.path.exists(c_path):
                with open(c_path, "rb") as f:
                    SHADOW_MODEL_META["contract_hash"] = hashlib.sha256(f.read()).hexdigest()
            else:
                SHADOW_MODEL_META["contract_hash"] = s_data.get("contract_hash", "unknown")

            SHADOW_MODEL_META["contract_version"] = s_data.get("contract_version", "unknown")
            SHADOW_MODEL_META["version"] = s_data.get("model_version", os.path.basename(shadow_path))
            SHADOW_MODEL_META["threshold"] = float(s_data.get("threshold", 0.35))
            print(f"[+] SHADOW Brain Loaded: {shadow_path} (SHA-256: {shadow_sha256[:12]}..., {len(SHADOW_FEATURE_MAP)} features)")
        except Exception as e:
            print(f"[-] Failed to load SHADOW model: {e}")
            raise
    else:
        print(f"WARNING: Missing SHADOW model {shadow_path}")
        
    yield

app = FastAPI(lifespan=lifespan, title="SAGE ML Inference")

# Endpoints
@app.post("/predict", response_model=InferenceResult)
async def predict_anomaly(data: GatewayTelemetry):
    """
    Receives real-time telemetry from the Java Gateway.
    Dispatches to 7-feature production model and model-specific shadow model.
    """
    if PROD_MODEL is None:
        raise HTTPException(status_code=503, detail="Production model not loaded")

    REQUESTS_TOTAL.inc()

    try:
        # --- PROD INFERENCE (7 features) ---
        prod_vector = [getattr(data, feat, 0.0) for feat in PROD_FEATURE_MAP]
        X_prod = pd.DataFrame([prod_vector], columns=PROD_FEATURE_MAP)

        prod_start = time.perf_counter()
        prod_probs = PROD_MODEL.predict_proba(X_prod)[0].tolist()
        prod_processing_time = time.perf_counter() - prod_start
        INFERENCE_LATENCY.observe(prod_processing_time)
        
        bot_probability = float(prod_probs[1])
        PROD_CONFIDENCE_THRESHOLD = float(os.getenv("PROD_CONFIDENCE_THRESHOLD", str(PROD_MODEL_META.get("threshold", 0.50))))
        is_malicious = bot_probability >= PROD_CONFIDENCE_THRESHOLD
        threat_class = "Bot" if is_malicious else "Benign"

        if is_malicious:
            THREATS_DETECTED_TOTAL.inc()

        # --- SHADOW INFERENCE (Model-specific features, e.g. 8 features for timing) ---
        shadow_status = "unavailable"
        shadow_is_bot = None
        shadow_bot_prob = None
        shadow_threat = None
        shadow_processing_time = None
        SHADOW_CONFIDENCE_THRESHOLD = float(os.getenv("SHADOW_CONFIDENCE_THRESHOLD", str(SHADOW_MODEL_META.get("threshold", 0.35))))
        shadow_model_sha256 = None
        shadow_contract_hash = None
        shadow_feature_list_hash = None
        
        if SHADOW_MODEL is not None:
            try:
                shadow_start = time.perf_counter()
                shadow_vector = [getattr(data, feat, 0.0) for feat in SHADOW_FEATURE_MAP]
                X_shadow = pd.DataFrame([shadow_vector], columns=SHADOW_FEATURE_MAP)
                shadow_probs = SHADOW_MODEL.predict_proba(X_shadow)[0].tolist()
                shadow_processing_time = (time.perf_counter() - shadow_start) * 1000.0
                shadow_bot_prob = float(shadow_probs[1])
                shadow_is_bot = shadow_bot_prob >= SHADOW_CONFIDENCE_THRESHOLD
                shadow_threat = "Bot" if shadow_is_bot else "Benign"
                shadow_status = "ok"
                shadow_model_sha256 = SHADOW_MODEL_META.get("sha256")
                shadow_contract_hash = SHADOW_MODEL_META.get("contract_hash")
                shadow_feature_list_hash = SHADOW_MODEL_META.get("feature_list_hash")
            except Exception as e:
                print(f"[-] Shadow inference failed: {e}")
                shadow_status = "error"

        return InferenceResult(
            session_id=data.session_id,
            is_bot=is_malicious,
            bot_probability=round(bot_probability, 4),
            threat_class=threat_class,
            confidence=round(bot_probability if is_malicious else (1.0 - bot_probability), 4),
            production_processing_time_ms=round(prod_processing_time * 1000, 3),
            shadow_status=shadow_status,
            shadow_is_bot=shadow_is_bot,
            shadow_bot_probability=round(shadow_bot_prob, 4) if shadow_bot_prob is not None else None,
            shadow_threat_class=shadow_threat,
            shadow_processing_time_ms=round(shadow_processing_time, 3) if shadow_processing_time is not None else None,
            contract_hash=CONTRACT_HASH,
            model_version=PROD_MODEL_META.get("version", "sage_binary_v1"),
            shadow_threshold=SHADOW_CONFIDENCE_THRESHOLD,
            prod_model_sha256=PROD_MODEL_META.get("sha256"),
            shadow_model_sha256=shadow_model_sha256,
            shadow_contract_hash=shadow_contract_hash,
            shadow_feature_list_hash=shadow_feature_list_hash
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health")
def health_check():
    return {
        "status": "operational" if PROD_MODEL is not None else "degraded",
        "prod_model_loaded": PROD_MODEL is not None,
        "shadow_model_loaded": SHADOW_MODEL is not None,
        "classes": CLASSES if PROD_MODEL is not None else [],
        "prod_feature_map": PROD_FEATURE_MAP,
        "shadow_feature_map": SHADOW_FEATURE_MAP,
        "prod_model_sha256": PROD_MODEL_META.get("sha256"),
        "prod_contract_hash": CONTRACT_HASH,
        "prod_feature_list_hash": PROD_MODEL_META.get("feature_list_hash"),
        "prod_threshold": PROD_MODEL_META.get("threshold", 0.50),
        "prod_model_version": PROD_MODEL_META.get("version", "unknown"),
        "shadow_model_sha256": SHADOW_MODEL_META.get("sha256"),
        "shadow_contract_hash": SHADOW_MODEL_META.get("contract_hash", "unknown"),
        "shadow_feature_list_hash": SHADOW_MODEL_META.get("feature_list_hash"),
        "shadow_threshold": SHADOW_MODEL_META.get("threshold", 0.35),
        "shadow_model_version": SHADOW_MODEL_META.get("version", "unknown"),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
