import ustruct
from micropython import const
from typing import TYPE_CHECKING

from storage import device
from trezor import config, io, log, loop, motor, utils, workflow
from trezor.lvglui import StatusBar
from trezor.ui import display

from apps import base

if TYPE_CHECKING:
    from trezor.lvglui.scrs.ble import PairCodeDisplay


_PREFIX = const(42330)  # 0xA55A
_FORMAT = ">HHB"
_HEADER_LEN = const(5)
# fmt: off
_CMD_BLE_NAME = _PRESS_SHORT = _USB_STATUS_PLUG_IN = _BLE_STATUS_CONNECTED = _BLE_PAIR_SUCCESS = CHARGE_START = const(1)
_PRESS_LONG = _USB_STATUS_PLUG_OUT = _BLE_STATUS_DISCONNECTED = _BLE_PAIR_FAILED = _CMD_BLE_STATUS = CHARGE_BY_WIRELESS = const(2)
_BTN_PRESS = const(0x20)
_BTN_RELEASE = const(0x40)
# fmt: on
_BLE_STATUS_OPENED = _POWER_STATUS_CHARGING = _CMD_BLE_PAIR_CODE = const(3)
_BLE_STATUS_CLOSED = _CMD_BLE_PAIR_RES = _POWER_STATUS_CHARGING_FINISHED = const(4)
_CMD_NRF_VERSION = const(5)  # ble firmware version
_CMD_DEVICE_CHARGING_STATUS = const(8)
_CMD_BATTERY_STATUS = const(9)
_CMD_SIDE_BUTTON_PRESS = const(10)
_CMD_LED_BRIGHTNESS = const(12)
_CMD_BATTERY_INFO = const(13)
_CMD_BLE_BUILD_ID = const(16)
_CMD_BLE_HASH = const(17)
_CMD_BLE_MAC = const(18)
CHARING_TYPE = 0  # 1 VIA USB / 2 VIA WIRELESS
SCREEN: PairCodeDisplay | None = None
BLE_ENABLED: bool | None = None
NRF_VERSION: str | None = None
BLE_CTRL = io.BLE()
FLASH_LED_BRIGHTNESS: int | None = None
BUTTON_PRESSING = False
BLE_PAIR_ABORT = False


async def handle_fingerprint_data_init():
    from trezor.lvglui.scrs import lv

    while True:
        if (
            config.fingerprint_is_unlocked()
            and not config.fingerprint_data_inited()
            and lv.disp_get_default().inv_p == 0
        ):
            config.fingerprint_data_read()
        if config.fingerprint_data_inited():
            break
        if display.backlight() == 0:
            await loop.sleep(20)
        else:
            await loop.sleep(50)


