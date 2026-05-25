# N64 Emulator with Bit-Exact RDP via WebGPU Compute

## Problem

Build a Nintendo 64 emulator in Rust that compiles to WebAssembly and runs in a web browser. The emulator must implement:

1. **MIPS R4300i CPU** — the N64's main 64-bit MIPS processor running at 93.75 MHz
2. **RSP (Reality Signal Processor)** — a custom MIPS-derived vector DSP with 128-bit SIMD, running per-game microcode
3. **RDP (Reality Display Processor)** — the N64's fixed-function pixel pipeline, implemented as WebGPU compute shaders that produce **bit-exact** output matching the Angrylion reference software renderer
4. **Audio** — RSP-processed audio output via the Audio Interface (AI) and Web Audio API
5. **Input** — controller input via the Peripheral Interface (PIF)
6. **Memory subsystem** — RDRAM (8 MB), ROM, SPMEM, PIF RAM/ROM, MMIO registers

The final artifact is a static website (HTML + WASM + JS) that:
- Loads with zero server-side dependencies (deployable to GitHub Pages / Cloudflare Pages)
- Ships with embedded open-source homebrew ROMs playable without user-provided data
- Accepts user-provided `.z64` / `.n64` / `.v64` ROMs via drag-and-drop
- Renders via WebGPU compute shaders (with software renderer fallback)
- Outputs audio via AudioWorklet
- Accepts gamepad and keyboard input

Place all Rust source code under `/app/`. The WASM build target is `wasm32-unknown-unknown`. The browser entry point must be at `/app/web/index.html`.

## Architecture

```
/app/
├── Cargo.toml                    # Workspace root
├── Cargo.lock
├── crates/
│   ├── n64-core/                 # Platform-agnostic emulation core
│   │   ├── src/
│   │   │   ├── cpu/              # MIPS R4300i interpreter + JIT
│   │   │   │   ├── interpreter.rs
│   │   │   │   ├── jit.rs        # Optional: MIPS → WASM dynamic recompiler
│   │   │   │   ├── cop0.rs       # System Control Coprocessor
│   │   │   │   ├── cop1.rs       # Floating Point Unit
│   │   │   │   └── instructions.rs
│   │   │   ├── rsp/              # Reality Signal Processor (LLE)
│   │   │   │   ├── core.rs       # Scalar unit
│   │   │   │   ├── vector.rs     # 128-bit SIMD vector unit
│   │   │   │   ├── dma.rs        # SP DMA
│   │   │   │   └── microcode.rs  # Microcode execution
│   │   │   ├── rdp/              # Reality Display Processor
│   │   │   │   ├── commands.rs   # RDP command decoder
│   │   │   │   ├── software.rs   # Software reference renderer
│   │   │   │   └── pipeline.rs   # Rasterizer, texture, color combiner, blender
│   │   │   ├── memory/           # Bus, RDRAM, MMIO
│   │   │   ├── audio/            # Audio Interface
│   │   │   ├── video/            # Video Interface
│   │   │   ├── pif/              # PIF (boot, controller I/O)
│   │   │   ├── pi/               # Peripheral Interface (ROM DMA)
│   │   │   └── lib.rs
│   │   └── Cargo.toml
│   ├── n64-rdp-wgpu/             # RDP implementation via WebGPU compute shaders
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── pipeline.rs       # Compute pipeline setup
│   │   │   ├── buffers.rs        # GPU buffer management
│   │   │   └── shaders/          # WGSL compute shaders
│   │   │       ├── rasterizer.wgsl
│   │   │       ├── texture.wgsl
│   │   │       ├── color_combiner.wgsl
│   │   │       ├── blender.wgsl
│   │   │       └── zbuffer.wgsl
│   │   └── Cargo.toml
│   ├── n64-frontend-web/         # WASM + browser glue
│   │   ├── src/lib.rs
│   │   └── Cargo.toml
│   └── n64-cli/                  # Native CLI for testing (headless mode)
│       ├── src/main.rs
│       └── Cargo.toml
└── web/
    ├── index.html                # Browser entry point
    ├── style.css
    ├── main.js                   # WASM loader, ROM drag-and-drop, UI
    └── roms/                     # Embedded homebrew ROMs (fetched at build)
```

