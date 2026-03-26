import json
import logging
import signal
import sys
import os
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.session_depth import SessionDepthCalculator
from features.request_velocity import RequestVelocityCalculator
from confluent_kafka import Consumer, KafkaError, KafkaException
from features.temporal_variance import TemporalVarianceCalculator

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from features.endpoint_diversity import EndpointDiversityCalculator

# Set up basic logging so we can see what's happening
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GatewayEventConsumer:
    def __init__(self, bootstrap_servers='localhost:9092', topic='gateway-telemetry', group_id='feature-engineering'):
        # 1. The Configuration Dictionary
        conf = {
            'bootstrap.servers': bootstrap_servers,
            'group.id': group_id,
            # 'earliest' means if this consumer crashes and restarts, it will pick up
            # exactly where it left off, preventing data loss.
            'auto.offset.reset': 'earliest',
            # Let Kafka handle acknowledging (committing) that we processed a message
            'enable.auto.commit': True
        }

        self.consumer = Consumer(conf)
        self.topic = topic
        self.running = True

        # Join the consumer group and subscribe to the topic
        self.consumer.subscribe([self.topic])
        logger.info(f"Initialized confluent-kafka consumer for topic: {self.topic}")

    def consume_events(self, process_callback):
        """
        The main polling loop.
        process_callback is a function we will pass in later to calculate ML features.
        """
        try:
            while self.running:
                # 2. The Polling Mechanism
                # We wait up to 1.0 seconds for a message. If none arrives, we loop.
                # This prevents the while loop from consuming 100% of the CPU.
                msg = self.consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                # 3. Error Handling
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        # Reached the end of the partition queue. This is normal.
                        continue
                    else:
                        raise KafkaException(msg.error())

                # 4. Processing Valid Messages
                try:
                    # Kafka sends raw bytes. Decode to string, then parse to a Python Dictionary
                    raw_value = msg.value().decode('utf-8')
                    event_data = json.loads(raw_value)

                    # Hand the data over to the feature engineering logic
                    process_callback(event_data)

                except json.JSONDecodeError:
                    logger.error("Failed to parse JSON. Skipping message.")
                except Exception as e:
                    logger.error(f"Error processing event payload: {e}")

        except KeyboardInterrupt:
            logger.info("Manual interrupt detected (Ctrl+C). Initiating shutdown...")
        finally:
            self.close()

    def stop(self, signum=None, frame=None):
        """Signal handler for graceful shutdown (e.g., when Docker stops the container)"""
        self.running = False

    def close(self):
        """
        5. Graceful Shutdown
        Tells Kafka we are leaving the group so it can instantly reassign our work
        to another instance if we scale up.
        """
        logger.info("Closing Kafka consumer connection politely...")
        self.consumer.close()

# Quick Test Block
if __name__ == "__main__":
    consumer = GatewayEventConsumer()

    # Initialize the complete Feature Engineering Suite
    diversity_calculator = EndpointDiversityCalculator()
    variance_calculator = TemporalVarianceCalculator()
    depth_calculator = SessionDepthCalculator()
    velocity_calculator = RequestVelocityCalculator()

    signal.signal(signal.SIGINT, consumer.stop)
    signal.signal(signal.SIGTERM, consumer.stop)

    def process_event(event):
        # Extract variables from your Java Gateway telemetry JSON
        user = event.get('userId', 'unknown_user')
        session = event.get('sessionId', user) # Fallback to user if session isn't set

        req_id = event.get('requestId')
        if not req_id:
            # If the Gateway didn't provide an ID, generate a random one instantly
            req_id = str(uuid.uuid4())

        path = event.get('request', {}).get('path', '')
        timestamp = event.get('timestamp', '')

        if path and timestamp:
            print("-" * 40) # Add a visual divider in the terminal for readability

            # Fire all four mathematical cylinders!
            diversity_calculator.calculate(user, path)
            variance_calculator.calculate(user, timestamp)
            depth_calculator.calculate(session)
            velocity_calculator.calculate(user, timestamp, req_id)

    logger.info("Starting SAGE ML Feature Pipeline. All 4 engines online...")
    consumer.consume_events(process_event)