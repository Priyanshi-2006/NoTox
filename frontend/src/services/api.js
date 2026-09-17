import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";

const ACCESS_TOKEN_KEY = "notox_access_token";
const REFRESH_TOKEN_KEY = "notox_refresh_token";

// Centralized token storage so nothing else in the app touches
// localStorage directly for auth state.
export const tokenStorage = {
  getAccess: () => localStorage.getItem(ACCESS_TOKEN_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_TOKEN_KEY),
  setTokens: ({ access, refresh }) => {
    if (access) localStorage.setItem(ACCESS_TOKEN_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
  },
  clear: () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const access = tokenStorage.getAccess();
  if (access) {
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});

// If a request fails with 401, try exactly one silent refresh before
// giving up and forcing the caller to handle a logged-out state. This
// keeps every page from having to know about token expiry.
let refreshPromise = null;

async function refreshAccessToken() {
  const refresh = tokenStorage.getRefresh();
  if (!refresh) throw new Error("No refresh token available.");

  const response = await axios.post(`${BASE_URL}/auth/token/refresh/`, {
    refresh,
  });
  tokenStorage.setTokens({ access: response.data.access });
  return response.data.access;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const isAuthEndpoint = originalRequest?.url?.includes("/auth/login") ||
      originalRequest?.url?.includes("/auth/register") ||
      originalRequest?.url?.includes("/auth/token/refresh");

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !isAuthEndpoint
    ) {
      originalRequest._retry = true;
      try {
        if (!refreshPromise) {
          refreshPromise = refreshAccessToken().finally(() => {
            refreshPromise = null;
          });
        }
        const newAccess = await refreshPromise;
        originalRequest.headers.Authorization = `Bearer ${newAccess}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        tokenStorage.clear();
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

/**
 * Normalizes any Axios/API error into a short, human-readable string.
 * Backend errors arrive as either {"detail": "..."} or
 * {"errors": {field: [messages]}} (see apps/accounts/exceptions.py).
 */
export function getErrorMessage(error) {
  if (!error.response) {
    return "Can't reach the server. Is the backend running?";
  }

  const data = error.response.data;
  if (typeof data === "string") return data;
  if (data?.detail) return data.detail;

  if (data?.errors) {
    const firstField = Object.keys(data.errors)[0];
    const firstMessage = data.errors[firstField];
    if (Array.isArray(firstMessage)) return firstMessage[0];
    return String(firstMessage);
  }

  return "Something went wrong. Please try again.";
}