## Detailed Requirements

### R1: MIPS R4300i CPU

Implement a cycle-stepped interpreter for the full MIPS R4300i instruction set:

- **Integer**: ADD, ADDU, SUB, SUBU, AND, OR, XOR, NOR, SLT, SLTU, DADD, DADDU, DSUB, DSUBU, MULT, MULTU, DIV, DIVU, DMULT, DMULTU, DDIV, DDIVU, all shift variants (SLL, SRL, SRA, DSLL, DSRL, DSRA, DSLL32, DSRL32, DSRA32, SLLV, SRLV, SRAV, DSLLV, DSRLV, DSRAV)
- **Branch**: BEQ, BNE, BLEZ, BGTZ, BLTZ, BGEZ, BEQL, BNEL, BLEZL, BGTZL, BLTZL, BGEZL, BLTZAL, BGEZAL, BLTZALL, BGEZALL, J, JAL, JR, JALR — all with correct branch delay slot behavior
- **Load/Store**: LB, LBU, LH, LHU, LW, LWU, LD, LWL, LWR, LDL, LDR, SB, SH, SW, SD, SWL, SWR, SDL, SDR, LL, LLD, SC, SCD
- **COP0**: MFC0, MTC0, DMFC0, DMTC0, ERET, TLBR, TLBWI, TLBWR, TLBP — full TLB with 32 entries, ASID matching, page mask support
- **COP1 (FPU)**: All single/double precision arithmetic, CVT, ROUND, TRUNC, CEIL, FLOOR, comparison ops, all four rounding modes. FPU must handle denormals, infinities, NaN, and status/cause register bits correctly
- **Exceptions**: Address Error, TLB Miss/Invalid/Modification, Integer Overflow, Trap, Breakpoint, Syscall, Floating Point, Interrupt — with correct EPC, Cause, BadVAddr, Status register updates
- **Cache**: Instruction and data cache operations (at minimum, cache invalidation must be recognized so self-modifying code works)

