# Xbox Controller Firmware Protocol Reference

This document describes the command protocol implemented by the current Arduino firmware in `arduino_controller_fixed.ino`.
It is a behavior reference only.

## 1. Overview

### 1.1 Transport

The firmware uses UDP in both directions:

- Inbound command port: `5005`
- Outbound response port: `5006`

The firmware listens for command packets on port `5005`. For responses, it captures the sender IP from the most recent received packet and sends responses to that IP on port `5006`.

### 1.2 Packet format

Commands are sent as JSON-like objects, but the parser strips `{`, `}`, `"`, spaces, and line breaks before processing. After stripping, the packet is treated as comma-separated `key:value` entries.

Example transmitted packet:

```json
{"seq":42,"resp":2,"aim_x":25,"aim_y":-10,"aim_duration":120}
```

Parser view of that packet:

```text
seq:42,resp:2,aim_x:25,aim_y:-10,aim_duration:120
```

### 1.3 Sequence and response mode fields

Two packet-level fields are parsed first:

- `seq` (integer): request sequence number echoed in responses
- `resp` (integer): response mode

Response mode values:

- `0`: no response
- `1`: `ack` responses only
- `2`: `ack` plus `complete` for timed command families that support completion events

If `resp` is absent, mode defaults to `0`.

### 1.4 Response types

The firmware emits three message types:

- `pong`: reply to `ping`
- `ack`: immediate acceptance/arming confirmation
- `complete`: emitted when a timed hold duration expires (only for certain command families)

### 1.5 Timing model

Timed command families (`aim`, `move`, `trigger`, `trigger_lt`) become active when their value keys are set and are finalized when their corresponding `*_duration` key is processed. Completion timing is tracked internally, and `complete` includes measured duration error fields.

### 1.6 Command composition

A single packet may include multiple `key:value` entries. Packet-level `seq` and `resp` apply to all command entries in that packet.

## 2. Packet Format Details

### 2.1 Accepted input shape

Use integer-valued fields in a JSON object. After stripping JSON punctuation, each remaining token must be parseable as `name:value`.

### 2.2 Parse order

The firmware parses:

1. `seq`
2. `resp`
3. Remaining comma-delimited entries in order

Entries named `seq` and `resp` are skipped during per-command dispatch because they were already consumed at packet level.

### 2.3 Key styles

Command keys use three patterns:

- Fixed command keys: `ping`, `reload`, `trigger`, `trigger_duration`, `trigger_lt`, `trigger_lt_duration`, `aim_x`, `aim_y`, `aim_duration`, `move_x`, `move_y`, `move_duration`, `hat_x`, `hat_y`, `hat_duration`
- Indexed key families: `button_N`, `axis_N`
- Indexed duration key family: `button_N_duration`
- Packet metadata: `seq`, `resp`

### 2.4 Value encoding and practical ranges

The firmware parses numeric values as integers.

- Axis-like values are intended for joystick ranges configured to `-100..100`.
- D-pad inputs are interpreted as directional components and are meaningful in `-1, 0, 1`.
- Button values are used as pressed flags (`0` or `1`).
- Durations are milliseconds.

The code does not clamp every input explicitly at parse time; callers should stay within expected ranges.

## 3. Command Reference

### 3.1 `aim` (right stick)

`aim` is a timed right-stick family composed of three keys:

- `aim_x` (int, expected `-100..100`): horizontal aim component
- `aim_y` (int, expected `-100..100`): vertical aim component
- `aim_duration` (int ms, non-negative): hold duration

Typical packet:

```json
{"seq":1001,"resp":2,"aim_x":30,"aim_y":-20,"aim_duration":90}
```

Self-release: **yes**. After `aim_duration` expires, firmware resets right-stick mapped axes back to neutral (`0`, `0`).

Responses when `resp=1`:

```json
{"msg_type":"ack","seq":1001,"cmd":"aim","x":30,"y":-20,"dur":90}
```

Responses when `resp=2`:

```json
{"msg_type":"ack","seq":1001,"cmd":"aim","x":30,"y":-20,"dur":90}
{"msg_type":"complete","seq":1001,"cmd":"aim","x":30,"y":-20,"dur":90,"actual_us":90123,"err_us":123}
```

Special behavior: `ack` is emitted when `aim_duration` is received, not when `aim_x`/`aim_y` arrive.

