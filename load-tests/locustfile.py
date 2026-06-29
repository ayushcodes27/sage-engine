import random
import sys
import gevent

from locust import HttpUser, between, task, tag


def ip_residential():
    return f"172.25.0.{random.randint(1, 254)}"


def ip_datacenter():
    prefix = random.choice((52, 34))
    return f"{prefix}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def ip_distributed():
    return f"{random.randint(11, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def ip_tor_like():
    prefix = random.choice((185, 176))
    return f"{prefix}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def ip_adversarial_scraper():
    return f"44.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def ip_slow_flood():
    return f"88.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


SCRAPER_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.111 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/124.0.2478.80 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


FLOOD_SEARCH_TERMS = [
    "deal",
    "wireless",
    "gaming",
    "summer",
    "pro",
    "new",
    "sale",
    "premium",
    "eco",
    "smart",
]


SQLI_QUERIES = ["' OR 1=1", "../etc/passwd"]


RECON_UA_POOL = [
    "python-requests/2.31.0",
    "python-requests/2.28.1",
    "python-urllib3/1.26.12",
    "Go-http-client/1.1",
    "Go-http-client/2.0",
    "Nmap Scripting Engine",
    "curl/7.68.0",
    "Wget/1.21.2",
    "masscan/1.3.2",
]


@tag("human")
class HumanBrowser(HttpUser):
    scenario_tags = {"human"}
    fixed_count = random.randint(6, 12)
    wait_time = between(10, 15)

    def _headers(self):
        return {
            "X-Forwarded-For": self._ip,
            "User-Agent": self._ua,
            "Content-Type": "application/json",
        }

    def _random_product_id(self):
        return random.randint(1, 50)

    def on_start(self):
        self._ip = ip_residential()
        self._ua = random.choice(SCRAPER_UA_POOL)
        headers = self._headers()
        self.client.get("/static/style.css", headers=headers, name="Human - static css")
        self.client.get("/static/app.js", headers=headers, name="Human - static js")
        self.client.get("/static/logo.png", headers=headers, name="Human - static logo")

    @task(4)
    def browse_pages(self):
        headers = self._headers()
        path = random.choice(["/", "/products", "/cart"])
        self.client.get(path, headers=headers, name=f"Human - {path}")

        # Human burst simulation: 30% chance to run 2-4 rapid requests
        if random.random() < 0.30:
            for _ in range(random.randint(2, 4)):
                gevent.sleep(random.uniform(0.2, 0.8))
                sub_path = random.choice(["/products", "/cart"])
                self.client.get(sub_path, headers=headers, name=f"Human - {sub_path} (burst)")

    @task(3)
    def view_product_and_price(self):
        product_id = self._random_product_id()
        headers = self._headers()
        self.client.get(f"/products/{product_id}", headers=headers, name="Human - /products/:id")
        gevent.sleep(random.uniform(0.5, 1.5))
        self.client.get(f"/api/price/{product_id}", headers=headers, name="Human - /api/price/:id")

        if random.random() < 0.30:
            self.client.post("/checkout", json={"status": "mock"}, headers=headers, name="Human - /checkout")


@tag("akamai_scraper")
class AkamaiScraper(HttpUser):
    scenario_tags = {"akamai_scraper"}
    fixed_count = random.randint(15, 25)
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self._ip = ip_datacenter()
        self._ua = random.choice(SCRAPER_UA_POOL)

    def _headers(self):
        return {
            "X-Forwarded-For": self._ip,
            "User-Agent": self._ua,
        }

    @task(1)
    def product_listing(self):
        self.client.get("/products", headers=self._headers(), name="Scraper - /products")

    @task(3)
    def price_inventory_sweep(self):
        product_id = random.randint(1, 50)
        headers = self._headers()
        self.client.get(f"/products/{product_id}", headers=headers, name="Scraper - /products/:id")
        self.client.get(f"/api/price/{product_id}", headers=headers, name="Scraper - /api/price/:id")
        self.client.get(f"/api/inventory/{product_id}", headers=headers, name="Scraper - /api/inventory/:id")

        if random.random() < 0.05:
            self.client.post("/checkout", json={"status": "mock"}, headers=headers, name="Scraper - /checkout")


@tag("unprotected_flood")
class UnprotectedFlood(HttpUser):
    scenario_tags = {"unprotected_flood"}
    fixed_count = random.randint(20, 30)
    wait_time = between(0.0, 0.1)

    def on_start(self):
        self._ip = ip_distributed()

    def _headers(self):
        return {
            "X-Forwarded-For": self._ip,
            "User-Agent": "curl/8.6.0",
            "Content-Type": "application/json",
        }

    @tag("unprotected_flood")
    @task(2)
    def flood_products(self):
        self.client.get("/products", headers=self._headers(), name="Unprotected Flood - /products")

    @tag("unprotected_flood")
    @task(2)
    def flood_search(self):
        term = random.choice(FLOOD_SEARCH_TERMS)
        self.client.get(
            f"/api/search?q={term}",
            headers=self._headers(),
            name="Unprotected Flood - /api/search",
        )

    @tag("unprotected_flood")
    @task(3)
    def flood_price(self):
        product_id = random.randint(1, 50)
        self.client.get(
            f"/api/price/{product_id}",
            headers=self._headers(),
            name="Unprotected Flood - /api/price/:id",
        )


