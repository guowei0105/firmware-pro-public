from typing import TYPE_CHECKING

import storage.cache
import storage.device
from trezor import config, loop, protobuf, ui, utils, wire, workflow
from trezor.enums import MessageType
from trezor.messages import Success, UnlockPath
from trezor.crypto import se_thd89

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
        GetPassphraseState,
        PassphraseState,
    )


def get_vendor():
    return "trezor.io" if storage.device.is_trezor_compatible() else "onekey.so"


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
    session_id = storage.cache.start_session(msg.session_id)  # 使用消息中的会话ID启动一个新会话

    if not utils.BITCOIN_ONLY:  # 如果不是仅比特币模式
        if utils.USE_THD89:  # 如果使用THD89安全元件
            if msg.derive_cardano is not None and msg.derive_cardano:  # 如果请求派生Cardano密钥
                # THD89 is not capable of Cardano  # THD89不支持Cardano
                from trezor.crypto import se_thd89  # 导入THD89安全元件模块

                state = se_thd89.get_session_state()  # 获取当前会话状态
                if state[0] & 0x80 and not state[0] & 0x40:  # 检查会话状态标志: 这行代码检查THD89安全元件的会话状态。
                                                            # 它检查状态的第一个字节，判断最高位(0x80)是否设置且第二高位(0x40)是否未设置。
                                                            # 如果条件满足，表示需要结束当前会话并开始一个新会话。
                    storage.cache.end_current_session()  # 结束当前会话
                    session_id = storage.cache.start_session()  # 开始一个新会话

                storage.cache.SESSION_DIRIVE_CARDANO = True  # 设置会话Cardano派生标志为真
            else:
                storage.cache.SESSION_DIRIVE_CARDANO = False  # 设置会话Cardano派生标志为假

        else:  # 如果使用其他安全元件
            derive_cardano = storage.cache.get(storage.cache.APP_COMMON_DERIVE_CARDANO)  # 获取Cardano派生设置
            have_seed = storage.cache.is_set(storage.cache.APP_COMMON_SEED)  # 检查是否已有种子
            if (
                have_seed  # 如果已有种子
                and msg.derive_cardano is not None  # 且请求中指定了Cardano派生设置
                and msg.derive_cardano != bool(derive_cardano)  # 且与当前设置不同
            ):
                # seed is already derived, and host wants to change derive_cardano setting
                # => create a new session  # 种子已派生，主机想要更改Cardano派生设置，创建新会话
                storage.cache.end_current_session()  # 结束当前会话
                session_id = storage.cache.start_session()  # 开始一个新会话
                have_seed = False  # 重置种子标志

            if not have_seed:  # 如果没有种子
                storage.cache.set(
                    storage.cache.APP_COMMON_DERIVE_CARDANO,  # 设置Cardano派生标志
                    b"\x01" if msg.derive_cardano else b"",  # 根据请求设置值
                )

    features = get_features()  # 获取设备特性
    features.session_id = session_id  # 设置会话ID
    storage.cache.update_res_confirm_refresh()  # 更新资源确认刷新
    return features  # 返回设备特性


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

    # 定义密钥链MAC密钥路径
    _KEYCHAIN_MAC_KEY_PATH = [b"TREZOR", b"Keychain MAC key"]

    # UnlockPath仅与SLIP-25路径相关。
    # 注意：目前我们只允许解锁整个SLIP-25目的子树，而不是按币种或按账户解锁，
    # 以避免UI复杂性。
    if msg.address_n != [SLIP25_PURPOSE]:
        raise wire.DataError("Invalid path")

    # 获取种子并派生节点
    seed = await get_seed(ctx)
    node = Slip21Node(seed)
    node.derive_path(_KEYCHAIN_MAC_KEY_PATH)
    # 创建HMAC哈希写入器
    mac = utils.HashWriter(hmac(hmac.SHA256, node.key()))
    # 将路径写入哈希
    for i in msg.address_n:
        write_uint32_le(mac, i)
    expected_mac = mac.get_digest()

    # 除非已授权，否则需要确认才能访问SLIP25路径。
    if msg.mac:
        # 验证提供的MAC是否与预期MAC匹配
        if len(msg.mac) != len(expected_mac) or not utils.consteq(
            expected_mac, msg.mac
        ):
            raise wire.DataError("Invalid MAC")
    else:
        # 如果没有提供MAC，则需要用户确认
        await confirm_action(
            ctx,
            "confirm_coinjoin_access",
            title="CoinJoin account",
            description="Do you want to allow access to your CoinJoin account?",
        )

    # 定义允许的消息类型
    wire_types = (MessageType.GetAddress, MessageType.GetPublicKey, MessageType.SignTx)
    # 调用任何允许的消息类型，并传递MAC
    req = await ctx.call_any(UnlockedPathRequest(mac=expected_mac), *wire_types)

    # 确保返回的消息类型在允许的类型中
    assert req.MESSAGE_WIRE_TYPE in wire_types
    # 查找对应的处理程序
    handler = workflow_handlers.find_registered_handler(
        ctx.iface, req.MESSAGE_WIRE_TYPE
    )
    assert handler is not None
    # 调用处理程序处理请求
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
    MessageType.GetPassphraseState,
    MessageType.PassphraseState
)


