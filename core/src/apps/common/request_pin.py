import utime
from typing import Any, NoReturn

import storage.cache
import storage.sd_salt
from trezor import config, loop, wire
from trezor.lvglui.i18n import gettext as _, keys as i18n_keys
from trezor.lvglui.lv_colors import lv_colors
from trezor.lvglui.scrs import fingerprints

from .sdcard import SdCardUnavailable, request_sd_salt


def can_lock_device() -> bool:
    """Return True if the device has a PIN set or SD-protect enabled."""
    return config.has_pin() or storage.sd_salt.is_enabled()


async def request_pin(
    ctx: wire.GenericContext,
    prompt: str = "",
    attempts_remaining: int | None = None,
    allow_cancel: bool = True,
    allow_fingerprint: bool = True,
    standy_wall_only: bool = False,
    **kwargs: Any,
) -> str:
    from trezor.ui.layouts import request_pin_on_device

    return await request_pin_on_device(
        ctx, prompt, attempts_remaining, allow_cancel, allow_fingerprint, standy_wall_only=standy_wall_only
    )


async def request_pin_confirm(ctx: wire.Context, *args: Any, **kwargs: Any) -> str:
    while True:
        if kwargs.get("show_tip", True):
            from trezor.ui.layouts import request_pin_tips

            await request_pin_tips(ctx)
        pin1 = await request_pin(
            ctx, _(i18n_keys.TITLE__ENTER_NEW_PIN), *args, **kwargs
        )
        pin2 = await request_pin(
            ctx, _(i18n_keys.TITLE__ENTER_PIN_AGAIN), *args, **kwargs
        )
        if pin1 == pin2:
            return pin1
        await pin_mismatch(ctx)


async def pin_mismatch(ctx) -> None:
    from trezor.ui.layouts import show_warning

    await show_warning(
        ctx=ctx,
        br_type="pin_not_match",
        header=_(i18n_keys.TITLE__NOT_MATCH),
        content=_(i18n_keys.SUBTITLE__SETUP_SET_PIN_PIN_NOT_MATCH),
        icon="A:/res/danger.png",
        btn_yes_bg_color=lv_colors.ONEKEY_BLACK,
    )


async def request_pin_and_sd_salt(
    ctx: wire.Context,
    prompt: str = "",
    allow_cancel: bool = True,
    allow_fingerprint: bool = True,
    standy_wall_only: bool = False,
) -> tuple[str, bytearray | None]:
    if config.has_pin():
        print("request_pin_and_sd_salt,standy_wall_only", standy_wall_only)
        pin = await request_pin(
            ctx, prompt, config.get_pin_rem(), allow_cancel, allow_fingerprint,standy_wall_only
        )
        config.ensure_not_wipe_code(pin)
    else:
        pin = ""

    salt = await request_sd_salt(ctx)

    return pin, salt


def _set_last_unlock_time() -> None:
    now = utime.ticks_ms()
    storage.cache.set_int(storage.cache.APP_COMMON_REQUEST_PIN_LAST_UNLOCK, now)


def _get_last_unlock_time() -> int:
    return storage.cache.get_int(storage.cache.APP_COMMON_REQUEST_PIN_LAST_UNLOCK) or 0


