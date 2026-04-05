# Helper app UI architecture (diagram)

```mermaid
graph TD
  PC[PC (Windows)] -->|USB| S3[ESP32-S3 USB device]

  subgraph S3FW[ESP32-S3 firmware]
    HID[USB HID Keyboard]
    CDC[USB CDC ACM COM port]
    UARTRX[UART RX frame parser]
    UARTTX[UART TX control sender]
    PROF[Profile runtime + macros]

    CDC -->|NDJSON cmds| UARTTX
    UARTRX -->|key events + status| PROF
    PROF -->|HID reports| HID
    UARTRX -->|NDJSON events| CDC
  end

  subgraph ESP32FW[ESP32 (Classic BT host firmware)]
    GAP[Inquiry scan + name match]
    HIDH[Classic HID host]
    MAP[Joy-Con mapper]
    UARTFR[UART framing]

    HIDH -->|reports| MAP
    GAP --> HIDH
    MAP --> UARTFR
  end

  S3 -->|UART ctrl frames| ESP32FW
  ESP32FW -->|UART key/status frames| S3FW

  APP[Helper app (Tkinter)] -->|NDJSON over COM| CDC
  CDC -->|NDJSON events| APP

  note1[[Anti-cheat constraint: PC sees a real USB HID keyboard]] --- HID
```

Notes:

- The helper app never injects inputs; it only configures profiles and requests BT scan/connect.
- Legacy 1-byte key events remain supported; dual Joy-Con uses extended key events.
