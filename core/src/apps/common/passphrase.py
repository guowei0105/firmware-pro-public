from micropython import const

import storage.device
from trezor import wire, workflow
from trezor.lvglui.i18n import gettext as _, keys as i18n_keys

_MAX_PASSPHRASE_LEN = const(50)


def is_enabled() -> bool:
    return storage.device.is_passphrase_enabled()


def is_passphrase_pin_enabled() -> bool:
    return storage.device.is_passphrase_pin_enabled()


def is_passphrase_auto_status() -> bool:
    return storage.device.is_passphrase_auto_status()


async def get(ctx: wire.Context) -> str:

    if __debug__:
        print(f"passphrase.get DEBUG: Function called")
        print(f"passphrase.get DEBUG: is_enabled(): {is_enabled()}")
    
    if is_enabled():
        # passphrase_pin_enabled = is_passphrase_pin_enabled()
        # if __debug__:
        #     print(f"passphrase.get DEBUG: is_enabled=True, is_passphrase_pin_enabled={passphrase_pin_enabled}")
        # if passphrase_pin_enabled:
        #     if __debug__:
        #         print("passphrase.get DEBUG: passphrase_pin_enabled=True, returning empty string")
        #     return ""
        if isinstance(ctx, wire.QRContext) and ctx.passphrase is not None:
            if __debug__:
                print("passphrase.get DEBUG: QRContext with passphrase, returning ctx.passphrase")
            return ctx.passphrase
        if __debug__:
            print("passphrase.get DEBUG: Calling _request_from_user")
        return await _request_from_user(ctx)
    else:
        if __debug__:
            print("passphrase.get DEBUG: is_enabled=False, returning empty string")
        return ""


async def _request_from_user(ctx: wire.Context) -> str:
    workflow.close_others()
    if storage.device.get_passphrase_always_on_device() or issubclass(
        ctx.__class__, (wire.DummyContext, wire.QRContext)
    ):
        from trezor.ui.layouts import request_passphrase_on_device

        from trezor.crypto import se_thd89

        current_space = se_thd89.get_pin_passphrase_space()

        passphrase = await request_passphrase_on_device(ctx, _MAX_PASSPHRASE_LEN)
        if isinstance(ctx, wire.QRContext):
            ctx.passphrase = passphrase
    else:
        passphrase = await _request_on_host(ctx)
    if len(passphrase.encode()) > _MAX_PASSPHRASE_LEN:
        raise wire.DataError(
            f"Maximum passphrase length is {_MAX_PASSPHRASE_LEN} bytes"
        )

    return passphrase


async def _request_on_host(ctx: wire.Context) -> str:
    from trezor.messages import PassphraseAck, PassphraseRequest

    # disable passphrase entry dialog for now
    # _entry_dialog()

    request = PassphraseRequest()
    from trezor.crypto import se_thd89

    current_space = se_thd89.get_pin_passphrase_space()
    if current_space < 30:
        request.exists_attach_pin_user = True
    else:
        request.exists_attach_pin_user = False

    ack = await ctx.call(request, PassphraseAck)

    if ack.on_device_attach_pin:
        from apps.base import unlock_device, lock_device
        from trezor.ui.layouts.common import button_request
        from trezor.enums import ButtonRequestType

        await button_request(ctx, "passphrase_device", code=ButtonRequestType.AttachPin)
        lock_device()
        from apps.common.pin_constants import PinType

        await unlock_device(
            ctx, pin_use_type=PinType.PASSPHRASE_PIN, attach_wall_only=True
        )
        storage.cache.start_session()
        return ""

    if ack.on_device:
        from trezor.ui.layouts import request_passphrase_on_device

        if ack.passphrase is not None:
            raise wire.DataError("Passphrase provided when it should not be")
        return await request_passphrase_on_device(ctx, _MAX_PASSPHRASE_LEN)
    if ack.passphrase is None:
        raise wire.DataError(
            "Passphrase not provided and on_device is False. Use empty string to set an empty passphrase."  # 错误信息：未提供密码短语且on_device为False，使用空字符串设置空密码短语
        )
    # # non-empty passphrase
    if ack.passphrase:
        from trezor.ui.layouts import require_confirm_passphrase

        if not await require_confirm_passphrase(ctx, ack.passphrase):
            raise wire.ActionCancelled("Passphrase cancelled")
    return ack.passphrase


def _entry_dialog() -> None:
    from trezor.ui.layouts import draw_simple_text

    draw_simple_text(
        _(i18n_keys.TITLE__ENTER_PASSPHRASE),
        _(i18n_keys.SUBTITLE__ENTER_PASSPHRASE_ON_SOFTWARE),
    )
