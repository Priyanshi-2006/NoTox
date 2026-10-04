import { useEffect, useRef, useState } from "react";
import { tokenStorage } from "../services/api";

const WS_BASE_URL =
    import.meta.env.VITE_WS_BASE_URL || "ws://127.0.0.1:8000";

export default function GlobalChat() {
    const [messages, setMessages] = useState([]);
    const [message, setMessage] = useState("");
    const [status, setStatus] = useState("Connecting...");
    const [username, setUsername] = useState("");
    const [myUsername, setMyUsername] = useState("");
    const [authenticated, setAuthenticated] = useState(false);

    const socketRef = useRef(null);
    const bottomRef = useRef(null);

    useEffect(() => {
        const token = tokenStorage.getAccess();

        if (!token) {
            setStatus("Please log in");
            return;
        }

        const socket = new WebSocket(`${WS_BASE_URL}/ws/chat/`);
        socketRef.current = socket;

        socket.onopen = () => {
            setStatus("Authenticating...");
            socket.send(JSON.stringify({
                type: "authenticate",
                token,
            }));
        };

        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                if (data.type === "auth_required") return;

                if (data.type === "authenticated") {
                    setUsername(data.display_name || data.username);
                    setMyUsername(data.username);
                    setAuthenticated(true);
                    setStatus("Connected");
                    return;
                }

                if (
                    data.type === "message" &&
                    typeof data.message === "string"
                ) {
                    setMessages((previous) => [
                        ...previous,
                        {
                            id: `${Date.now()}-${Math.random()}`,
                            text: data.message,
                            username: data.username || "User",
                            displayName:
                                data.display_name || data.username || "User",
                            time: new Date().toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                            }),
                        },
                    ]);
                }
            } catch {
                console.error("Invalid chat message received");
            }
        };

        socket.onerror = () => setStatus("Connection error");

        socket.onclose = (event) => {
            setAuthenticated(false);

            if (event.code === 4401) {
                setStatus("Authentication failed. Please log in again.");
            } else if (event.code === 4403) {
                setStatus("Chat access denied.");
            } else {
                setStatus("Disconnected");
            }
        };

        return () => {
            socket.close();
            socketRef.current = null;
        };
    }, []);

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
            !socket ||
            socket.readyState !== WebSocket.OPEN
        ) {
            return;
        }

        socket.send(JSON.stringify({
            type: "message",
            message: text,
        }));

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
                            : "Chat live with connected users"}
                    </p>
                </div>

                <span className="text-sm text-slate-500">{status}</span>
            </header>

            <div
                className="flex-1 space-y-3 overflow-y-auto bg-slate-50 p-5"
                aria-live="polite"
            >
                {messages.length === 0 ? (
                    <p className="py-10 text-center text-sm text-slate-500">
                        No messages yet. Start the conversation!
                    </p>
                ) : (
                    messages.map((item) => {
                        const isMine = item.username === myUsername;

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
                    placeholder="Type a message..."
                    maxLength={2000}
                    aria-label="Chat message"
                    disabled={!authenticated}
                    className="min-w-0 flex-1 rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100"
                />

                <button
                    type="submit"
                    disabled={!authenticated || !message.trim()}
                    className="rounded-xl bg-indigo-600 px-5 py-3 font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    Send
                </button>
            </form>
        </section>
    );
}