@tag("recon")
class ReconBot(HttpUser):
    scenario_tags = {"recon"}
    fixed_count = random.randint(3, 8)
    wait_time = between(2, 5)

    def on_start(self):
        self._ip = ip_tor_like()
        self._ua = random.choice(RECON_UA_POOL)

    def _headers(self):
        return {
            "X-Forwarded-For": self._ip,
            "User-Agent": self._ua,
            "Content-Type": "application/json",
        }

    @task(2)
    def probe_admin_metrics(self):
        headers = self._headers()
        self.client.get("/actuator/prometheus", headers=headers, name="Recon - /actuator/prometheus")
        self.client.get("/admin/routes", headers=headers, name="Recon - /admin/routes")

    @task(2)
    def probe_search_injection(self):
        payload = random.choice(SQLI_QUERIES)
        self.client.get(f"/api/search?q={payload}", headers=self._headers(), name="Recon - /api/search (sqli)")

    @task(1)
    def probe_invalid_product(self):
        self.client.get("/products/99999", headers=self._headers(), name="Recon - /products/99999")

    @task(1)
    def probe_path_traversal(self):
        self.client.get("/static/../etc/passwd", headers=self._headers(), name="Recon - traversal")


@tag("scraper")
class StealthScraper(HttpUser):
    scenario_tags = {"scraper"}
    fixed_count = random.randint(8, 15)
    wait_time = between(2, 5)

    def on_start(self):
        self._ip = ip_datacenter()
        self._ua = random.choice(SCRAPER_UA_POOL)

    def _headers(self):
        return {
            "X-Forwarded-For": self._ip,
            "User-Agent": self._ua,
        }

    @task
    def sequential_crawl(self):
        product_id = random.randint(1, 50)
        headers = self._headers()
        self.client.get(f"/products/{product_id}", headers=headers, name="StealthScraper - /products/:id")
        gevent.sleep(random.uniform(0.1, 0.3))
        self.client.get(f"/api/price/{product_id}", headers=headers, name="StealthScraper - /api/price/:id")

        if random.random() < 0.05:
            self.client.post("/checkout", json={"status": "mock"}, headers=headers, name="StealthScraper - /checkout")


@tag("flood")
class JitteredFlood(HttpUser):
    scenario_tags = {"flood"}
    fixed_count = random.randint(15, 20)
    wait_time = between(10, 12)

    def on_start(self):
        self._ip = ip_distributed()

    def _headers(self):
        return {
            "X-Forwarded-For": self._ip,
            "User-Agent": "curl/8.6.0",
            "Content-Type": "application/json",
        }

    @tag("flood")
    @task
    def burst_flood(self):
        headers = self._headers()
        for _ in range(40):
            term = random.choice(FLOOD_SEARCH_TERMS)
            path = random.choice([
                "/products",
                f"/api/search?q={term}",
                f"/api/price/{random.randint(1, 50)}"
            ])
            self.client.get(path, headers=headers, name="JitteredFlood - burst")
            gevent.sleep(0.02)


@tag("adversarial_scraper")
class AdversarialScraper(HttpUser):
    scenario_tags = {"adversarial_scraper"}
    fixed_count = random.randint(8, 15)
    wait_time = between(1, 4)
    _next_product_id = random.randint(1, 50)

    def on_start(self):
        self._ip = ip_adversarial_scraper()
        self._ua = random.choice(SCRAPER_UA_POOL)

    def _headers(self):
        return {
            "X-Forwarded-For": self._ip,
            "User-Agent": self._ua,
        }

    @tag("adversarial_scraper")
    @task(7)
    def scrape_product_details(self):
        product_id = self._next_product_id
        self._next_product_id = 1 if self._next_product_id >= 50 else self._next_product_id + 1
        headers = self._headers()
        self.client.get(f"/products/{product_id}", headers=headers, name="AdversarialScraper - /products/:id")
        gevent.sleep(random.uniform(0.1, 0.3))
        self.client.get(f"/api/price/{product_id}", headers=headers, name="AdversarialScraper - /api/price/:id")
        self.client.get(f"/api/inventory/{product_id}", headers=headers, name="AdversarialScraper - /api/inventory/:id")

        if random.random() < 0.18:
            self.client.post("/checkout", json={"status": "mock"}, headers=headers, name="AdversarialScraper - /checkout")

    @tag("adversarial_scraper")
    @task(3)
    def scrape_products(self):
        self.client.get("/products", headers=self._headers(), name="AdversarialScraper - /products")

    @tag("adversarial_scraper")
    @task(2)
    def scrape_search(self):
        term = random.choice(FLOOD_SEARCH_TERMS)
        self.client.get(f"/api/search?q={term}", headers=self._headers(), name="AdversarialScraper - /api/search")

    @tag("adversarial_scraper")
    @task(2)
    def hit_asset(self):
        self.client.get("/static/style.css", headers=self._headers(), name="AdversarialScraper - /static/style.css")


@tag("slow_flood")
class SlowFlood(HttpUser):
    scenario_tags = {"slow_flood"}
    fixed_count = random.randint(10, 15)
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self._ip = ip_slow_flood()

    def _headers(self):
        return {
            "X-Forwarded-For": self._ip,
            "User-Agent": "curl/8.6.0",
            "Content-Type": "application/json",
        }

    @tag("slow_flood")
    @task
    def flood_endpoint(self):
        self.client.post("/checkout", json={"status": "mock"}, headers=self._headers(), name="SlowFlood - /checkout")


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
        HumanBrowser,
        AkamaiScraper,
        UnprotectedFlood,
        ReconBot,
        StealthScraper,
        JitteredFlood,
        AdversarialScraper,
        SlowFlood,
    ]

    for user_cls in user_classes:
        class_tags = getattr(user_cls, "scenario_tags", set())
        user_cls.abstract = class_tags.isdisjoint(selected_tags)


_apply_tag_based_user_activation()

# Run config
# Run config
# locust -f load-tests/locustfile.py --headless -u 40 -r 5 --run-time 5m --host http://localhost:8083
# HumanBrowser: 12 users
# AkamaiScraper: 14 users
# UnprotectedFlood: 20-30 users
# ReconBot: 6 users
