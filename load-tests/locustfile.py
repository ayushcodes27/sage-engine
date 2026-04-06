import random
import sys
from locust import HttpUser, task, between, constant, tag

def generate_akamai_ip():
    return f"192.168.10.{random.randint(1, 254)}"

CLOUDFLARE_BOTNET_POOL = [
    f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    for _ in range(1000)
]

def generate_cloudflare_ip():
    return random.choice(CLOUDFLARE_BOTNET_POOL)

RECON_PROXIES = ["45.33.22.1", "45.33.22.2", "45.33.22.3", "45.33.22.4", "45.33.22.5"]

@tag('human')
class NormalHumanUser(HttpUser):
    scenario_tags = {"human"}
    wait_time = between(3, 7)

    def on_start(self):
        self.session_ip = f"203.0.113.{random.randint(1, 100)}"
        self.headers = {
            "X-Forwarded-For": self.session_ip,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Content-Type": "application/json"
        }

    @task(3)
    def browse_api(self):
        self.client.get("/api/get", headers=self.headers, name="Human - /api/get")

    @task(1)
    def ping_echo(self):
        self.client.get(f"/echo?q={random.randint(1, 1000)}", headers=self.headers, name="Human - /echo")

@tag('akamai_scraper')
class AkamaiAdvancedScraper(HttpUser):
    scenario_tags = {"akamai_scraper"}
    wait_time = constant(15)

    def on_start(self):
        self.session_ip = generate_akamai_ip()
        self.headers = {
            "X-Forwarded-For": self.session_ip,
            "User-Agent": "ScraperBot/5.2 (Burst/Sleep Mode)",
            "Content-Type": "application/json"
        }

    @task
    def execute_burst_scrape(self):
        for _ in range(5):
            self.client.get("/api/get", headers=self.headers, name="Akamai Scraper - Burst")

@tag('cloudflare_flood')
class CloudflareVolumetricFlood(HttpUser):
    scenario_tags = {"cloudflare_flood"}
    wait_time = constant(0)

    @task
    def execute_flood(self):
        spoofed_ip = generate_cloudflare_ip()
        headers = {
            "X-Forwarded-For": spoofed_ip,
            "User-Agent": "curl/7.68.0",
            "Content-Type": "application/json"
        }

        with self.client.get("/echo?q=flood", headers=headers, name="Cloudflare Flood - DDoS", catch_response=True) as response:
            if response.status_code in (200, 429, 403):
                response.success()

@tag('recon')
class InfiltrationReconBot(HttpUser):
    scenario_tags = {"recon"}
    wait_time = constant(2)

    def on_start(self):
        self.headers = {
            "User-Agent": "python-requests/2.31.0",
            "Content-Type": "application/json"
        }

    @task
    def probe_api(self):
        self.headers["X-Forwarded-For"] = random.choice(RECON_PROXIES)
        self.client.get("/api/get", headers=self.headers, name="Recon - /api/get")


def _parse_selected_tags(argv):
    selected = set()
    for idx, token in enumerate(argv):
        if token == "--tags" and idx + 1 < len(argv):
            selected.update(part.strip() for part in argv[idx + 1].split(",") if part.strip())
        elif token.startswith("--tags="):
            selected.update(part.strip() for part in token.split("=", 1)[1].split(",") if part.strip())
    return selected


def _apply_tag_based_user_activation():
    selected_tags = _parse_selected_tags(sys.argv)
    if not selected_tags:
        return

    user_classes = [
        NormalHumanUser,
        AkamaiAdvancedScraper,
        CloudflareVolumetricFlood,
        InfiltrationReconBot,
    ]

    for user_cls in user_classes:
        class_tags = getattr(user_cls, "scenario_tags", set())
        user_cls.abstract = class_tags.isdisjoint(selected_tags)


_apply_tag_based_user_activation()