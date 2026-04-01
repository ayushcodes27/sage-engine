const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const { Kafka, CompressionTypes, CompressionCodecs } = require('kafkajs');
const SnappyCodec = require('kafkajs-snappy');

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec;

const app = express();
const server = http.createServer(app);
const io = new Server(server);

app.use(express.static('public'));

// Configure Kafka Client
const kafka = new Kafka({
    clientId: 'sage-dashboard',
    brokers: ['localhost:9092']
});

const consumer = kafka.consumer({
    groupId: `dashboard-group-${Date.now()}`
});

async function startKafkaConsumer() {
    await consumer.connect();
    console.log('✅ Connected to Kafka Broker');

    await consumer.subscribe({
        topic: 'gateway-telemetry',
        fromBeginning: true
    });

    await consumer.run({
        eachMessage: async ({ topic, partition, message }) => {
            try {
                const eventData = JSON.parse(message.value.toString());
                console.log("📥 Received from Kafka:", eventData);
                io.emit('sage-telemetry', eventData);

            } catch (err) {
                console.error("Failed to parse Kafka message", err);
            }
        },
    });
}

startKafkaConsumer().catch(console.error);

server.listen(3000, () => {
    console.log('📊 SAGE Dashboard running on http://localhost:3000');
});