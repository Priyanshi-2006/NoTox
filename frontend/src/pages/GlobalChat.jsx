import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiClient, refreshAccessToken, tokenStorage } from "../services/api";

function getWebSocketBaseUrl() {
    if (import.meta.env.VITE_WS_BASE_URL) {
        return import.meta.env.VITE_WS_BASE_URL;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.hostname || "127.0.0.1";
    return `${protocol}//${host}:8000`;
}

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;

export default function GlobalChat() {
    const [messages, setMessages] = useState([]);
    const [message, setMessage] = useState("");
    const [status, setStatus] = useState("Connecting...");
    const [username, setUsername] = useState("");
    const [myUsername, setMyUsername] = useState("");
    const [authenticated, setAuthenticated] = useState(false);
    const [isRestricted, setIsRestricted] = useState(false);
    const [loadingHistory, setLoadingHistory] = useState(false);

    const socketRef = useRef(null);
    const bottomRef = useRef(null);
    const reconnectAttemptRef = useRef(0);
    const reconnectTimeoutRef = useRef(null);
    const hasRefreshedAuthRef = useRef(false);
    const isUnmountedRef = useRef(false);

    const navigate = useNavigate();

    const formatMessage = (msg) => ({
        id: msg.id,
        text: msg.message || msg.content,
        username: msg.username || "User",
        displayName: msg.display_name || msg.username || "User",
        time: msg.created_at
            ? new Date(msg.created_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
            })
            : "",
        createdAt: msg.created_at,
        blocked: msg.blocked || false,
    });

    const loadHistory = useCallback(async () => {
        try {
            setLoadingHistory(true);

            const response = await apiClient.get("/chat/messages/");
            const history = Array.isArray(response.data) ? response.data : [];

            const historyMessages = history.map(formatMessage);

            setMessages((previous) => {
                const historyIds = new Set(
                    historyMessages.map((msg) => msg.id)
                );

                // Keep messages that arrived through WebSocket
                // while history was loading.
                const liveMessages = previous.filter(
                    (msg) => !historyIds.has(msg.id)
                );

                return [...historyMessages, ...liveMessages];
            });
        } catch (error) {
            if (error.response?.status === 403) {
                setIsRestricted(true);
                setStatus("Chat access denied: Account restricted");
            } else {
                console.error("Failed to load chat history:", error);
            }
        } finally {
            setLoadingHistory(false);
        }
    }, []);

    const connectWebSocket = useCallback(() => {
        if (isUnmountedRef.current) return;

        const token = tokenStorage.getAccess();
        if (!token) {
            setStatus("Please log in");
            return;
        }

        // Cleanly detach and close any existing socket
        if (socketRef.current) {
            const oldSocket = socketRef.current;
            socketRef.current = null;
            oldSocket.onopen = null;
            oldSocket.onmessage = null;
            oldSocket.onerror = null;
            oldSocket.onclose = null;
            oldSocket.close(1000, "Switching socket");
        }

        const wsBaseUrl = getWebSocketBaseUrl();
        const socket = new WebSocket(`${wsBaseUrl}/ws/chat/`);
        socketRef.current = socket;
        setStatus("Connecting...");

        socket.onopen = () => {
            if (isUnmountedRef.current || socketRef.current !== socket) return;
            setStatus("Authenticating...");
            socket.send(
                JSON.stringify({
                    type: "authenticate",
                    token,
                })
            );
        };

        socket.onmessage = (event) => {
            if (isUnmountedRef.current || socketRef.current !== socket) return;
            try {
                const data = JSON.parse(event.data);

                if (data.type === "auth_required") return;

                if (data.type === "authenticated") {
                    setUsername(data.display_name || data.username);
                    setMyUsername(data.username);
                    setAuthenticated(true);
                    setIsRestricted(false);
                    setStatus("Connected");
                    reconnectAttemptRef.current = 0;
                    hasRefreshedAuthRef.current = false;

                    // Load persisted message history on successful authentication
                    loadHistory();
                    return;
                }

                if (data.type === "moderation_block" && typeof data.message === "string") {
                    setMessages((previous) => [
                        ...previous,
                        {
                            id: data.id,
                            text: data.message,
                            username: data.username,
                            displayName: data.display_name || data.username || "You",
                            time: data.created_at
                                ? new Date(data.created_at).toLocaleTimeString([], {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                })
                                : "",
                            createdAt: data.created_at,
                            blocked: true,
                        },
                    ]);

                    return;
                }
                if (data.type === "message" && typeof data.message === "string") {
                    setMessages((previous) => {
                        // Prevent duplicate message IDs
                        if (data.id && previous.some((m) => m.id === data.id)) {
                            return previous;
                        }
                        return [...previous, formatMessage(data)];
                    });
                }
            } catch (err) {
                console.error("Invalid chat message received:", err);
            }
        };

        socket.onerror = (err) => {
            if (isUnmountedRef.current || socketRef.current !== socket) return;
            console.warn("WebSocket error:", err);
            setStatus("Connection error");
        };

        socket.onclose = async (event) => {
            // Ignore events from old or unmounted sockets
            if (isUnmountedRef.current || socketRef.current !== socket) return;
            socketRef.current = null;
            setAuthenticated(false);

            // Clean close, do not reconnect
            if (event.code === 1000) {
                setStatus("Disconnected");
                return;
            }

            if (event.code === 4401) {
                if (!hasRefreshedAuthRef.current) {
                    hasRefreshedAuthRef.current = true;
                    setStatus("Session expired. Refreshing token...");
                    try {
                        await refreshAccessToken();
                        connectWebSocket();
                        return;
                    } catch (err) {
                        setStatus("Authentication failed. Please log in again.");
                        tokenStorage.clear();
                        navigate("/login");
                        return;
                    }
                } else {
                    setStatus("Authentication failed. Please log in again.");
                    tokenStorage.clear();
                    navigate("/login");
                    return;
                }
            }

            if (event.code === 4403) {
                setIsRestricted(true);
                setStatus("Chat access denied: Account restricted");
                return;
            }

            // Standard unexpected connection drop - retry with capped exponential backoff
            const delay = Math.min(
                INITIAL_BACKOFF_MS * Math.pow(2, reconnectAttemptRef.current),
                MAX_BACKOFF_MS
            );
            reconnectAttemptRef.current += 1;
            setStatus(`Disconnected. Reconnecting in ${Math.round(delay / 1000)}s...`);

            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
            reconnectTimeoutRef.current = setTimeout(() => {
                connectWebSocket();
            }, delay);
        };
    }, [loadHistory, navigate]);

    useEffect(() => {
        isUnmountedRef.current = false;
        connectWebSocket();

        return () => {
            isUnmountedRef.current = true;
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
            if (socketRef.current) {
                const s = socketRef.current;
                socketRef.current = null;
                s.onopen = null;
                s.onmessage = null;
                s.onerror = null;
                s.onclose = null;
                s.close(1000, "Component unmounted");
            }
        };
    }, [connectWebSocket]);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    function sendMessage(event) {
        event.preventDefault();

        const text = message.trim();
        const socket = socketRef.current;

        if (
            !text ||
            !authenticated ||
            isRestricted ||
            !socket ||
            socket.readyState !== WebSocket.OPEN
        ) {
            return;
        }

        socket.send(
            JSON.stringify({
                type: "message",
                message: text,
            })
        );

        setMessage("");
    }

    return (
        <section className="mx-auto flex h-[70vh] max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <header className="flex items-center justify-between border-b border-slate-200 p-5">
                <div>
                    <h1 className="text-xl font-bold text-slate-900">
                        NoTox Global Chat
                    </h1>
                    <p className="mt-1 text-sm text-slate-500">
                        {authenticated
                            ? `Logged in as ${username}`
                            : isRestricted
                                ? "Account restricted"
                                : "Chat live with connected users"}
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    {isRestricted && (
                        <span className="rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-semibold text-rose-800">
                            Restricted
                        </span>
                    )}
                    <span className="text-sm text-slate-500">{status}</span>
                </div>
            </header>

            {isRestricted && (
                <div
                    className="border-b border-rose-200 bg-rose-50 px-5 py-3 text-sm text-rose-700"
                    role="alert"
                >
                    <strong>Access Restricted:</strong> Your account is currently restricted from participating in chat.
                </div>
            )}

            <div
                className="flex-1 space-y-3 overflow-y-auto bg-slate-50 p-5"
                aria-live="polite"
            >
                {loadingHistory && messages.length === 0 ? (
                    <p className="py-10 text-center text-sm text-slate-500">
                        Loading message history...
                    </p>
                ) : messages.length === 0 ? (
                    <p className="py-10 text-center text-sm text-slate-500">
                        No messages yet. Start the conversation!
                    </p>
                ) : (
                    messages.map((item) => {
                        const isMine = item.blocked || item.username === myUsername;

                        return (
                            <div
                                key={item.id}
                                className={`flex w-full ${isMine ? "justify-end" : "justify-start"
                                    }`}
                            >
                                <article
                                    className={`max-w-[85%] rounded-2xl p-3 shadow-sm ${isMine
                                        ? "rounded-br-sm bg-indigo-600 text-white"
                                        : "rounded-bl-sm border border-slate-200 bg-white text-slate-800"
                                        }`}
                                >
                                    <p
                                        className={`mb-1 text-xs font-semibold ${isMine
                                            ? "text-indigo-100"
                                            : "text-indigo-700"
                                            }`}
                                    >
                                        {isMine ? "You" : item.displayName}
                                    </p>

                                    {item.blocked && (
                                        <div className="mb-1 flex items-center justify-end gap-1 text-xs text-indigo-200">
                                            <span>🚫</span>
                                            <span>Message blocked</span>
                                        </div>
                                    )}

                                    <p className="break-words whitespace-pre-wrap">
                                        {item.text}
                                    </p>

                                    <time
                                        className={`mt-1 block text-right text-xs ${isMine
                                            ? "text-indigo-200"
                                            : "text-slate-400"
                                            }`}
                                    >
                                        {item.time}
                                    </time>
                                </article>
                            </div>
                        );
                    })
                )}

                <div ref={bottomRef} />
            </div>

            <form
                onSubmit={sendMessage}
                className="flex gap-3 border-t border-slate-200 p-4"
            >
                <input
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    placeholder={
                        isRestricted
                            ? "Chat disabled for restricted accounts."
                            : "Type a message..."
                    }
                    maxLength={2000}
                    aria-label="Chat message"
                    disabled={!authenticated || isRestricted}
                    className="min-w-0 flex-1 rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100"
                />

                <button
                    type="submit"
                    disabled={!authenticated || !message.trim() || isRestricted}
                    className="rounded-xl bg-indigo-600 px-5 py-3 font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    Send
                </button>
            </form>
        </section>
    );
}
