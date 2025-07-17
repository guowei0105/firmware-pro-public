from typing import TYPE_CHECKING

import storage.cache
import storage.device
from trezor import config, loop, protobuf, ui, utils, wire, workflow
from trezor.enums import MessageType
from trezor.messages import Success, UnlockPath

from . import workflow_handlers

if TYPE_CHECKING:
    from trezor.messages import (
        Features,
        Initialize,
        EndSession,
        GetFeatures,
        Cancel,
        LockDevice,
        Ping,
        DoPreauthorized,
        CancelAuthorization,
        SetBusy,
        OnekeyGetFeatures,
        OnekeyFeatures,
    )


def get_vendor():
    return "trezor.io" if storage.device.is_trezor_compatible() else "onekey.so"


FW_VENDOR_BTC_ONLY = "OneKey Bitcoin-only"


def busy_expiry_ms() -> int:
    """
    Returns the time left until the busy state expires or 0 if the device is not in the busy state.
    """

    busy_deadline_ms = storage.cache.get_int(storage.cache.APP_COMMON_BUSY_DEADLINE_MS)
    if busy_deadline_ms is None:
        return 0

    import utime

    expiry_ms = utime.ticks_diff(busy_deadline_ms, utime.ticks_ms())
    return expiry_ms if expiry_ms > 0 else 0


def get_features() -> Features:
    import storage.recovery
    import storage.sd_salt
    import storage  # workaround for https://github.com/microsoft/pyright/issues/2685

    from trezor import sdcard
    from trezor.enums import Capability, OneKeyDeviceType, OneKeySeType
    from trezor.messages import Features
    from trezor import uart
    from apps.common import mnemonic, safety_checks

    storage_serial_no = storage.device.get_serial()
    serial_no = storage_serial_no
    if serial_no[0:2] == "PR":
        serial_no = "TC" + serial_no[2:]
    f = Features(
        vendor=get_vendor(),
        language=storage.device.get_language(),
        major_version=utils.VERSION_MAJOR,
        minor_version=utils.VERSION_MINOR,
        patch_version=utils.VERSION_PATCH,
        onekey_version=utils.ONEKEY_VERSION,
        revision=utils.SCM_REVISION,
        model=utils.MODEL,
        device_id=storage.device.get_device_id(),
        label=storage.device.get_label(),
        pin_protection=config.has_pin(),
        unlocked=config.is_unlocked(),
        ble_name=uart.get_ble_name(),
        ble_ver=uart.get_ble_version(),
        ble_enable=storage.device.ble_enabled(),
        serial_no=serial_no,
        build_id=utils.BUILD_ID[-7:],
        bootloader_version=utils.boot_version(),
        boardloader_version=utils.board_version(),
        busy=busy_expiry_ms() > 0,
        onekey_device_type=OneKeyDeviceType.PRO,
        onekey_se_type=OneKeySeType.THD89,
        onekey_board_version=utils.board_version(),
        onekey_boot_version=utils.boot_version(),
        onekey_se01_version=storage.device.get_se01_version(),
        onekey_se02_version=storage.device.get_se02_version(),
        onekey_se03_version=storage.device.get_se03_version(),
        onekey_se04_version=storage.device.get_se04_version(),
        onekey_firmware_version=utils.ONEKEY_VERSION,
        onekey_serial_no=storage_serial_no,
        onekey_ble_name=uart.get_ble_name(),
        onekey_ble_version=uart.get_ble_version(),
    )

    if utils.BITCOIN_ONLY:
        f.capabilities = [
            Capability.Bitcoin,
            Capability.Crypto,
            Capability.Shamir,
            Capability.ShamirGroups,
        ]
        f.fw_vendor = FW_VENDOR_BTC_ONLY
    else:
        f.capabilities = [
            Capability.Bitcoin,
            Capability.Bitcoin_like,
            Capability.Binance,
            Capability.Cardano,
            Capability.Crypto,
            Capability.EOS,
            Capability.Ethereum,
            # Capability.Monero,
            Capability.NEM,
            Capability.Ripple,
            Capability.Stellar,
            Capability.Tezos,
            # Capability.U2F,
            # Capability.Shamir,
            # Capability.ShamirGroups,
        ]

    # Other models are not capable of PassphraseEntry
    if utils.MODEL in ("T",):
        f.capabilities.append(Capability.PassphraseEntry)

    f.sd_card_present = sdcard.is_present()
    f.initialized = storage.device.is_initialized()

    # private fields:
    if config.is_unlocked():
        # passphrase_protection is private, see #1807
        f.passphrase_protection = storage.device.is_passphrase_enabled()
        f.needs_backup = storage.device.needs_backup()
        f.unfinished_backup = storage.device.unfinished_backup()
        f.no_backup = storage.device.no_backup()
        f.flags = storage.device.get_flags()
        f.recovery_mode = False  # storage.recovery.is_in_progress()
        f.backup_type = mnemonic.get_type()
        f.sd_protection = storage.sd_salt.is_enabled()
        f.wipe_code_protection = config.has_wipe_code()
        f.passphrase_always_on_device = storage.device.get_passphrase_always_on_device()
        f.safety_checks = safety_checks.read_setting()
        f.auto_lock_delay_ms = storage.device.get_autolock_delay_ms()
        f.display_rotation = storage.device.get_rotation()
        f.experimental_features = storage.device.get_experimental_features()

    return f