def set_homescreen() -> None:
    import lvgl as lv  # type: ignore[Import "lvgl" could not be resolved]

    from trezor.lvglui.scrs import fingerprints

    ble_name = storage.device.get_ble_name()
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


async def unlock_device(ctx: wire.GenericContext = wire.DUMMY_CONTEXT, pin_use_type: int = 2) -> None:
    """Ensure the device is in unlocked state.

    If the storage is locked, attempt to unlock it. Reset the homescreen and the wire
    handler.
    Args:
        ctx: The wire context.
    """
    from apps.common.request_pin import verify_user_pin, verify_user_fingerprint  # 导入PIN验证和指纹验证功能
    pin_use_type_int = int(pin_use_type)

    if not config.is_unlocked():  
        if __debug__:  
            print(f"pin is locked, using pin_use_type: {pin_use_type}")  
        await verify_user_pin(ctx, allow_fingerprint=False, pin_use_type=pin_use_type_int)  
    else: 
        from trezor.lvglui.scrs import fingerprints  
        
        if not fingerprints.is_unlocked():  
            if __debug__:  
                print(f"fingerprint is locked, using pin_use_type: {pin_use_type_int}")
            verify_pin = verify_user_pin(ctx, close_others=False, pin_use_type=pin_use_type_int)
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

    def hex_to_bytes(hex_str):
        if hex_str is None:
            return None
        # 确保字符串长度是偶数
        if len(hex_str) % 2 != 0:
            hex_str = '0' + hex_str
        return bytes(int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2))


def handle_session_management(msg):
    """处理会话管理和 Cardano 派生逻辑
    
    Args:
        msg: 包含 session_id 和可能的 derive_cardano 字段的消息
        
    Returns:
        创建或恢复的会话 ID
    """
    import storage.cache
    from trezor import utils
    
    # 定义一个辅助函数来将 bytes 转换为十六进制字符串
    def bytes_to_hex(b):
        if b is None:
            return 'None'
        return ''.join('{:02x}'.format(x) for x in b)
    def hex_to_bytes(hex_str):
        if hex_str is None:
            return None
        # 确保字符串长度是偶数
        if len(hex_str) % 2 != 0:
            hex_str = '0' + hex_str
        return bytes(int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2))
    
    #b"\x81tH\x19\x04\xb7\x1c\xa3f\x92\xc6\t\x90\x87\x8b\xcbi\\\x94\xfb:\xc2ZJ\xd7'\xbeJ\xa7\xe7\xd2\x08"
    # 打印输入的 session_id
    input_session_id = msg.session_id if hasattr(msg, 'session_id') else None
    print(f"input_session_id: {bytes_to_hex(input_session_id)}") 
    print(f"input_session_id_nobyte: {input_session_id}") 
    session_id = storage.cache.start_session(input_session_id)
    print(f"first session_id: {bytes_to_hex(session_id)}")
    print(f"first session_id_nobyte: {session_id}")
    # session_id = storage.cache.start_session(session_id)
    # print(f"second session_id: {bytes_to_hex(session_id)}")
    # session_id = storage.cache6622d03e06f15ea9c2d8994bee073cd80b1c49a8491206f5509975f6dadcbf2b.start_session(session_id)
    # print(f"third start_session: {bytes_to_hex(session_id)}")   
    # # 打印启动后的 session_id
    # print(f"Started/Resumed session_id: {bytes_to_hex(session_id)}")
    # 处理 Cardano 相关逻辑
    if not utils.BITCOIN_ONLY and utils.USE_THD89:
        if hasattr(msg, 'derive_cardano') and msg.derive_cardano is not None and msg.derive_cardano:
            from trezor.crypto import se_thd89
            state = se_thd89.get_session_state()
            if state[0] & 0x80 and not state[0] & 0x40:
                storage.cache.end_current_session()
                session_id = storage.cache.start_session()
                print(f"New session_id after Cardano processing: {bytes_to_hex(session_id)}")
            storage.cache.SESSION_DIRIVE_CARDANO = True
        else:
            storage.cache.SESSION_DIRIVE_CARDANO = False
    
    print(f"Final session_id: {bytes_to_hex(session_id)}")
    
    return session_id

