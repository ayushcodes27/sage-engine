import requests
import time
import random

GATEWAY_URL = "http://localhost:8083"
RUN_ID = "shadow-2026-09-18-a"

def send_traffic(client_id, is_bot):
    headers = {
        "X-SAGE-Client-Id": client_id,
        "X-SAGE-Run-Id": RUN_ID,
        "X-Forwarded-For": f"192.168.1.{random.randint(1, 255)}"
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    num_requests = 25 if is_bot else 22
    
    for i in range(num_requests):
        path = "/products"
        if is_bot:
            # Scraper/Flood behavior
            path = f"/api/price/{i}"
        else:
            # Human behavior
            paths = ["/products", "/products/123", "/cart", "/checkout", "/static/style.css"]
            path = random.choice(paths)
            
        try:
            session.get(f"{GATEWAY_URL}{path}", timeout=2)
        except Exception:
            pass
            
        # Add some delay for duration > 3.0s constraint and to avoid rate limits
        if not is_bot:
            time.sleep(0.3)
        else:
            time.sleep(0.3)
            
    print(f"Finished traffic for {client_id}")

clients = [
    ("human-01", False),
    ("human-02", False),
    ("scraper-01", True),
    ("flood-01", True)
]

for c, bot in clients:
    send_traffic(c, bot)

print("Done generating shadow traffic.")
