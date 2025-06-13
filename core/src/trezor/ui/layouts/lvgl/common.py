from typing import TYPE_CHECKING

from trezor import log, loop, wire, workflow
from trezor.enums import ButtonRequestType
from trezor.messages import ButtonAck, ButtonRequest

if TYPE_CHECKING:
    from typing import Any, Awaitable, TypeVar

    T = TypeVar("T")
    LayoutType = Awaitable[Any]
    from ....lvglui.scrs.common import Screen, FullSizeWindow

CANCEL = 0
CONFIRM = 1
SHOW_MORE = 2


async def button_request(
    ctx: wire.GenericContext,
    br_type: str,
    code: ButtonRequestType = ButtonRequestType.Other,
    close_others: bool = True,
) -> None:
    """
    按钮请求处理函数
    
    参数:
    ctx: wire.GenericContext - 通信上下文
    br_type: str - 按钮请求类型
    code: ButtonRequestType - 按钮请求代码,默认为Other类型
    close_others: bool - 是否关闭其他工作流,默认为True
    """
    if __debug__:
        log.debug(__name__, "ButtonRequest.type=%s", br_type)
    # 如果不是虚拟上下文且需要关闭其他工作流
    if not isinstance(ctx, wire.DummyContext) and close_others:
        workflow.close_others()
    # 发送按钮请求并等待确认
    await ctx.call(ButtonRequest(code=code), ButtonAck)


async def raise_if_cancelled(a: Awaitable[T], exc: Any = wire.ActionCancelled) -> T:
    result = await a
    if not result:
        await loop.sleep(300)
        raise exc
    return result


async def interact(
    ctx: wire.GenericContext,
    screen: Screen | FullSizeWindow,
    br_type: str,
    br_code: ButtonRequestType = ButtonRequestType.Other,
) -> Any:
    await button_request(ctx, br_type, br_code)
    return await ctx.wait(screen.request())