def get_onekey_features() -> OnekeyFeatures:
    from trezor.enums import OneKeyDeviceType, OneKeySeType
    from trezor.messages import OnekeyFeatures
    from trezor import uart

    storage_serial_no = storage.device.get_serial()
    serial_no = storage_serial_no
    if serial_no[0:2] == "PR":
        serial_no = "TC" + serial_no[2:]
    f = OnekeyFeatures(
        onekey_device_type=OneKeyDeviceType.PRO,
        onekey_serial_no=storage_serial_no,
        onekey_se_type=OneKeySeType.THD89,
        onekey_board_version=utils.board_version(),
        onekey_board_hash=utils.board_hash(),
        onekey_board_build_id=utils.board_build_id(),
        onekey_boot_version=utils.boot_version(),
        onekey_boot_hash=utils.boot_hash(),
        onekey_boot_build_id=utils.boot_build_id(),
        onekey_firmware_version=utils.ONEKEY_VERSION,
        onekey_firmware_build_id=utils.BUILD_ID[-7:].decode(),
        onekey_firmware_hash=utils.onekey_firmware_hash(),
        onekey_ble_name=uart.get_ble_name(),
        onekey_ble_version=uart.get_ble_version(),
        onekey_ble_build_id=uart.get_ble_build_id(),
        onekey_ble_hash=uart.get_ble_hash(),
        onekey_se01_version=storage.device.get_se01_version(),
        onekey_se01_hash=storage.device.get_se01_hash(),
        onekey_se01_build_id=storage.device.get_se01_build_id(),
        onekey_se01_boot_version=storage.device.get_se01_boot_version(),
        onekey_se01_boot_hash=storage.device.get_se01_boot_hash(),
        onekey_se01_boot_build_id=storage.device.get_se01_boot_build_id(),
        onekey_se02_version=storage.device.get_se02_version(),
        onekey_se02_hash=storage.device.get_se02_hash(),
        onekey_se02_build_id=storage.device.get_se02_build_id(),
        onekey_se02_boot_version=storage.device.get_se02_boot_version(),
        onekey_se02_boot_hash=storage.device.get_se02_boot_hash(),
        onekey_se02_boot_build_id=storage.device.get_se02_boot_build_id(),
        onekey_se03_version=storage.device.get_se03_version(),
        onekey_se03_hash=storage.device.get_se03_hash(),
        onekey_se03_build_id=storage.device.get_se03_build_id(),
        onekey_se03_boot_version=storage.device.get_se03_boot_version(),
        onekey_se03_boot_hash=storage.device.get_se03_boot_hash(),
        onekey_se03_boot_build_id=storage.device.get_se03_boot_build_id(),
        onekey_se04_version=storage.device.get_se04_version(),
        onekey_se04_hash=storage.device.get_se04_hash(),
        onekey_se04_build_id=storage.device.get_se04_build_id(),
        onekey_se04_boot_version=storage.device.get_se04_boot_version(),
        onekey_se04_boot_hash=storage.device.get_se04_boot_hash(),
        onekey_se04_boot_build_id=storage.device.get_se04_boot_build_id(),
    )

    return f


