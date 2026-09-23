import argparse
import json
from confluent_kafka import Consumer, KafkaException

def parse_args():
    parser = argparse.ArgumentParser(description="Collect shadow telemetry from Kafka.")
    parser.add_argument("--topic", default="gateway-telemetry", help="Kafka topic to consume")
    parser.add_argument("--bootstrap-servers", default="localhost:9092", help="Kafka bootstrap server(s)")
    parser.add_argument("--group-id", default="shadow-data-export", help="Kafka consumer group id")
    parser.add_argument("--output", default="ml_pipeline/data/shadow_telemetry.jsonl", help="Output JSONL path")
    parser.add_argument("--consumer-timeout-ms", type=int, default=10000, help="Stop if no new messages during timeout")
    parser.add_argument("--run-id", help="Only write telemetry for this SAGE run_id")
    return parser.parse_args()

def main():
    args = parse_args()

    conf = {
        "bootstrap.servers": args.bootstrap_servers,
        "group.id": args.group_id,
        "auto.offset.reset": "earliest",
    }
    consumer = Consumer(conf)
    consumer.subscribe([args.topic])

    rows_written = 0
    with open(args.output, "w", encoding="utf-8") as f:
        try:
            while True:
                msg = consumer.poll(timeout=args.consumer_timeout_ms / 1000.0)
                if msg is None:
                    break
                if msg.error():
                    raise KafkaException(msg.error())

                payload = msg.value().decode("utf-8")
                # Ensure it's valid JSON before writing
                try:
                    event = json.loads(payload)
                    if args.run_id and event.get("runId") != args.run_id:
                        continue
                    f.write(json.dumps(event) + "\n")
                    rows_written += 1
                except json.JSONDecodeError:
                    pass
        finally:
            consumer.close()

    print(f"Export complete. Rows written: {rows_written}")
    print(f"Output file: {args.output}")

if __name__ == "__main__":
    main()
