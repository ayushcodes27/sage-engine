import json
import time
from confluent_kafka import Consumer

conf = {
    "bootstrap.servers": "localhost:9092",
    "group.id": f"kafka-inspector-{int(time.time())}",  # new group id to read from earliest
    "auto.offset.reset": "earliest",
}
consumer = Consumer(conf)
consumer.subscribe(["gateway-telemetry"])

label_counts = {}
read_count = 0
empty_polls = 0

print("Starting to consume from earliest...")

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
        label = payload.get("label", "unknown")
        label_counts[label] = label_counts.get(label, 0) + 1
        
        if read_count % 10000 == 0:
            print(f"Read {read_count} messages...")
            
except Exception as e:
    print("Error:", e)
finally:
    consumer.close()

print("Label counts in Kafka:")
print(label_counts)