async def handle_Initialize(
    ctx: wire.Context | wire.QRContext, msg: Initialize
) -> Features:
    session_id = storage.cache.start_session(msg.session_id)

    if not utils.BITCOIN_ONLY:
        if utils.USE_THD89:
            if msg.derive_cardano is not None and msg.derive_cardano:
                # THD89 is not capable of Cardano
                from trezor.crypto import se_thd89

                state = se_thd89.get_session_state()
                if state[0] & 0x80 and not state[0] & 0x40:
                    storage.cache.end_current_session()
                    session_id = storage.cache.start_session()

                storage.cache.SESSION_DIRIVE_CARDANO = True
            else:
                storage.cache.SESSION_DIRIVE_CARDANO = False

        else:
            derive_cardano = storage.cache.get(storage.cache.APP_COMMON_DERIVE_CARDANO)
            have_seed = storage.cache.is_set(storage.cache.APP_COMMON_SEED)

            if (
                have_seed
                and msg.derive_cardano is not None
                and msg.derive_cardano != bool(derive_cardano)
            ):
                # seed is already derived, and host wants to change derive_cardano setting
                # => create a new session
                storage.cache.end_current_session()
                session_id = storage.cache.start_session()
                have_seed = False

            if not have_seed:
                storage.cache.set(
                    storage.cache.APP_COMMON_DERIVE_CARDANO,
                    b"\x01" if msg.derive_cardano else b"",
                )

    features = get_features()
    features.session_id = session_id
    storage.cache.update_res_confirm_refresh()
    return features


async def handle_GetFeatures(ctx: wire.Context, msg: GetFeatures) -> Features:
    return get_features()


async def handle_OnekeyGetFeatures(
    ctx: wire.Context, msg: OnekeyGetFeatures
) -> OnekeyFeatures:
    return get_onekey_features()


async def handle_Cancel(ctx: wire.Context, msg: Cancel) -> Success:
    raise wire.ActionCancelled


async def handle_LockDevice(ctx: wire.Context, msg: LockDevice) -> Success:
    lock_device()
    return Success()


async def handle_SetBusy(ctx: wire.Context, msg: SetBusy) -> Success:
    if not storage.device.is_initialized():
        raise wire.NotInitialized("Device is not initialized")

    if msg.expiry_ms:
        import utime

        deadline = utime.ticks_add(utime.ticks_ms(), msg.expiry_ms)
        storage.cache.set_int(storage.cache.APP_COMMON_BUSY_DEADLINE_MS, deadline)
    else:
        storage.cache.delete(storage.cache.APP_COMMON_BUSY_DEADLINE_MS)
    set_homescreen()
    workflow.close_others()
    return Success()


async def handle_EndSession(ctx: wire.Context, msg: EndSession) -> Success:
    storage.cache.end_current_session()
    return Success()


async def handle_Ping(ctx: wire.Context, msg: Ping) -> Success:
    if msg.button_protection:
        from trezor.ui.layouts import confirm_action
        from trezor.enums import ButtonRequestType as B

        await confirm_action(ctx, "ping", "Confirm", "ping", br_code=B.ProtectCall)
    return Success(message=msg.message)


async def handle_DoPreauthorized(
    ctx: wire.Context, msg: DoPreauthorized
) -> protobuf.MessageType:
    from trezor.messages import PreauthorizedRequest
    from apps.common import authorization

    if not authorization.is_set():
        raise wire.ProcessError("No preauthorized operation")

    wire_types = authorization.get_wire_types()
    utils.ensure(bool(wire_types), "Unsupported preauthorization found")

    req = await ctx.call_any(PreauthorizedRequest(), *wire_types)

    assert req.MESSAGE_WIRE_TYPE is not None
    handler = workflow_handlers.find_registered_handler(
        ctx.iface, req.MESSAGE_WIRE_TYPE
    )
    if handler is None:
        return wire.unexpected_message()

    return await handler(ctx, req, authorization.get())  # type: ignore [Expected 2 positional arguments]


