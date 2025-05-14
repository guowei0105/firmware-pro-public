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
    **kwargs: Any,
) -> str:
    from trezor.ui.layouts import request_pin_on_device

    return await request_pin_on_device(
        ctx, prompt, attempts_remaining, allow_cancel, allow_fingerprint
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
) -> tuple[str, bytearray | None]:
    if config.has_pin():
        pin = await request_pin(
            ctx, prompt, config.get_pin_rem(), allow_cancel, allow_fingerprint
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
    ctx: wire.GenericContext = wire.DUMMY_CONTEXT,  # 上下文，默认为虚拟上下文
    prompt: str = "",  # 提示信息
    allow_cancel: bool = True,  # 是否允许取消
    retry: bool = True,  # 是否允许重试
    cache_time_ms: int = 0,  # PIN缓存时间（毫秒）
    re_loop: bool = False,  # 是否重新循环
    callback=None,  # 回调函数
    allow_fingerprint: bool = True,  # 是否允许指纹解锁
    close_others: bool = True,  # 是否关闭其他界面
) -> None:
    last_unlock = _get_last_unlock_time()  # 获取上次解锁时间
    if (
        cache_time_ms  # 如果设置了缓存时间
        and last_unlock  # 且有上次解锁记录
        and utime.ticks_ms() - last_unlock <= cache_time_ms  # 且当前时间与上次解锁时间的差值小于等于缓存时间
        and config.is_unlocked()  # 且配置已解锁
        and fingerprints.is_unlocked()  # 且指纹已解锁
    ):
        return  # 直接返回，无需再次验证

    if config.has_pin():  # 如果设置了PIN码
        from trezor.ui.layouts import request_pin_on_device  # 导入PIN码请求界面

        pin = await request_pin_on_device(  # 在设备上请求PIN码
            ctx,
            prompt,
            config.get_pin_rem(),  # 获取剩余尝试次数
            allow_cancel,
            allow_fingerprint,
            close_others=close_others,
        )

        config.ensure_not_wipe_code(pin)  # 确保输入的不是擦除码
    else:
        pin = ""  # 如果没有设置PIN码，则使用空字符串
    try:
        salt = await request_sd_salt(ctx)  # 请求SD卡盐值
    except SdCardUnavailable:  # 如果SD卡不可用
        raise wire.PinCancelled("SD salt is unavailable")  # 抛出PIN取消异常

    if not config.is_unlocked():  # 如果配置未解锁
        # verified = config.unlock(pin, salt,1)  # 尝试解锁
        verified, usertype = config.unlock(pin, salt,1)  # 尝试解锁
        from storage import device

        if verified:
            if usertype == 3:
                device.set_passphrase_pin_enabled(True)  # 启用密码短语 PIN
                print("Passphrase PIN mode enabled (usertype=3)")
            elif usertype == 1:
                device.set_passphrase_pin_enabled(False)  # 禁用密码短语 PIN
                print("Passphrase PIN mode disabled (usertype=1)")
            else:
                print(f"Unhandled usertype: {usertype}, passphrase PIN status unchanged")
        else:
            verified = config.check_pin(pin, salt,1)  # 检查PIN码是否正确
    if verified:  # 如果验证成功
        if re_loop:  # 如果需要重新循环
            loop.clear()  # 清除循环
        elif callback:  # 如果有回调函数
            callback()  # 执行回调
        _set_last_unlock_time()  # 设置最后解锁时间
        return  # 返回
    elif not config.has_pin():  # 如果没有设置PIN码但验证失败
        raise RuntimeError  # 抛出运行时错误
    while retry:  # 当允许重试时
        pin_rem = config.get_pin_rem()  # 获取剩余尝试次数
        pin = await request_pin_on_device(  # type: ignore ["request_pin_on_device" is possibly unbound]  # 再次请求PIN码
            ctx,
            _(i18n_keys.TITLE__ENTER_PIN),  # 使用本地化的"输入PIN"标题
            pin_rem,
            allow_cancel,
            allow_fingerprint,
            close_others=close_others,
        )
        if not config.is_unlocked():  # 如果配置未解锁
            verified = config.unlock(pin, salt)  # 尝试解锁
        else:
            verified = config.check_pin(pin, salt)  # 检查PIN码是否正确
        if verified:  # 如果验证成功
            if re_loop:  # 如果需要重新循环
                loop.clear()  # 清除循环
            elif callback:  # 如果有回调函数
                callback()  # 执行回调
            _set_last_unlock_time()  # 设置最后解锁时间
            return  # 返回
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
