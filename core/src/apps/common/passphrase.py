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

async def get(ctx: wire.Context) -> str:  # 获取密码短语的异步函数
    if is_enabled():  # 如果密码短语功能已启用
        if is_passphrase_pin_enabled():
            # 如果密码短语PIN已启用，则不弹出密码短语输入框
            # 这里应该返回一个空字符串或者预设的密码短语
            # 具体行为取决于您的需求
            print("Passphrase PIN is enabled, skipping passphrase input")
            return ""  # 或者返回预设的密码短语
        if isinstance(ctx, wire.QRContext) and ctx.passphrase is not None:  # 如果是QR上下文且已有密码短语
            return ctx.passphrase  # 直接返回上下文中的密码短语
        return await _request_from_user(ctx)  # 否则从用户请求密码短语
    else:  # 如果密码短语功能未启用
        return ""  # 返回空字符串


async def _request_from_user(ctx: wire.Context) -> str:  # 从用户请求密码短语的内部异步函数
    workflow.close_others()  # 关闭其他工作流，请求独占UI访问权限
    if storage.device.get_passphrase_always_on_device() or issubclass(  # 如果设置为始终在设备上输入密码短语，或者是特定上下文类型
        ctx.__class__, (wire.DummyContext, wire.QRContext)
    ):
        from trezor.ui.layouts import request_passphrase_on_device  # 导入设备上请求密码短语的布局

        passphrase = await request_passphrase_on_device(ctx, _MAX_PASSPHRASE_LEN)  # 在设备上请求密码短语
        if isinstance(ctx, wire.QRContext):  # 如果是QR上下文
            ctx.passphrase = passphrase  # 将密码短语保存到上下文中
    else:  # 否则
        passphrase = await _request_on_host(ctx)  # 在主机上请求密码短语
    if len(passphrase.encode()) > _MAX_PASSPHRASE_LEN:  # 如果密码短语长度超过最大限制
        raise wire.DataError(  # 抛出数据错误
            f"Maximum passphrase length is {_MAX_PASSPHRASE_LEN} bytes"  # 错误信息：密码短语最大长度为50字节
        )
    return passphrase  # 返回密码短语


async def _request_on_host(ctx: wire.Context) -> str:  # 在主机上请求密码短语的内部异步函数
    from trezor.messages import PassphraseAck, PassphraseRequest  # 导入密码短语相关消息类型
    # disable passphrase entry dialog for now  # 暂时禁用密码短语输入对话框
    # _entry_dialog()
    request = PassphraseRequest()  # 创建密码短语请求
    ack = await ctx.call(request, PassphraseAck)  # 等待主机响应密码短语请求
    if ack.on_device:  # 如果主机请求在设备上输入
        from trezor.ui.layouts import request_passphrase_on_device  # 导入设备上请求密码短语的布局
        if ack.passphrase is not None:  # 如果主机同时提供了密码短语
            raise wire.DataError("Passphrase provided when it should not be")  # 抛出错误：不应该提供密码短语
        return await request_passphrase_on_device(ctx, _MAX_PASSPHRASE_LEN)  # 在设备上请求密码短语并返回
    if ack.passphrase is None:  # 如果主机没有提供密码短语且不要求在设备上输入
        raise wire.DataError(  # 抛出数据错误
            "Passphrase not provided and on_device is False. Use empty string to set an empty passphrase."  # 错误信息：未提供密码短语且on_device为False，使用空字符串设置空密码短语
        )
    # # non-empty passphrase  # 非空密码短语
    if ack.passphrase:  # 如果密码短语非空
        from trezor.ui.layouts import require_confirm_passphrase  # 导入确认密码短语的布局
        if not await require_confirm_passphrase(ctx, ack.passphrase):  # 要求用户确认密码短语
            raise wire.ActionCancelled("Passphrase cancelled")  # 如果用户取消，抛出操作取消错误

    return ack.passphrase  # 返回密码短语


def _entry_dialog() -> None:
    from trezor.ui.layouts import draw_simple_text

    draw_simple_text(
        _(i18n_keys.TITLE__ENTER_PASSPHRASE),
        _(i18n_keys.SUBTITLE__ENTER_PASSPHRASE_ON_SOFTWARE),
    )