### 3.2 `move` (left stick)

`move` is a timed left-stick family composed of:

- `move_x` (int, expected `-100..100`)
- `move_y` (int, expected `-100..100`)
- `move_duration` (int ms)

Typical packet:

```json
{"seq":1002,"resp":2,"move_x":-40,"move_y":60,"move_duration":250}
```

Self-release: **yes**. After duration expiry, firmware resets left stick to neutral (`0`, `0`).

Responses when `resp=1`:

```json
{"msg_type":"ack","seq":1002,"cmd":"move","x":-40,"y":60,"dur":250}
```

Responses when `resp=2`:

```json
{"msg_type":"ack","seq":1002,"cmd":"move","x":-40,"y":60,"dur":250}
{"msg_type":"complete","seq":1002,"cmd":"move","x":-40,"y":60,"dur":250,"actual_us":250318,"err_us":318}
```

Special behavior: `ack` is emitted when `move_duration` is received.

### 3.3 `trigger` (right trigger)

Timed right-trigger family:

- `trigger` (int, expected `-100..100`; released baseline is `-100`)
- `trigger_duration` (int ms)

Typical packet:

```json
{"seq":1003,"resp":2,"trigger":100,"trigger_duration":35}
```

Self-release: **yes**. After duration expiry, firmware resets right trigger to `-100` (released).

Responses when `resp=1`:

```json
{"msg_type":"ack","seq":1003,"cmd":"trigger","val":100,"dur":35}
```

Responses when `resp=2`:

```json
{"msg_type":"ack","seq":1003,"cmd":"trigger","val":100,"dur":35}
{"msg_type":"complete","seq":1003,"cmd":"trigger","val":100,"dur":35,"actual_us":35102,"err_us":102}
```

Special behavior: `ack` is emitted when `trigger_duration` is received.

### 3.4 `trigger_lt` (left trigger)

Timed left-trigger family:

- `trigger_lt` (int, expected `-100..100`; released baseline is `-100`)
- `trigger_lt_duration` (int ms)

Typical packet:

```json
{"seq":1004,"resp":2,"trigger_lt":80,"trigger_lt_duration":120}
```

Self-release: **yes**. After duration expiry, firmware resets left trigger to `-100`.

Responses when `resp=1`:

```json
{"msg_type":"ack","seq":1004,"cmd":"trigger_lt","val":80,"dur":120}
```

Responses when `resp=2`:

```json
{"msg_type":"ack","seq":1004,"cmd":"trigger_lt","val":80,"dur":120}
{"msg_type":"complete","seq":1004,"cmd":"trigger_lt","val":80,"dur":120,"actual_us":120444,"err_us":444}
```

Special behavior: `ack` is emitted when `trigger_lt_duration` is received.

### 3.5 `button_N`

Dynamic button command family:

- Key shape: `button_N` where `N` is a decimal index parsed from the key name
- Value: integer pressed state (conventionally `0` release, `1` press)

Typical packets:

```json
{"seq":1005,"resp":1,"button_0":1}
{"seq":1006,"resp":1,"button_0":0}
```

Self-release: **no**. Firmware applies the state immediately and keeps it until another packet changes it.

Responses when `resp=1`:

```json
{"msg_type":"ack","seq":1005,"cmd":"button","btn":0,"pressed":1}
```

Responses when `resp=2`: same `ack` behavior only; no `complete` is emitted for button commands.

Special behavior: button index is parsed from the key text between `button_` and `:`.

### 3.6 `hat_x` / `hat_y`

D-pad vector components:

- `hat_x` (expected `-1, 0, 1`)
- `hat_y` (expected `-1, 0, 1`)

The firmware maintains internal `hat_x` and `hat_y` state and maps the pair to an 8-way hat angle (`0,45,90,...,315`) or neutral (`-1`).

Typical packet:

```json
{"seq":1007,"resp":0,"hat_x":1,"hat_y":0}
```

Self-release: **no**. Hat state remains until changed by another `hat_x`/`hat_y` update.

Responses when `resp=1` or `resp=2`: none. The firmware does not emit `ack` or `complete` for hat commands.

Special behavior: whichever of `hat_x` or `hat_y` arrives updates first uses the latest value of the other component.

### 3.7 `reload`

Reload helper command:

- Key: `reload`
- Value: parsed but not used for branching (any integer value triggers behavior)

