import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ICE_SERVERS, openStreamSocket } from "../services/streamService.js";

export default function Watch() {
  const { id } = useParams();
  const [status, setStatus] = useState("Connecting…");
  const videoRef = useRef(null);

  useEffect(() => {
    let ws;
    let pc;
    let closed = false;
    let chain = Promise.resolve();
    const myId = crypto.randomUUID();

    const send = (msg) => {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    };

    const handle = async (msg) => {
      if (msg.type === "offer" && msg.to === myId) {
        pc?.close();
        pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
        pc.ontrack = (e) => {
          videoRef.current.srcObject = e.streams[0];
          setStatus("Live");
        };
        pc.onicecandidate = (e) => {
          if (e.candidate) {
            send({ type: "ice", to: "host", from: myId, candidate: e.candidate });
          }
        };
        await pc.setRemoteDescription(msg.sdp);
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        send({ type: "answer", to: "host", from: myId, sdp: pc.localDescription });
      } else if (msg.type === "ice" && msg.to === myId) {
        await pc?.addIceCandidate(msg.candidate);
      } else if (msg.type === "ended") {
        setStatus("The host ended this stream.");
        pc?.close();
      }
    };

    (async () => {
      try {
        ws = await openStreamSocket(id);
        if (closed) return ws.close();
        ws.onopen = () => {
          setStatus("Waiting for the host's video…");
          send({ type: "viewer-join", from: myId });
        };
        ws.onmessage = (e) => {
          const msg = JSON.parse(e.data);
          chain = chain.then(() => handle(msg)).catch(console.error);
        };
        ws.onclose = (e) => {
          if (e.code === 4404) setStatus("This stream has ended or doesn't exist.");
          if (e.code === 4401) setStatus("Please log in again.");
        };
      } catch {
        setStatus("Couldn't connect. Are you logged in?");
      }
    })();

    return () => {
      closed = true;
      ws?.close();
      pc?.close();
    };
  }, [id]);

  return (
    <div className="mx-auto max-w-3xl p-6">
      <Link to="/streams" className="text-blue-600">← All streams</Link>
      <video ref={videoRef} autoPlay playsInline controls className="my-4 w-full rounded bg-black" />
      <p>{status}</p>
    </div>
  );
}