# NoTox Bloom Pre-Filter (Layer 2) Benchmark Report

**Generated:** 2026-10-15 20:12:05 UTC

**Simulated Provider Latency:** 10.0 ms (*labeled as simulated*)

## 1. False Positive Rate (FPR) across (m, k, n)

| Capacity (n) | Target p | Bits (m) | Size (KB) | Hash funcs (k) | Empirical FPR |
|---|---|---|---|---|---|
| 50,000 | 0.01 | 479,253 | 58.5 KB | 7 | 0.00000 |
| 50,000 | 0.001 | 718,880 | 87.8 KB | 10 | 0.00000 |
| 50,000 | 0.0001 | 958,506 | 117.0 KB | 13 | 0.00000 |
| 10,000 | 0.001 | 143,776 | 17.6 KB | 10 | 0.00000 |

## 2. API-Call Reduction and End-to-End Latency

- **Total Messages Evaluated:** 300
- **Clean Messages:** 200
- **Toxic Messages:** 100

### API Calls to Layer 3 Provider
- **Without Bloom filter:** 245 calls
- **With Bloom filter:** 55 calls
- **API-Call Reduction:** **77.55%**

### End-to-End Latency Comparison (Simulated Delay: 10.0 ms)
| Metric | Without Bloom Filter (ms) | With Bloom Filter (ms) | Speedup |
|---|---|---|---|
| **Mean** | 26.24 ms | 11.66 ms | 2.25x |
| **p50 (Median)** | 30.67 ms | 9.52 ms | 3.22x |
| **p95** | 46.51 ms | 27.59 ms | - |
| **p99** | 47.53 ms | 32.25 ms | - |

## 3. Labeled Dataset Accuracy & Miss Rate (Omitted by SDS)

- **Toxic Test Dataset Size:** 100
- **Toxic Misses (False Negatives):** 0
- **Measured Miss Rate:** **0.00%** (Target: 0.00% zero false negatives)
- **Clean Traffic Dataset Size:** 200
- **Clean Fast-Patched (Clean):** 190 (95.00%)
- **Clean Marked Uncertain (Sent to Provider):** 10 (5.00%)

## 4. Backend Comparison: Local vs Redis

| Backend | Status | Avg Lookup Latency per Message (ms) | Notes |
|---|---|---|---|
| **LocalBloomBackend** | Healthy | 0.1284 ms | In-memory, zero network overhead |
| **RedisBloomBackend** | Offline (Fail-safe verified) | N/A | Redis not running; fail-safe automatically routes to provider without coverage loss |