async def handle_fingerprint():
    from trezorio import fingerprint

    from trezor.lvglui.scrs import fingerprints

    global BUTTON_PRESSING
    while True:
        if any(
            (
                BUTTON_PRESSING,
                utils.is_collecting_fingerprint(),
                display.backlight() == 0,
                not fingerprints.is_available(),
                fingerprints.is_unlocked(),
            )
        ):
            return

        if not fingerprint.sleep():
            await loop.sleep(100)
            continue
        state = await loop.wait(io.FINGERPRINT_STATE)
        if __debug__:
            print(f"state == {state}")

        if fingerprints.is_unlocked():
            return

        try:
            detected = fingerprint.detect()
            if detected:
                await loop.sleep(100)
                if not fingerprint.detect():
                    continue
                if __debug__:
                    print("finger detected ....")
                try:
                    match_id = fingerprint.match()
                    fps = fingerprints.get_fingerprint_list()
                    assert match_id in fps
                except Exception as e:
                    if __debug__:
                        log.exception(__name__, e)
                        print("fingerprint mismatch")
                    warning_level = 0
                    if isinstance(e, fingerprint.ExtractFeatureFail):
                        warning_level = 4
                    elif isinstance(e, (fingerprint.NoFp, fingerprint.GetImageFail)):
                        warning_level = 3
                    elif isinstance(e, fingerprint.NotMatch):
                        # increase failed count
                        device.finger_failed_count_incr()
                        failed_count = device.finger_failed_count()
                        if failed_count >= utils.MAX_FP_ATTEMPTS:
                            from trezor.lvglui.scrs.pinscreen import InputPin

                            pin_wind = InputPin.get_window_if_visible()
                            if pin_wind:
                                pin_wind.refresh_fingerprint_prompt()
                            if config.is_unlocked():
                                config.lock()

                        warning_level = 1 if failed_count < utils.MAX_FP_ATTEMPTS else 2
                    from trezor.lvglui.scrs.lockscreen import LockScreen

                    # failed prompt
                    visible, scr = LockScreen.retrieval()
                    if visible and scr is not None:
                        motor.vibrate()
                        from trezor.lvglui.scrs.pinscreen import InputPin

                        pin_wind = InputPin.get_window_if_visible()
                        if pin_wind:
                            pin_wind.show_fp_failed_prompt(warning_level)
                        else:
                            scr.show_finger_mismatch_anim()
                        scr.show_tips(warning_level)
                    await loop.sleep(500)
                else:
                    if __debug__:
                        print(f"fingerprint match {match_id}")
                    motor.vibrate(weak=True)
                    # # 1. publish signal
                    if fingerprints.has_takers():
                        if __debug__:
                            print("publish signal")
                        fingerprints.signal_match()
                    else:
                        # 2. unlock
                        res = fingerprints.unlock()
                        if __debug__:
                            print(f"uart unlock result {res}")
                        await base.unlock_device()
                    # await loop.sleep(2000)
                    return
            else:
                await loop.sleep(200)
        except Exception as e:
            if __debug__:
                log.exception(__name__, e)
            loop.clear()
            return  # pylint: disable=lost-exception


async def handle_usb_state():
    while True:
        try:
            utils.AIRGAP_MODE_CHANGED = False
            usb_state = loop.wait(io.USB_STATE)
            state, enable = await usb_state
            if enable is not None and not device.is_airgap_mode():
                import usb

                usb.bus.connect_ctrl(enable)
                continue

            utils.turn_on_lcd_if_possible()
            if state:
                # if display.backlight() == 0:
                #     prompt = ChargingPromptScr.get_instance()
                #     await loop.sleep(300)
                #     prompt.show()
                StatusBar.get_instance().show_usb(True)
                # deal with charging state
                StatusBar.get_instance().show_charging(True)
                if utils.BATTERY_CAP:
                    StatusBar.get_instance().set_battery_img(utils.BATTERY_CAP, True)
                motor.vibrate()
            else:
                StatusBar.get_instance().show_usb(False)
                # deal with charging state
                StatusBar.get_instance().show_charging()
                if utils.BATTERY_CAP:
                    StatusBar.get_instance().set_battery_img(utils.BATTERY_CAP, False)
                    _request_charging_status()
            if not utils.AIRGAP_MODE_CHANGED:  # not enable or disable airgap mode
                usb_auto_lock = device.is_usb_lock_enabled()
                if usb_auto_lock and device.is_initialized() and config.has_pin():
                    from trezor.lvglui.scrs import fingerprints

                    if config.is_unlocked():
                        if fingerprints.is_available():
                            fingerprints.lock()
                        else:
                            config.lock()
                        await safe_reloop()
                        await workflow.spawn(utils.internal_reloop())
                elif not usb_auto_lock and not state:
                    await safe_reloop(ack=False)
            else:
                utils.AIRGAP_MODE_CHANGED = False
            base.reload_settings_from_storage()
        except Exception as exec:
            if __debug__:
                log.exception(__name__, exec)
            loop.clear()


async def safe_reloop(ack=True):
    from trezor import wire
    from trezor.lvglui.scrs.homescreen import change_state

    change_state()
    if ack:
        await wire.signal_ack()


async def handle_uart():
    # await fetch_all()
    while True:
        try:
            await process_push()
        except Exception as exec:
            if __debug__:
                log.exception(__name__, exec)
            loop.clear()
            return  # pylint: disable=lost-exception


async def handle_ble_info():
    while True:
        fetch_ble_info()
        await loop.sleep(500)