async def handle_UnlockPath(ctx: wire.Context, msg: UnlockPath) -> protobuf.MessageType:
    from trezor.crypto import hmac
    from trezor.messages import UnlockedPathRequest
    from trezor.ui.layouts import confirm_action
    from apps.common.paths import SLIP25_PURPOSE
    from apps.common.seed import Slip21Node, get_seed
    from apps.common.writers import write_uint32_le

    _KEYCHAIN_MAC_KEY_PATH = [b"TREZOR", b"Keychain MAC key"]

    # UnlockPath is relevant only for SLIP-25 paths.
    # Note: Currently we only allow unlocking the entire SLIP-25 purpose subtree instead of
    # per-coin or per-account unlocking in order to avoid UI complexity.
    if msg.address_n != [SLIP25_PURPOSE]:
        raise wire.DataError("Invalid path")

    seed = await get_seed(ctx)
    node = Slip21Node(seed)
    node.derive_path(_KEYCHAIN_MAC_KEY_PATH)
    mac = utils.HashWriter(hmac(hmac.SHA256, node.key()))
    for i in msg.address_n:
        write_uint32_le(mac, i)
    expected_mac = mac.get_digest()

    # Require confirmation to access SLIP25 paths unless already authorized.
    if msg.mac:
        if len(msg.mac) != len(expected_mac) or not utils.consteq(
            expected_mac, msg.mac
        ):
            raise wire.DataError("Invalid MAC")
    else:
        await confirm_action(
            ctx,
            "confirm_coinjoin_access",
            title="CoinJoin account",
            description="Do you want to allow access to your CoinJoin account?",
        )

    wire_types = (MessageType.GetAddress, MessageType.GetPublicKey, MessageType.SignTx)
    req = await ctx.call_any(UnlockedPathRequest(mac=expected_mac), *wire_types)

    assert req.MESSAGE_WIRE_TYPE in wire_types
    handler = workflow_handlers.find_registered_handler(
        ctx.iface, req.MESSAGE_WIRE_TYPE
    )
    assert handler is not None
    return await handler(ctx, req, msg)  # type: ignore [Expected 2 positional arguments]


async def handle_CancelAuthorization(
    ctx: wire.Context, msg: CancelAuthorization
) -> protobuf.MessageType:
    from apps.common import authorization

    authorization.clear()
    return Success(message="Authorization cancelled")


ALLOW_WHILE_LOCKED = (
    MessageType.Initialize,
    MessageType.EndSession,
    MessageType.GetFeatures,
    MessageType.OnekeyGetFeatures,
    MessageType.Cancel,
    MessageType.LockDevice,
    MessageType.DoPreauthorized,
    MessageType.WipeDevice,
    MessageType.SetBusy,
)


def set_homescreen() -> None:
    import lvgl as lv  # type: ignore[Import "lvgl" could not be resolved]

    from trezor.lvglui.scrs import fingerprints

    ble_name = storage.device.get_ble_name()
    first_unlock = False
    if storage.device.is_initialized():
        dev_state = get_state()
        device_name = storage.device.get_label()
        if not device_is_unlocked():
            if __debug__:
                print(
                    f"Device is locked by pin {not config.is_unlocked()} === fingerprint {not fingerprints.is_unlocked()}"
                )
            from trezor.lvglui.scrs.lockscreen import LockScreen

            screen = LockScreen(device_name, ble_name, dev_state)
        else:
            if __debug__:
                print(
                    f"Device is unlocked and has fingerprint {fingerprints.is_available() and not fingerprints.is_unlocked()}"
                )
            from trezor.lvglui.scrs.homescreen import MainScreen

            store_ble_name(ble_name)
            screen = MainScreen(device_name, ble_name, dev_state)
            if not first_unlock:
                first_unlock = True
                if (
                    not fingerprints.data_version_is_new()
                    and not fingerprints.data_upgrade_is_prompted()
                ):
                    fingerprints.FingerprintDataUpgrade(True)
                    fingerprints.data_upgrade_prompted()

    else:
        from trezor.lvglui.scrs.initscreen import InitScreen

        InitScreen()
        return
    if not screen.is_visible():
        lv.scr_load(screen)
    lv.refr_now(None)


