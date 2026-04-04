const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const { Kafka, CompressionTypes, CompressionCodecs } = require('kafkajs');
const SnappyCodec = require('kafkajs-snappy');
const cors = require('cors');

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec;

const app = express();
app.use(cors());

const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: '*',
    methods: ['GET', 'POST'],
  },
});

const kafka = new Kafka({
  clientId: 'sage-dashboard',
  brokers: ['localhost:9092'],
});

const consumer = kafka.consumer({ groupId: 'sage-dashboard-live-v1' });

async function runKafkaConsumer() {
  await consumer.connect();
  console.log('[+] Connected to Kafka Broker');

  await consumer.subscribe({ topic: 'gateway-telemetry', fromBeginning: false });

  consumer.on(consumer.events.CRASH, (e) => {
    console.error('[Bridge] Kafka consumer crashed:', e.payload.error);
  });

  await consumer.run({
    eachMessage: async ({ message }) => {
      try {
        if (!message || !message.value) return;

        const telemetryEvent = JSON.parse(message.value.toString());
        console.log('[Kafka->Socket] Forwarding event:', {
          eventId: telemetryEvent.eventId,
          status: telemetryEvent.response?.status,
          path: telemetryEvent.request?.path,
        });

        io.emit('telemetry_update', telemetryEvent);
      } catch (error) {
        console.error('[Bridge] Failed to process Kafka message:', error);
      }
    },
  });
}

io.on('connection', (socket) => {
  console.log(`[+] Dashboard UI Connected: ${socket.id}`);
  socket.on('disconnect', () => {
    console.log(`[-] Dashboard UI Disconnected: ${socket.id}`);
  });
});

const PORT = 6006;
server.listen(PORT, async () => {
  console.log(`[SAGE Bridge] WebSocket Server running on port ${PORT}`);
  await runKafkaConsumer().catch(console.error);
});