async def process_push() -> None:

    uart = loop.wait(io.UART | io.POLL_READ)

    response = await uart
    header = response[:_HEADER_LEN]
    prefix, length, cmd = ustruct.unpack(_FORMAT, header)
    if prefix != _PREFIX:
        # unexpected prefix, ignore directly
        return
    value = response[_HEADER_LEN:][: length - 2]
    if __debug__:
        print(f"cmd == {cmd} with value {value} ")
    if cmd == _CMD_BLE_STATUS:
        # 1 connected 2 disconnected 3 opened 4 closed
        await _deal_ble_status(value)
    elif cmd == _CMD_BLE_PAIR_CODE:
        # show six bytes pair code as string
        workflow.spawn(_deal_ble_pair(value))
    elif cmd == _CMD_BLE_PAIR_RES:
        # paring result 1 success 2 failed
        await _deal_pair_res(value)
    elif cmd == _CMD_DEVICE_CHARGING_STATUS:
        # 1 usb plug in 2 usb plug out 3 charging
        await _deal_charging_state(value)
    elif cmd == _CMD_BATTERY_STATUS:
        # current battery level, 0-100 only effective when not charging
        res = ustruct.unpack(">B", value)[0]
        utils.BATTERY_CAP = res
        StatusBar.get_instance().set_battery_img(res, utils.CHARGING)
    elif cmd == _CMD_SIDE_BUTTON_PRESS:
        # 1 short press 2 long press
        await _deal_button_press(value)
    elif cmd == _CMD_BLE_NAME:
        # retrieve ble name has format: ^T[0-9]{4}$
        _retrieve_ble_name(value)
    elif cmd == _CMD_NRF_VERSION:
        # retrieve nrf version
        _retrieve_nrf_version(value)
    elif cmd == _CMD_LED_BRIGHTNESS:
        # retrieve led brightness
        _retrieve_flashled_brightness(value)
    elif cmd == _CMD_BATTERY_INFO:
        _deal_battery_info(value)
    elif cmd == _CMD_BLE_BUILD_ID:
        _retrieve_ble_build_id(value)
    elif cmd == _CMD_BLE_HASH:
        _retrieve_ble_hash(value)
    elif cmd == _CMD_BLE_MAC:
        _retrieve_ble_mac(value)
    else:
        if __debug__:
            print("unknown or not care command:", cmd)


async def _deal_ble_pair(value):
    from trezor.qr import close_camera

    close_camera()
    flashled_close()

    if not device.is_initialized():
        from trezor.lvglui.scrs.ble import PairForbiddenScreen

        PairForbiddenScreen()
        return
    global BLE_PAIR_ABORT
    BLE_PAIR_ABORT = False

    if not base.device_is_unlocked():
        try:
            await base.unlock_device()
        except Exception:
            await safe_reloop()
            workflow.spawn(utils.internal_reloop())
            return
        else:
            if BLE_PAIR_ABORT:
                return

    global SCREEN
    pair_codes = value.decode("utf-8")
    # pair_codes = "".join(list(map(lambda c: chr(c), ustruct.unpack(">6B", value))))
    utils.turn_on_lcd_if_possible()
    from trezor.lvglui.scrs.ble import PairCodeDisplay

    SCREEN = PairCodeDisplay(pair_codes)


async def _deal_button_press(value: bytes) -> None:
    res = ustruct.unpack(">B", value)[0]
    if res in (_PRESS_SHORT, _PRESS_LONG):
        flashled_close()
        if utils.is_collecting_fingerprint():
            return
    if res == _PRESS_SHORT:
        if display.backlight():
            display.backlight(0)
            if device.is_initialized():
                if utils.is_initialization_processing():
                    return
                utils.AUTO_POWER_OFF = True
                utils.RESTART_MAIN_LOOP = True
                from trezor.lvglui.scrs import fingerprints

                if config.has_pin() and config.is_unlocked():
                    if fingerprints.is_available():
                        if fingerprints.is_unlocked():
                            fingerprints.lock()
                    else:
                        config.lock()
                await loop.race(safe_reloop(), loop.sleep(200))
                workflow.spawn(utils.internal_reloop())
                base.set_homescreen()
                return
        else:
            utils.turn_on_lcd_if_possible()

    elif res == _PRESS_LONG:
        from trezor.lvglui.scrs.homescreen import PowerOff
        from trezor.qr import close_camera

        close_camera()
        PowerOff(
            True
            if not utils.is_initialization_processing() and device.is_initialized()
            else False
        )
        await loop.sleep(200)
        utils.lcd_resume()
    elif res == _BTN_PRESS:
        global BUTTON_PRESSING
        BUTTON_PRESSING = True
        if utils.is_collecting_fingerprint():
            from trezor.lvglui.scrs.fingerprints import CollectFingerprintProgress

            if CollectFingerprintProgress.has_instance():
                CollectFingerprintProgress.get_instance().prompt_tips()
                return
    elif res == _BTN_RELEASE:
        global BUTTON_PRESSING
        BUTTON_PRESSING = False