def store_ble_name(ble_name):
    from trezor import uart

    temp_ble_name = uart.get_ble_name()
    if not ble_name and temp_ble_name:
        storage.device.set_ble_name(temp_ble_name)


def get_state() -> str | None:
    from trezor.lvglui.i18n import gettext as _, keys as i18n_keys

    if storage.device.no_backup():
        dev_state = _(i18n_keys.MSG__SEEDLESS)
    elif storage.device.unfinished_backup():
        dev_state = _(i18n_keys.MSG__BACKUP_FAILED)
    elif storage.device.needs_backup():
        dev_state = _(i18n_keys.MSG__NEEDS_BACKUP)
    elif not config.has_pin():
        dev_state = _(i18n_keys.MSG__PIN_NOT_SET)
    elif storage.device.get_experimental_features():
        dev_state = _(i18n_keys.MSG__EXPERIMENTAL_MODE)
    else:
        dev_state = None
    return dev_state


def lock_device() -> None:
    if storage.device.is_initialized() and config.has_pin():
        from trezor.lvglui.scrs import fingerprints

        if fingerprints.is_available():
            fingerprints.lock()
        else:
            if __debug__:
                print(
                    f"pin locked,  finger is available: {fingerprints.is_available()} ===== finger is unlocked: {fingerprints.is_unlocked()} "
                )
            config.lock()
        wire.find_handler = get_pinlocked_handler
        set_homescreen()
        workflow.close_others()


def device_is_unlocked():
    from trezor.lvglui.scrs import fingerprints

    if fingerprints.is_available():
        return fingerprints.is_unlocked()
    else:
        return config.is_unlocked()


def lock_device_if_unlocked() -> None:
    if config.is_unlocked():
        lock_device()

    loop.schedule(utils.turn_off_lcd())


def screen_off_if_possible() -> None:
    if not ui.display.backlight():
        return

    if ui.display.backlight():
        from trezor import uart

        uart.flashled_close()

        if config.is_unlocked():
            ui.display.backlight(ui.style.BACKLIGHT_LOW)
        workflow.idle_timer.set(3 * 1000, lock_device_if_unlocked)


async def screen_off_delay():
    if not ui.display.backlight():
        return
    from trezor import uart

    uart.flashled_close()
    ui.display.backlight(ui.style.BACKLIGHT_LOW)
    workflow.idle_timer.set(3 * 1000, lock_device_if_unlocked)


def shutdown_device() -> None:
    from trezor import uart

    if storage.device.is_initialized():
        if not utils.CHARGING:
            uart.ctrl_power_off()


async def unlock_device(ctx: wire.GenericContext = wire.DUMMY_CONTEXT) -> None:
    """Ensure the device is in unlocked state.

    If the storage is locked, attempt to unlock it. Reset the homescreen and the wire
    handler.
    """
    from apps.common.request_pin import verify_user_pin, verify_user_fingerprint

    if not config.is_unlocked():
        if __debug__:
            print("pin is locked ")
        # verify_user_pin will raise if the PIN was invalid
        await verify_user_pin(ctx, allow_fingerprint=False)
    else:
        from trezor.lvglui.scrs import fingerprints

        if not fingerprints.is_unlocked():
            if __debug__:
                print("fingerprint is locked")
            verify_pin = verify_user_pin(ctx, close_others=False)
            verify_finger = verify_user_fingerprint(ctx)
            racer = loop.race(verify_pin, verify_finger)
            await racer
            if verify_finger in racer.finished:
                from trezor.lvglui.scrs.pinscreen import InputPin

                pin_wind = InputPin.get_window_if_visible()
                if pin_wind:
                    pin_wind.destroy()
    if storage.device.is_fingerprint_unlock_enabled():
        storage.device.finger_failed_count_reset()

    utils.mark_pin_verified()

    # reset the idle_timer
    reload_settings_from_storage()
    set_homescreen()
    wire.find_handler = workflow_handlers.find_registered_handler


