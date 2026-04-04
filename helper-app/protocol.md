# Serial protocol (helper app)

Transport: USB serial (COM port), 115200 8N1 unless you changed it.

Encoding: UTF-8 text.

Framing: **one JSON object per line** (newline-delimited JSON / NDJSON).

## Commands (PC -> device)

All commands are JSON objects containing a `cmd`.

### Ping

```json
{"cmd":"ping"}
```

### Write profile slot

`profile` is an arbitrary JSON object; the firmware decides what it means.

```json
{"cmd":"write_profile","slot":0,"profile":{}}
```

### Read profile slot

```json
{"cmd":"read_profile","slot":0}
```

### Set active slot

```json
{"cmd":"set_active_profile","slot":0}
```

## Events (device -> PC)

The device may emit events for:

- input reports
- mapped key events
- diagnostic status

Example:

```json
{"evt":"mapped_key","pressed":true,"key_id":1}
```

This helper app is tolerant of non-JSON log lines; it will display them as text.
