import storage.cache
from trezor import loop, res, ui, wire

from . import HomescreenBase


async def lockscreen() -> None:  # 定义锁屏异步函数
    from apps.common.request_pin import can_lock_device  # 导入判断设备是否可以锁定的函数
    from apps.base import unlock_device  # 导入解锁设备的函数

    # Only show the lockscreen UI if the device can in fact be locked.  # 只有当设备实际上可以被锁定时才显示锁屏界面
    if can_lock_device():  # 如果设备可以被锁定
        await Lockscreen()  # 等待显示锁屏界面
    # Otherwise proceed directly to unlock() call. If the device is already unlocked,  # 否则直接调用解锁函数。如果设备已经解锁，
    # it should be a no-op storage-wise, but it resets the internal configuration  # 存储方面不会有操作，但会重置内部配置
    # to an unlocked state.  # 到解锁状态
    try:  # 尝试执行
        await unlock_device()  # 等待解锁设备
    except wire.PinCancelled:  # 捕获PIN取消异常
        pass  # 不做任何处理


class Lockscreen(HomescreenBase):
    BACKLIGHT_LEVEL = ui.BACKLIGHT_LOW
    RENDER_SLEEP = loop.SLEEP_FOREVER
    RENDER_INDICATOR = storage.cache.LOCKSCREEN_ON

    def __init__(self, bootscreen: bool = False) -> None:
        if bootscreen:
            self.BACKLIGHT_LEVEL = ui.BACKLIGHT_NORMAL
            self.lock_label = "Not connected"
            self.tap_label = "Tap to connect"
        else:
            self.lock_label = "Locked"
            self.tap_label = "Tap to unlock"

        super().__init__()

    def do_render(self) -> None:
        # homescreen with label text on top
        ui.display.text_center(
            ui.WIDTH // 2, 35, self.label, ui.BOLD, ui.TITLE_GREY, ui.BG
        )
        ui.display.avatar(48, 48, self.get_image(), ui.WHITE, ui.BLACK)

        # lock bar
        ui.display.bar_radius(40, 100, 160, 40, ui.TITLE_GREY, ui.BG, 4)
        ui.display.bar_radius(42, 102, 156, 36, ui.BG, ui.TITLE_GREY, 4)
        ui.display.text_center(
            ui.WIDTH // 2, 128, self.lock_label, ui.BOLD, ui.TITLE_GREY, ui.BG
        )

        # "tap to unlock"
        ui.display.text_center(
            ui.WIDTH // 2 + 10, 220, self.tap_label, ui.BOLD, ui.TITLE_GREY, ui.BG
        )
        ui.display.icon(45, 202, res.load(ui.ICON_CLICK), ui.TITLE_GREY, ui.BG)

    def on_touch_end(self, _x: int, _y: int) -> None:
        raise ui.Result(None)
