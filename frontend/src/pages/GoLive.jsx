import { useEffect, useRef, useState } from "react";
import { getErrorMessage } from "../services/api.js";
import {
  ICE_SERVERS,
  openStreamSocket,
  openTranscriptionSocket,
  streamService,
} from "../services/streamService.js";

export default function GoLive() {
  const [title, setTitle] = useState("");
  const [live, setLive] = useState(false);
  const [viewers, setViewers] = useState(0);
  const [error, setError] = useState("");

  const accumulatedTranscriptRef = useRef("");

  const videoRef = useRef(null);
  const localStreamRef = useRef(null);
  const broadcastStreamRef = useRef(null);
  const broadcastDestRef = useRef(null);
  const socketRef = useRef(null);
  const transcriptionSocketRef = useRef(null);
  const audioContextRef = useRef(null);
  const audioWorkletRef = useRef(null);
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
      Object.values(peersRef.current).filter(
        (pc) => pc.connectionState === "connected"
      ).length
    );
  };

  const handleMessage = async (msg) => {
    if (msg.type === "viewer-join") {
      const viewerId = msg.from;

      peersRef.current[viewerId]?.close();

      const pc = new RTCPeerConnection({
        iceServers: ICE_SERVERS,
      });

      peersRef.current[viewerId] = pc;

      // Stream the moderated broadcast stream (fallback to local media if unavailable)
      const streamToSend = broadcastStreamRef.current || localStreamRef.current;
      streamToSend.getTracks().forEach((track) => {
        pc.addTrack(track, streamToSend);
      });

      pc.onicecandidate = (event) => {
        if (event.candidate) {
          send({
            type: "ice",
            to: viewerId,
            from: "host",
            candidate: event.candidate,
          });
        }
      };

      pc.onconnectionstatechange = () => {
        if (["closed", "failed"].includes(pc.connectionState)) {
          pc.close();

          if (peersRef.current[viewerId] === pc) {
            delete peersRef.current[viewerId];
          }
        }

        updateViewers();
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      send({
        type: "offer",
        to: viewerId,
        from: "host",
        sdp: pc.localDescription,
      });
    } else if (msg.type === "answer" && msg.to === "host") {
      await peersRef.current[msg.from]?.setRemoteDescription(msg.sdp);
    } else if (msg.type === "ice" && msg.to === "host") {
      await peersRef.current[msg.from]?.addIceCandidate(msg.candidate);
    }
  };

  const stopStream = async () => {
    // End the existing WebRTC signaling session.
    send({ type: "ended", from: "host" });

    Object.values(peersRef.current).forEach((pc) => pc.close());
    peersRef.current = {};

    socketRef.current?.close();
    socketRef.current = null;

    // Close transcription independently of the stream socket.
    if (transcriptionSocketRef.current) {
      const ws = transcriptionSocketRef.current;
      transcriptionSocketRef.current = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(1000, "Stream ended");
      }
    }

    // Release the audio processing resources.
    if (audioWorkletRef.current) {
      audioWorkletRef.current.port.onmessage = null;
      audioWorkletRef.current.port.close();
      audioWorkletRef.current.disconnect();
      audioWorkletRef.current = null;
    }

    if (audioContextRef.current) {
      const context = audioContextRef.current;
      audioContextRef.current = null;

      if (context.state !== "closed") {
        await context.close().catch(console.error);
      }
    }

    broadcastDestRef.current = null;

    if (broadcastStreamRef.current) {
      broadcastStreamRef.current.getTracks().forEach((track) => {
        track.stop();
      });
      broadcastStreamRef.current = null;
    }

    // Stop the camera and microphone.
    localStreamRef.current?.getTracks().forEach((track) => {
      track.stop();
    });

    localStreamRef.current = null;

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    const id = streamIdRef.current;
    streamIdRef.current = null;

    setLive(false);
    setViewers(0);

    if (id) {
      try {
        await streamService.end(id);
      } catch (err) {
        console.error("Could not end stream on the server:", err);
      }
    }
  };

  const startStream = async () => {
    if (live) return;
    setError("");
    accumulatedTranscriptRef.current = "";

    if (!title.trim()) {
      setError("Give your stream a title.");
      return;
    }

    try {
      // 1. Get the camera and microphone with speech processing constraints
      const media = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      localStreamRef.current = media;

      if (videoRef.current) {
        videoRef.current.srcObject = media;
      }

      // 2. Set up Web Audio pipeline with broadcast buffer and interval moderation
      let audioContext;
      try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        audioContextRef.current = audioContext;

        await audioContext.audioWorklet.addModule("/audio-processor.js");

        const micSource = audioContext.createMediaStreamSource(media);
        const audioWorklet = new AudioWorkletNode(audioContext, "audio-processor", {
          numberOfInputs: 1,
          numberOfOutputs: 1,
          outputChannelCount: [1],
        });
        audioWorkletRef.current = audioWorklet;

        const broadcastDest = audioContext.createMediaStreamDestination();
        broadcastDestRef.current = broadcastDest;

        // Route: micSource -> audioWorklet (buffers 1.5s & silences profanity) -> broadcastDest
        micSource.connect(audioWorklet);
        audioWorklet.connect(broadcastDest);

        // Keep Web Audio render quantum processing active via silent destination path
        const silentGain = audioContext.createGain();
        silentGain.gain.value = 0;
        audioWorklet.connect(silentGain);
        silentGain.connect(audioContext.destination);

        // Forward 100ms 16kHz PCM chunks to WebSocket
        audioWorklet.port.onmessage = (event) => {
          const currentSocket = transcriptionSocketRef.current;

          if (
            event.data.type === "audio" &&
            event.data.pcm16 &&
            currentSocket?.readyState === WebSocket.OPEN
          ) {
            currentSocket.send(event.data.pcm16);
          }
        };

        // Construct broadcast stream with video track and moderated audio track
        const broadcastTracks = [];
        const videoTrack = media.getVideoTracks()[0];
        if (videoTrack) broadcastTracks.push(videoTrack);
        const moderatedAudioTrack = broadcastDest.stream.getAudioTracks()[0];
        if (moderatedAudioTrack) {
          moderatedAudioTrack.enabled = true;
          broadcastTracks.push(moderatedAudioTrack);
        }

        broadcastStreamRef.current = new MediaStream(broadcastTracks);
        await audioContext.resume();
      } catch (err) {
        console.warn("[NoTox] Web Audio broadcast setup warning:", err);
        broadcastStreamRef.current = media;
      }

      // 3. Create the existing live stream.
      const stream = await streamService.create(title.trim());
      streamIdRef.current = stream.id;

      // 4. Connect the existing WebRTC signaling socket.
      const ws = await openStreamSocket(stream.id);
      socketRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          chainRef.current = chainRef.current
            .then(() => handleMessage(msg))
            .catch(console.error);
        } catch (err) {
          console.error("Invalid stream message:", err);
        }
      };

      ws.onclose = () => {
        if (socketRef.current === ws) {
          socketRef.current = null;
        }
      };

      // The existing stream can run even if transcription fails.
      setLive(true);

      // 5. Authenticate the separate transcription socket.
      let transcriptionWs;

      try {
        transcriptionWs = await openTranscriptionSocket();

        transcriptionSocketRef.current = transcriptionWs;
        console.log("[NoTox] Transcription status: Connected");
        console.log("[NoTox] Transcript stream started");

        // Synchronize worklet buffer timeline with speech recognition connection
        audioWorkletRef.current?.port.postMessage({
          type: "transcription_start",
        });

        transcriptionWs.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);

            if (message.type === "transcript" && message.text) {
              if (message.is_final) {
                accumulatedTranscriptRef.current =
                  `${accumulatedTranscriptRef.current} ${message.text}`.trim();
                console.log("[NoTox Transcript]:", message.text);
              }

              // Send moderation decision and word intervals directly to the audio buffer worklet
              if (audioWorkletRef.current) {
                audioWorkletRef.current.port.postMessage({
                  type: "moderation_decision",
                  text: message.text,
                  words: message.words || [],
                  moderation: message.moderation,
                  censor: Boolean(message.censor || message.moderation?.is_flagged),
                });
              }
            } else if (message.type === "error") {
              console.error(
                "[NoTox] Transcription error:",
                message.message
              );
            }
          } catch (err) {
            console.error(
              "Invalid transcription message:",
              err
            );
          }
        };

        transcriptionWs.onclose = (event) => {
          if (transcriptionSocketRef.current === transcriptionWs) {
            transcriptionSocketRef.current = null;
          }
          const reasonStr = event.reason ? `: ${event.reason}` : "";
          console.warn(`[NoTox] Transcription disconnected${reasonStr}`);
        };

        transcriptionWs.onerror = (err) => {
          console.error("[NoTox] Transcription WebSocket error:", err);
        };
      } catch (err) {
        console.error(
          "[NoTox] Transcription could not connect:",
          err.message
        );
      }
    } catch (err) {
      const message =
        err.name === "NotAllowedError"
          ? "Camera/microphone permission was denied."
          : err.response
            ? getErrorMessage(err)
            : err.message;

      setError(message);
      await stopStream();
    }
  };

  // End the stream if the host leaves the page.
  useEffect(() => {
    return () => {
      void stopStream();
    };
  }, []);

  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="mb-4 text-2xl font-bold">Go live</h1>

      {error && (
        <p className="mb-3 text-red-500">{error}</p>
      )}

      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        className="mb-4 w-full rounded bg-black"
      />

      {!live ? (
        <div className="flex gap-2">
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Stream title"
            className="flex-1 rounded border p-2"
          />

          <button
            onClick={startStream}
            className="rounded bg-red-600 px-4 py-2 text-white"
          >
            Start stream
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between">
          <p>🔴 You are live · {viewers} watching</p>

          <button
            onClick={stopStream}
            className="rounded bg-gray-800 px-4 py-2 text-white"
          >
            End stream
          </button>
        </div>
      )}
    </div>
  );
}