# async def auth(ctx: wire.GenericContext = wire.DUMMY_CONTEXT) -> None:

#     from apps.common.request_pin import verify_user_pin, verify_user_fingerprint

#     verify_pin = verify_user_pin(ctx, close_others=False)
#     verify_finger = verify_user_fingerprint(ctx)
#     racer = loop.race(verify_pin, verify_finger)
#     await racer
#     if verify_finger in racer.finished:
#         from trezor.lvglui.scrs.pinscreen import InputPin

#         pin_wind = InputPin.get_window_if_visible()
#         if pin_wind:
#             pin_wind.destroy()


def get_pinlocked_handler(
    iface: wire.WireInterface, msg_type: int
) -> wire.Handler[wire.Msg] | None:
    orig_handler = workflow_handlers.find_registered_handler(iface, msg_type)
    if orig_handler is None:
        return None

    if __debug__:
        import usb

        if iface is usb.iface_debug:
            return orig_handler

    if msg_type in ALLOW_WHILE_LOCKED:
        return orig_handler

    async def wrapper(ctx: wire.Context, msg: wire.Msg) -> protobuf.MessageType:
        await unlock_device(ctx)
        return await orig_handler(ctx, msg)

    return wrapper


# this function is also called when handling ApplySettings
def reload_settings_from_storage(timeout_ms: int | None = None) -> None:
    workflow.idle_timer.remove(lock_device_if_unlocked)
    if not storage.device.is_initialized():
        return
    autolock_delay_ms = storage.device.get_autolock_delay_ms()
    workflow.idle_timer.set(
        timeout_ms if timeout_ms is not None else autolock_delay_ms,
        screen_off_if_possible,
    )
    if utils.AUTO_POWER_OFF:
        workflow.idle_timer.set(
            storage.device.get_autoshutdown_delay_ms(), shutdown_device
        )
    else:
        workflow.idle_timer.remove(shutdown_device)
    wire.experimental_enabled = storage.device.get_experimental_features()
    ui.display.orientation(storage.device.get_rotation())


def boot() -> None:
    workflow_handlers.register(MessageType.Initialize, handle_Initialize)
    workflow_handlers.register(MessageType.GetFeatures, handle_GetFeatures)
    workflow_handlers.register(MessageType.OnekeyGetFeatures, handle_OnekeyGetFeatures)
    workflow_handlers.register(MessageType.Cancel, handle_Cancel)
    workflow_handlers.register(MessageType.LockDevice, handle_LockDevice)
    workflow_handlers.register(MessageType.EndSession, handle_EndSession)
    workflow_handlers.register(MessageType.Ping, handle_Ping)
    workflow_handlers.register(MessageType.DoPreauthorized, handle_DoPreauthorized)
    workflow_handlers.register(MessageType.UnlockPath, handle_UnlockPath)
    workflow_handlers.register(
        MessageType.CancelAuthorization, handle_CancelAuthorization
    )
    workflow_handlers.register(MessageType.SetBusy, handle_SetBusy)

    reload_settings_from_storage()
    from trezor.lvglui.scrs import fingerprints

    if __debug__:
        print(f"fingerprints.is_unlocked(): {fingerprints.is_unlocked()}")
        print(f"config.is_unlocked(): {config.is_unlocked()}")
    if config.is_unlocked() and fingerprints.is_unlocked():
        if __debug__:
            print("fingerprints is unlocked and config is unlocked")
        wire.find_handler = workflow_handlers.find_registered_handler
    else:
        if __debug__:
            print("fingerprints is locked or config is locked")
        wire.find_handler = get_pinlocked_handler