async def handle_GetPassphraseState(ctx: wire.Context, msg: GetPassphraseState) -> PassphraseState:
    from trezor import wire, messages, config, utils
    from apps.common import paths
    from trezor.crypto import se_thd89
    from trezor.messages import PassphraseState
    import utime
    
    def bytes_to_hex(b):
        if b is None:
            return 'None'
        return ''.join('{:02x}'.format(x) for x in b)
    print(f"Message attributes: {dir(msg)}")
    print(f"only_main_pin value: {msg.only_main_pin if hasattr(msg, 'only_main_pin') else 'N/A'}")
    print(f"only_main_pin type: {type(msg.only_main_pin) if hasattr(msg, 'only_main_pin') else 'N/A'}")
    print(f"only_main_pin is True: {msg.only_main_pin is True if hasattr(msg, 'only_main_pin') else 'N/A'}")
    print(f"only_main_pin == True: {msg.only_main_pin == True if hasattr(msg, 'only_main_pin') else 'N/A'}")

    has_only_main_pin = hasattr(msg, 'only_main_pin') and msg.only_main_pin is True
    if has_only_main_pin:
        print("has_only_main_pin")
        lock_device()
        try:
            await unlock_device(ctx, pin_use_type=0)
            session_id = handle_session_management(msg)

        except Exception as e:
            return PassphraseState(btc_test=f"Unlock error: {str(e)}")
    else:            
        is_valid = False
        try:
            if msg.btc_test is None:
                is_valid = False
            else:           
                is_valid = se_thd89.check_passphrase_btc_test_address(msg.btc_test)            
                if is_valid:
                    print("Bitcoin test address validation successful")
                else:
                    print("Bitcoin test address validation failed")
        except Exception as e:
            print(f"Error checking Bitcoin test address: {e}")
            is_valid = False
    
        if is_valid:
            lock_device()
            try:
                await unlock_device(ctx, pin_use_type=2)
                if not config.is_unlocked():
                    return PassphraseState(btc_test="Device unlock failed, user interaction required")
                session_id = handle_session_management(msg)
                utime.sleep_ms(500)
                if not config.is_unlocked():
                    return PassphraseState(btc_test="Device locked again after unlock")       
            except Exception as e:
                print(f"Error unlocking device: {e}")
                return PassphraseState(btc_test=f"Unlock error: {e}")
        else:
            await unlock_device(ctx)
            session_id = handle_session_management(msg)     
            print("session_id:",session_id)

    try:
        fixed_path = "m/44'/1'/0'/0/0"
        address_msg = messages.GetAddress(
            address_n=paths.parse_path(fixed_path), 
            show_display=False,  
            script_type=0,  
            coin_name="Testnet"  
        )
        from apps.bitcoin.get_address import get_address as btc_get_address
        try:
            address_obj = await btc_get_address(ctx, address_msg) 
            session_id = storage.cache.start_session(session_id)
            print(f"final session_id: {bytes_to_hex(session_id)}")
            return PassphraseState(btc_test=address_obj.address, session_id=session_id)
        except Exception as e:
            error_msg = str(e) if e else "Unknown error in btc_get_address"
            return PassphraseState(btc_test=f"Error in btc_get_address: {error_msg}")
    except Exception as e:
        error_msg = str(e) if e else "Unknown error getting Bitcoin address"
        if is_valid and config.is_unlocked():
            print("Device locked again due to error")
        
        return PassphraseState(btc_test=f"Error getting address: {error_msg}")


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
    workflow_handlers.register(MessageType.GetPassphraseState, handle_GetPassphraseState)

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