**Verification**: Must pass all tests in [n64-systemtest](https://github.com/lemmy-64/n64-systemtest) (3,650+ tests as of v2.1.0). The test ROM is self-reporting: it prints pass/fail counts. Parse stdout and assert `Failed: 0`.

### R2: Reality Signal Processor (RSP)

Implement full Low-Level Emulation of the RSP:

- **Scalar unit**: 32 general-purpose 32-bit registers, subset of MIPS instruction set (no exceptions, no TLB, no 64-bit ops), plus RSP-specific DMA and status instructions
- **Vector unit**: 32 × 128-bit vector registers (each = 8 × 16-bit elements), 48-bit accumulator per lane (8 lanes). All vector opcodes: VMULF, VMULU, VMACF, VMACU, VMUDL, VMUDM, VMUDN, VMUDH, VMADL, VMADM, VMADN, VMADH, VADD, VSUB, VABS, VADDC, VSUBC, VSAR, VLT, VEQ, VNE, VGE, VCL, VCH, VCR, VMRG, VAND, VNAND, VOR, VNOR, VXOR, VNXOR, VRCP, VRCPL, VRCPH, VMOV, VRSQ, VRSQL, VRSQH, VNOP — with correct saturation, clamping, and accumulator behavior
- **Load/Store vector**: LBV, LSV, LLV, LDV, LQV, LRV, LPV, LUV, LHV, LFV, LTV, SBV, SSV, SLV, SDV, SQV, SRV, SPV, SUV, SHV, SFV, STV — with correct element alignment and DMEM wrapping
- **SP DMA**: Transfers between RDRAM and SPMEM (IMEM/DMEM), with correct wrapping behavior for transfers exceeding 4 KB IMEM/DMEM boundaries
- **Status/control**: SP_STATUS register, semaphore, halt/break/interrupt handling

**Verification**: Must pass all RSP tests in n64-systemtest (RSP scalar, RSP vector, SP DMA sections). Additionally, pass [Peter Lemon's RSP test ROMs](https://github.com/PeterLemon/N64/tree/master/RSPTest).

### R3: Reality Display Processor (RDP)

Implement the full N64 RDP pixel pipeline. The primary implementation must use **WebGPU compute shaders** (WGSL). A software fallback renderer must also be provided for environments without WebGPU.

The RDP pipeline stages:

1. **Command decoder**: Parse RDP command buffer (triangle, rectangle, texture rectangle, fill rectangle, sync, set commands)
2. **Rasterizer**: Edge-walking for triangles and rectangles, sub-pixel precision, scissoring
3. **Texture unit**: All 5 texture formats (RGBA, YUV, CI, IA, I) × 4 sizes (4, 8, 16, 32 bpp), bilinear filtering, texture LOD, TLUT (palette lookup), texture coordinate perspective correction, mid-texel offset
4. **Color combiner**: Two-cycle mode with configurable A/B/C/D sources for RGB and Alpha
5. **Blender**: Fog, anti-aliasing, z-buffer blending, dithering (magic-square and Bayer matrices), coverage calculation and update
6. **Z-buffer**: Per-pixel depth comparison with configurable modes, deltaZ
7. **Framebuffer**: 16-bit and 32-bit color framebuffer writes, coverage memory, dithered quantization

**Bit-exact requirement**: For every RDP command sequence, the WebGPU compute shader output must produce pixel-identical results to the [Angrylion-Plus](https://github.com/ata4/angrylion-rdp-plus) reference software renderer. Verification is done by hashing framebuffer contents — not visual comparison. A single differing pixel is a test failure.

**Verification**: Run the RDP test suite (see Tests section) which compares your output against pre-computed Angrylion golden hashes for each test case.

### R4: Audio

- RSP audio microcode execution produces PCM samples written to RDRAM
- Audio Interface (AI) DMA reads samples from RDRAM and feeds them to the output
- In browser: output via AudioWorklet with a ring buffer to handle timing drift
- Dynamic resampling from N64's native sample rate to the host's 44100/48000 Hz
- AI interrupt generation at correct intervals for DMA buffer completion

**Verification**: Audio DMA interrupt timing is covered by integration tests. Audio quality is verified by ensuring homebrew audio test ROMs produce non-silent, non-clipping output (waveform energy check).

### R5: Memory Subsystem

- **RDRAM**: 4 MB (unexpanded) / 8 MB (expanded), with correct access widths
- **ROM**: Cartridge ROM mapped at 0x10000000, PI DMA for bulk transfers
- **SPMEM**: 4 KB IMEM + 4 KB DMEM, accessible by both CPU and RSP
- **PIF RAM/ROM**: 64 bytes PIF RAM, boot ROM (IPL2/IPL3), controller/EEPROM/mempak communication
- **MMIO**: All memory-mapped I/O registers (RI, PI, SI, AI, VI, SP, DP, MI) with correct read/write behavior and interrupt routing
- **TLB**: 32-entry TLB for virtual memory translation

**Verification**: Memory access tests in n64-systemtest cover 8/16/32/64-bit access to RAM, ROM, SPMEM, PIF across the address map.

### R6: Video Interface (VI)

- Read the framebuffer from RDRAM and present it
- Support VI display modes: 320×240, 640×480, various interlace/progressive modes
- VI interrupt (VBlank) at the correct scanline
- Anti-aliasing and divot filter (as configured by VI registers)

### R7: Browser Frontend

The web frontend at `/app/web/index.html` must provide:

1. **Embedded homebrew ROM**: At least one legally distributable homebrew game loads by default with no user action required. Recommended: a [64brew Game Jam](https://n64brew.dev/wiki/N64brew_Game_Jam_2025) entry or [libdragon](https://github.com/DragonMinded/libdragon) example
2. **ROM loader**: Drag-and-drop or file picker for `.z64`, `.n64`, `.v64` format ROMs (auto-detect byte order)
3. **Canvas rendering**: WebGPU-backed `<canvas>` displaying the emulated framebuffer
4. **Input**: Keyboard mapping for N64 controller (WASD = analog stick, Arrow keys = C-buttons, Enter = Start, Z/X = A/B, etc.) and Gamepad API support
5. **Audio toggle**: Mute/unmute button
6. **Performance overlay**: FPS counter, VI/s counter
7. **Hardware test runner**: A "Run Tests" button that executes n64-systemtest and displays pass/fail results live in the browser

### R8: Native CLI

The native CLI at `/app/crates/n64-cli/` must support:

```
n64-cli run <rom.z64>                    # Run with display window
n64-cli run --headless <rom.z64>         # Run headless (for CI)
n64-cli test <test_rom.z64>              # Run test ROM, parse pass/fail, exit with code
n64-cli bench <rom.z64> --frames 1000    # Benchmark: report frames/sec
n64-cli rdp-test <rdp_commands.bin>      # Run RDP commands, dump framebuffer hash
```

Headless mode is essential for CI — the emulator must be able to run test ROMs without a display and report results to stdout.

## Expected Final Artifact

When the agent is finished, the repository must contain:

1. **`/app/`** — Complete Rust workspace that builds with `cargo build --release` (native) and `cargo build --release --target wasm32-unknown-unknown` (WASM)
2. **`/app/web/`** — Static website with `index.html` entry point. Running `python3 -m http.server` in this directory (after WASM build + wasm-bindgen) and opening in Chrome produces a working emulator
3. **All tests pass** — `./test.sh` exits 0
4. **Demo works** — Opening the web frontend shows an embedded homebrew ROM running with graphics, audio, and input

### Quality Gates

| Gate | Requirement | Checked By |
|---|---|---|
| Build (native) | `cargo build --release` succeeds with zero warnings | `tests/wasm/build_native.sh` |
| Build (WASM) | `cargo build --release --target wasm32-unknown-unknown` succeeds | `tests/wasm/build_wasm.sh` |
| WASM binary size | `n64_frontend_web.wasm` < 15 MB (after wasm-opt) | `tests/wasm/binary_size.sh` |
| CPU correctness | n64-systemtest: 0 failures out of 3,650+ tests | `tests/cpu/n64_systemtest.sh` |
| RSP correctness | All RSP vector/scalar/DMA tests pass | `tests/rsp/rsp_tests.sh` |
| RDP correctness | Bit-exact match against Angrylion on all RDP test vectors | `tests/rdp/bitexact.sh` |
| Integration | 5+ homebrew ROMs boot and render ≥60 frames without crash | `tests/integration/homebrew_boot.sh` |
| Performance (native) | ≥30 VI/s on a reference workload (4-core x86_64, no GPU) using software renderer | `tests/performance/native_benchmark.sh` |
| Performance (WASM) | ≥15 VI/s on reference workload in headless Chrome | `tests/performance/wasm_benchmark.sh` |
| Demo site | index.html loads, WASM initializes, canvas renders frames | `tests/integration/demo_site.sh` |

## Resources

### Test ROMs (legally distributable, must be fetched by `scripts/fetch_test_roms.sh`)

| Resource | URL | Purpose |
|---|---|---|
| n64-systemtest | https://github.com/lemmy-64/n64-systemtest | 3,650+ CPU/RSP/memory tests |
| Peter Lemon N64 Tests | https://github.com/PeterLemon/N64 | Bare-metal CPU, RSP, RDP tests |
| libdragon | https://github.com/DragonMinded/libdragon | SDK + example ROMs for integration testing |
| 64brew Game Jam 2025 | https://github.com/N64brew-Game-Jam-2025 | Legally distributable homebrew games |

### Reference Implementations

| Resource | URL | Purpose |
|---|---|---|
| Angrylion-Plus | https://github.com/ata4/angrylion-rdp-plus | RDP reference renderer (bit-exact ground truth) |
| parallel-rdp | https://github.com/Themaister/parallel-rdp | Vulkan compute RDP (architecture reference for WebGPU port) |
| gopher64 | https://github.com/gopher64/gopher64 | Rust N64 emulator (reference for CPU/RSP/memory) |
| n64js | https://github.com/hulkholden/n64js | JavaScript N64 emulator (browser architecture reference) |

### Technical Documentation

| Resource | URL |
|---|---|
| N64brew Wiki | https://n64brew.dev/wiki/ |
| VR4300 Datasheet | http://datasheets.chipdb.org/NEC/Vr-Series/Vr43xx/U10504EJ7V0UMJ1.pdf |
| RCP Documentation | https://n64brew.dev/wiki/Reality_Display_Processor |
| RSP Documentation | https://n64brew.dev/wiki/Reality_Signal_Processor |

## Key Technical Challenges

### 1. RDP via WebGPU Compute (Hardest)

The N64 RDP is a fixed-function pixel pipeline. [parallel-rdp](https://github.com/Themaister/parallel-rdp) implements it bit-exactly in ~10K lines of Vulkan compute GLSL. You must port this approach to WebGPU compute (WGSL).

Challenges:
- **Subgroup operations**: parallel-rdp uses Vulkan subgroup shuffles. WebGPU's [subgroups proposal](https://github.com/gpuweb/gpuweb/blob/main/proposals/subgroups.md) has limited browser support. You need fallback paths using workgroup shared memory
- **Memory model**: WebGPU storage buffers have different alignment rules and size limits vs Vulkan. Restructure data access patterns accordingly
- **Integer-only arithmetic**: For bit-exact results, use integer math throughout (no floating point in the pixel pipeline). This matches Angrylion's approach
- **GPU readback**: WebGPU `mapAsync` for framebuffer readback is async-only. The test framework must handle this

### 2. MIPS R4300i → WASM JIT (Hard, Optional)

For performance, a dynamic recompiler that translates MIPS basic blocks to WASM functions:
- WASM has structured control flow (no goto). Must reconstruct loops/if-else from MIPS branch graphs (stackifier algorithm)
- `new WebAssembly.Module()` compilation latency (~1-10ms) — batch basic blocks into larger compilation units
- Self-modifying code detection and compiled block invalidation
- Branch delay slot handling in the JIT

This is optional — an interpreter may achieve sufficient performance for many games, especially with the RDP offloaded to GPU compute.

### 3. RSP Vector Unit in WASM

The RSP has 128-bit SIMD vectors. WASM SIMD (`v128`) maps well to RSP vectors, but:
- RSP saturation/clamping behaviors don't map 1:1 to WASM SIMD instructions
- The 48-bit accumulator per lane has no native WASM type — emulate with i32/i64 pairs
- Performance: gopher64 uses AVX2/AVX-512 natively; WASM SIMD is 128-bit only

### 4. Audio Synchronization in Browser

- Web Audio API adds 20-50ms latency (vs N64's ~5ms)
- AudioWorklet with ring buffer and dynamic resampling
- Buffer underruns cause pops/clicks — need careful timing

## Difficulty

This is a 16–25 month project for a skilled systems engineer:

| Milestone | Estimate |
|---|---|
| CPU interpreter passing n64-systemtest | 2–3 months |
| RSP LLE passing RSP tests | 2–3 months |
| RDP software renderer (reference) | 2–3 months |
| WASM build running in browser | 1 month |
| RDP → WebGPU compute (bit-exact) | 4–6 months |
| Audio (RSP + AI + WebAudio) | 1–2 months |
| JIT (MIPS → WASM) | 3–6 months |
| Polish + demo site | 1 month |
