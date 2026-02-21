import http from 'k6/http';
import { check } from 'k6';

export const options = {
    // Virtual-user model selected for stable local execution and controlled socket reuse.
    vus: 200,
    duration: '2m',
    thresholds: {
        http_req_duration: ['p(99)<100'], // Latency threshold adjusted for local development constraints.
    },
};

export default function () {
    // Resolve target URL from environment variable, defaulting to local echo endpoint.
    const url = __ENV.URL || 'http://localhost:8081/echo';

    const res = http.get(url);

    check(res, {
        'status is 200': (r) => r.status === 200,
    });
}