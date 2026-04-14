import { ESPLoader, Transport } from "https://unpkg.com/esptool-js@0.6.0/lib/index.js";

const HOST_BAUD = 115200;
const FLASH_BAUD = 460800;
const ESCAPE_GUARD_MS = 1000;
const HOST_MANIFEST = "manifest-esp32.json";
const S3_FIRMWARE_PATH = "firmware/esp32s3-usb-kbd.bin";

const diagLog = document.getElementById("diag-log");
const diagSection = document.getElementById("diag-section");
const statusNode = document.getElementById("install-status");
const progressNode = document.getElementById("install-progress");
const installButton = document.getElementById("install-s3-via-host");
const unsupportedNode = document.getElementById("unsupported");

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function dlog(message) {
  diagSection.hidden = false;
  const timestamp = new Date().toLocaleTimeString();
  diagLog.textContent += `[${timestamp}] ${message}\n`;
  diagLog.scrollTop = diagLog.scrollHeight;
}

function setStatus(message, progress = null) {
  statusNode.textContent = message;
  if (typeof progress === "number") {
    progressNode.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function readTextLine(session, timeoutMs) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const newlineIndex = session.buffer.search(/\r?\n/);
    if (newlineIndex >= 0) {
      const line = session.buffer.slice(0, newlineIndex).trim();
      session.buffer = session.buffer.slice(newlineIndex + (session.buffer[newlineIndex] === "\r" ? 2 : 1));
      if (line.length > 0) {
        return line;
      }
      continue;
    }

    const remaining = deadline - Date.now();
    const result = await Promise.race([
      session.reader.read(),
      new Promise((resolve) => window.setTimeout(() => resolve({ timeout: true }), remaining)),
    ]);

    if (result?.timeout) {
      break;
    }

    if (result.done) {
      break;
    }

    session.buffer += decoder.decode(result.value, { stream: true });
  }

  throw new Error("Timed out waiting for host response");
}

async function sendHostCommand(session, command, timeoutMs = 4000) {
  dlog(`Host <= ${command}`);
  await session.writer.write(encoder.encode(`${command}\n`));

  while (true) {
    const line = await readTextLine(session, timeoutMs);
    dlog(`Host => ${line}`);
    if (!line.startsWith("BBI ")) {
      continue;
    }
    return line;
  }
}

async function openCommandSession(port) {
  await port.open({ baudRate: HOST_BAUD, bufferSize: 8192 });
  return {
    port,
    reader: port.readable.getReader(),
    writer: port.writable.getWriter(),
    buffer: "",
  };
}

async function closeCommandSession(session) {
  if (!session) {
    return;
  }
  await session.reader.cancel().catch(() => {});
  session.reader.releaseLock();
  session.writer.releaseLock();
  await session.port.close().catch(() => {});
}

async function withCommandSession(port, callback) {
  const session = await openCommandSession(port);
  try {
    return await callback(session);
  } finally {
    await closeCommandSession(session);
  }
}

