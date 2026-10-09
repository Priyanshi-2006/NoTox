import { apiClient, tokenStorage } from "./api.js";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL || "ws://localhost:8000";

export const ICE_SERVERS = [{ urls: "stun:stun.l.google.com:19302" }];

export const streamService = {
  list: () => apiClient.get("/streams/").then((r) => r.data),
  create: (title) => apiClient.post("/streams/", { title }).then((r) => r.data),
  end: (id) => apiClient.post(`/streams/${id}/end/`).then((r) => r.data),
};

// The WebSocket can't auto-refresh a token, so make one cheap API call
// first (the interceptor refreshes an expired token), then connect.
export async function openStreamSocket(streamId) {
  await apiClient.get("/auth/me/");
  return new WebSocket(
    `${WS_BASE}/ws/streams/${streamId}/?token=${tokenStorage.getAccess()}`
  );
}