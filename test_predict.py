import requests

payload = {
    "session_id": "test",
    "SAGE_Session_Depth": 21.0,
    "SAGE_Temporal_Variance": 1.2,
    "SAGE_Request_Velocity": 4.5,
    "SAGE_Behavioral_Diversity": 3.4,
    "SAGE_Endpoint_Concentration": 0.8,
    "SAGE_Cart_Ratio": 0.1,
    "SAGE_Asset_Skip_Ratio": 0.9
}

response = requests.post("http://localhost:8000/predict", json=payload)
print(f"Status Code: {response.status_code}")
print(f"Response Body: {response.text}")