Typical packet:

```json
{"seq":1008,"resp":1,"reload":1}
```

Self-release: **yes**. Firmware presses `button_0`, holds for a fixed `50 ms`, then releases automatically.

Responses when `resp=1`:

```json
{"msg_type":"ack","seq":1008,"cmd":"reload"}
```

Responses when `resp=2`: same `ack` behavior only; no `complete` is emitted for reload.

Special behavior: hold duration is fixed in firmware (`RELOAD_DURATION_MS = 50`) and cannot be overridden by packet payload.

### 3.8 `ping`

Connectivity command:

- Key: `ping`
- Value: parsed but not used

Typical packet:

```json
{"seq":1009,"resp":0,"ping":1}
```

Self-release: not applicable.

Response behavior: always replies with `pong` regardless of `resp` mode.

```json
{"msg_type":"pong","seq":1009}
```

Special behavior: `ping` bypasses `resp` gating and unconditionally sends `pong` if a valid sender IP has been captured.

### 3.9 `axis_N` passthrough (legacy)

Legacy axis family retained for backward compatibility:

- Key shape: `axis_N` where `N` is `0..5`
- Value: integer axis value

Axis mapping implemented by firmware:

- `axis_0` -> `X`
- `axis_1` -> `Y`
- `axis_2` -> `Z`
- `axis_3` -> `Rz`
- `axis_4` -> `Rx`
- `axis_5` -> `Ry`

Typical packet:

```json
{"seq":1010,"resp":0,"axis_2":35}
```

Self-release: **no**. Passthrough writes the axis directly and leaves it at that value until another command changes it.

Responses when `resp=1` or `resp=2`: none. No `ack`/`complete` exists for legacy `axis_N` commands.

Special behavior: this family is explicitly marked as legacy in the firmware source and exists for compatibility with older senders.

### 3.10 `button_N_duration`

Timed self-release companion for `button_N`:

- Key shape: `button_N_duration` where `N` is `0..14`
- Value: duration in milliseconds
- Required pairing: the corresponding `button_N` press (`1`) must be seen before the duration key to arm the timer

Typical packet:

```json
{"seq":1011,"resp":2,"button_3":1,"button_3_duration":75}
```

Self-release: **yes**. After `button_N_duration` expires, firmware sets `button_N` back to `0` automatically.

Responses when `resp=1`:

```json
{"msg_type":"ack","seq":1011,"cmd":"button","btn":3,"pressed":1}
{"msg_type":"ack","seq":1011,"cmd":"button_duration","btn":3,"dur":75}
```

Responses when `resp=2`:

```json
{"msg_type":"ack","seq":1011,"cmd":"button","btn":3,"pressed":1}
{"msg_type":"ack","seq":1011,"cmd":"button_duration","btn":3,"dur":75}
{"msg_type":"complete","seq":1011,"cmd":"button_duration","btn":3,"dur":75,"actual_us":75210,"err_us":210}
```

Special behavior: if a new `button_N:1` arrives while a timer is active for the same `N`, that press is authoritative and supersedes the running timer; the next `button_N_duration` sets the new hold window.

### 3.11 `hat_duration`

Timed self-release companion for `hat_x`/`hat_y`:

- Key: `hat_duration`
- Value: duration in milliseconds
- Required pairing: a hat state must be set via `hat_x` and/or `hat_y` before arming duration

Typical packet:

```json
{"seq":1012,"resp":2,"hat_x":1,"hat_y":0,"hat_duration":120}
```

Self-release: **yes**. On expiry, firmware resets to neutral by setting hat components to `(0,0)` and applying `mapHatDirection(0,0)`.

Responses when `resp=1`:

```json
{"msg_type":"ack","seq":1012,"cmd":"hat_duration","x":1,"y":0,"dur":120}
```

Responses when `resp=2`:

```json
{"msg_type":"ack","seq":1012,"cmd":"hat_duration","x":1,"y":0,"dur":120}
{"msg_type":"complete","seq":1012,"cmd":"hat_duration","x":1,"y":0,"dur":120,"actual_us":120350,"err_us":350}
```

Special behavior: duration arming is separate from directional state updates; raw `hat_x`/`hat_y` still work without duration.

## 4. Response Payload Reference

This section summarizes exact response schema by message type.

### 4.1 `pong`

