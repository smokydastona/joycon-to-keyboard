#pragma once

#include <stdbool.h>
#include <stdint.h>

/*
 * Binary Config Block Protocol
 * ============================
 * Fast binary config push over CDC serial, bypassing JSON overhead.
 *
 * Frame format (sent from helper-app over CDC):
 *   0xCB <block_type:u8> <slot:u8> <len:u16-LE> <payload...> <crc16:u16-LE>
 *
 * Block types:
 *   0x01  MAPPING_ENTRY   - Single mapping for one key_id
 *   0x02  MACRO_DEF       - Complete macro definition
 *   0x03  LAYER_DEF       - Complete layer definition
 *   0x04  CHORD_DEF       - Complete chord definition
 *   0x05  STICK_CONFIG    - Stick + deadzone + sensitivity config
 *   0x06  ZONE_DEF        - Zone-based mapping (Phase 3)
 *   0x07  ACTIVATOR_DEF   - Activator chain definition (Phase 3)
 *   0x08  GYRO_CONFIG     - Gyro-to-mouse configuration (Phase 5)
 *   0x10  PROFILE_BEGIN   - Start atomic profile push (clears slot)
 *   0x11  PROFILE_END     - Commit atomic profile push
 *   0x12  PROFILE_ABORT   - Abort and rollback
 *   0xFE  BULK_JSON       - Fallback: raw JSON profile (compatibility)
 *
 * Response (device → host, NDJSON):
 *   {"rsp":"config_block","ok":true,"type":1,"seq":0}
 *   {"rsp":"config_block","ok":false,"error":"crc_mismatch"}
 *
 * CRC16: CRC-CCITT (xmodem) over block_type + slot + len + payload.
 */

#define CONFIG_BLOCK_MARKER 0xCB

// Block type IDs
#define CFG_BLOCK_MAPPING       0x01
#define CFG_BLOCK_MACRO         0x02
#define CFG_BLOCK_LAYER         0x03
#define CFG_BLOCK_CHORD         0x04
#define CFG_BLOCK_STICK         0x05
#define CFG_BLOCK_ZONE          0x06
#define CFG_BLOCK_ACTIVATOR     0x07
#define CFG_BLOCK_GYRO          0x08
#define CFG_BLOCK_PROFILE_BEGIN 0x10
#define CFG_BLOCK_PROFILE_END   0x11
#define CFG_BLOCK_PROFILE_ABORT 0x12
#define CFG_BLOCK_BULK_JSON     0xFE

// Mapping entry binary format (for CFG_BLOCK_MAPPING):
//   key_id:u8, mode:u8, <mode-specific payload>
//
// Mode-specific payloads:
//   MAP_DISABLED(1):        (no additional data)
//   MAP_REMAP(2):           remap_to:u8
//   MAP_REMAP_HID(4):       hid_mod:u8, hid_keycode:u8
//   MAP_MACRO(3):           macro_index:u8
//   MAP_DOUBLE_TAP(5):      s_mod:u8,s_kc:u8,d_mod:u8,d_kc:u8,timeout:u16-LE
//   MAP_TURBO(6):           mod:u8,kc:u8,delay_ms:u16-LE
//   MAP_STICKY_MOD(7):      mod:u8,kc:u8
//   MAP_TAP_HOLD(8):        tap_mod:u8,tap_kc:u8,hold_mod:u8,hold_kc:u8,hold_ms:u16-LE
//   MAP_ONESHOT_MOD(9):     mod:u8,kc:u8
//   MAP_AUTO_SHIFT(10):     n_mod:u8,n_kc:u8,s_mod:u8,s_kc:u8,hold_ms:u16-LE
//   MAP_MOUSE_BUTTON(11):   button:u8
//   MAP_SEQUENTIAL(12):     count:u8, [mod:u8,kc:u8] * count
//   MAP_LEADER(13):         (no additional data)
//   MAP_PROFILE_SWITCH(14): slot:u8
//   MAP_ZONE(15):           zone_index:u8
//   MAP_ACTIVATOR(16):      activator_index:u8

// Stick config binary format (for CFG_BLOCK_STICK):
//   right_stick_mode:u8, mouse_sensitivity:u16-LE,
//   sprint_enabled:u8, sprint_threshold:u8,
//   sprint_key_mod:u8, sprint_key_kc:u8,
//   curve_type:u8, curve_exp_x100:u8,
//   socd_mode:u8,
//   rapid_trigger_act:u8, rapid_trigger_deact:u8,
//   deadzone_inner:u16-LE (0..4096), deadzone_outer:u16-LE (0..4096)

// Zone definition binary format (for CFG_BLOCK_ZONE):
//   zone_index:u8, input_source:u8 (0=lstick, 1=rstick, 2=ltrigger, 3=rtrigger),
//   shape:u8 (0=radial, 1=sector, 2=box),
//   inner_radius:u16-LE (0..4096), outer_radius:u16-LE (0..4096),
//   angle_start:u16-LE (degrees*10, 0..3600),
//   angle_end:u16-LE (degrees*10, 0..3600),
//   action_mode:u8, <action payload per mode>

// Activator definition binary format (for CFG_BLOCK_ACTIVATOR):
//   activator_index:u8, type:u8
//     0=press, 1=release, 2=double_press, 3=long_press,
//     4=chord(multi-key), 5=turbo_hold
//   key_id:u8,
//   param1:u16-LE (timeout/delay depending on type),
//   action_mode:u8, <action payload per mode>

// Gyro config binary format (for CFG_BLOCK_GYRO):
//   enabled:u8, mode:u8 (0=off, 1=mouse, 2=flick_stick),
//   sensitivity_x:u16-LE, sensitivity_y:u16-LE,
//   deadzone:u16-LE, accel_type:u8 (0=none, 1=linear, 2=power),
//   accel_param:u16-LE (x100),
//   invert_x:u8, invert_y:u8,
//   activation_key_id:u8 (0=always, >0=hold-to-enable)

// Initialize the config block processor.
void config_block_init(void);

// Feed raw bytes from CDC serial. Returns number consumed.
// Interleaves with NDJSON: detects 0xCB marker to switch to binary mode.
size_t config_block_feed(const uint8_t *data, size_t len);

// Check if we're currently in binary receive mode.
bool config_block_receiving(void);

// CRC16-CCITT (xmodem polynomial 0x1021, init 0x0000).
uint16_t config_block_crc16(const uint8_t *data, size_t len);
