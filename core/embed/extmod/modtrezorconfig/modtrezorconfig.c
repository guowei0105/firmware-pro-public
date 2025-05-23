/*
 * This file is part of the Trezor project, https://trezor.io/
 *
 * Copyright (c) SatoshiLabs
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include <string.h>

#include "py/mphal.h"
#include "py/objstr.h"
#include "py/runtime.h"

#if MICROPY_PY_TREZORCONFIG

#include "embed/extmod/trezorobj.h"

#include "common.h"
#include "memzero.h"
#include "storage.h"

#ifndef TREZOR_EMULATOR
#include "bip39.h"
#include "device.h"
#include "display.h"
#include "emmc.h"
#include "fpsensor_platform.h"
#include "mini_printf.h"
#include "se_thd89.h"

#define MAX_MNEMONIC_LEN 240

#endif

typedef struct {
  bool hal_pin_initialized;
  bool has_pin;
  bool pin_unlocked_initialized;
  bool pin_unlocked;
  bool fp_unlocked_initialized;
  bool fp_unlocked;
} pin_state_t;

static pin_state_t pin_state = {0};

static secbool wrapped_ui_wait_callback(uint32_t wait, uint32_t progress,
                                        const char *message) {
  if (mp_obj_is_callable(MP_STATE_VM(trezorconfig_ui_wait_callback))) {
    mp_obj_t args[3] = {0};
    args[0] = mp_obj_new_int(wait);
    args[1] = mp_obj_new_int(progress);
    args[2] = mp_obj_new_str(message, strlen(message));
    if (mp_call_function_n_kw(MP_STATE_VM(trezorconfig_ui_wait_callback), 3, 0,
                              args) == mp_const_true) {
      return sectrue;
    }
  }
  return secfalse;
}

#ifdef TREZOR_EMULATOR
#error "Emulator not support SE_THD89"
#endif

/// def init(
///    ui_wait_callback: Callable[[int, int, str], bool] | None = None
/// ) -> None:
///     """
///     Initializes the storage.  Must be called before any other method is
///     called from this module!
///     """
STATIC mp_obj_t mod_trezorconfig_init(size_t n_args, const mp_obj_t *args) {
  if (n_args > 0) {
    MP_STATE_VM(trezorconfig_ui_wait_callback) = args[0];
    se_set_ui_callback(wrapped_ui_wait_callback);
  }
  return mp_const_none;
}

STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_init_obj, 0, 1,
                                           mod_trezorconfig_init);

/// def is_initialized() -> bool:
///     """
///     Returns True if device is initialized.
///     """
STATIC mp_obj_t mod_trezorconfig_is_initialized(void) {
  if (sectrue != se_isInitialized()) {
    return mp_const_false;
  }

  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_is_initialized_obj,
                                 mod_trezorconfig_is_initialized);

/// def unlock(pin: str, ext_salt: bytes | None, pin_use_type: int = 0)
/// -> tuple[bool, int]:
///     """
///     Attempts to unlock the storage with the given PIN and external salt.
///     Returns True on success, False on failure.
///     """
STATIC mp_obj_t mod_trezorconfig_unlock(size_t n_args, const mp_obj_t *args) {
  mp_buffer_info_t pin_b = {0};
  mp_get_buffer_raise(args[0], &pin_b, MP_BUFFER_READ);

  mp_buffer_info_t ext_salt_b = {0};
  ext_salt_b.buf = NULL;
  if (n_args > 1 && args[1] != mp_const_none) {
    mp_get_buffer_raise(args[1], &ext_salt_b, MP_BUFFER_READ);
    if (ext_salt_b.len != EXTERNAL_SALT_SIZE)
      mp_raise_msg(&mp_type_ValueError, "Invalid length of external salt.");
  }

  pin_type_t pin_use_type = PIN_TYPE_USER;

  if (n_args > 2) {
    pin_use_type = mp_obj_get_int(args[2]);
  }

  // display_clear();
  // display_loader_ex(0, false, 0, 0xFFFF, 0x0000, NULL, 0, 0);
  secbool ret = secfalse;

  // verify se pin first when not in emulator
  ret = se_verifyPin(pin_b.buf, pin_use_type);
  if (ret != sectrue) {
    if (!pin_state.pin_unlocked_initialized) {
      pin_state.pin_unlocked = false;
      pin_state.pin_unlocked_initialized = true;
    }
    
    // 创建并返回一个元组 (False, 0)
    mp_obj_t tuple[2] = {mp_const_false, mp_obj_new_int(0)};
    return mp_obj_new_tuple(2, tuple);
  }

  pin_result_t pin_type = se_get_pin_result_type();

  fpsensor_data_init();
  pin_state.pin_unlocked = true;
  pin_state.pin_unlocked_initialized = true;
  pin_state.fp_unlocked = true;
  pin_state.fp_unlocked_initialized = true;

  mp_obj_tuple_t *tuple = MP_OBJ_TO_PTR(mp_obj_new_tuple(2, NULL));
  tuple->items[0] = mp_const_true;
  tuple->items[1] = mp_obj_new_int(pin_type);
  return MP_OBJ_FROM_PTR(tuple);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_unlock_obj, 2, 3,
                                           mod_trezorconfig_unlock);

/// def check_pin(pin: str, ext_salt: bytes | None, pin_use_type: int = 0) ->
/// bool:
///     """
///     Check the given PIN with the given external salt.
///     Returns True on success, False on failure.
///     """
STATIC mp_obj_t mod_trezorconfig_check_pin(size_t n_args,
                                           const mp_obj_t *args) {
  return mod_trezorconfig_unlock(n_args, args);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_check_pin_obj, 2, 3,
                                           mod_trezorconfig_check_pin);

/// def lock() -> None:
///     """
///     Locks the storage.
///     """
STATIC mp_obj_t mod_trezorconfig_lock(void) {
  se_clearSecsta();
  pin_state.pin_unlocked = false;
  pin_state.pin_unlocked = false;
  return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_lock_obj,
                                 mod_trezorconfig_lock);

/// def is_unlocked() -> bool:
///     """
///     Returns True if storage is unlocked, False otherwise.
///     """
STATIC mp_obj_t mod_trezorconfig_is_unlocked(void) {
  if (!pin_state.pin_unlocked_initialized) {
    pin_state.pin_unlocked = se_getSecsta() ? true : false;
    pin_state.pin_unlocked_initialized = true;
  }
  if (!pin_state.pin_unlocked) {
    return mp_const_false;
  }
  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_is_unlocked_obj,
                                 mod_trezorconfig_is_unlocked);

/// def has_pin() -> bool:
///     """
///     Returns True if storage has a configured PIN, False otherwise.
///     """
STATIC mp_obj_t mod_trezorconfig_has_pin(void) {
  if (!pin_state.hal_pin_initialized) {
    pin_state.has_pin = se_hasPin() ? true : false;
    pin_state.hal_pin_initialized = true;
  }
  if (!pin_state.has_pin) {
    return mp_const_false;
  }

  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_has_pin_obj,
                                 mod_trezorconfig_has_pin);

/// def get_pin_rem() -> int:
///     """
///     Returns the number of remaining PIN entry attempts.
///     """
STATIC mp_obj_t mod_trezorconfig_get_pin_rem(void) {
  uint8_t retry_cnts = 0;
  if (sectrue != se_getRetryTimes(&retry_cnts)) {
    mp_raise_msg(&mp_type_RuntimeError, "Failed to get pin retry times.");
  }

  printf("PIN retry count remaining: %d\n", retry_cnts);


  return mp_obj_new_int_from_uint(retry_cnts);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_get_pin_rem_obj,
                                 mod_trezorconfig_get_pin_rem);

/// def change_pin(
///     oldpin: str,
///     newpin: str,
///     old_ext_salt: bytes | None,
///     new_ext_salt: bytes | None,
/// ) -> bool:
///     """
///     Change PIN and external salt. Returns True on success, False on failure.
///     """
STATIC mp_obj_t mod_trezorconfig_change_pin(size_t n_args,
                                            const mp_obj_t *args) {
  mp_buffer_info_t oldpin = {0};
  mp_get_buffer_raise(args[0], &oldpin, MP_BUFFER_READ);

  mp_buffer_info_t newpin = {0};
  mp_get_buffer_raise(args[1], &newpin, MP_BUFFER_READ);

  if (!pin_state.hal_pin_initialized) {
    pin_state.has_pin = se_hasPin() ? true : false;
    pin_state.hal_pin_initialized = true;
  }

  if (!pin_state.has_pin) {
    if (sectrue != se_setPin(newpin.buf)) {
      return mp_const_false;
    }
    pin_state.has_pin = true;

  } else {
    if (sectrue != se_changePin(oldpin.buf, newpin.buf)) {
      return mp_const_false;
    }
  }
  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_change_pin_obj, 4,
                                           4, mod_trezorconfig_change_pin);

/// def ensure_not_wipe_code(pin: str) -> None:
///     """
///     Wipes the device if the entered PIN is the wipe code.
///     """
STATIC mp_obj_t mod_trezorconfig_ensure_not_wipe_code(mp_obj_t pin) {
  mp_buffer_info_t pin_b = {0};
  mp_get_buffer_raise(pin, &pin_b, MP_BUFFER_READ);
  // storage_ensure_not_wipe_code(pin_b.buf, pin_b.len);
  return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_1(mod_trezorconfig_ensure_not_wipe_code_obj,
                                 mod_trezorconfig_ensure_not_wipe_code);

/// def has_wipe_code() -> bool:
///     """
///     Returns True if storage has a configured wipe code, False otherwise.
///     """
STATIC mp_obj_t mod_trezorconfig_has_wipe_code(void) {
  if (sectrue != se_hasWipeCode()) {
    return mp_const_false;
  }

  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_has_wipe_code_obj,
                                 mod_trezorconfig_has_wipe_code);

/// def change_wipe_code(
///     pin: str,
///     ext_salt: bytes | None,
///     wipe_code: str,
/// ) -> bool:
///     """
///     Change wipe code. Returns True on success, False on failure.
///     """
STATIC mp_obj_t mod_trezorconfig_change_wipe_code(size_t n_args,
                                                  const mp_obj_t *args) {
  mp_buffer_info_t pin_b = {0};
  mp_get_buffer_raise(args[0], &pin_b, MP_BUFFER_READ);

  mp_buffer_info_t wipe_code_b = {0};
  mp_get_buffer_raise(args[2], &wipe_code_b, MP_BUFFER_READ);

  if (pin_b.len == wipe_code_b.len) {
    if (memcmp(pin_b.buf, wipe_code_b.buf, pin_b.len) == 0) {
      mp_raise_msg(&mp_type_ValueError,
                   "The new PIN must be different from your wipe code.");
    }
  }

  if (sectrue != se_changeWipeCode(pin_b.buf, wipe_code_b.buf)) {
    return mp_const_false;
  }
  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(
    mod_trezorconfig_change_wipe_code_obj, 3, 3,
    mod_trezorconfig_change_wipe_code);

/// def get_needs_backup() -> bool:
///     """
///     Returns needs_backup.
///     """
STATIC mp_obj_t mod_trezorconfig_get_needs_backup(void) {
  bool needs_backup = false;
  if (sectrue != se_get_needs_backup(&needs_backup)) {
    return mp_const_false;
  }

  return needs_backup ? mp_const_true : mp_const_false;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_get_needs_backup_obj,
                                 mod_trezorconfig_get_needs_backup);

/// def set_needs_backup(needs_backup: bool = False) -> bool:
///     """
///     Set needs_backup.
///     """
STATIC mp_obj_t mod_trezorconfig_set_needs_backup(mp_obj_t needs_backup) {
  bool needs_backup_b = mp_obj_is_true(needs_backup);

  if (sectrue != se_set_needs_backup(needs_backup_b)) {
    return mp_const_false;
  }

  return mp_const_true;
}

STATIC MP_DEFINE_CONST_FUN_OBJ_1(mod_trezorconfig_set_needs_backup_obj,
                                 mod_trezorconfig_set_needs_backup);

/// def get_val_len(app: int, key: int, public: bool = False) -> int:
///     """
///     Gets the length of the value of the given key for the given app (or None
///     if not set). Raises a RuntimeError if decryption or authentication of
///     the stored value fails.
///     """
STATIC mp_obj_t mod_trezorconfig_get_val_len(size_t n_args,
                                             const mp_obj_t *args) {
  uint32_t key = trezor_obj_get_uint(args[1]);

  bool is_private = key & (1 << 31);

  secbool (*reader)(uint16_t, void *, uint16_t) =
      is_private ? se_get_private_region : se_get_public_region;

  // key is position
  key &= ~(1 << 31);

  uint8_t temp[4] = {0};
  if (sectrue != reader(key, temp, 3)) {
    return mp_const_none;
  }
  // has flag
  if (temp[0] != 1) {
    return mp_const_none;
  }

  uint16_t len = 0;
  len = (temp[1] << 8) + temp[2];

  return mp_obj_new_int_from_uint(len);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_get_val_len_obj, 2,
                                           3, mod_trezorconfig_get_val_len);

/// def get(app: int, key: int, public: bool = False) -> bytes | None:
///     """
///     Gets the value of the given key for the given app (or None if not set).
///     Raises a RuntimeError if decryption or authentication of the stored
///     value fails.
///     """
STATIC mp_obj_t mod_trezorconfig_get(size_t n_args, const mp_obj_t *args) {
  uint8_t app = trezor_obj_get_uint8(args[0]);
  // webauthn resident credentials, FIDO2
  if (app == 4) {
    uint32_t index = trezor_obj_get_uint(args[1]);
    uint16_t len = sizeof(CTAP_credential_id_storage) -
                   FIDO2_RESIDENT_CREDENTIALS_HEADER_LEN;
    CTAP_credential_id_storage cred_id = {0};

    if (!se_get_fido2_resident_credentials(index, cred_id.rp_id_hash, &len)) {
      return mp_const_none;
    }
    return mp_obj_new_bytes(cred_id.rp_id_hash, len);
  }

  uint32_t key = trezor_obj_get_uint(args[1]);

  bool is_private = key & (1 << 31);

  secbool (*reader)(uint16_t, void *, uint16_t) =
      is_private ? se_get_private_region : se_get_public_region;

  // key is position
  key &= ~(1 << 31);

  uint8_t temp[4] = {0};
  if (sectrue != reader(key, temp, 3)) {
    return mp_const_none;
  }
  // has flag
  if (temp[0] != 1) {
    return mp_const_none;
  }

  uint16_t len = 0;
  len = (temp[1] << 8) + temp[2];

  if (len == 0) {
    return mp_const_empty_bytes;
  }
  vstr_t vstr = {0};
  vstr_init_len(&vstr, len);
  vstr.len = len;
  if (sectrue != reader(key + 3, vstr.buf, vstr.len)) {
    vstr_clear(&vstr);
    mp_raise_msg(&mp_type_RuntimeError, "Failed to get value from storage.");
  }
  return mp_obj_new_str_from_vstr(&mp_type_bytes, &vstr);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_get_obj, 2, 3,
                                           mod_trezorconfig_get);

/// def set(app: int, key: int, value: bytes, public: bool = False) -> None:
///     """
///     Sets a value of given key for given app.
///     """
STATIC mp_obj_t mod_trezorconfig_set(size_t n_args, const mp_obj_t *args) {
  uint8_t app = trezor_obj_get_uint8(args[0]);
  // webauthn resident credentials, FIDO2
  if (app == 4) {
    uint32_t index = trezor_obj_get_uint(args[1]);

    mp_buffer_info_t cred_id;
    mp_get_buffer_raise(args[2], &cred_id, MP_BUFFER_READ);
    if (cred_id.len > sizeof(CTAP_credential_id_storage) -
                          FIDO2_RESIDENT_CREDENTIALS_HEADER_LEN) {
      mp_raise_msg(&mp_type_RuntimeError, "Credential ID too long");
    }
    if (!se_set_fido2_resident_credentials(index, cred_id.buf, cred_id.len)) {
      mp_raise_msg(&mp_type_RuntimeError, "Could not save value");
    }
    return mp_const_none;
  }

  uint32_t key = trezor_obj_get_uint(args[1]);
  bool is_private = key & (1 << 31);
  secbool (*writer)(uint16_t, const void *, uint16_t) =
      is_private ? se_set_private_region : se_set_public_region;

  mp_buffer_info_t value;
  mp_get_buffer_raise(args[2], &value, MP_BUFFER_READ);
  if (value.len > UINT16_MAX) {
    mp_raise_msg(&mp_type_RuntimeError, "Could not save value");
  }
  uint8_t temp[4] = {0};
  temp[0] = 1;
  temp[1] = (value.len >> 8) & 0xff;
  temp[2] = value.len & 0xff;

  if (sectrue != writer(key, temp, 3)) {
    mp_raise_msg(&mp_type_RuntimeError, "Could not save value");
  }
  if (sectrue != writer(key + 3, value.buf, value.len)) {
    mp_raise_msg(&mp_type_RuntimeError, "Could not save value");
  }
  return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_set_obj, 3, 4,
                                           mod_trezorconfig_set);

/// def delete(
///     app: int, key: int, public: bool = False, writable_locked: bool = False
/// ) -> bool:
///     """
///     Deletes the given key of the given app.
///     """
STATIC mp_obj_t mod_trezorconfig_delete(size_t n_args, const mp_obj_t *args) {
  uint8_t app = trezor_obj_get_uint8(args[0]);
  // webauthn resident credentials, FIDO2
  if (app == 4) {
    uint32_t index = trezor_obj_get_uint(args[1]);
    if (!se_delete_fido2_resident_credentials(index)) {
      mp_raise_msg(&mp_type_RuntimeError, "Could not delete value");
    }
    return mp_const_true;
  }

  uint32_t key = trezor_obj_get_uint(args[1]);
  bool is_private = key & (1 << 31);
  secbool (*writer)(uint16_t, const void *, uint16_t) =
      is_private ? se_set_private_region : se_set_public_region;

  uint8_t temp[1] = {0};
  temp[0] = 0;
  if (sectrue != writer(key, temp, 1)) {
    mp_raise_msg(&mp_type_RuntimeError, "Could not delete key");
  }
  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_delete_obj, 2, 4,
                                           mod_trezorconfig_delete);

/// def set_counter(
///     app: int, key: int, count: int, writable_locked: bool = False
/// ) -> None:
///     """
///     Sets the given key of the given app as a counter with the given value.
///     """
STATIC mp_obj_t mod_trezorconfig_set_counter(size_t n_args,
                                             const mp_obj_t *args) {
  mp_uint_t count = trezor_obj_get_uint(args[2]);
  if (count > UINT32_MAX || !se_set_u2f_counter(count)) {
    mp_raise_msg(&mp_type_RuntimeError, "Failed to set u2f counter.");
  }
  return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_set_counter_obj, 3,
                                           4, mod_trezorconfig_set_counter);

/// def next_counter(
///    app: int, key: int, writable_locked: bool = False,
/// ) -> int:
///     """
///     Increments the counter stored under the given key of the given app and
///     returns the new value.
///     """
STATIC mp_obj_t mod_trezorconfig_next_counter(size_t n_args,
                                              const mp_obj_t *args) {
  uint32_t count = 0;
  if (sectrue != se_get_u2f_counter(&count)) {
    mp_raise_msg(&mp_type_RuntimeError, "Failed to get u2f counter.");
  }
  return mp_obj_new_int_from_uint(count);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_trezorconfig_next_counter_obj, 2,
                                           3, mod_trezorconfig_next_counter);

/// def wipe() -> None:
///     """
///     Erases the whole config. Use with caution!
///     """
STATIC mp_obj_t mod_trezorconfig_wipe(void) {
  fpsensor_data_cache_clear();
  if (sectrue != se_reset_storage()) {
    mp_raise_msg(&mp_type_RuntimeError, "Failed to reset storage.");
  }
  return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_wipe_obj,
                                 mod_trezorconfig_wipe);

#ifndef TREZOR_EMULATOR
STATIC mp_obj_t mod_trezorconfig_se_import_mnemonic(mp_obj_t mnemonic) {
  mp_buffer_info_t mnemo = {0};
  mp_get_buffer_raise(mnemonic, &mnemo, MP_BUFFER_READ);

  if (sectrue != se_set_mnemonic(mnemo.buf, mnemo.len)) {
    return mp_const_false;
  }

  return mp_const_true;
}

STATIC MP_DEFINE_CONST_FUN_OBJ_1(mod_trezorconfig_se_import_mnemonic_obj,
                                 mod_trezorconfig_se_import_mnemonic);

/// def se_export_mnemonic() -> bytes:
///     """
///     Export mnemonic from SE.
///     """
STATIC mp_obj_t mod_trezorconfig_se_export_mnemonic(void) {
  char mnemonic[MAX_MNEMONIC_LEN + 1];

  if (sectrue != se_exportMnemonic(mnemonic, sizeof(mnemonic))) {
    mp_raise_ValueError("Get se mnemonic");
  }

  mp_obj_t res = mp_obj_new_str_copy(&mp_type_bytes, (const uint8_t *)mnemonic,
                                     strlen(mnemonic));
  memzero(mnemonic, sizeof(mnemonic));
  return res;
}

STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_se_export_mnemonic_obj,
                                 mod_trezorconfig_se_export_mnemonic);

/// def fingerprint_is_unlocked() -> bool:
///     """
///     Returns True if fingerprint is unlocked, False otherwise.
///     """
STATIC mp_obj_t mod_trezorcrypto_se_fingerprint_is_unlocked(void) {
  if (!pin_state.fp_unlocked_initialized) {
    pin_state.fp_unlocked = se_fingerprint_state() ? true : false;
    pin_state.fp_unlocked_initialized = true;
  }
  if (!pin_state.fp_unlocked) {
    return mp_const_false;
  }
  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(
    mod_trezorcrypto_se_fingerprint_is_unlocked_obj,
    mod_trezorcrypto_se_fingerprint_is_unlocked);

/// def fingerprint_lock() -> bool:
///     """
///     fingerprint lock.
///     """
STATIC mp_obj_t mod_trezorcrypto_se_fingerprint_lock(void) {
  if (sectrue != se_fingerprint_lock()) {
    return mp_const_false;
  }
  pin_state.fp_unlocked = false;
  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorcrypto_se_fingerprint_lock_obj,
                                 mod_trezorcrypto_se_fingerprint_lock);

/// def fingerprint_unlock() -> bool:
///     """
///     fingerprint unlock.
///     """
STATIC mp_obj_t mod_trezorcrypto_se_fingerprint_unlock(void) {
  if (sectrue != se_fingerprint_unlock()) {
    pin_state.fp_unlocked = false;
    pin_state.fp_unlocked_initialized = true;
    return mp_const_false;
  }
  pin_state.fp_unlocked = true;
  pin_state.fp_unlocked_initialized = true;
  return mp_const_true;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorcrypto_se_fingerprint_unlock_obj,
                                 mod_trezorcrypto_se_fingerprint_unlock);

#endif

#ifndef TREZOR_EMULATOR
/// def get_serial() -> str:
///     """
///     get device serial
///     """
STATIC mp_obj_t mod_trezorconfig_get_serial(void) {
  mp_obj_t res;

  char *dev_serial;
  if (device_get_serial(&dev_serial)) {
    res = mp_obj_new_str_copy(&mp_type_str, (const uint8_t *)dev_serial,
                              strlen(dev_serial));
  } else {
    res = mp_obj_new_str_copy(&mp_type_str, (const uint8_t *)"NULL",
                              strlen("NULL"));
  }

  return res;
}

STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_get_serial_obj,
                                 mod_trezorconfig_get_serial);

/// def get_capacity() -> str:
///     """
///     get emmc capacity
///     """
STATIC mp_obj_t mod_trezorconfig_get_capacity(void) {
  char cap_info[32] = {0};
  uint64_t cap = emmc_get_capacity_in_bytes();

  if (cap > (1024 * 1024 * 1024)) {
    mini_snprintf(cap_info, sizeof(cap_info), "%d GB",
                  (unsigned int)(cap >> 30));
  } else if (cap > (1024 * 1024)) {
    mini_snprintf(cap_info, sizeof(cap_info), "%d MB",
                  (unsigned int)(cap >> 20));
  } else {
    mini_snprintf(cap_info, sizeof(cap_info), "%d Bytes", (unsigned int)cap);
  }
  return mp_obj_new_str_copy(&mp_type_str, (const uint8_t *)cap_info,
                             strlen(cap_info));
}

STATIC MP_DEFINE_CONST_FUN_OBJ_0(mod_trezorconfig_get_capacity_obj,
                                 mod_trezorconfig_get_capacity);
#endif

STATIC const mp_rom_map_elem_t mp_module_trezorconfig_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_trezorconfig)},
    {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&mod_trezorconfig_init_obj)},
    {MP_ROM_QSTR(MP_QSTR_check_pin),
     MP_ROM_PTR(&mod_trezorconfig_check_pin_obj)},
    {MP_ROM_QSTR(MP_QSTR_unlock), MP_ROM_PTR(&mod_trezorconfig_unlock_obj)},
    {MP_ROM_QSTR(MP_QSTR_lock), MP_ROM_PTR(&mod_trezorconfig_lock_obj)},
    {MP_ROM_QSTR(MP_QSTR_is_unlocked),
     MP_ROM_PTR(&mod_trezorconfig_is_unlocked_obj)},
    {MP_ROM_QSTR(MP_QSTR_has_pin), MP_ROM_PTR(&mod_trezorconfig_has_pin_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_pin_rem),
     MP_ROM_PTR(&mod_trezorconfig_get_pin_rem_obj)},
    {MP_ROM_QSTR(MP_QSTR_change_pin),
     MP_ROM_PTR(&mod_trezorconfig_change_pin_obj)},
    {MP_ROM_QSTR(MP_QSTR_ensure_not_wipe_code),
     MP_ROM_PTR(&mod_trezorconfig_ensure_not_wipe_code_obj)},
    {MP_ROM_QSTR(MP_QSTR_has_wipe_code),
     MP_ROM_PTR(&mod_trezorconfig_has_wipe_code_obj)},
    {MP_ROM_QSTR(MP_QSTR_change_wipe_code),
     MP_ROM_PTR(&mod_trezorconfig_change_wipe_code_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_val_len),
     MP_ROM_PTR(&mod_trezorconfig_get_val_len_obj)},
    {MP_ROM_QSTR(MP_QSTR_get), MP_ROM_PTR(&mod_trezorconfig_get_obj)},
    {MP_ROM_QSTR(MP_QSTR_set), MP_ROM_PTR(&mod_trezorconfig_set_obj)},
    {MP_ROM_QSTR(MP_QSTR_delete), MP_ROM_PTR(&mod_trezorconfig_delete_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_counter),
     MP_ROM_PTR(&mod_trezorconfig_set_counter_obj)},
    {MP_ROM_QSTR(MP_QSTR_next_counter),
     MP_ROM_PTR(&mod_trezorconfig_next_counter_obj)},
    {MP_ROM_QSTR(MP_QSTR_wipe), MP_ROM_PTR(&mod_trezorconfig_wipe_obj)},
#ifndef TREZOR_EMULATOR
    {MP_ROM_QSTR(MP_QSTR_se_import_mnemonic),
     MP_ROM_PTR(&mod_trezorconfig_se_import_mnemonic_obj)},
    {MP_ROM_QSTR(MP_QSTR_se_export_mnemonic),
     MP_ROM_PTR(&mod_trezorconfig_se_export_mnemonic_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_serial),
     MP_ROM_PTR(&mod_trezorconfig_get_serial_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_capacity),
     MP_ROM_PTR(&mod_trezorconfig_get_capacity_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_needs_backup),
     MP_ROM_PTR(&mod_trezorconfig_get_needs_backup_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_needs_backup),
     MP_ROM_PTR(&mod_trezorconfig_set_needs_backup_obj)},
    {MP_ROM_QSTR(MP_QSTR_fingerprint_is_unlocked),
     MP_ROM_PTR(&mod_trezorcrypto_se_fingerprint_is_unlocked_obj)},
    {MP_ROM_QSTR(MP_QSTR_fingerprint_lock),
     MP_ROM_PTR(&mod_trezorcrypto_se_fingerprint_lock_obj)},
    {MP_ROM_QSTR(MP_QSTR_fingerprint_unlock),
     MP_ROM_PTR(&mod_trezorcrypto_se_fingerprint_unlock_obj)},
#endif
#if USE_THD89
    {MP_ROM_QSTR(MP_QSTR_is_initialized),
     MP_ROM_PTR(&mod_trezorconfig_is_initialized_obj)},

#endif
};
STATIC MP_DEFINE_CONST_DICT(mp_module_trezorconfig_globals,
                            mp_module_trezorconfig_globals_table);

const mp_obj_module_t mp_module_trezorconfig = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&mp_module_trezorconfig_globals,
};

MP_REGISTER_MODULE(MP_QSTR_trezorconfig, mp_module_trezorconfig,
                   MICROPY_PY_TREZORCONFIG);

#endif  // MICROPY_PY_TREZORCONFIG
