/**
 * AudioWorkletProcessor for NoTox Live Audio Moderation:
 * 1. Resamples microphone audio continuously to 16 kHz without sample-dropping or phase jumps.
 * 2. Emits clean 100ms (1600-sample) PCM16 chunks to the speech recognition WebSocket.
 * 3. Retains incoming microphone audio in a circular broadcast buffer (1.5s delay).
 * 4. Silences ONLY the precise time intervals of detected profane words.
 * 5. Allows clean speech and background audio to proceed normally without artificial silencing.
 * 6. Synchronizes Vosk speech recognition timestamps with the delayed broadcast buffer timeline.
 */

class AudioProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.inputSampleRate = sampleRate;
        this.targetSampleRate = 16000;

        // --- Downsampling & STT Chunk Buffering ---
        this.downsampleRatio = this.inputSampleRate / this.targetSampleRate;
        this.resampleBuffer = [];
        this.resampleReadPos = 0.0;

        this.chunkSize16k = 1600; // 100ms of 16kHz audio
        this.pcm16Chunk = new Int16Array(this.chunkSize16k);
        this.pcm16ChunkIndex = 0;
        this.totalSent16kSamples = 0;

        // --- Broadcast Ring Buffer (1.5s delay) ---
        this.bufferDelaySeconds = 1.5;
        this.delaySamples = Math.round(this.bufferDelaySeconds * this.inputSampleRate);
        this.ringBufferSize = Math.max(this.delaySamples * 3, 96000); // ~2-3 seconds capacity
        this.broadcastRingBuffer = new Float32Array(this.ringBufferSize);
        this.writeSampleCount = 0; // Total input samples processed
        this.currentGain = 1.0;

        // --- Vosk Timeline Synchronization ---
        this.voskActive = false;
        this.voskStreamOffset = 0.0; // Timeline offset in seconds when Vosk stream starts

        // --- Moderation Interval Tracking ---
        // Censored intervals: [{ start: float, end: float }] in stream time seconds
        this.censoredIntervals = [];

        this.port.onmessage = (event) => {
            this.handleMessage(event.data);
        };
    }

    handleMessage(data) {
        if (!data) return;

        if (data.type === "transcription_start") {
            this.voskActive = true;
            this.voskStreamOffset = this.writeSampleCount / this.inputSampleRate;
            this.pcm16ChunkIndex = 0;
            this.resampleBuffer = [];
            this.resampleReadPos = 0.0;
            return;
        }

        if (data.type === "moderation_decision") {
            const { words = [], flagged_segments = [], censor = false } = data;

            // 1. Process explicit flagged word segments
            if (Array.isArray(flagged_segments) && flagged_segments.length > 0) {
                for (const seg of flagged_segments) {
                    if (seg.start != null && seg.end != null && seg.end >= seg.start) {
                        const segStart = this.voskStreamOffset + Number(seg.start);
                        const segEnd = this.voskStreamOffset + Number(seg.end);
                        // Apply minimal 60ms padding around word boundaries to cover acoustic plosives/fricatives
                        const padStart = Math.max(0.0, segStart - 0.06);
                        const padEnd = segEnd + 0.06;
                        this.censoredIntervals.push({ start: padStart, end: padEnd });
                    }
                }
            }

            // 2. Cross-check all recognized words
            if (Array.isArray(words) && words.length > 0) {
                const flaggedSet = new Set(
                    (data.moderation?.flagged_words || []).map((w) => String(w).toLowerCase().trim())
                );

                for (const w of words) {
                    const wordStr = String(w.word || "").toLowerCase().trim();
                    const wStart = Number(w.start);
                    const wEnd = Number(w.end);

                    if (!isNaN(wStart) && !isNaN(wEnd) && wEnd >= wStart) {
                        const actualStart = this.voskStreamOffset + wStart;
                        const actualEnd = this.voskStreamOffset + wEnd;

                        if (flaggedSet.has(wordStr) || (censor && flaggedSet.size === 0)) {
                            const padStart = Math.max(0.0, actualStart - 0.06);
                            const padEnd = actualEnd + 0.06;
                            this.censoredIntervals.push({ start: padStart, end: padEnd });
                        }
                    }
                }
            }

            // 3. Fallback when profanity is flagged but individual timestamps were missing
            if (censor && flagged_segments.length === 0 && words.length === 0) {
                const nowStreamTime = this.writeSampleCount / this.inputSampleRate;
                const fallbackStart = Math.max(0.0, nowStreamTime - 1.2);
                this.censoredIntervals.push({ start: fallbackStart, end: nowStreamTime });
            }

            // 4. Prune old intervals older than 15 seconds to avoid array growth
            const currentStreamTime = this.writeSampleCount / this.inputSampleRate;
            const pruneBefore = currentStreamTime - 15.0;
            if (pruneBefore > 0) {
                this.censoredIntervals = this.censoredIntervals.filter((iv) => iv.end > pruneBefore);
            }
        }
    }

    process(inputs, outputs) {
        const inputChannel = inputs[0]?.[0];
        const outputChannel = outputs[0]?.[0];

        if (!inputChannel || inputChannel.length === 0) {
            if (outputs[0]) {
                for (let ch = 0; ch < outputs[0].length; ch++) {
                    outputs[0][ch].fill(0);
                }
            }
            return true;
        }

        const quantumLength = inputChannel.length;

        // 1. Write incoming microphone samples into circular broadcast buffer
        for (let i = 0; i < quantumLength; i++) {
            const val = inputChannel[i];
            const writeIdx = (this.writeSampleCount + i) % this.ringBufferSize;
            this.broadcastRingBuffer[writeIdx] = val;
        }

        // 2. Continuous, phase-accurate downsampling to 16 kHz for Vosk STT (if streaming active)
        if (this.voskActive) {
            if (this.inputSampleRate === 16000) {
                for (let i = 0; i < quantumLength; i++) {
                    const s = Math.max(-1.0, Math.min(1.0, inputChannel[i]));
                    this.pcm16Chunk[this.pcm16ChunkIndex++] =
                        s < 0 ? Math.round(s * 32768) : Math.round(s * 32767);

                    if (this.pcm16ChunkIndex >= this.chunkSize16k) {
                        this.flushPcm16Chunk();
                    }
                }
            } else {
                for (let i = 0; i < quantumLength; i++) {
                    this.resampleBuffer.push(inputChannel[i]);
                }

                while (this.resampleReadPos + this.downsampleRatio < this.resampleBuffer.length) {
                    const idx = Math.floor(this.resampleReadPos);
                    const frac = this.resampleReadPos - idx;
                    const s0 = this.resampleBuffer[idx];
                    const s1 =
                        this.resampleBuffer[idx + 1] !== undefined
                            ? this.resampleBuffer[idx + 1]
                            : s0;
                    const interpolated = s0 + frac * (s1 - s0);

                    const clamped = Math.max(-1.0, Math.min(1.0, interpolated));
                    this.pcm16Chunk[this.pcm16ChunkIndex++] =
                        clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767);

                    if (this.pcm16ChunkIndex >= this.chunkSize16k) {
                        this.flushPcm16Chunk();
                    }

                    this.resampleReadPos += this.downsampleRatio;
                }

                if (this.resampleReadPos > 2048) {
                    const pruneCount = Math.floor(this.resampleReadPos);
                    this.resampleBuffer.splice(0, pruneCount);
                    this.resampleReadPos -= pruneCount;
                }
            }
        }

        // 3. Render broadcast output delayed by bufferDelaySeconds (1.5s)
        if (outputChannel && outputs[0]) {
            for (let i = 0; i < quantumLength; i++) {
                const sampleGlobalIndex = this.writeSampleCount + i;
                const playoutGlobalIndex = sampleGlobalIndex - this.delaySamples;

                if (playoutGlobalIndex < 0) {
                    // Initial buffering phase: output silence until buffer delay is reached
                    for (let ch = 0; ch < outputs[0].length; ch++) {
                        outputs[0][ch][i] = 0.0;
                    }
                    continue;
                }

                const playoutTime = playoutGlobalIndex / this.inputSampleRate;
                const delayedSample = this.broadcastRingBuffer[playoutGlobalIndex % this.ringBufferSize];

                // Determine whether this playout sample must be silenced
                let isCensored = false;
                for (let c = 0; c < this.censoredIntervals.length; c++) {
                    const iv = this.censoredIntervals[c];
                    if (playoutTime >= iv.start && playoutTime <= iv.end) {
                        isCensored = true;
                        break;
                    }
                }

                // If censored: silence the audio (targetGain = 0.0). Otherwise: normal clean audio (targetGain = 1.0)
                const targetGain = isCensored ? 0.0 : 1.0;

                // Smooth linear gain transition (prevents audio pops/clicks at mute boundaries)
                this.currentGain += (targetGain - this.currentGain) * 0.08;
                const outSample = delayedSample * this.currentGain;

                // Copy to all output channels (e.g. left and right for stereo destination)
                for (let ch = 0; ch < outputs[0].length; ch++) {
                    outputs[0][ch][i] = outSample;
                }
            }
        }

        this.writeSampleCount += quantumLength;
        return true;
    }

    flushPcm16Chunk() {
        // Send a complete 100ms 16kHz chunk to the transcription WebSocket
        const bufferCopy = this.pcm16Chunk.buffer.slice(0);
        this.totalSent16kSamples += this.chunkSize16k;

        this.port.postMessage(
            {
                type: "audio",
                pcm16: bufferCopy,
                streamTime: this.totalSent16kSamples / this.targetSampleRate,
            },
            [bufferCopy]
        );

        this.pcm16ChunkIndex = 0;
    }
}

registerProcessor("audio-processor", AudioProcessor);
