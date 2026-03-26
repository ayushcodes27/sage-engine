from fastapi import FastAPI, HTTPException
import joblib
import os
import numpy as np
from contextlib import asynccontextmanager
from assembler import FeatureAssembler



model = None

# Initialize our assembler
# later in a real setup -> these would come from environment variables
assembler = FeatureAssembler(host='localhost', port=6379)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    # Get the absolute path to the .pkl file
    base_path = os.path.dirname(__file__)
    model_path = os.path.join(base_path, "isolation_forest.pkl")

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found at {model_path}.")

    # Load model into memory
    print(f"Loading model from {model_path}...")
    model = joblib.load(model_path)
    yield

    print("Shutting down...")

app = FastAPI(
    title="SAGE Engine Inference Service",
    lifespan=lifespan
)

@app.get("/predict/{user_id}")
async def predict_bot(user_id: str):
    try:
        # Assemble the vector
        vector = assembler.assemble(user_id)
        prediction = model.predict(vector)
        score = model.decision_function(vector)
        # Dummy logic for now
        # since we haven't loaded the real .pkl file yet
        return {
                "user_id": user_id,
                "is_bot": bool(prediction[0] == -1),
                "anomaly_score": float(score[0])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)