async def _deal_charging_state(value: bytes) -> None:
    """THIS DOESN'T WORK CORRECT DUE TO THE PUSHED STATE, ONLY USED AS A FALLBACK WHEN
    CHARGING WITH A CHARGER NOW.

    """
    global CHARING_TYPE
    res, CHARING_TYPE = ustruct.unpack(">BB", value)

    if res in (
        CHARGE_START,
        _POWER_STATUS_CHARGING,
    ):
        StatusBar.get_instance().show_charging(True)
        if utils.BATTERY_CAP:
            StatusBar.get_instance().set_battery_img(utils.BATTERY_CAP, True)
        if CHARING_TYPE == CHARGE_BY_WIRELESS:

            if utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_STOP:
                utils.CHARGE_WIRELESS_STATUS = utils.CHARGE_WIRELESS_CHARGE_STARTING
                fetch_battery_temperature()
                loop.schedule(base.screen_off_delay())
            elif utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGE_STOPPING:
                utils.CHARGE_WIRELESS_STATUS = utils.CHARGE_WIRELESS_CHARGE_STARTING
                if display.backlight() > 0:
                    loop.schedule(base.screen_off_delay())
                return
            elif utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGE_STARTING:
                return
            elif utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGING:
                return
        else:
            if utils.CHARGING:
                return
            utils.CHARGE_WIRELESS_STATUS = utils.CHARGE_WIRELESS_STOP
            ctrl_charge_switch(True)
            utils.CHARGING = True
    elif res in (_USB_STATUS_PLUG_OUT, _POWER_STATUS_CHARGING_FINISHED):
        utils.CHARGING = False
        ctrl_charge_switch(False)
        StatusBar.get_instance().show_charging(False)
        StatusBar.get_instance().show_usb(False)
        if utils.BATTERY_CAP:
            StatusBar.get_instance().set_battery_img(utils.BATTERY_CAP, False)

        if utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGING:
            utils.CHARGE_WIRELESS_STATUS = utils.CHARGE_WIRELESS_STOP

        elif utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGE_STARTING:
            utils.CHARGE_WIRELESS_STATUS = utils.CHARGE_WIRELESS_CHARGE_STOPPING
            return
        elif utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGE_STOPPING:
            return
            # utils.CHARGE_WIRELESS_STATUS = utils.CHARGE_WIRELESS_STOP

    utils.turn_on_lcd_if_possible()


async def _deal_pair_res(value: bytes) -> None:
    res = ustruct.unpack(">B", value)[0]
    if res in [_BLE_PAIR_SUCCESS, _BLE_PAIR_FAILED]:
        if SCREEN is not None and not SCREEN.destroyed:
            SCREEN.destroy()
    if res == _BLE_PAIR_FAILED:
        global BLE_PAIR_ABORT
        BLE_PAIR_ABORT = True
        StatusBar.get_instance().show_ble(StatusBar.BLE_STATE_ENABLED)
        if device.is_initialized():
            from trezor.ui.layouts import show_pairing_error

            await show_pairing_error()