```json
{"msg_type":"pong","seq":<seq>}
```

### 4.2 `ack`

Timed families:

```json
{"msg_type":"ack","seq":<seq>,"cmd":"aim","x":<int>,"y":<int>,"dur":<ms>}
{"msg_type":"ack","seq":<seq>,"cmd":"move","x":<int>,"y":<int>,"dur":<ms>}
{"msg_type":"ack","seq":<seq>,"cmd":"trigger","val":<int>,"dur":<ms>}
{"msg_type":"ack","seq":<seq>,"cmd":"trigger_lt","val":<int>,"dur":<ms>}
{"msg_type":"ack","seq":<seq>,"cmd":"button_duration","btn":<index>,"dur":<ms>}
{"msg_type":"ack","seq":<seq>,"cmd":"hat_duration","x":<int>,"y":<int>,"dur":<ms>}
```

Untimed helpers:

```json
{"msg_type":"ack","seq":<seq>,"cmd":"button","btn":<index>,"pressed":<0|1>}
{"msg_type":"ack","seq":<seq>,"cmd":"reload"}
```

### 4.3 `complete`

`complete` is available only for timed families:

```json
{"msg_type":"complete","seq":<seq>,"cmd":"aim","x":<int>,"y":<int>,"dur":<ms>,"actual_us":<us>,"err_us":<us_delta>}
{"msg_type":"complete","seq":<seq>,"cmd":"move","x":<int>,"y":<int>,"dur":<ms>,"actual_us":<us>,"err_us":<us_delta>}
{"msg_type":"complete","seq":<seq>,"cmd":"trigger","val":<int>,"dur":<ms>,"actual_us":<us>,"err_us":<us_delta>}
{"msg_type":"complete","seq":<seq>,"cmd":"trigger_lt","val":<int>,"dur":<ms>,"actual_us":<us>,"err_us":<us_delta>}
{"msg_type":"complete","seq":<seq>,"cmd":"button_duration","btn":<index>,"dur":<ms>,"actual_us":<us>,"err_us":<us_delta>}
{"msg_type":"complete","seq":<seq>,"cmd":"hat_duration","x":<int>,"y":<int>,"dur":<ms>,"actual_us":<us>,"err_us":<us_delta>}
```

### 4.4 Response mode matrix

- `resp=0`: suppresses `ack` and `complete`; `ping` still yields `pong`
- `resp=1`: enables `ack` where supported
- `resp=2`: enables `ack` plus timed-family `complete`

## 5. Self-Release Summary

Self-release means the firmware itself performs the release transition after a duration or fixed hold, so callers do not need to send a separate release packet.

| Command family | Hardware self-release |
| --- | --- |
| `aim` | Yes |
| `move` | Yes |
| `trigger` | Yes |
| `trigger_lt` | Yes |
| `button_N` | No |
| `button_N_duration` | Yes |
| `hat_x` / `hat_y` | No |
| `hat_duration` | Yes |
| `reload` | Yes |
| `ping` | N/A |
| `axis_N` (legacy) | No |

Caller responsibility for non-self-releasing families (`button_N`, `hat_x/hat_y`, `axis_N`): send explicit follow-up packets to return state to neutral/released values.

## 6. End-to-End Examples

### 6.1 Fire-and-forget timed move (`resp=0`)

```json
{"seq":2001,"resp":0,"move_x":0,"move_y":100,"move_duration":150}
```

Expected response: none.

### 6.2 Ack-only button press (`resp=1`)

```json
{"seq":2002,"resp":1,"button_2":1}
```

Expected response:

```json
{"msg_type":"ack","seq":2002,"cmd":"button","btn":2,"pressed":1}
```

To release later:

```json
{"seq":2003,"resp":1,"button_2":0}
```

### 6.3 Ack+complete trigger (`resp=2`)

```json
{"seq":2004,"resp":2,"trigger":100,"trigger_duration":40}
```

Expected responses (order: immediate then post-duration):

```json
{"msg_type":"ack","seq":2004,"cmd":"trigger","val":100,"dur":40}
{"msg_type":"complete","seq":2004,"cmd":"trigger","val":100,"dur":40,"actual_us":40110,"err_us":110}
```

### 6.4 Ping round-trip

```json
{"seq":2005,"resp":0,"ping":1}
```

Expected response:

```json
{"msg_type":"pong","seq":2005}
```
