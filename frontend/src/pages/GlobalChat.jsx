
import { useEffect, useRef, useState } from "react";

export default function GlobalChat() {
    const [messages, setMessages] = useState([]);
    const [message, setMessage] = useState("");
    const [status, setStatus] = useState("Connecting...");
    const socketRef = useRef(null);
    const bottomRef = useRef(null);

    useEffect(() => {
        const socket = new WebSocket("ws://127.0.0.1:8000/ws/chat/");
        socketRef.current = socket;

        socket.onopen = () => setStatus("Connected");
        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                if (typeof data.message === "string") {
                    setMessages((previous) => [
                        ...previous,
                        {
                            id: `${Date.now()}-${Math.random()}`,
                            text: data.message,
                            time: new Date().toLocaleTimeString(),
                        },
                    ]);
                }
            } catch {
                console.error("Invalid chat message received");
            }
        };

        socket.onerror = () => setStatus("Connection error");
        socket.onclose = () => setStatus("Disconnected");

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

        if (!text || !socket || socket.readyState !== WebSocket.OPEN) {
            return;
        }

        socket.send(JSON.stringify({ message: text }));
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
                        Chat live with connected users
                    </p>
                </div>

                <span className="text-sm text-slate-500">
                    {status}
                </span>
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
                    messages.map((item) => (
                        <article
                            key={item.id}
                            className="max-w-[85%] rounded-xl border border-slate-200 bg-white p-3"
                        >
                            <p className="break-words text-slate-800">{item.text}</p>
                            <time className="mt-1 block text-xs text-slate-400">
                                {item.time}
                            </time>
                        </article>
                    ))
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
                    className="min-w-0 flex-1 rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />

                <button
                    type="submit"
                    disabled={status !== "Connected" || !message.trim()}
                    className="rounded-xl bg-indigo-600 px-5 py-3 font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    Send
                </button>
            </form>
        </section>
    );
}