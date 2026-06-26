import json
from confluent_kafka import Consumer

conf = {
    "bootstrap.servers": "localhost:9092",
    "group.id": "kafka-printer",
    "auto.offset.reset": "earliest",
}
consumer = Consumer(conf)
consumer.subscribe(["gateway-telemetry"])

try:
    msg = consumer.poll(timeout=5.0)
    if msg is not None:
        payload = json.loads(msg.value().decode("utf-8"))
        print(json.dumps(payload, indent=2))
except Exception as e:
    print(e)
finally:
    consumer.close()