async function fetchBinary(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to download ${path}: HTTP ${response.status}`);
  }
  return new Uint8Array(await response.arrayBuffer());
}

function createLoaderTerminal() {
  return {
    clean() {},
    writeLine(data) {
      if (data) {
        dlog(`[esptool] ${data}`);
      }
    },
    write(data) {
      if (data) {
        dlog(`[esptool] ${data}`);
      }
    },
  };
}

async function flashS3ThroughHost(port, firmwareBytes) {
  const transport = new Transport(port, true);
  const loader = new ESPLoader({
    transport,
    baudrate: FLASH_BAUD,
    terminal: createLoaderTerminal(),
    debugLogging: false,
  });

  try {
    const chip = await loader.main("no_reset");
    dlog(`Connected to ${chip}`);

    await loader.writeFlash({
      fileArray: [{ data: firmwareBytes, address: 0x0 }],
      flashMode: "dio",
      flashFreq: "40m",
      flashSize: "4MB",
      eraseAll: true,
      compress: true,
      reportProgress(_fileIndex, written, total) {
        const percent = total > 0 ? (written / total) * 100 : 0;
        setStatus(`Flashing ESP32-S3 through host... ${percent.toFixed(1)}%`, percent);
      },
    });
  } finally {
    await transport.disconnect().catch(() => {});
  }
}

async function escapeHostBridge(port) {
  await withCommandSession(port, async (session) => {
    await sleep(ESCAPE_GUARD_MS);
    await session.writer.write(encoder.encode("+++"));

    let line;
    do {
      line = await readTextLine(session, 5000);
      dlog(`Host => ${line}`);
    } while (!line.startsWith("BBI OK BRIDGE_STOP"));

    const runResponse = await sendHostCommand(session, "BBI S3_RUN", 4000);
    if (!runResponse.startsWith("BBI OK S3_RUN")) {
      throw new Error(`Unexpected S3_RUN response: ${runResponse}`);
    }
  });
}

async function runHostAssistedInstall() {
  if (!("serial" in navigator)) {
    throw new Error("Web Serial is unavailable in this browser");
  }

  installButton.disabled = true;
  setStatus("Downloading ESP32-S3 firmware image...", 2);

  let port;

  try {
    const firmwareBytes = await fetchBinary(S3_FIRMWARE_PATH);
    dlog(`Loaded S3 firmware image (${(firmwareBytes.length / 1024).toFixed(1)} KB)`);

    setStatus("Pick the ESP32 host serial port...", 5);
    port = await navigator.serial.requestPort();

    await withCommandSession(port, async (session) => {
      const hello = await sendHostCommand(session, "BBI HELLO", 4000);
      if (!hello.startsWith("BBI OK HELLO")) {
        throw new Error(`Unexpected HELLO response: ${hello}`);
      }

      const prep = await sendHostCommand(session, "BBI S3_DOWNLOAD", 4000);
      if (!prep.startsWith("BBI OK S3_DOWNLOAD")) {
        throw new Error(`Unexpected S3_DOWNLOAD response: ${prep}`);
      }

      const bridge = await sendHostCommand(session, "BBI BRIDGE_START", 4000);
      if (!bridge.startsWith("BBI OK BRIDGE_START")) {
        throw new Error(`Unexpected BRIDGE_START response: ${bridge}`);
      }
    });

    setStatus("Opening raw bridge to the Nano bootloader...", 12);
    await sleep(250);

    await flashS3ThroughHost(port, firmwareBytes);

    setStatus("Leaving bridge mode and rebooting the Nano...", 96);
    await escapeHostBridge(port);

    setStatus("ESP32-S3 install finished. Move USB to the Nano for normal use.", 100);
    dlog("Host-assisted S3 flash completed successfully.");
  } finally {
    if (port?.readable || port?.writable) {
      await port.close().catch(() => {});
    }
    installButton.disabled = false;
  }
}

async function runDiag() {
  dlog("Pre-flight checks starting...");
  dlog(`Secure context: ${window.isSecureContext} | Web Serial API: ${"serial" in navigator}`);
  dlog(`User-Agent: ${navigator.userAgent.slice(0, 120)}`);

  if (customElements.get("esp-web-install-button")) {
    dlog("ESP Web Tools component registered.");
  } else {
    dlog("ESP Web Tools component not registered.");
  }

  try {
    dlog(`Fetching manifest: ${HOST_MANIFEST}`);
    const manifestResponse = await fetch(HOST_MANIFEST);
    dlog(`  HTTP ${manifestResponse.status} ${manifestResponse.statusText}`);
    if (manifestResponse.ok) {
      const manifest = await manifestResponse.json();
      dlog(`  Host manifest OK - ${manifest.name} (${manifest.builds?.[0]?.chipFamily || "unknown chip"})`);
    }
  } catch (error) {
    dlog(`  Manifest error: ${error.message}`);
  }

  try {
    dlog(`Fetching firmware: ${S3_FIRMWARE_PATH}`);
    const firmware = await fetchBinary(S3_FIRMWARE_PATH);
    dlog(`  S3 firmware OK - ${(firmware.length / 1024).toFixed(1)} KB`);
  } catch (error) {
    dlog(`  Firmware error: ${error.message}`);
  }

  dlog("Pre-flight done.\n");
}

if (!("serial" in navigator)) {
  unsupportedNode.hidden = false;
}

installButton.addEventListener("click", async () => {
  try {
    await runHostAssistedInstall();
  } catch (error) {
    dlog(`Host-assisted install failed: ${error.message}`);
    setStatus(`Install failed: ${error.message}`, 0);
  }
});

document.querySelectorAll("esp-web-install-button").forEach((button) => {
  const label = button.closest(".card, .fallback-box")?.querySelector("h2, summary")?.textContent || "ESP Web Tools";
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.tagName && node.tagName.toLowerCase() === "ew-install-dialog") {
          dlog(`[${label}] install dialog opened`);
          node.addEventListener("state-changed", (event) => {
            dlog(`[${label}] state: ${event.detail?.state || JSON.stringify(event.detail)}`);
          });
          node.addEventListener("closed", () => {
            dlog(`[${label}] dialog closed`);
          });
          node.addEventListener("error", (event) => {
            dlog(`[${label}] error: ${event.detail?.message || event.detail || event}`);
          });
        }
      }
    }
  });
  observer.observe(document.body, { childList: true });

  button.addEventListener("click", () => {
    dlog(`[${label}] install button clicked`);
  }, true);
});

runDiag().catch((error) => {
  dlog(`Diagnostics failed: ${error.message}`);
});