import json
import time
from confluent_kafka import Consumer

conf = {
    "bootstrap.servers": "localhost:9092",
    "group.id": f"kafka-inspector-{int(time.time())}",
    "auto.offset.reset": "earliest",
}
consumer = Consumer(conf)
consumer.subscribe(["gateway-telemetry"])

ip_stats = {}
read_count = 0
empty_polls = 0

try:
    while empty_polls < 5:
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            empty_polls += 1
            continue
        
        empty_polls = 0
        if msg.error():
            continue
        
        read_count += 1
        payload = json.loads(msg.value().decode("utf-8"))
        ip = payload.get("request", {}).get("ip") or payload.get("userId") or "unknown"
        label = payload.get("label", "unknown")
        
        if ip not in ip_stats:
            ip_stats[ip] = {"label": label, "count": 0}
        ip_stats[ip]["count"] += 1
        
        if read_count % 20000 == 0:
            print(f"Processed {read_count} messages...")
            
except Exception as e:
    print("Error:", e)
finally:
    consumer.close()

# Sort IPs by count
sorted_ips = sorted(ip_stats.items(), key=lambda x: x[1]["count"], reverse=True)
print("\nTop 30 IPs in Kafka:")
for ip, data in sorted_ips[:30]:
    print(f"IP: {ip:<20} Label: {data['label']:<10} Count: {data['count']}")

# Check if there are any 172.25.* IPs
print("\nChecking for any 172.25.* IPs in the dataset:")
found_172 = {ip: data for ip, data in ip_stats.items() if ip.startswith("172.25.")}
print(f"Found {len(found_172)} IPs starting with 172.25.")
for ip, data in list(found_172.items())[:10]:
    print(f"IP: {ip:<20} Label: {data['label']:<10} Count: {data['count']}")
