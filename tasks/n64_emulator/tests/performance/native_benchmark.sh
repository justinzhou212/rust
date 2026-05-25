#!/usr/bin/env bash
# =============================================================================
# Gate: Native Performance Benchmark
#
# Measures the emulator's performance on a reference workload and verifies
# it meets the minimum threshold. This gate ensures the emulator is fast
# enough to be usable — not just correct.
#
# Metric: VI/s (Video Interface interrupts per second). On real N64 hardware,
# the VI fires at 60 Hz (NTSC) or 50 Hz (PAL). The emulator must sustain
# at least 30 VI/s on the reference hardware to be considered playable.
#
# Reference hardware: 4-core x86_64 CPU, no GPU acceleration
# (software renderer path). This represents the minimum CI environment.
#
# Thresholds:
#   - Hard fail:  < 30 VI/s (unplayable)
#   - Warning:    < 60 VI/s (below full speed)
#   - Target:     >= 60 VI/s (full speed NTSC)
#
# The benchmark runs a known ROM for a fixed number of frames and reports
# the average VI/s. Multiple runs are averaged to reduce variance.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$SCRIPT_DIR/../.."
APP_DIR="$TASK_DIR/../../app"
ROM_DIR="$TASK_DIR/reference/test_roms"
CLI="$APP_DIR/target/release/n64-cli"

MIN_VIS=30         # Minimum VI/s to pass
WARN_VIS=60        # Warning threshold
BENCH_FRAMES=300   # Number of frames to benchmark
NUM_RUNS=3         # Number of runs to average

if [ ! -f "$CLI" ]; then
    echo "ERROR: n64-cli not found at $CLI"
    exit 1
fi

# Use n64-systemtest as the benchmark ROM (it's always available and exercises
# CPU heavily). For more realistic benchmarks, a homebrew game ROM can be used.
BENCH_ROM="$ROM_DIR/n64-systemtest.z64"
if [ ! -f "$BENCH_ROM" ]; then
    echo "ERROR: Benchmark ROM not found at $BENCH_ROM"
    exit 1
fi

echo "========================================="
echo "Native Performance Benchmark"
echo "========================================="
echo "ROM: $(basename "$BENCH_ROM")"
echo "Frames: $BENCH_FRAMES"
echo "Runs: $NUM_RUNS"
echo "Min VI/s: $MIN_VIS"
echo ""

TOTAL_VIS=0
RESULTS=()

for i in $(seq 1 $NUM_RUNS); do
    echo "  Run $i/$NUM_RUNS..."

    # Run benchmark — the CLI should output VI/s stats
    OUTPUT=$("$CLI" bench "$BENCH_ROM" \
        --frames "$BENCH_FRAMES" \
        --renderer software \
        2>&1) || true

    # Parse VI/s from output
    # Expected format: "average_vis: 45.2" or "VI/s: 45.2"
    VIS=$(echo "$OUTPUT" | grep -oP '(average_vis|VI/s|vis):\s*\K[0-9]+(\.[0-9]+)?' | tail -1)

    if [ -z "$VIS" ]; then
        # Try alternate format: "X frames in Y.Zs"
        FRAMES=$(echo "$OUTPUT" | grep -oP '\K\d+(?= frames in)' | tail -1)
        SECONDS=$(echo "$OUTPUT" | grep -oP 'frames in \K[0-9]+(\.[0-9]+)?' | tail -1)

        if [ -n "$FRAMES" ] && [ -n "$SECONDS" ]; then
            VIS=$(echo "scale=2; $FRAMES / $SECONDS" | bc)
        fi
    fi

    if [ -z "$VIS" ]; then
        echo "    WARN: Could not parse VI/s from output"
        echo "$OUTPUT" | tail -5
        continue
    fi

    echo "    $VIS VI/s"
    RESULTS+=("$VIS")
    TOTAL_VIS=$(echo "scale=2; $TOTAL_VIS + $VIS" | bc)
done

if [ "${#RESULTS[@]}" -eq 0 ]; then
    echo ""
    echo "FAIL: No valid benchmark results. Check n64-cli bench output format."
    exit 1
fi

AVG_VIS=$(echo "scale=2; $TOTAL_VIS / ${#RESULTS[@]}" | bc)

echo ""
echo "Average: $AVG_VIS VI/s (over ${#RESULTS[@]} runs)"

# Check against thresholds
VIS_INT=$(echo "$AVG_VIS" | cut -d. -f1)

if [ "$VIS_INT" -lt "$MIN_VIS" ]; then
    echo ""
    echo "FAIL: $AVG_VIS VI/s is below minimum threshold ($MIN_VIS VI/s)"
    echo ""
    echo "Performance optimization suggestions:"
    echo "  - Profile with 'cargo flamegraph' to find hotspots"
    echo "  - Enable JIT recompilation for the CPU"
    echo "  - Optimize RSP vector operations with SIMD intrinsics"
    echo "  - Reduce memory allocation in the main emulation loop"
    echo "  - Consider batch-processing RDP commands"
    exit 1
fi

if [ "$VIS_INT" -lt "$WARN_VIS" ]; then
    echo ""
    echo "WARN: $AVG_VIS VI/s is below full-speed ($WARN_VIS VI/s)"
    echo "The emulator works but may not achieve real-time on all games."
fi

echo ""
echo "Performance gate passed: $AVG_VIS VI/s >= $MIN_VIS VI/s"
