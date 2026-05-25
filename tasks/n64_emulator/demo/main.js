// =============================================================================
// N64 Emulator — Browser Entry Point
//
// This file is the reference skeleton for the web frontend. The agent must
// implement the actual WASM bindings and emulator integration.
//
// Expected exports from the WASM module (via wasm-bindgen):
//   - N64Emulator.new()           → Create emulator instance
//   - N64Emulator.load_rom(bytes) → Load a ROM from a Uint8Array
//   - N64Emulator.run_frame()     → Run one frame (one VI interrupt)
//   - N64Emulator.get_framebuffer() → Get RGBA pixel data for the canvas
//   - N64Emulator.set_input(button, pressed) → Set controller input
//   - N64Emulator.get_audio_samples() → Get PCM audio samples
//   - N64Emulator.frame_count()   → Get total VI count
//   - N64Emulator.run_test_rom(bytes) → Run a test ROM and return results string
// =============================================================================

const $ = (sel) => document.querySelector(sel);
const log = (msg, cls = 'info') => {
    const el = $('#status');
    const div = document.createElement('div');
    div.className = cls;
    div.textContent = msg;
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let emu = null;
let running = false;
let muted = false;
let audioCtx = null;
let audioWorklet = null;
let frameCount = 0;
let lastFpsTime = performance.now();
let lastFpsFrames = 0;

// Expose frame count globally for benchmark scripts
Object.defineProperty(window, '__n64_frame_count', {
    value: () => frameCount,
    writable: false,
});
window.n64FrameCount = 0;

// ---------------------------------------------------------------------------
// WASM initialization
// ---------------------------------------------------------------------------
async function init() {
    try {
        // Import the wasm-bindgen generated module
        // The agent must produce this file via: wasm-bindgen --target web
        const wasm = await import('./pkg/n64_frontend_web.js');
        await wasm.default();

        log('WASM module loaded', 'ok');

        // Check WebGPU support
        if (navigator.gpu) {
            const adapter = await navigator.gpu.requestAdapter();
            if (adapter) {
                const device = await adapter.requestDevice();
                log(`WebGPU: ${adapter.info?.device || 'available'}`, 'ok');
            } else {
                log('WebGPU adapter not available — using software renderer', 'warn');
            }
        } else {
            log('WebGPU not supported — using software renderer', 'warn');
        }

        // Create emulator instance
        emu = wasm.N64Emulator.new();
        log('Emulator initialized', 'ok');

        // Enable buttons
        $('#btn-play').disabled = false;
        $('#btn-demo').disabled = false;
        $('#btn-test').disabled = false;

    } catch (e) {
        log(`Init failed: ${e.message}`, 'err');
        console.error(e);
    }
}

// ---------------------------------------------------------------------------
// ROM loading
// ---------------------------------------------------------------------------
function detectByteOrder(data) {
    // .z64 (big-endian):    first 4 bytes = 80 37 12 40
    // .v64 (byte-swapped):  first 4 bytes = 37 80 40 12
    // .n64 (little-endian): first 4 bytes = 40 12 37 80
    const view = new DataView(data.buffer || data);
    const magic = view.getUint32(0);

    if (magic === 0x80371240) return 'z64';
    if (magic === 0x37804012) return 'v64';
    if (magic === 0x40123780) return 'n64';
    return 'unknown';
}

function convertToZ64(data) {
    const order = detectByteOrder(data);
    if (order === 'z64') return data;

    const out = new Uint8Array(data.length);
    if (order === 'v64') {
        // Byte-swap pairs
        for (let i = 0; i < data.length; i += 2) {
            out[i] = data[i + 1];
            out[i + 1] = data[i];
        }
    } else if (order === 'n64') {
        // Word-swap (4 bytes)
        for (let i = 0; i < data.length; i += 4) {
            out[i] = data[i + 3];
            out[i + 1] = data[i + 2];
            out[i + 2] = data[i + 1];
            out[i + 3] = data[i];
        }
    } else {
        log('Unknown ROM format — loading as-is', 'warn');
        return data;
    }

    log(`Converted from ${order} to z64 format`, 'info');
    return out;
}

async function loadROM(data) {
    if (!emu) { log('Emulator not initialized', 'err'); return; }

    const rom = convertToZ64(new Uint8Array(data));
    log(`Loading ROM (${(rom.length / 1024 / 1024).toFixed(1)} MB)...`, 'info');

    try {
        emu.load_rom(rom);
        log('ROM loaded', 'ok');
        $('#btn-play').disabled = false;
        $('#btn-reset').disabled = false;
    } catch (e) {
        log(`ROM load failed: ${e.message}`, 'err');
    }
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------
const canvas = $('#screen');
const ctx = canvas.getContext('2d');

function mainLoop() {
    if (!running || !emu) return;

    try {
        emu.run_frame();
        frameCount++;
        window.n64FrameCount = frameCount;

        // Get framebuffer and draw to canvas
        const fb = emu.get_framebuffer();
        if (fb && fb.length > 0) {
            const imageData = new ImageData(
                new Uint8ClampedArray(fb.buffer || fb),
                320, 240
            );
            ctx.putImageData(imageData, 0, 0);
        }

        // Get audio samples
        if (!muted && audioCtx) {
            const samples = emu.get_audio_samples();
            if (samples && samples.length > 0) {
                // Feed to AudioWorklet
            }
        }

        // Update FPS counter
        const now = performance.now();
        if (now - lastFpsTime >= 1000) {
            const fps = ((frameCount - lastFpsFrames) * 1000) / (now - lastFpsTime);
            $('#perf-overlay').textContent = `${fps.toFixed(1)} VI/s | Frame ${frameCount}`;
            lastFpsFrames = frameCount;
            lastFpsTime = now;
        }

    } catch (e) {
        log(`Emulation error: ${e.message}`, 'err');
        running = false;
        return;
    }

    requestAnimationFrame(mainLoop);
}

// ---------------------------------------------------------------------------
// Input handling
// ---------------------------------------------------------------------------
const KEY_MAP = {
    'KeyW': 'ANALOG_UP',    'KeyS': 'ANALOG_DOWN',
    'KeyA': 'ANALOG_LEFT',  'KeyD': 'ANALOG_RIGHT',
    'ArrowUp': 'C_UP',      'ArrowDown': 'C_DOWN',
    'ArrowLeft': 'C_LEFT',  'ArrowRight': 'C_RIGHT',
    'Enter': 'START',
    'KeyZ': 'A',             'KeyX': 'B',
    'KeyQ': 'L',             'KeyE': 'R',
    'ShiftLeft': 'Z',        'ShiftRight': 'Z',
};

document.addEventListener('keydown', (e) => {
    const btn = KEY_MAP[e.code];
    if (btn && emu) {
        e.preventDefault();
        emu.set_input(btn, true);
    }
});

document.addEventListener('keyup', (e) => {
    const btn = KEY_MAP[e.code];
    if (btn && emu) {
        e.preventDefault();
        emu.set_input(btn, false);
    }
});

// Gamepad API
function pollGamepads() {
    const gamepads = navigator.getGamepads();
    for (const gp of gamepads) {
        if (!gp || !emu) continue;
        // Standard gamepad mapping
        emu.set_input('A', gp.buttons[0]?.pressed || false);
        emu.set_input('B', gp.buttons[1]?.pressed || false);
        emu.set_input('START', gp.buttons[9]?.pressed || false);
        emu.set_input('L', gp.buttons[4]?.pressed || false);
        emu.set_input('R', gp.buttons[5]?.pressed || false);
        emu.set_input('Z', gp.buttons[6]?.pressed || false);
        // Analog stick
        const lx = gp.axes[0] || 0;
        const ly = gp.axes[1] || 0;
        emu.set_input('ANALOG_LEFT', lx < -0.3);
        emu.set_input('ANALOG_RIGHT', lx > 0.3);
        emu.set_input('ANALOG_UP', ly < -0.3);
        emu.set_input('ANALOG_DOWN', ly > 0.3);
    }
    if (running) requestAnimationFrame(pollGamepads);
}

// ---------------------------------------------------------------------------
// Button handlers
// ---------------------------------------------------------------------------
$('#btn-play').addEventListener('click', () => {
    if (!emu) return;
    running = true;
    requestAnimationFrame(mainLoop);
    requestAnimationFrame(pollGamepads);
    log('Playing', 'ok');
    $('#btn-play').disabled = true;
    $('#btn-pause').disabled = false;
});

$('#btn-pause').addEventListener('click', () => {
    running = false;
    log('Paused', 'info');
    $('#btn-play').disabled = false;
    $('#btn-pause').disabled = true;
});

$('#btn-reset').addEventListener('click', () => {
    if (!emu) return;
    running = false;
    emu.reset?.();
    frameCount = 0;
    log('Reset', 'info');
    $('#btn-play').disabled = false;
    $('#btn-pause').disabled = true;
});

$('#btn-mute').addEventListener('click', () => {
    muted = !muted;
    $('#btn-mute').textContent = muted ? 'Unmute' : 'Mute';
});

$('#btn-fullscreen').addEventListener('click', () => {
    canvas.requestFullscreen?.() || canvas.webkitRequestFullscreen?.();
});

$('#btn-demo').addEventListener('click', async () => {
    log('Loading embedded demo ROM...', 'info');
    try {
        const resp = await fetch('roms/demo.z64');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.arrayBuffer();
        await loadROM(data);
    } catch (e) {
        log(`Demo load failed: ${e.message}`, 'err');
    }
});

$('#btn-test').addEventListener('click', async () => {
    if (!emu) return;
    log('Loading n64-systemtest...', 'info');
    const resultsDiv = $('#test-results');
    resultsDiv.style.display = 'block';
    resultsDiv.textContent = 'Running hardware tests...\n';

    try {
        const resp = await fetch('roms/n64-systemtest.z64');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = new Uint8Array(await resp.arrayBuffer());
        const result = emu.run_test_rom(data);
        resultsDiv.textContent = result;
        log('Hardware tests complete', 'ok');
    } catch (e) {
        log(`Test failed: ${e.message}`, 'err');
        resultsDiv.textContent += `\nError: ${e.message}`;
    }
});

// ---------------------------------------------------------------------------
// Drag-and-drop / file picker
// ---------------------------------------------------------------------------
const dropZone = $('#drop-zone');
const romInput = $('#rom-input');

dropZone.addEventListener('click', () => romInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', async (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) {
        log(`Loading: ${file.name}`, 'info');
        const data = await file.arrayBuffer();
        await loadROM(data);
    }
});

romInput.addEventListener('change', async () => {
    const file = romInput.files[0];
    if (file) {
        log(`Loading: ${file.name}`, 'info');
        const data = await file.arrayBuffer();
        await loadROM(data);
    }
});

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------
init();