async def _deal_ble_status(value: bytes) -> None:
    global BLE_ENABLED
    res = ustruct.unpack(">B", value)[0]
    if res == _BLE_STATUS_CONNECTED:
        utils.BLE_CONNECTED = True
        # show icon in status bar
        utils.turn_on_lcd_if_possible(2 * 60 * 1000)
        StatusBar.get_instance().show_ble(StatusBar.BLE_STATE_CONNECTED)
    elif res == _BLE_STATUS_DISCONNECTED:
        utils.BLE_CONNECTED = False
        if not BLE_ENABLED:
            return
        StatusBar.get_instance().show_ble(StatusBar.BLE_STATE_ENABLED)
        await safe_reloop()
    elif res == _BLE_STATUS_OPENED:
        BLE_ENABLED = True
        if utils.BLE_CONNECTED:
            return
        StatusBar.get_instance().show_ble(StatusBar.BLE_STATE_ENABLED)
        if config.is_unlocked():
            device.set_ble_status(enable=True)
    elif res == _BLE_STATUS_CLOSED:
        utils.BLE_CONNECTED = False
        if not device.is_initialized():
            StatusBar.get_instance().show_ble(StatusBar.BLE_STATE_ENABLED)
            ctrl_ble(True)
            return
        BLE_ENABLED = False
        StatusBar.get_instance().show_ble(StatusBar.BLE_STATE_DISABLED)
        if config.is_unlocked():
            device.set_ble_status(enable=False)


def _retrieve_flashled_brightness(value: bytes) -> None:
    if value != b"":
        global FLASH_LED_BRIGHTNESS
        flag, FLASH_LED_BRIGHTNESS = ustruct.unpack(">BB", value)
        if __debug__:
            print("flag:", flag)
            print(f"flash led brightness: {FLASH_LED_BRIGHTNESS}")
        utils.FLASH_LED_BRIGHTNESS = FLASH_LED_BRIGHTNESS


def _deal_battery_info(value: bytes) -> None:
    res, val = ustruct.unpack(">BH", value)
    if res == 4:
        if (
            val <= 38
            and display.backlight() == 0
            and utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGE_STARTING
        ):
            utils.CHARGE_WIRELESS_STATUS = utils.CHARGE_WIRELESS_CHARGING
            ctrl_charge_switch(True)
        utils.BATTERY_TEMP = val


def _retrieve_ble_name(value: bytes) -> None:
    if value != b"":
        utils.BLE_NAME = value.decode("utf-8")
        # if config.is_unlocked():
        #     device.set_ble_name(BLE_NAME)


def _retrieve_nrf_version(value: bytes) -> None:
    global NRF_VERSION
    if value != b"":
        NRF_VERSION = value.decode("utf-8")
        # if config.is_unlocked():
        #     device.set_ble_version(NRF_VERSION)


def _retrieve_ble_build_id(value: bytes) -> None:
    if value != b"":
        utils.BLE_BUILD_ID = value.decode("utf-8")


def _retrieve_ble_hash(value: bytes) -> None:
    if value != b"":
        utils.BLE_HASH = value


def _retrieve_ble_mac(value: bytes) -> None:
    if value != b"":
        utils.BLE_MAC = value


def _request_ble_name():
    """Request ble name."""
    BLE_CTRL.ctrl(0x83, b"\x01")


def _request_ble_version():
    """Request ble version."""
    BLE_CTRL.ctrl(0x83, b"\x02")


def _request_battery_level():
    """Request battery level."""
    BLE_CTRL.ctrl(0x82, b"\x04")


def _request_ble_status():
    """Request current ble status."""
    BLE_CTRL.ctrl(0x81, b"\x04")


def _request_charging_status():
    """Request charging status."""
    BLE_CTRL.ctrl(0x82, b"\x05")


def disconnect_ble():
    if utils.BLE_CONNECTED:
        BLE_CTRL.ctrl(0x81, b"\x03")


async def fetch_all():
    """Request some important data."""
    while True:
        if display.backlight():
            flashled_close()
            _request_ble_name()
            _request_ble_version()
            _request_ble_status()
            _request_battery_level()
            _request_charging_status()
            _fetch_flashled_brightness()
            return
        await loop.sleep(100)


def fetch_ble_info():
    if not utils.BLE_NAME:
        BLE_CTRL.ctrl(0x83, b"\x01")

    global NRF_VERSION
    if NRF_VERSION is None:
        BLE_CTRL.ctrl(0x83, b"\x02")

    global BLE_ENABLED
    if BLE_ENABLED is None:
        BLE_CTRL.ctrl(0x81, b"\x04")

    if utils.BLE_BUILD_ID is None:
        BLE_CTRL.ctrl(0x83, b"\x05")

    if utils.BLE_HASH is None:
        BLE_CTRL.ctrl(0x83, b"\x06")

    if utils.BLE_MAC is None:
        BLE_CTRL.ctrl(0x83, b"\x07")