async def verify_user_pin(
    ctx: wire.GenericContext = wire.DUMMY_CONTEXT,
    prompt: str = "",
    allow_cancel: bool = True,
    retry: bool = True,
    cache_time_ms: int = 0,
    re_loop: bool = False,
    callback=None,
    allow_fingerprint: bool = True,
    close_others: bool = True,
    attach_wall_only: bool = False,
    pin_use_type: int = 2,
    standy_wall_only: bool=False,
) -> None:
    from storage import device
    pin_use_type = int(pin_use_type)
    # 如果密码短语功能未启用，强制 pin_use_type 为 0（只验证主 PIN）
    if not device.is_passphrase_enabled():
        pin_use_type = 0
        # 再次确保是整数类型
        pin_use_type = int(pin_use_type)
    if pin_use_type is 3:
       prompt = f"{_(i18n_keys.TITLE__ENTER_HIDDEN_WALLET_PIN)}"
    last_unlock = _get_last_unlock_time()  # 获取上次解锁时间
    if (
        cache_time_ms
        and last_unlock
        and utime.ticks_ms() - last_unlock <= cache_time_ms
        and config.is_unlocked()
        and fingerprints.is_unlocked()
    ):
        return

    print(f"[DEBUG] Has PIN: {config.has_pin()}, PIN remaining attempts: {config.get_pin_rem()}")
    if config.has_pin():  # 如果设置了PIN码
        print("[DEBUG] Device has PIN, requesting PIN input")
        from trezor.ui.layouts import request_pin_on_device  # 导入PIN码请求界面
        try:
            pin = await request_pin_on_device(  # 在设备上请求PIN码
                ctx,
                prompt,
                config.get_pin_rem(),  # 获取剩余尝试次数
                allow_cancel,
                allow_fingerprint,
                close_others=close_others,
                standy_wall_only = standy_wall_only,
            )
            config.ensure_not_wipe_code(pin)  # 确保输入的不是擦除码
        except Exception as e:
            print(f"[ERROR] Exception during PIN request: {type(e).__name__}: {e}")
            raise
    else:
        pin = ""
    try:
        salt = await request_sd_salt(ctx)  # 请求SD卡盐值
        print("[DEBUG] SD salt received")
    except SdCardUnavailable as e:  # 如果SD卡不可用
        print(f"[ERROR] SD card unavailable: {e}")
        raise wire.PinCancelled("SD salt is unavailable")  # 抛出PIN取消异常
    except Exception as e:
        print(f"[ERROR] Unexpected error requesting SD salt: {type(e).__name__}: {e}")
        raise

    if not config.is_unlocked():  # 如果配置未解锁
        print(f"[DEBUG] Attempting to unlock with pin_use_type={pin_use_type}")
        try:
            verified, usertype = config.unlock(pin, salt, pin_use_type)  # 尝试解锁
            print(f"[DEBUG] Unlock result: verified={verified}, usertype={usertype}")
            from storage import device

            if verified:
                if usertype == 3:
                    device.set_passphrase_pin_enabled(True)  # 启用密码短语 PIN
                elif usertype == 0:
                    device.set_passphrase_pin_enabled(False)  # 禁用密码短语 PIN
                else:
                    print(f"[DEBUG] Unhandled usertype: {usertype}, passphrase PIN status unchanged")
            # else:
            #     print(f"[DEBUG] Verification failed, checking PIN with pin_use_type={pin_use_type}")
            #     verified, usertype = config.check_pin(pin, salt, pin_use_type)  # 检查PIN码是否正确
            #     print(f"[DEBUG] PIN check result: {verified}")
        except Exception as e:
            print(f"[ERROR] Exception during unlock: {type(e).__name__}: {e}")
            raise
    else:
        print("[DEBUG] Device already unlocked, checking PIN")
        try:
            verified, usertype = config.check_pin(pin, salt, pin_use_type)
            print(f"[DEBUG] PIN check result: {verified}")
        except Exception as e:
            print(f"[ERROR] Exception during PIN check: {type(e).__name__}: {e}")
            raise

    if verified:  # 如果验证成功
        print("[DEBUG] PIN verification successful")
        if re_loop:  # 如果需要重新循环
            print("[DEBUG] Clearing loop")
            loop.clear()  # 清除循环
        elif callback:  # 如果有回调函数
            print("[DEBUG] Executing callback")
            callback()  # 执行回调
        print("[DEBUG] Setting last unlock time")
        _set_last_unlock_time()  # 设置最后解锁时间
        return  # 返回
    elif not config.has_pin():  
        print("[ERROR] No PIN set but verification failed, raising RuntimeError")
        raise RuntimeError  # 抛出运行时错误

    print("[DEBUG] PIN verification failed, entering retry loop")
    while retry:  # 当允许重试时
        print("[DEBUG] Retrying PIN verification")
        pin_rem = config.get_pin_rem()  # 获取剩余尝试次数
        print(f"[DEBUG] PIN remaining attempts: {pin_rem}")
        try:
            pin = await request_pin_on_device(  # type: ignore ["request_pin_on_device" is possibly unbound]  # 再次请求PIN码
                ctx,
                _(i18n_keys.TITLE__ENTER_PIN),  # 使用本地化的"输入PIN"标题
                pin_rem,
                allow_cancel,
                allow_fingerprint,
                close_others=close_others,
                standy_wall_only = standy_wall_only,
            )
            print("[DEBUG] Retry PIN input received")
        except Exception as e:
            print(f"[ERROR] Exception during retry PIN request: {type(e).__name__}: {e}")
            raise

        try:
            if not config.is_unlocked():  # 如果配置未解锁
                print("[DEBUG] Attempting to unlock in retry loop")
                verified, usertype = config.unlock(pin, salt,pin_use_type)  # 尝试解锁
                print(f"[DEBUG] Retry unlock result: {verified}")
            else:
                print("[DEBUG] Device already unlocked in retry loop, checking PIN")
                verified, usertype = config.check_pin(pin, salt,pin_use_type)  # 检查PIN码是否正确
                print(f"[DEBUG] Retry PIN check result: {verified}")
        except Exception as e:
            print(f"[ERROR] Exception during retry verification: {type(e).__name__}: {e}")
            raise

        if verified:  # 如果验证成功
            print("[DEBUG] Retry PIN verification successful")
            if re_loop:  # 如果需要重新循环
                print("[DEBUG] Clearing loop in retry")
                loop.clear()  # 清除循环
            elif callback:  # 如果有回调函数
                print("[DEBUG] Executing callback in retry")
                callback()  # 执行回调
            print("[DEBUG] Setting last unlock time in retry")
            _set_last_unlock_time()  # 设置最后解锁时间
            return  # 返回
        else:
            print("continue continue continue continue continue continue continue") 
            continue


    print("[ERROR] All PIN verification attempts failed, raising PinInvalid")
    raise wire.PinInvalid  # 如果所有尝试都失败，抛出PIN无效异常




async def verify_user_fingerprint(
    ctx: wire.GenericContext = wire.DUMMY_CONTEXT,
    re_loop: bool = False,
    callback=None,
):
    if fingerprints.is_unlocked():
        return
    if await fingerprints.request():
        fingerprints.unlock()
        if re_loop:
            loop.clear()
        elif callback:
            callback()
        _set_last_unlock_time


async def error_pin_invalid(ctx: wire.Context) -> NoReturn:
    from trezor.ui.layouts import show_error_and_raise

    await show_error_and_raise(
        ctx,
        "warning_wrong_pin",
        header=_(i18n_keys.TITLE__WRONG_PIN),
        content=_(i18n_keys.SUBTITLE__SET_PIN_WRONG_PIN),
        red=True,
        exc=wire.PinInvalid,
    )
    assert False


async def error_pin_matches_wipe_code(ctx: wire.Context) -> NoReturn:
    from trezor.ui.layouts import show_error_and_raise

    await show_error_and_raise(
        ctx,
        "warning_invalid_new_pin",
        header="Invalid PIN",
        content="The new PIN must be different from your\nwipe code.",
        red=True,
        exc=wire.PinInvalid,
    )
    assert False
