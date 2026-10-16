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


export async function openTranscriptionSocket() {
  await apiClient.get("/auth/me/");

  const token = tokenStorage.getAccess();
  if (!token) {
    throw new Error("No access token available. Please log in again.");
  }

  const ws = new WebSocket(`${WS_BASE}/ws/transcription/`);

  await new Promise((resolve, reject) => {
    let settled = false;

    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      ws.close();
      reject(new Error("Transcription authentication timed out."));
    }, 10000);

    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: "authenticate",
        token,
      }));
    };

    ws.onmessage = (event) => {
      let message;

      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }

      if (message.type === "authenticated" && !settled) {
        settled = true;
        clearTimeout(timeout);
        resolve();
      } else if (message.type === "error" && !settled) {
        settled = true;
        clearTimeout(timeout);
        ws.close();
        reject(new Error(message.message || "Transcription setup failed."));
      }
    };

    ws.onerror = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      reject(new Error("Could not connect to transcription WebSocket."));
    };

    ws.onclose = (event) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      reject(
        new Error(
          event.code === 4401
            ? "Authentication failed. Please log in again."
            : event.code === 4403
              ? "Your account cannot use live transcription."
              : "Transcription WebSocket closed before authentication."
        )
      );
    };
  });

  return ws;
}
