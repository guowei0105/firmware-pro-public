import storage
from trezor import config, io, log, loop, ui, utils, wire
from trezor.lvglui import lvgl_tick
from trezor.pin import show_pin_timeout

lvgl_task = lvgl_tick()  # 创建LVGL定时任务，用于处理LVGL界面刷新


def clear() -> None:
    """if device is not initialized, pin is needless, so clear it"""  # 如果设备未初始化，PIN码不需要，所以清除它
    if not storage.device.is_initialized() and config.has_pin():  # 如果设备未初始化但有PIN码
        storage.wipe()  # 擦除存储
    if config.has_pin() and config.get_pin_rem() == 0:  # 如果有PIN码且剩余尝试次数为0
        storage.wipe()  # 擦除存储
    if not utils.EMULATOR:  # 如果不是模拟器环境
        if storage.device.get_wp_cnts() == 0:  # 如果壁纸计数为0
            for _size, _attrs, name in io.fatfs.listdir("1:/res/wallpapers"):  # 遍历壁纸目录
                io.fatfs.unlink(f"1:/res/wallpapers/{name}")  # 删除壁纸文件


async def bootscreen() -> None:
    from trezor.lvglui.scrs.bootscreen import BootScreen  # 导入启动屏幕
    from trezor.lvglui.scrs.lockscreen import LockScreen  # 导入锁屏
    from apps.common.request_pin import can_lock_device, verify_user_pin  # 导入PIN验证相关函数

    bootscreen = BootScreen()  # 创建启动屏幕实例
    # wait for bootscreen animation to finish  # 等待启动屏幕动画完成
    await loop.sleep(1500)  # 等待1.5秒
    bootscreen.del_delayed(100)  # 延迟100毫秒删除启动屏幕
    # await bootscreen.request()
    lockscreen = LockScreen(storage.device.get_label())  # 创建锁屏实例，使用设备标签
    while True:  # 循环尝试PIN验证
        try:
            if can_lock_device():  # 如果设备可以锁定
                await lockscreen.request()  # 显示锁屏
            await verify_user_pin()  # 验证用户PIN
            storage.init_unlocked()  # 初始化已解锁的存储
            loop.close(lvgl_task)  # 关闭LVGL任务
            return  # 返回，结束函数
        except wire.PinCancelled:  # 捕获PIN取消异常
            # verify_user_pin will convert a SdCardUnavailable (in case of sd salt)
            # to PinCancelled exception.
            # Ignore exception, retry loop.  # 忽略异常，重试循环
            pass
        except BaseException as e:  # 捕获其他所有异常
            # other exceptions here are unexpected and should halt the device  # 其他异常是意外的，应该停止设备
            if __debug__:  # 如果是调试模式
                log.exception(__name__, e)  # 记录异常日志
            utils.halt(e.__class__.__name__)  # 停止设备，显示异常类名


async def boot_animation() -> None:
    from trezor.lvglui.scrs.bootscreen import BootScreen  # 导入启动屏幕
    from apps.common.request_pin import can_lock_device, verify_user_pin  # 导入PIN验证相关函数

    bootscreen = BootScreen()  # 创建启动屏幕实例
    # wait for bootscreen animation to finish  # 等待启动屏幕动画完成
    utils.onekey_firmware_hash()  # 计算固件哈希值
    await loop.sleep(500)  # 等待0.5秒
    bootscreen.del_delayed(100)  # 延迟100毫秒删除启动屏幕
    loop.close(lvgl_task)  # 关闭LVGL任务
    if not utils.USE_THD89:  # 如果不使用THD89
        if not can_lock_device():  # 如果设备不能锁定
            await verify_user_pin(allow_fingerprint=False)  # 验证用户PIN，不允许指纹
            storage.init_unlocked()  # 初始化已解锁的存储


ui.display.backlight(ui.BACKLIGHT_NONE)  # 关闭屏幕背光
config.init(show_pin_timeout)  # 初始化配置，设置PIN超时显示回调
ui.display.backlight(storage.device.get_brightness())  # 设置屏幕背光为存储的亮度值
clear()  # 执行清理函数

# stupid!, so we remove it  # 愚蠢的代码，所以我们移除它
# if __debug__ and not utils.EMULATOR:
#     config.wipe()


loop.schedule(boot_animation())  # 调度启动动画

loop.schedule(lvgl_task)  # 调度LVGL任务

loop.run()  # 运行事件循环