def fetch_battery_temperature():
    BLE_CTRL.ctrl(0x86, b"\x04")
    # BLE_CTRL.ctrl(0x86, b"\x05")


def ctrl_ble(enable: bool) -> None:
    """Request to open or close ble.
    @param enable: True to open, False to close
    """
    if enable:
        BLE_CTRL.ctrl(0x81, b"\x01")
    else:
        BLE_CTRL.ctrl(0x81, b"\x02")


def _ctrl_flashled(enable: bool, brightness=15) -> None:
    """Request to open or close flashlight.
    @param enable: True to open, False to close
    """
    if brightness > 50:
        brightness = 50
    BLE_CTRL.ctrl(
        0x85, b"\x01" + (int.to_bytes(brightness, 1, "big") if enable else b"\x00")
    )


def _fetch_flashled_brightness() -> None:
    """Request to get led brightness."""
    if utils.FLASH_LED_BRIGHTNESS is None:
        BLE_CTRL.ctrl(0x85, b"\x02")


def flashled_open() -> None:
    """Request to open led."""
    utils.FLASH_LED_BRIGHTNESS = 15
    _ctrl_flashled(True)


def flashled_close() -> None:
    """Request to close led."""
    if utils.FLASH_LED_BRIGHTNESS is not None and utils.FLASH_LED_BRIGHTNESS > 0:
        utils.FLASH_LED_BRIGHTNESS = 0
        _ctrl_flashled(False)


def is_flashled_opened() -> bool:
    """Check if led is opened."""
    if utils.FLASH_LED_BRIGHTNESS is None:
        _fetch_flashled_brightness()
        return False
    return utils.FLASH_LED_BRIGHTNESS > 0


def ctrl_power_off() -> None:
    """Request to power off the device."""
    BLE_CTRL.ctrl(0x82, b"\x01")


def get_ble_name() -> str:
    """Get ble name."""
    return utils.BLE_NAME if utils.BLE_NAME else ""


def get_ble_version() -> str:
    """Get ble version."""
    if utils.EMULATOR:
        return "1.0.0"
    return NRF_VERSION if NRF_VERSION else ""


def get_ble_build_id() -> str:
    return utils.BLE_BUILD_ID if utils.BLE_BUILD_ID else ""


def get_ble_hash() -> bytes:
    return utils.BLE_HASH if utils.BLE_HASH else b""


def get_ble_mac() -> bytes:
    """Get ble MAC address."""
    return utils.BLE_MAC if utils.BLE_MAC else b""


def is_ble_opened() -> bool:
    return BLE_ENABLED if BLE_ENABLED is not None else True


def ctrl_charge_switch(enable: bool) -> None:
    """Request to open or close charge.
    @param enable: True to open, False to close
    """
    if enable:
        if utils.CHARGE_ENABLE is None or not utils.CHARGE_ENABLE:
            BLE_CTRL.ctrl(0x82, b"\x06")
            utils.CHARGE_ENABLE = True
    else:
        if utils.CHARGE_ENABLE is None or utils.CHARGE_ENABLE:
            BLE_CTRL.ctrl(0x82, b"\x07")
            utils.CHARGE_ENABLE = False


def ctrl_wireless_charge(enable: bool) -> None:
    """Request to open or close charge.
    @param enable: True to open, False to close
    """
    if utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGING:
        utils.CHARGE_WIRELESS_STATUS = utils.CHARGE_WIRELESS_CHARGE_STARTING
        ctrl_charge_switch(enable)


def get_wireless_charge_status() -> bool:
    if utils.CHARGE_ENABLE:
        return True
    return False


def stop_mode(reset_timer: bool = False):
    disconnect_ble()

    lp_timer_enable = False
    wireless_charge = False

    if utils.CHARGE_WIRELESS_STATUS == utils.CHARGE_WIRELESS_CHARGE_STARTING:
        lp_timer_enable = True
        wireless_charge = True

    utils.enter_lowpower(
        reset_timer, device.get_autoshutdown_delay_ms(), lp_timer_enable
    )
    if wireless_charge:
        fetch_battery_temperature()
