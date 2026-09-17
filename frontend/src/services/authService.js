import { apiClient, tokenStorage } from "./api";

export const authService = {
  async register({ username, email, password, phoneNumber }) {
    const response = await apiClient.post("/auth/register/", {
      username,
      email,
      password,
      phone_number: phoneNumber || "",
    });
    tokenStorage.setTokens(response.data.tokens);
    return response.data.user;
  },

  async login({ identifier, password }) {
    const response = await apiClient.post("/auth/login/", {
      identifier,
      password,
    });
    tokenStorage.setTokens(response.data.tokens);
    return response.data.user;
  },

  async logout() {
    const refresh = tokenStorage.getRefresh();
    try {
      if (refresh) {
        await apiClient.post("/auth/logout/", { refresh });
      }
    } finally {
      // Always clear local state, even if the blacklist call fails
      // (e.g. token already expired) — the user still expects to be
      // logged out locally.
      tokenStorage.clear();
    }
  },

  async getCurrentUser() {
    const response = await apiClient.get("/auth/me/");
    return response.data;
  },

  isAuthenticated() {
    return Boolean(tokenStorage.getAccess());
  },
};
