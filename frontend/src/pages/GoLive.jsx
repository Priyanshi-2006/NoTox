import { useEffect, useRef, useState } from "react";
import { getErrorMessage } from "../services/api.js";
import {
  ICE_SERVERS,
  openStreamSocket,
  streamService,
} from "../services/streamService.js";

export default function GoLive() {
  const [title, setTitle] = useState("");
  const [live, setLive] = useState(false);
  const [viewers, setViewers] = useState(0);
  const [error, setError] = useState("");

  const videoRef = useRef(null);
  const localStreamRef = useRef(null);
  const socketRef = useRef(null);
  const peersRef = useRef({});
  const streamIdRef = useRef(null);
  const chainRef = useRef(Promise.resolve());

  const send = (msg) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(msg));
    }
  };

  const updateViewers = () => {
    setViewers(
      Object.values(peersRef.current).filter((pc) => pc.connectionState === "connected").length
    );
  };

  const handleMessage = async (msg) => {
    if (msg.type === "viewer-join") {
      const viewerId = msg.from;
      peersRef.current[viewerId]?.close();
      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      peersRef.current[viewerId] = pc;

      localStreamRef.current
        .getTracks()
        .forEach((track) => pc.addTrack(track, localStreamRef.current));

      pc.onicecandidate = (e) => {
        if (e.candidate) {
          send({ type: "ice", to: viewerId, from: "host", candidate: e.candidate });
        }
      };
      pc.onconnectionstatechange = () => {
        if (["closed", "failed"].includes(pc.connectionState)) {
          pc.close();
          if (peersRef.current[viewerId] === pc) delete peersRef.current[viewerId];
        }
        updateViewers();
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      send({ type: "offer", to: viewerId, from: "host", sdp: pc.localDescription });
    } else if (msg.type === "answer" && msg.to === "host") {
      await peersRef.current[msg.from]?.setRemoteDescription(msg.sdp);
    } else if (msg.type === "ice" && msg.to === "host") {
      await peersRef.current[msg.from]?.addIceCandidate(msg.candidate);
    }
  };

  const stopStream = async () => {
    send({ type: "ended", from: "host" });
    Object.values(peersRef.current).forEach((pc) => pc.close());
    peersRef.current = {};
    socketRef.current?.close();
    socketRef.current = null;
    localStreamRef.current?.getTracks().forEach((t) => t.stop());
    localStreamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;

    const id = streamIdRef.current;
    streamIdRef.current = null;
    setLive(false);
    setViewers(0);
    if (id) {
      try {
        await streamService.end(id);
      } catch {
        /* already ended */
      }
    }
  };

  const startStream = async () => {
    setError("");
    if (!title.trim()) return setError("Give your stream a title.");
    try {
      const media = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      localStreamRef.current = media;
      videoRef.current.srcObject = media;

      const stream = await streamService.create(title.trim());
      streamIdRef.current = stream.id;

      const ws = await openStreamSocket(stream.id);
      socketRef.current = ws;
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        // Handle messages one at a time, in order.
        chainRef.current = chainRef.current
          .then(() => handleMessage(msg))
          .catch(console.error);
      };
      setLive(true);
    } catch (err) {
      setError(
        err.name === "NotAllowedError"
          ? "Camera/microphone permission was denied."
          : err.response
          ? getErrorMessage(err)
          : err.message
      );
      stopStream();
    }
  };

  // End the stream if the host leaves the page.
  useEffect(() => () => { stopStream(); }, []);

  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="mb-4 text-2xl font-bold">Go live</h1>
      {error && <p className="mb-3 text-red-500">{error}</p>}
      <video ref={videoRef} autoPlay muted playsInline className="mb-4 w-full rounded bg-black" />
      {!live ? (
        <div className="flex gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Stream title"
            className="flex-1 rounded border p-2"
          />
          <button onClick={startStream} className="rounded bg-red-600 px-4 py-2 text-white">
            Start stream
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between">
          <p>🔴 You are live · {viewers} watching</p>
          <button onClick={stopStream} className="rounded bg-gray-800 px-4 py-2 text-white">
            End stream
          </button>
        </div>
      )}
    </div>
  );
}