// Load test del mix de un CCU (SDD 7 §5). NO corre en CI.
//   BASE_URL=https://host/api/v1 VUS=200 DURATION=3m k6 run tests/load/k6_ccu.js
//
// Cada VU = un jugador: se registra+onboardea una vez, luego repite el bucle del cliente
// (refresh /players/me cada ~4 s + una acción ocasional). El SSE se aproxima con un GET a
// /notifications cada ~2 s (el stream real es una conexión larga; acá medimos la carga DB).
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE = __ENV.BASE_URL || "http://localhost:8099/api/v1";
const meLatency = new Trend("me_latency", true);

export const options = {
  vus: Number(__ENV.VUS || 50),
  duration: __ENV.DURATION || "2m",
  thresholds: {
    // Criterio de aceptación: p95 de /players/me bajo objetivo.
    me_latency: ["p(95)<200"],
    http_req_failed: ["rate<0.01"],
  },
};

function authHeaders(token) {
  return { headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } };
}

export function setup() {
  // nada global; cada VU crea su jugador en el primer iter
  return {};
}

export default function () {
  // Registro+onboarding una sola vez por VU.
  if (!__ENV._done) {
    const u = `load_${__VU}_${Date.now()}`;
    const reg = http.post(`${BASE}/auth/register`, JSON.stringify({ username: u, password: "password123" }), {
      headers: { "Content-Type": "application/json" },
    });
    const token = reg.json("access_token");
    http.post(
      `${BASE}/players/onboard`,
      JSON.stringify({ galaxy_key: "milky_way", planet_key: "earth", race_key: "terran" }),
      authHeaders(token)
    );
    exec_state.token = token;
  }

  const h = authHeaders(exec_state.token);

  // ~0.5 rps: aproxima el poll del SSE.
  http.get(`${BASE}/notifications?unread=true`, h);
  sleep(2);

  // ~0.25 rps: el refresh caro (advance lazy).
  const me = http.get(`${BASE}/players/me`, h);
  meLatency.add(me.timings.duration);
  check(me, { "me 200": (r) => r.status === 200 });
  sleep(2);

  // ~0.05 rps: una acción ocasional (consulta al asistente).
  if (Math.random() < 0.2) {
    http.post(`${BASE}/players/me/advisor/ask`, JSON.stringify({ message: "que construyo?" }), h);
  }
}

const exec_state = {};
