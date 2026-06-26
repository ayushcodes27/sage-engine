import random
import time
from locust import HttpUser, task, between, events

# ---------------------------------------------------------------------------
# IP Generators — ALL residential ranges
# ---------------------------------------------------------------------------
RESIDENTIAL_RANGES = [
    ("172.16.0.", 1, 254),
    ("192.168.1.", 1, 254),
    ("10.0.1.", 1, 254),
    ("10.10.0.", 1, 254),
    ("172.25.0.", 1, 254),
    ("172.31.0.", 1, 254),
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

def ip_residential():
    prefix, lo, hi = random.choice(RESIDENTIAL_RANGES)
    return f"{prefix}{random.randint(lo, hi)}"

def ip_residential_bot():
    prefix, lo, hi = random.choice(RESIDENTIAL_RANGES)
    return f"{prefix}{random.randint(lo, hi)}"

def random_headers(ip):
    return {
        "X-Forwarded-For": ip,
        "User-Agent": random.choice(USER_AGENTS),
        "Content-Type": "application/json",
    }

# ---------------------------------------------------------------------------
# Endpoint pools (aligned with mock-target-site routes)
# ---------------------------------------------------------------------------
PRODUCT_ENDPOINTS = [f"/products/{i}" for i in range(1, 9)]

STATIC_ASSETS = [
    "/static/style.css",
    "/static/app.js",
    "/static/logo.png",
]

SENSITIVE_ENDPOINTS = [
    "/admin/routes",
    "/actuator/prometheus",
    "/../etc/passwd",
    "/api/search?q=' OR 1=1"
]

SCRAPER_TARGETS = [
    "/products/1", "/products/2", 
    "/api/price/1", "/api/inventory/1"
]

# ---------------------------------------------------------------------------
# 1. Human User (ground truth — should never be blocked)
# ---------------------------------------------------------------------------
class HumanUser(HttpUser):
    weight = 10
    wait_time = between(2, 8)

    def on_start(self):
        self.ip = ip_residential()
        self.headers = random_headers(self.ip)

    @task(3)
    def browse_product(self):
        endpoint = random.choice(PRODUCT_ENDPOINTS)
        self.client.get(endpoint, headers=self.headers, name="Human - /products/[id]")
        time.sleep(random.uniform(0.1, 0.4))
        for asset in random.sample(STATIC_ASSETS, k=random.randint(1, 3)):
            self.client.get(asset, headers=self.headers, name="Human - /static/[asset]")

    @task(1)
    def visit_cart(self):
        self.client.get("/cart", headers=self.headers, name="Human - /cart")
        time.sleep(random.uniform(1.0, 3.0))
        if random.random() < 0.3:
            self.client.post("/checkout", json={"status":"mock"}, headers=self.headers, name="Human - /checkout")

    @task(1)
    def visit_homepage(self):
        self.client.get("/", headers=self.headers, name="Human - /")
        time.sleep(random.uniform(0.2, 0.5))
        for asset in STATIC_ASSETS:
            self.client.get(asset, headers=self.headers, name="Human - /static/[asset]")

# ---------------------------------------------------------------------------
# 2. Stealth Scraper (residential IP, paced — hardest ML challenge)
# ---------------------------------------------------------------------------
class StealthScraperUser(HttpUser):
    weight = 10
    wait_time = between(1, 3)

    def on_start(self):
        self.ip = ip_residential_bot()
        self.headers = random_headers(self.ip)

    @task(10)
    def scrape_product(self):
        endpoint = random.choice(SCRAPER_TARGETS)
        self.client.get(endpoint, headers=self.headers, name="Scraper - target")

# ---------------------------------------------------------------------------
# 3. Slow Flood Bot (residential IP, elevated velocity)
# ---------------------------------------------------------------------------
class SlowFloodUser(HttpUser):
    weight = 10
    wait_time = between(0.2, 0.8)

    def on_start(self):
        self.ip = ip_residential_bot()
        self.headers = random_headers(self.ip)
        self.target = random.choice(["/", "/products/1"])

    @task
    def flood(self):
        self.client.get(self.target, headers=self.headers, name="Flood - target")

# ---------------------------------------------------------------------------
# 4. Stealth Recon Bot (residential IP, slow probing)
# ---------------------------------------------------------------------------
class StealthReconUser(HttpUser):
    weight = 10
    wait_time = between(3, 8)

    def on_start(self):
        self.ip = ip_residential_bot()
        self.headers = random_headers(self.ip)

    @task(5)
    def probe_sensitive(self):
        endpoint = random.choice(SENSITIVE_ENDPOINTS)
        self.client.get(endpoint, headers=self.headers, name="Recon - sensitive")

    @task(1)
    def probe_product(self):
        self.client.get(random.choice(PRODUCT_ENDPOINTS), headers=self.headers, name="Recon - blend")
