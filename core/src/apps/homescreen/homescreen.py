import utime
from micropython import const
from typing import Tuple

import storage
import storage.cache
import storage.device
from trezor import config, io, loop, ui, utils
from trezor.ui.loader import Loader, LoaderNeutral

from apps.base import lock_device

from . import HomescreenBase

_LOADER_DELAY_MS = const(500)
_LOADER_TOTAL_MS = const(2500)


async def homescreen() -> None:
    await Homescreen()
    lock_device()


class Homescreen(HomescreenBase):
    RENDER_INDICATOR = storage.cache.HOMESCREEN_ON  # 渲染指示器，用于缓存主屏幕状态

    def __init__(self) -> None:
        super().__init__()  # 调用父类初始化方法
        if not storage.device.is_initialized():  # 如果设备未初始化
            self.label = "Go to trezor.io/start"  # 设置标签文本为引导用户访问初始化网站

        self.loader = Loader(  # 创建加载器对象
            style=LoaderNeutral,  # 设置加载器样式为中性
            target_ms=_LOADER_TOTAL_MS - _LOADER_DELAY_MS,  # 设置目标时间（总时间减去延迟时间）
            offset_y=-10,  # 设置Y轴偏移量
            reverse_speedup=3,  # 设置反向加速度
        )
        self.touch_ms: int | None = None  # 初始化触摸时间戳为空

    def create_tasks(self) -> Tuple[loop.AwaitableTask, ...]:
        return super().create_tasks() + (self.usb_checker_task(),)  # 创建任务，包括父类任务和USB检查任务

    async def usb_checker_task(self) -> None:
        usbcheck = loop.wait(io.USB_CHECK)  # 创建USB检查等待事件
        while True:  # 无限循环
            await usbcheck  # 等待USB检查事件
            self.set_repaint(True)  # 设置需要重绘

    def do_render(self) -> None:
        # warning bar on top  # 顶部警告栏
        if storage.device.is_initialized() and storage.device.no_backup():  # 如果设备已初始化但没有备份
            ui.header_error("SEEDLESS")  # 显示无种子错误
        elif storage.device.is_initialized() and storage.device.unfinished_backup():  # 如果设备已初始化但备份未完成
            ui.header_error("BACKUP FAILED!")  # 显示备份失败错误
        elif storage.device.is_initialized() and storage.device.needs_backup():  # 如果设备已初始化但需要备份
            ui.header_warning("NEEDS BACKUP!")  # 显示需要备份警告
        elif storage.device.is_initialized() and not config.has_pin():  # 如果设备已初始化但没有设置PIN码
            ui.header_warning("PIN NOT SET!")  # 显示未设置PIN警告
        elif storage.device.get_experimental_features():  # 如果启用了实验性功能
            ui.header_warning("EXPERIMENTAL MODE!")  # 显示实验模式警告
        else:  # 其他情况
            ui.display.bar(0, 0, ui.WIDTH, ui.get_header_height(), ui.BG)  # 绘制顶部背景条

        # homescreen with shifted avatar and text on bottom  # 主屏幕显示偏移的头像和底部文本
        # Differs for each model  # 根据不同型号有所不同

        if not utils.usb_data_connected():  # 如果USB数据未连接
            ui.header_error("NO USB CONNECTION")  # 显示无USB连接错误

        # TODO: support homescreen avatar change for R and 1  # 待办：支持R和1型号的主屏幕头像更改
        if utils.MODEL in ("T",):  # 如果是T型号
            ui.display.avatar(48, 48 - 10, self.get_image(), ui.WHITE, ui.BLACK)  # 显示头像
        elif utils.MODEL in ("R",):  # 如果是R型号
            icon = "trezor/res/homescreen_model_r.toif"  # 92x92 px  # 设置R型号图标路径
            ui.display.icon(18, 18, ui.res.load(icon), ui.style.FG, ui.style.BG)  # 显示图标
        elif utils.MODEL in ("1",):  # 如果是1型号
            icon = "trezor/res/homescreen_model_1.toif"  # 64x36 px  # 设置1型号图标路径
            ui.display.icon(33, 14, ui.res.load(icon), ui.style.FG, ui.style.BG)  # 显示图标

        label_heights = {"1": 60, "R": 120, "T": 220}  # 不同型号的标签高度
        ui.display.text_center(  # 居中显示文本
            ui.WIDTH // 2, label_heights[utils.MODEL], self.label, ui.BOLD, ui.FG, ui.BG  # 位置、文本和样式
        )

        ui.refresh()  # 刷新显示

    def on_touch_start(self, _x: int, _y: int) -> None:
        if self.loader.start_ms is not None:  # 如果加载器已经启动
            self.loader.start()  # 重新启动加载器
        elif config.has_pin():  # 如果设置了PIN码
            self.touch_ms = utime.ticks_ms()  # 记录触摸开始时间

    def on_touch_end(self, _x: int, _y: int) -> None:
        if self.loader.start_ms is not None:  # 如果加载器已经启动
            ui.display.clear()  # 清除显示
            self.set_repaint(True)  # 设置需要重绘
        self.loader.stop()  # 停止加载器
        self.touch_ms = None  # 清除触摸时间戳

        # raise here instead of self.loader.on_finish so as not to send TOUCH_END to the lockscreen  # 在这里抛出而不是在loader.on_finish中，以避免向锁屏发送TOUCH_END事件
        if self.loader.elapsed_ms() >= self.loader.target_ms:  # 如果经过时间超过目标时间
            raise ui.Result(None)  # 抛出结果，触发锁屏

    def _loader_start(self) -> None:
        ui.display.clear()  # 清除显示
        ui.display.text_center(ui.WIDTH // 2, 35, "Hold to lock", ui.BOLD, ui.FG, ui.BG)  # 显示"按住锁定"提示
        self.loader.start()  # 启动加载器

    def dispatch(self, event: int, x: int, y: int) -> None:
        if (  # 如果触摸持续时间超过延迟时间
            self.touch_ms is not None
            and self.touch_ms + _LOADER_DELAY_MS < utime.ticks_ms()
        ):
            self.touch_ms = None  # 清除触摸时间戳
            self._loader_start()  # 启动加载器

        if event is ui.RENDER and self.loader.start_ms is not None:  # 如果是渲染事件且加载器已启动
            self.loader.dispatch(event, x, y)  # 分发事件到加载器
        else:  # 其他情况
            super().dispatch(event, x, y)  # 调用父类的事件分发方法
