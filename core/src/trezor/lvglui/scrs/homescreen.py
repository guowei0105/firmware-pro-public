import gc
import math
from micropython import const
import utime

import storage.cache
import storage.device as storage_device
from trezor import io, loop, uart, utils, wire, workflow
from trezor.enums import SafetyCheckLevel
from trezor.langs import langs, langs_keys
from trezor.lvglui.i18n import gettext as _, i18n_refresh, keys as i18n_keys
from trezor.lvglui.lv_colors import lv_colors
from trezor.lvglui.scrs.components.pageable import Indicator
from trezor.qr import (
    close_camera,
    get_hd_key,
    retrieval_encoder,
    retrieval_hd_key,
    save_app_obj,
    scan_qr,
)
from trezor.ui import display, style

import ujson as json
from apps.common import passphrase, safety_checks

from . import font_GeistRegular20,font_GeistRegular26, font_GeistRegular30, font_GeistSemiBold26,font_GeistSemiBold30,font_GeistSemiBold38, font_GeistSemiBold48
from .address import AddressManager, chains_brief_info
from .common import AnimScreen, FullSizeWindow, Screen, lv  # noqa: F401, F403, F405
from .components.anim import Anim
from .components.banner import LEVEL, Banner
from .components.button import ListItemBtn, ListItemBtnWithSwitch, NormalButton
from .components.container import ContainerFlexCol, ContainerFlexRow, ContainerGrid
from .components.listitem import (
    DisplayItemWithFont_30,
    DisplayItemWithFont_TextPairs,
    ImgGridItem,
    ListItemWithLeadingCheckbox,
)
from .deviceinfo import DeviceInfoManager
from .widgets.style import StyleWrapper

_attach_to_pin_task_running = False

# 动画状态跟踪
_animation_in_progress = False
_animation_start_time = 0
_last_operation_time = 0  # 防止操作过于频繁
_last_jpeg_loaded = None  # 缓存上次加载的JPEG路径
_operation_count = 0  # 操作计数器
_active_timers = []  # 跟踪活动的定时器
_cached_styles = {}  # 缓存样式对象字典

def get_timestamp():
    """获取当前时间戳（毫秒）"""
    return utime.ticks_ms()

def log_with_timestamp(message):
    """带时间戳的日志 - 轻量版"""
    if __debug__ and False:  # 禁用日志输出以提高性能
        timestamp = get_timestamp()
        print(f"[{timestamp}] {message}")
        
def check_operation_frequency():
    """检查操作频率，防止过快操作"""
    global _last_operation_time, _operation_count
    current_time = get_timestamp()
    if current_time - _last_operation_time < 100:  # 100ms 内不允许重复操作
        return False
    
    _last_operation_time = current_time
    _operation_count += 1
    if __debug__ and _operation_count % 5 == 0:  # 每5次操作打印一次内存
        print(f"Operation #{_operation_count}: Memory status: {get_memory_info()}")
    return True

def cleanup_timers():
    """清理所有活动的定时器"""
    global _active_timers
    for timer in _active_timers:
        try:
            if timer:
                timer.delete()
        except:
            pass
    _active_timers.clear()

def force_memory_cleanup():
    """强制内存清理"""
    if __debug__:
        mem_before = gc.mem_alloc()
    
    # 多次垃圾收集
    for i in range(5):  # 增加到5次
        try:
            gc.collect()
        except:
            pass
    
    # 定期清理样式缓存（保留最近使用的2个）
    global _cached_styles
    styles_cleaned = 0
    if len(_cached_styles) > 2:
        # 只保留最后2个，清理其他
        keys = list(_cached_styles.keys())
        for key in keys[:-2]:
            del _cached_styles[key]
            styles_cleaned += 1
    
    if __debug__:
        mem_after = gc.mem_alloc()
        print(f"[GC] Memory cleanup: before {mem_before}B, after {mem_after}B, cleaned {styles_cleaned} styles")
    
    # 注意：不清理定时器和JPEG缓存，避免重复加载和破坏正在运行的动画

def get_cached_style(image_src):
    """获取缓存的样式对象，避免重复创建"""
    global _cached_styles
    if image_src not in _cached_styles:
        _cached_styles[image_src] = StyleWrapper().bg_img_src(image_src).border_width(0)
    return _cached_styles[image_src]

def get_memory_info():
    """获取内存信息"""
    try:
        mem_alloc = gc.mem_alloc()
        mem_free = gc.mem_free()
        return f"{mem_alloc}B used, {mem_free}B free, {mem_alloc + mem_free}B total"
    except:
        return "memory info unavailable"

def brightness2_percent_str(brightness: int) -> str:
    return f"{int(brightness / style.BACKLIGHT_MAX * 100)}%"


GRID_CELL_SIZE_ROWS = const(240)
GRID_CELL_SIZE_COLS = const(144)

APP_DRAWER_UP_TIME = 10
APP_DRAWER_DOWN_TIME = 50
APP_DRAWER_UP_DELAY = 0
APP_DRAWER_DOWN_DELAY = 0
if __debug__:
    PATH_OVER_SHOOT = lv.anim_t.path_overshoot
    PATH_BOUNCE = lv.anim_t.path_bounce
    PATH_LINEAR = lv.anim_t.path_linear
    PATH_EASE_IN_OUT = lv.anim_t.path_ease_in_out
    PATH_EASE_IN = lv.anim_t.path_ease_in
    PATH_EASE_OUT = lv.anim_t.path_ease_out
    PATH_STEP = lv.anim_t.path_step
    APP_DRAWER_UP_PATH_CB = PATH_EASE_OUT
    APP_DRAWER_DOWN_PATH_CB = PATH_EASE_IN_OUT

# Global variables for debouncing busy state
_busy_state_counter = 0
_last_busy_time = 0
_busy_debounce_ms = 1000  # 1 second debounce time
_cleanup_task = None

def _get_persistent_busy_state():
    """Get busy state from storage cache"""
    try:
        import storage.cache
        return storage.cache.get_int(storage.cache.APP_COMMON_BUSY_STATE, 0)
    except:
        return 0

def _get_persistent_busy_time():
    """Get last busy time from storage cache"""
    try:
        import storage.cache
        return storage.cache.get_int(storage.cache.APP_COMMON_BUSY_TIME, 0)
    except:
        return 0

def _set_persistent_busy_state(counter):
    """Set busy state to storage cache"""
    try:
        import storage.cache
        import utime
        
        # Get current saved counter to see if this is the first time going busy
        current_saved = storage.cache.get_int(storage.cache.APP_COMMON_BUSY_STATE, 0)
        
        storage.cache.set_int(storage.cache.APP_COMMON_BUSY_STATE, counter)
        
        # Only update timestamp when going from 0 to non-zero (first busy)
        if current_saved == 0 and counter > 0:
            storage.cache.set_int(storage.cache.APP_COMMON_BUSY_TIME, utime.ticks_ms())
            if __debug__:
                print(f"[PERSISTENT] Saved busy state: {counter} with NEW timestamp {utime.ticks_ms()}")
        else:
            if __debug__:
                print(f"[PERSISTENT] Saved busy state: {counter} (timestamp unchanged)")
    except:
        pass

async def _delayed_cleanup():
    """Delayed cleanup task to restore non-busy state after debounce time"""
    global _busy_state_counter, _cleanup_task
    
    import utime
    from trezor import loop
    
    if __debug__:
        print(f"[CLEANUP] Starting cleanup task, will wait {_busy_debounce_ms}ms")
    
    await loop.sleep(_busy_debounce_ms)
    
    if __debug__:
        print(f"[CLEANUP] Cleanup task woke up, checking state...")
    
    # Check if we should restore non-busy state
    current_time = utime.ticks_ms()
    time_since_last_busy = utime.ticks_diff(current_time, _last_busy_time)
    
    if _busy_state_counter == 0 and time_since_last_busy >= _busy_debounce_ms:
        if __debug__:
            print(f"[CLEANUP] Restoring non-busy state after debounce")
        
        # Clear persistent state now that debounce is complete
        _set_persistent_busy_state(0)
        
        if hasattr(MainScreen, "_instance") and MainScreen._instance:
            # Ensure AppDrawer stays hidden
            if hasattr(MainScreen._instance, 'apps') and MainScreen._instance.apps:
                if not MainScreen._instance.apps.has_flag(lv.obj.FLAG.HIDDEN):
                    MainScreen._instance.apps.hide_to_mainscreen_fallback()
            
            if __debug__:
                print(f"[CLEANUP] Calling MainScreen.change_state(False) to restore normal state")
            MainScreen._instance.change_state(False)
            
            if __debug__:
                print(f"[CLEANUP] MainScreen state restored - should show up arrow and normal text")
    
    _cleanup_task = None

def change_state(is_busy: bool = False):
    global _busy_state_counter, _last_busy_time, _cleanup_task
    
    if __debug__:
        print(f"[CHANGE_STATE] Called with is_busy={is_busy}")
    
    import utime
    from trezor import workflow
    current_time = utime.ticks_ms()
    
    # Initialize from persistent state if needed
    if _busy_state_counter == 0 and _last_busy_time == 0:
        _busy_state_counter = _get_persistent_busy_state()
        if __debug__:
            print(f"[CHANGE_STATE] Loaded persistent counter: {_busy_state_counter}")
    
    if is_busy:
        # Increment busy counter and update timestamp
        _busy_state_counter += 1
        _last_busy_time = current_time
        _set_persistent_busy_state(_busy_state_counter)
        if __debug__:
            print(f"[CHANGE_STATE] Busy counter: {_busy_state_counter}")
    else:
        # Decrement busy counter
        if _busy_state_counter > 0:
            _busy_state_counter -= 1
            # Don't save persistent state here - only save when counter > 0
            if _busy_state_counter > 0:
                _set_persistent_busy_state(_busy_state_counter)
        
        # Only restore to non-busy state if counter is 0 AND enough time has passed
        time_since_last_busy = utime.ticks_diff(current_time, _last_busy_time)
        if _busy_state_counter > 0 or time_since_last_busy < _busy_debounce_ms:
            if __debug__:
                print(f"[CHANGE_STATE] Staying busy - counter: {_busy_state_counter}, time_diff: {time_since_last_busy}ms")
            
            # Schedule cleanup task if not already scheduled and counter is 0
            if _busy_state_counter == 0 and _cleanup_task is None:
                if __debug__:
                    print(f"[CHANGE_STATE] Scheduling cleanup task")
                _cleanup_task = workflow.spawn(_delayed_cleanup())
            
            return  # Don't change to non-busy state yet
        
        if __debug__:
            print(f"[CHANGE_STATE] Restoring non-busy state - counter: {_busy_state_counter}")
        
        # Cancel cleanup task if it exists
        if _cleanup_task is not None:
            _cleanup_task = None
        
        # Don't clear persistent state here - let cleanup task handle it
    
    if hasattr(MainScreen, "_instance") and MainScreen._instance:
        # When setting busy state, ensure MainScreen is visible
        if is_busy:
            # Make sure MainScreen is the active screen
            if not MainScreen._instance.is_visible():
                if __debug__:
                    print(f"[CHANGE_STATE] MainScreen not visible, switching to it")
                lv.scr_load(MainScreen._instance)
            else:
                if __debug__:
                    print(f"[CHANGE_STATE] MainScreen already visible")
            
            # Hide AppDrawer if it's visible
            if hasattr(MainScreen._instance, 'apps') and MainScreen._instance.apps:
                if not MainScreen._instance.apps.has_flag(lv.obj.FLAG.HIDDEN):
                    if __debug__:
                        print(f"[CHANGE_STATE] Hiding AppDrawer to show MainScreen")
                    MainScreen._instance.apps.hide_to_mainscreen_fallback()
        else:
            # When restoring from busy state, ensure AppDrawer stays hidden
            if hasattr(MainScreen._instance, 'apps') and MainScreen._instance.apps:
                if not MainScreen._instance.apps.has_flag(lv.obj.FLAG.HIDDEN):
                    if __debug__:
                        print(f"[CHANGE_STATE] Ensuring AppDrawer stays hidden after communication")
                    MainScreen._instance.apps.hide_to_mainscreen_fallback()
        
        MainScreen._instance.change_state(is_busy)
    elif is_busy:
        # If MainScreen instance doesn't exist, create and show it
        if __debug__:
            print(f"[CHANGE_STATE] MainScreen instance doesn't exist, creating it")
        main_screen = MainScreen()
        lv.scr_load(main_screen)
        main_screen.change_state(is_busy)

class MainScreen(Screen):
    def __init__(self, device_name=None, ble_name=None, dev_state=None):
        # homescreen = storage_device.get_homescreen()
        lockscreen = storage_device.get_homescreen()
        if not hasattr(self, "_init"):
            self._init = True
            # self._cached_lockscreen = lockscreen
            
            # Check if device name display is enabled
            show_device_names = storage_device.is_device_name_display_enabled()
            
            # Get real device names
            real_device_name = storage_device.get_model()  # "OneKey Pro"
            real_ble_name = storage_device.get_ble_name() or uart.get_ble_name()
            
            # Debug output
            if __debug__:
                print(f"[MAINSCREEN] Init - show_device_names: {show_device_names}, device: {real_device_name}, ble: {real_ble_name}")
            
            # Initialize Screen with proper kwargs
            if show_device_names:
                super().__init__(title=real_device_name, subtitle=real_ble_name)
                self.title.add_style(StyleWrapper().text_align_center(), 0)
                self.subtitle.add_style(
                    StyleWrapper().text_align_center().text_color(lv_colors.WHITE), 0
                )
            else:
                super().__init__()
                if __debug__:
                    print(f"[MAINSCREEN] Not showing device names, initialized without title/subtitle")
            
            # Set background for first-time initialization
            self.add_style(
                StyleWrapper().bg_img_src(lockscreen),
                0,
            )
            if __debug__:
                print(f"MainScreen: Initial background set to {lockscreen}")
        else:
            # Check if device name display setting has changed
            show_device_names = storage_device.is_device_name_display_enabled()
            
            # Get real device names
            real_device_name = storage_device.get_model()  # "OneKey Pro"
            real_ble_name = storage_device.get_ble_name() or uart.get_ble_name()
            
            # Update title and subtitle based on current setting
            if __debug__:
                print(f"[MAINSCREEN] Else branch - show_device_names: {show_device_names}, device: {real_device_name}, ble: {real_ble_name}")
            
            if show_device_names:
                # Check if title and subtitle exist before using them
                if hasattr(self, 'title') and self.title:
                    self.title.set_text(real_device_name)
                    self.title.clear_flag(lv.obj.FLAG.HIDDEN)
                if hasattr(self, 'subtitle') and self.subtitle:
                    self.subtitle.set_text(real_ble_name)
                    self.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)
                if __debug__:
                    print(f"[MAINSCREEN] Else branch - titles set and shown")
            else:
                # Hide device names if they exist
                if hasattr(self, 'title') and self.title:
                    self.title.add_flag(lv.obj.FLAG.HIDDEN)
                    self.title.set_text("")
                if hasattr(self, 'subtitle') and self.subtitle:
                    self.subtitle.add_flag(lv.obj.FLAG.HIDDEN)
                    self.subtitle.set_text("")
                if __debug__:
                    print(f"[MAINSCREEN] Else branch - titles hidden and cleared")
            
            # if (
            #     not hasattr(self, "_cached_lockscreen")
            #     or self._cached_lockscreen != lockscreen
            # ):
            #     self._cached_lockscreen = lockscreen
            lockscreen = storage_device.get_homescreen()
            self.add_style(
                    StyleWrapper().bg_img_src(lockscreen),
                    0,
                )
            if __debug__:
                print(f"MainScreen: Background refreshed to {lockscreen}")
            if hasattr(self, "dev_state"):
                from apps.base import get_state

                state = get_state()
                if state:
                    self.dev_state.show(state)
                else:
                    self.dev_state.delete()
                    del self.dev_state
            if self.bottom_tips:
                self.bottom_tips.set_text(_(i18n_keys.BUTTON__SWIPE_TO_SHOW_APPS))
                self.up_arrow.align_to(self.bottom_tips, lv.ALIGN.OUT_TOP_MID, 0, -8)
            if self.apps:
                self.apps.refresh_text()
                # 刷新AppDrawer背景以确保壁纸更新后背景同步更新
                self.refresh_appdrawer_background()
            return
        # Align title and subtitle if they exist
        if hasattr(self, 'title') and self.title:
            self.title.align_to(self.content_area, lv.ALIGN.TOP_MID, 0, 76)
        if hasattr(self, 'subtitle') and self.subtitle:
            if hasattr(self, 'title') and self.title:
                self.subtitle.align_to(self.title, lv.ALIGN.OUT_BOTTOM_MID, 0, 16)
            else:
                self.subtitle.align_to(self.content_area, lv.ALIGN.TOP_MID, 0, 76)
        if dev_state:
            self.dev_state = MainScreen.DevStateTipsBar(self)
            # Align to subtitle if it exists, otherwise to title, otherwise to content area
            if hasattr(self, 'subtitle') and self.subtitle:
                self.dev_state.align_to(self.subtitle, lv.ALIGN.OUT_BOTTOM_MID, 0, 48)
            elif hasattr(self, 'title') and self.title:
                self.dev_state.align_to(self.title, lv.ALIGN.OUT_BOTTOM_MID, 0, 48)
            else:
                self.dev_state.align_to(self.content_area, lv.ALIGN.TOP_MID, 0, 124)
            self.dev_state.show(dev_state)
        self.add_style(
            StyleWrapper().bg_img_src(storage_device.get_homescreen()),
            0,
        )
        self.clear_flag(lv.obj.FLAG.SCROLLABLE)
        self.bottom_tips = lv.label(self.content_area)
        self.bottom_tips.set_long_mode(lv.label.LONG.WRAP)
        self.bottom_tips.set_size(456, lv.SIZE.CONTENT)
        self.bottom_tips.set_text(_(i18n_keys.BUTTON__SWIPE_TO_SHOW_APPS))
        self.bottom_tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .text_color(lv_colors.WHITE)
            .text_align_center(),
            0,
        )
        self.bottom_tips.align(lv.ALIGN.BOTTOM_MID, 0, 0)
        self.up_arrow = lv.img(self.content_area)
        self.up_arrow.set_src("A:/res/up-home.png")
        self.up_arrow.align_to(self.bottom_tips, lv.ALIGN.OUT_TOP_MID, 0, -8)
        
        self.apps = self.AppDrawer(self)
        self.set_size(480, 800)
        
        # 默认显示AppDrawer而不是MainScreen
        # 隐藏MainScreen元素
        self.hidden_others(True)
        if hasattr(self, 'up_arrow'):
            self.up_arrow.add_flag(lv.obj.FLAG.HIDDEN)
        if hasattr(self, 'bottom_tips'):
            self.bottom_tips.add_flag(lv.obj.FLAG.HIDDEN)
            
        # Check if we're in busy state - if so, don't show AppDrawer
        global _busy_state_counter, _last_busy_time
        
        # Load persistent state if not already loaded
        if _busy_state_counter == 0 and _last_busy_time == 0:
            _busy_state_counter = _get_persistent_busy_state()
            if __debug__:
                print(f"MainScreen: Loaded persistent busy counter: {_busy_state_counter}")
        
        # Check if we should clear old busy state (no active communication for a while)
        import utime
        current_time = utime.ticks_ms()
        
        # If we have a saved busy state, check if it's too old
        if _busy_state_counter > 0:
            last_busy_time = _get_persistent_busy_time()
            time_since_last_busy = utime.ticks_diff(current_time, last_busy_time)
            
            if __debug__:
                print(f"MainScreen: Checking busy state age - current: {current_time}, last_busy: {last_busy_time}, diff: {time_since_last_busy}ms")
            
            # If more than 3 seconds have passed since last busy activity, clear it
            if time_since_last_busy > 3000:  # 3 seconds
                if __debug__:
                    print(f"MainScreen: Clearing old busy state (last activity {time_since_last_busy}ms ago)")
                _busy_state_counter = 0
                _set_persistent_busy_state(0)
            else:
                if __debug__:
                    print(f"MainScreen: Keeping busy state (activity only {time_since_last_busy}ms ago)")
        
        if _busy_state_counter > 0:
            # Keep AppDrawer hidden during busy state
            self.apps.add_flag(lv.obj.FLAG.HIDDEN)
            self.apps.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.apps.visible = False
            print("MainScreen: Staying in MainScreen view (busy state)")
            
            # Show MainScreen elements including title and subtitle
            if hasattr(self, 'title') and self.title:
                self.title.clear_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self, 'subtitle') and self.subtitle:
                self.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self, 'up_arrow'):
                self.up_arrow.add_flag(lv.obj.FLAG.HIDDEN)  # Hide during busy
            if hasattr(self, 'bottom_tips'):
                self.bottom_tips.clear_flag(lv.obj.FLAG.HIDDEN)
                self.bottom_tips.set_text(_(i18n_keys.BUTTON__PROCESSING))
        else:
            # Check if device is locked before showing AppDrawer
            from trezor import config
            from . import fingerprints
            
            if not config.is_unlocked() or not fingerprints.is_unlocked():
                # Device is locked, keep MainScreen visible without showing AppDrawer
                if hasattr(self, 'title') and self.title:
                    self.title.clear_flag(lv.obj.FLAG.HIDDEN)
                if hasattr(self, 'subtitle') and self.subtitle:
                    self.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)
                if hasattr(self, 'up_arrow'):
                    self.up_arrow.add_flag(lv.obj.FLAG.HIDDEN)
                if hasattr(self, 'bottom_tips'):
                    self.bottom_tips.clear_flag(lv.obj.FLAG.HIDDEN)
                    self.bottom_tips.set_text("")  # Clear processing text
                print("MainScreen: Device locked, staying in MainScreen view")
            else:
                # Device is unlocked, show AppDrawer
                self.apps.clear_flag(lv.obj.FLAG.HIDDEN)
                self.apps.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
                self.apps.visible = True
                self.apps._showing = False
                print("MainScreen: Default to AppDrawer view")
        
        # 为 MainScreen 添加手势处理
        self.add_event_cb(self.on_main_gesture, lv.EVENT.GESTURE, None)
        print("MainScreen: Added gesture event handler")
        
        save_app_obj(self)

    def on_main_gesture(self, event_obj):
        """处理 MainScreen 的手势事件 - 严格控制：只有MainScreen可见时才允许UP手势"""
        global _animation_in_progress
        code = event_obj.code
        if code == lv.EVENT.GESTURE:
            # 如果动画正在进行，忽略手势
            if _animation_in_progress:
                return
            
            # 检查AppDrawer是否可见
            if hasattr(self, 'apps') and self.apps:
                is_app_drawer_hidden = self.apps.has_flag(lv.obj.FLAG.HIDDEN)
                if not is_app_drawer_hidden:
                    # AppDrawer可见时，MainScreen不处理任何手势
                    return
                
            # 只有AppDrawer隐藏时（MainScreen可见），才允许UP手势
            indev = lv.indev_get_act()
            _dir = indev.get_gesture_dir()
            
            # 严格控制：只允许UP手势
            if _dir == lv.DIR.TOP:
                self.refresh_appdrawer_background()
                self.show_appdrawer_simple()
                
    def show_appdrawer_simple(self):
        """显示AppDrawer，带layer2动画"""
        global _animation_in_progress, _animation_start_time
        
        # 防止重复调用
        if _animation_in_progress:
            return
            
        # 检查操作频率
        if not check_operation_frequency():
            return
            
        if __debug__:
            global _operation_count
            print(f"MainScreen: Starting show_appdrawer (operation #{_operation_count})")
        log_with_timestamp("MainScreen: === show_appdrawer_simple START ===")
        
        if hasattr(self, 'apps') and self.apps:
            try:
                _animation_in_progress = True
                _animation_start_time = get_timestamp()
                log_with_timestamp(f"MainScreen: Animation started, setting _animation_in_progress = True")
                
                from trezorui import Display
                display = Display()
                
                # 步骤1: 加载并显示 layer2 背景
                if hasattr(display, 'cover_background_load_jpeg'):
                    try:
                        from storage import device
                        lockscreen_path = device.get_homescreen()
                        
                        if not lockscreen_path:
                            display_path = "res/wallpaper-1.jpg"
                        else:
                            if lockscreen_path.startswith("A:/"):
                                # Special handling for NFT files
                                if "/res/nfts/" in lockscreen_path:
                                    display_path = "1:" + lockscreen_path[2:]  # A:/res/nfts/... -> 1:/res/nfts/...
                                else:
                                    display_path = lockscreen_path[3:]  # A:/res/wallpapers/... -> res/wallpapers/...
                            elif lockscreen_path.startswith("A:1:"):
                                display_path = lockscreen_path[2:]  # A:1:/res/wallpapers/xxx -> 1:/res/wallpapers/xxx
                            else:
                                display_path = lockscreen_path
                        
                        if __debug__:
                            log_with_timestamp(f"MainScreen: Layer2 path conversion: {lockscreen_path} -> {display_path}")
                        
                        # 检查是否需要重新加载JPEG
                        global _last_jpeg_loaded
                        if _last_jpeg_loaded != display_path:
                            # 尝试释放内存后再加载
                            gc.collect()
                            if __debug__:
                                print(f"MainScreen: Memory before JPEG load: {get_memory_info()}")
                            display.cover_background_load_jpeg(display_path)
                            _last_jpeg_loaded = display_path
                            if __debug__:
                                print(f"MainScreen: Layer2 background loaded: {display_path}")
                                print(f"MainScreen: Memory after JPEG load: {get_memory_info()}")
                        else:
                            if __debug__:
                                print(f"MainScreen: Layer2 background already loaded, skipping: {display_path}")
                        
                    except Exception:
                        # 使用纯黑色背景作为备用
                        if hasattr(display, 'cover_background_set_image'):
                            width, height = 480, 800
                            black_image = bytearray(width * height * 2)
                            for i in range(len(black_image)):
                                black_image[i] = 0x00
                            display.cover_background_set_image(bytes(black_image))
                        log_with_timestamp("MainScreen: Layer2 fallback to black background")
                
                # 步骤2: 显示 layer2（初始位置在屏幕顶部）
                if hasattr(display, 'cover_background_animate_to_y'):
                    # 关键修改：先显示Layer2再设置位置，避免提前启用未完全配置的Layer
                    if hasattr(display, 'cover_background_set_visible'):
                        display.cover_background_set_visible(True)
                    if hasattr(display, 'cover_background_show'):
                        display.cover_background_show()  # 先显示，此时已正确配置
                    display.cover_background_move_to_y(0)  # 然后设置位置
                    log_with_timestamp("MainScreen: Layer2 shown at screen top")
                    
                    # 步骤3: 立即显示 AppDrawer 并恢复其原始背景（此时被layer2覆盖）
                    def show_appdrawer_behind_layer2():
                        # 隐藏MainScreen元素
                        self.hidden_others(True)
                        if hasattr(self, 'up_arrow'):
                            self.up_arrow.add_flag(lv.obj.FLAG.HIDDEN)
                        if hasattr(self, 'bottom_tips'):
                            self.bottom_tips.add_flag(lv.obj.FLAG.HIDDEN)
                            
                        # 显示AppDrawer
                        self.apps.clear_flag(lv.obj.FLAG.HIDDEN)
                        self.apps.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
                        self.apps.visible = True
                        
                        # 恢复 AppDrawer 的原始背景 (2222.png)
                        current_homescreen = storage_device.get_appdrawer_background()
                        self.apps.add_style(
                            get_cached_style(current_homescreen),
                            0,
                        )
                        log_with_timestamp("MainScreen: AppDrawer shown behind layer2")
                    
                    # 立即显示 AppDrawer
                    show_appdrawer_behind_layer2()
                    log_with_timestamp("MainScreen: AppDrawer display sequence completed")
                    
                    # 步骤4: 延迟后让 layer2 向上滑出到屏幕外
                    def start_layer2_animation():
                        # 动画开始前禁用LVGL自动刷新，避免与Layer动画冲突
                        try:
                            lv.timer_handler_pause()
                        except:
                            pass  # 如果方法不存在则忽略
                        
                        display.cover_background_animate_to_y(-800, 200)  # 200ms 动画 (优化响应速度)
                        log_with_timestamp("MainScreen: Layer2 started sliding up animation (200ms)")
                        
                        # 动画完成后恢复LVGL刷新
                        try:
                            lv.timer_handler_resume()
                        except:
                            pass  # 如果方法不存在则忽略
                        
                        # 步骤5: 动画完成后隐藏 layer2
                        def on_slide_complete():
                            global _animation_in_progress
                            log_with_timestamp("MainScreen: === Animation complete callback ===")
                            if hasattr(display, 'cover_background_hide'):
                                display.cover_background_hide()
                                log_with_timestamp("MainScreen: Layer2 hidden after slide up animation")
                            _animation_in_progress = False
                            elapsed = get_timestamp() - _animation_start_time
                            log_with_timestamp(f"MainScreen: Animation completed, total time: {elapsed}ms, setting _animation_in_progress = False")
                            # 清理定时器并强制内存清理
                            cleanup_timers()
                            force_memory_cleanup()
                            if __debug__:
                                print(f"MainScreen: Memory after animation complete: {get_memory_info()}")
                            
                            # 确保LVGL刷新已恢复
                            try:
                                lv.timer_handler_resume()
                            except:
                                pass  # 如果方法不存在或已经恢复则忽略
                        
                        # 动画完成后隐藏 layer2
                        completion_timer = lv.timer_create(
                            lambda t: on_slide_complete(),
                            200, None  # 200ms 动画 (与动画时间匹配)
                        )
                        completion_timer.set_repeat_count(1)
                        # 跟踪定时器
                        global _active_timers
                        _active_timers.append(completion_timer)
                    
                    # 20ms 延迟后开始 layer2 向上滑动动画 (优化响应速度)
                    animation_timer = lv.timer_create(
                        lambda t: start_layer2_animation(),
                        20, None
                    )
                    animation_timer.set_repeat_count(1)
                    # 跟踪定时器
                    _active_timers.append(animation_timer)
                    log_with_timestamp("MainScreen: Layer2 animation timer created (20ms delay)")
                    
            except Exception as e:
                print(f"MainScreen: Error in show_appdrawer_simple: {e}")
                # 出错时使用简单方式显示AppDrawer
                self.hidden_others(True)
                if hasattr(self, 'up_arrow'):
                    self.up_arrow.add_flag(lv.obj.FLAG.HIDDEN)
                if hasattr(self, 'bottom_tips'):
                    self.bottom_tips.add_flag(lv.obj.FLAG.HIDDEN)
                self.apps.clear_flag(lv.obj.FLAG.HIDDEN)
                self.apps.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
                self.apps.visible = True
                print("MainScreen: AppDrawer shown via fallback method")
    
    def show_layer2_and_appdrawer(self):
        """显示 layer2 并恢复 AppDrawer，然后让 layer2 向上滑出"""
        try:
            from trezorui import Display
            display = Display()
            
            # 步骤1: 加载并显示 layer2
            if hasattr(display, 'cover_background_load_jpeg'):
                try:
                    from storage import device
                    lockscreen_path = device.get_homescreen()
                    
                    if not lockscreen_path:
                        display_path = "res/wallpaper-1.jpg"
                    else:
                        if lockscreen_path.startswith("A:/"):
                            display_path = lockscreen_path[3:]  # 为display系统创建专门变量
                        elif lockscreen_path.startswith("A:1:"):
                            display_path = lockscreen_path[2:]  # A:1:/res/wallpapers/xxx -> 1:/res/wallpapers/xxx
                        else:
                            display_path = lockscreen_path
                    
                    if __debug__:
                        print(f"MainScreen: Layer2 path conversion (2): {lockscreen_path} -> {display_path}")
                    display.cover_background_load_jpeg(display_path)
                    print("MainScreen: Layer2 background loaded")
                    
                except Exception:
                    # 使用纯黑色背景作为备用
                    if hasattr(display, 'cover_background_set_image'):
                        width, height = 480, 800
                        black_image = bytearray(width * height * 2)
                        for i in range(len(black_image)):
                            black_image[i] = 0x00
                        display.cover_background_set_image(bytes(black_image))
                    print("MainScreen: Layer2 fallback to black background")
            
            # 步骤2: 显示 layer2（初始位置在屏幕顶部，准备向下显示）
            if hasattr(display, 'cover_background_animate_to_y'):
                # 关键修改：先显示Layer2再设置位置，避免提前启用未完全配置的Layer
                if hasattr(display, 'cover_background_set_visible'):
                    display.cover_background_set_visible(True)
                if hasattr(display, 'cover_background_show'):
                    display.cover_background_show()  # 先显示，此时已正确配置
                display.cover_background_move_to_y(0)  # 然后设置位置
                print("MainScreen: Layer2 shown at screen top")
                
                # 步骤3: 立即显示 AppDrawer 并恢复其原始背景（此时被layer2覆盖）
                def show_appdrawer_behind_layer2():
                    if hasattr(self.apps, 'show'):
                        # 使用 show() 方法来正确显示 AppDrawer
                        # show() 方法会：
                        # 1. 清除 HIDDEN 标志
                        # 2. 设置 visible = True
                        # 3. 清除 FLAG.GESTURE_BUBBLE 标志，确保手势不会冒泡
                        self.apps.show()
                        # 恢复 AppDrawer 的原始背景 (2222.png)
                        current_homescreen = storage_device.get_appdrawer_background()
                        self.apps.add_style(
                            StyleWrapper().bg_img_src(current_homescreen).border_width(0),
                            0,
                        )
                        print("MainScreen: AppDrawer shown behind layer2 with proper gesture handling")
                
                # 短暂延迟后显示 AppDrawer（让 layer2 先显示完毕）
                show_timer = lv.timer_create(
                    lambda t: show_appdrawer_behind_layer2(),
                    50, None  # 50ms 延迟
                )
                show_timer.set_repeat_count(1)
                
                # 步骤4: 延迟后让 layer2 向上滑出到屏幕外
                def start_layer2_animation():
                    display.cover_background_animate_to_y(-800, 200)  # 200ms 动画 (优化响应速度)
                    print("MainScreen: Layer2 started sliding up animation")
                    
                    # 步骤5: 动画完成后隐藏 layer2
                    def on_slide_complete():
                        if hasattr(display, 'cover_background_hide'):
                            display.cover_background_hide()
                            print("MainScreen: Layer2 hidden after slide up animation")
                    
                    # 动画完成后隐藏 layer2
                    completion_timer = lv.timer_create(
                        lambda t: on_slide_complete(),
                        350, None  # 300ms 动画 + 50ms 缓冲
                    )
                    completion_timer.set_repeat_count(1)
                
                # 100ms 延迟后开始 layer2 向上滑动动画 (优化响应速度)
                animation_timer = lv.timer_create(
                    lambda t: start_layer2_animation(),
                    100, None  # 100ms 延迟 (从150ms减少)
                )
                animation_timer.set_repeat_count(1)
                
        except Exception as e:
            print(f"MainScreen: Error in show_layer2_and_appdrawer: {e}")

    def hidden_others(self, hidden: bool = True):
        if hidden:
            if hasattr(self, "title"):
                self.title.add_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self, "subtitle"):
                self.subtitle.add_flag(lv.obj.FLAG.HIDDEN)
        else:
            if hasattr(self, "title"):
                self.title.clear_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self, "subtitle"):
                self.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)
    
    def refresh_appdrawer_background(self):
        """刷新AppDrawer的背景"""
        if hasattr(self, 'apps') and self.apps:
            self.apps.refresh_background()
            print("MainScreen: AppDrawer background refreshed")

    def change_state(self, busy: bool):
        if busy:
            self.clear_flag(lv.obj.FLAG.CLICKABLE)
            self.up_arrow.add_flag(lv.obj.FLAG.HIDDEN)
            self.bottom_tips.set_text(_(i18n_keys.BUTTON__PROCESSING))
            
            # Ensure title and subtitle are visible during busy state
            if hasattr(self, 'title') and self.title:
                self.title.clear_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self, 'subtitle') and self.subtitle:
                self.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)
        else:
            self.add_flag(lv.obj.FLAG.CLICKABLE)
            self.up_arrow.clear_flag(lv.obj.FLAG.HIDDEN)
            self.bottom_tips.set_text(_(i18n_keys.BUTTON__SWIPE_TO_SHOW_APPS))
            
            # Keep title and subtitle visible in non-busy state too
            if hasattr(self, 'title') and self.title:
                self.title.clear_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self, 'subtitle') and self.subtitle:
                self.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)


    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)

    class DevStateTipsBar(lv.obj):
        def __init__(self, parent) -> None:
            super().__init__(parent)
            self.remove_style_all()
            self.set_size(432, 64)
            self.add_style(
                StyleWrapper()
                .bg_color(lv.color_hex(0x332C00))
                .bg_opa(lv.OPA._50)
                .border_width(1)
                .border_color(lv.color_hex(0xC1A400))
                .pad_ver(16)
                .pad_hor(24)
                .radius(40)
                .text_color(lv.color_hex(0xE0BC00))
                .text_font(font_GeistRegular26)
                .text_align_left(),
                0,
            )
            self.icon = lv.img(self)
            self.icon.set_align(lv.ALIGN.LEFT_MID)
            self.icon.set_src("A:/res/alert-warning-yellow-solid.png")
            self.warnings = lv.label(self)
            self.warnings.align_to(self.icon, lv.ALIGN.OUT_RIGHT_MID, 8, 0)

        def show(self, text=None):
            self.clear_flag(lv.obj.FLAG.HIDDEN)
            if text:
                self.warnings.set_text(text)

        def hidden(self):
            self.add_flag(lv.obj.FLAG.HIDDEN)


    class AppDrawer(lv.obj):
        PAGE_SIZE = 2

        def __init__(self, parent):
            super().__init__(parent)
            self.parent = parent
            self.visible = False  # 简化状态管理，只保留必要的标志
            self.text_label = {}
            self.init_ui()
            self.init_items()
            self.init_indicators()
            self.init_anim()

        def init_ui(self):
            self.remove_style_all()
            self.set_pos(0, 0)
            self.set_size(lv.pct(100), lv.pct(100))
            self.add_style(
                StyleWrapper().bg_opa(lv.OPA.COVER).bg_color(lv_colors.BLACK).border_width(0),
                0,
            )
            homescreen = storage_device.get_appdrawer_background()
            if homescreen:
                self.add_style(
                    StyleWrapper().bg_img_src(homescreen).border_width(0),
                    0,
                )
            # If homescreen is empty, keep the existing black background

            self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

            # Initially allow gesture bubbling when AppDrawer is hidden
            # This will be managed by show/hide methods
            self.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.add_event_cb(self.on_gesture, lv.EVENT.GESTURE, None)

            self.main_cont = lv.obj(self)
            self.main_cont.set_size(480, 750)
            self.main_cont.set_pos(64, 75)
            self.main_cont.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
            self.main_cont.set_style_pad_all(0, 0)
            self.main_cont.set_style_border_width(0, 0)
            self.main_cont.set_style_bg_opa(lv.OPA.TRANSP, 0)
            self.clear_flag(lv.obj.FLAG.SCROLLABLE)

            self.current_page = 0
            self.page_items = [[] for _ in range(2)]

        def init_items(self):
            if utils.BITCOIN_ONLY:
                items = [
                    ("connect", "app-connect", i18n_keys.APP__CONNECT_WALLET),
                    ("scan", "app-scan", i18n_keys.APP__SCAN),
                    ("my_address", "app-address", i18n_keys.APP__ADDRESS),
                    ("settings", "app-settings", i18n_keys.APP__SETTINGS),
                    ("backup", "app-backup", i18n_keys.APP__BACK_UP),
                    ("nft", "app-nft", i18n_keys.APP__NFT_GALLERY),
                    ("guide", "app-tips", i18n_keys.APP__TIPS),
                ]
            else:
                items = [
                    ("connect", "app-connect", i18n_keys.APP__CONNECT_WALLET),
                    ("scan", "app-scan", i18n_keys.APP__SCAN),
                    ("my_address", "app-address", i18n_keys.APP__ADDRESS),
                    ("settings", "app-settings", i18n_keys.APP__SETTINGS),
                    ("passkey", "app-keys", i18n_keys.FIDO_FIDO_KEYS_LABEL),
                    ("backup", "app-backup", i18n_keys.APP__BACK_UP),
                    ("nft", "app-nft", i18n_keys.APP__NFT_GALLERY),
                    ("guide", "app-tips", i18n_keys.APP__TIPS),
                ]

            items_per_page = 6
            cols = 2
            rows = 2  # 2 columns × 3 rows = 6 items per page
            item_width = 144
            item_height = 214
            col_gap = 48
            row_gap = 24

            for idx, (name, img, text) in enumerate(items):
                page = idx // items_per_page
                page_idx = idx % items_per_page
                # Fix grid calculation: For a 2×3 grid, divide by cols to get row
                row = page_idx // cols  # Fixed: was page_idx // rows
                col = page_idx % cols
                x = col * (item_width + col_gap)
                y = row * (item_height + row_gap)

                item = self.create_item(name, img, text, x, y)
                self.page_items[page].append(item)
                if page != 0:
                    item.add_flag(lv.obj.FLAG.HIDDEN)

        def create_item(self, name, img_src, text_key, x, y):
            cont = lv.obj(self.main_cont)
            cont.add_style(
                StyleWrapper()
                .bg_color(lv_colors.BLACK)
                .bg_opa(lv.OPA.TRANSP)
                .radius(0)
                .border_width(0)
                .pad_all(0),
                0,
            )
            cont.set_size(144, 214)  # Updated to match main branch
            cont.set_pos(x, y)
            cont.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

            btn = lv.imgbtn(cont)
            btn.set_size(144, 144)  # Updated to match main branch
            btn.set_style_bg_img_src(f"A:/res/{img_src}.png", 0)  # Changed from .jpg to .png
            btn.add_style(
                StyleWrapper()
                # .bg_img_recolor_opa(lv.OPA._30)  # Commented out like main branch
                .bg_img_recolor(lv_colors.BLACK),
                lv.PART.MAIN | lv.STATE.PRESSED,
            )
            btn.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
            btn.align(lv.ALIGN.TOP_MID, 0, 0)
            btn.set_style_border_width(0, 0)  
            btn.clear_flag(lv.obj.FLAG.SCROLLABLE)
            btn.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)

            label = lv.label(cont)
            label.set_text(_(text_key))
            label.add_style(
                StyleWrapper()
                .width(144)  # Updated to match button width
                .text_font(font_GeistSemiBold26)
                .text_color(lv_colors.WHITE)
                .text_align_center(),
                0,
            )

            label.align_to(btn, lv.ALIGN.OUT_BOTTOM_MID, 0, 8)

            self.text_label[text_key] = label

            btn.add_event_cb(
                lambda e: self.on_pressed(text_key), lv.EVENT.PRESSED, None
            )
            btn.add_event_cb(
                lambda e: self.on_released(text_key), lv.EVENT.RELEASED, None
            )
            btn.add_event_cb(lambda e: self.on_item_click(name), lv.EVENT.CLICKED, None)
            return cont

        def create_down_arrow(self):
            img_down = lv.imgbtn(self)
            img_down.set_size(40, 40)
            img_down.set_style_bg_img_src("A:/res/slide-down.jpg", 0)
            img_down.align(lv.ALIGN.TOP_MID, 0, 64)
            img_down.add_event_cb(lambda e: self.dismiss(), lv.EVENT.CLICKED, None)
            img_down.set_ext_click_area(100)

        def init_indicators(self):
            self.container = ContainerFlexRow(self, None, padding_col=0)
            self.container.align(lv.ALIGN.BOTTOM_MID, 0, -32)
            self.indicators = [
                Indicator(self.container, i) for i in range(self.PAGE_SIZE)
            ]

        def init_anim(self):
            self.show_anim = Anim(
                130,
                75,
                self.set_position,
                start_cb=self.show_anim_start_cb,
                delay=APP_DRAWER_UP_DELAY,
                time=APP_DRAWER_UP_TIME,
                path_cb=lv.anim_t.path_linear
                if not __debug__
                else APP_DRAWER_UP_PATH_CB,
            )
            self.dismiss_anim = Anim(
                75,
                130,
                self.set_position,
                path_cb=lv.anim_t.path_linear
                if not __debug__
                else APP_DRAWER_DOWN_PATH_CB,
                time=50 if not __debug__ else APP_DRAWER_DOWN_TIME,
                start_cb=self.dismiss_anim_start_cb,
                del_cb=self.dismiss_anim_del_cb,
                delay=0 if not __debug__ else APP_DRAWER_DOWN_DELAY,
            )

        def set_position(self, val):
            pass
                # self.main_cont.set_y(val)

        def on_gesture(self, event_obj):
            global _animation_in_progress
            code = event_obj.code
            is_hidden = self.has_flag(lv.obj.FLAG.HIDDEN)
            
            if _animation_in_progress:
                return
                
            if code == lv.EVENT.GESTURE:
                # 严格控制：AppDrawer可见时只允许DOWN手势
                if is_hidden:
                    return
                    
                indev = lv.indev_get_act()
                _dir = indev.get_gesture_dir()
                
                # 严格控制：只允许DOWN手势
                if _dir == lv.DIR.BOTTOM:
                    self.hide_to_mainscreen()
                elif _dir == lv.DIR.TOP:
                    return
                else:
                    # 处理左右手势用于翻页
                    self.handle_page_gesture(_dir)
                    
        def hide_to_mainscreen(self):
            """隐藏AppDrawer并显示MainScreen，带layer2动画"""
            global _animation_in_progress, _animation_start_time
            
            # 防止重复调用
            if _animation_in_progress:
                return
                
            # 检查操作频率
            if not check_operation_frequency():
                return
                
            if __debug__:
                global _operation_count
                print(f"AppDrawer: Starting hide_to_mainscreen (operation #{_operation_count})")
            log_with_timestamp("AppDrawer: === hide_to_mainscreen START ===")
            
            try:
                _animation_in_progress = True
                _animation_start_time = get_timestamp()
                log_with_timestamp(f"AppDrawer: Animation started, setting _animation_in_progress = True")
                
                from trezorui import Display
                display = Display()
                

                from storage import device
                # lockscreen_path = device.get_homescreen()
                # # 步骤1: 加载layer2背景
                # self.add_style(
                #     StyleWrapper().bg_img_src(lockscreen_path).border_width(0),
                #     0,
                # )
                if hasattr(display, 'cover_background_load_jpeg'):
                    try:
                        from storage import device
                        lockscreen_path = device.get_homescreen()
                        
                        if not lockscreen_path:
                            display_path = "res/wallpaper-1.jpg"
                        else:
                            if lockscreen_path.startswith("A:/"):
                                # Special handling for NFT files
                                if "/res/nfts/" in lockscreen_path:
                                    display_path = "1:" + lockscreen_path[2:]  # A:/res/nfts/... -> 1:/res/nfts/...
                                else:
                                    display_path = lockscreen_path[3:]  # A:/res/wallpapers/... -> res/wallpapers/...
                            elif lockscreen_path.startswith("A:1:"):
                                display_path = lockscreen_path[2:]  # A:1:/res/wallpapers/xxx -> 1:/res/wallpapers/xxx
                            else:
                                display_path = lockscreen_path
                        
                        if __debug__:
                            log_with_timestamp(f"AppDrawer: Layer2 path conversion: {lockscreen_path} -> {display_path}")
                        
                        # 检查是否需要重新加载JPEG
                        global _last_jpeg_loaded
                        if _last_jpeg_loaded != display_path:
                            # 尝试释放内存后再加载
                            gc.collect()
                            if __debug__:
                                print(f"AppDrawer: Memory before JPEG load: {get_memory_info()}")
                            display.cover_background_load_jpeg(display_path)
                            _last_jpeg_loaded = display_path
                            if __debug__:
                                print(f"AppDrawer: Layer2 background loaded: {display_path}")
                                print(f"AppDrawer: Memory after JPEG load: {get_memory_info()}")
                        else:
                            if __debug__:
                                print(f"AppDrawer: Layer2 background already loaded, skipping: {display_path}")
                        
                    except Exception:
                        # 使用纯黑色背景作为备用
                        if hasattr(display, 'cover_background_set_image'):
                            width, height = 480, 800
                            black_image = bytearray(width * height * 2)
                            for i in range(len(black_image)):
                                black_image[i] = 0x00
                            display.cover_background_set_image(bytes(black_image))
                        log_with_timestamp("AppDrawer: Layer2 fallback to black background")
                
                # 步骤2: DOWN手势：Layer2 从上方滑入填满屏幕，然后消失显示MainScreen
                if hasattr(display, 'cover_background_animate_to_y'):
                    log_with_timestamp("AppDrawer: Starting Layer2 slide down animation from top")
                    
                    # 显示MainScreen元素（但不立即隐藏AppDrawer，让动画自然进行）
                    self.parent.hidden_others(False)
                    if hasattr(self.parent, 'up_arrow'):
                        self.parent.up_arrow.clear_flag(lv.obj.FLAG.HIDDEN)
                    if hasattr(self.parent, 'bottom_tips'):
                        self.parent.bottom_tips.clear_flag(lv.obj.FLAG.HIDDEN)
                    if hasattr(self.parent, "dev_state"):
                        self.parent.dev_state.show()
                    log_with_timestamp("AppDrawer: MainScreen elements shown")
                    
                    # 步骤1: 先将Layer2移动到屏幕上方
                    display.cover_background_move_to_y(-800)
                    if hasattr(display, 'cover_background_set_visible'):
                        display.cover_background_set_visible(True)
                    log_with_timestamp("AppDrawer: Layer2 positioned above screen")
                    
                    # 步骤2: 从上方滑入到屏幕中心（y=0），正好填满屏幕
                    display.cover_background_animate_to_y(0, 200)  # 滑动到屏幕中心，填满屏幕 (优化响应速度)
                    log_with_timestamp("AppDrawer: Layer2 sliding down to fill screen (200ms)")
                    
                    # 步骤3: 在Layer2覆盖屏幕后，准备MainScreen状态并隐藏AppDrawer
                    def prepare_mainscreen_after_coverage():
                        log_with_timestamp("AppDrawer: === prepare_mainscreen_after_coverage (50ms timer) ===")
                        # 现在隐藏AppDrawer
                        log_with_timestamp("AppDrawer: Hiding AppDrawer")
                        self.add_flag(lv.obj.FLAG.HIDDEN)
                        self.visible = False
                        self.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
                        log_with_timestamp(f"AppDrawer: Hidden flag set, visible={self.visible}")
                        
                        # 确保MainScreen背景是lockscreen
                        from storage import device
                        current_lockscreen = device.get_homescreen()
                        if current_lockscreen:
                            self.parent.add_style(
                                get_cached_style(current_lockscreen),
                                0
                            )
                            log_with_timestamp(f"AppDrawer: MainScreen background set to lockscreen: {current_lockscreen}")
                        
                        # 强制LVGL渲染MainScreen
                        lv.refr_now(None)
                        # 释放内存
                        gc.collect()
                        if __debug__:
                            print(f"AppDrawer: Memory after state preparation: {get_memory_info()}")
                        log_with_timestamp("AppDrawer: MainScreen state prepared, AppDrawer hidden, LVGL refreshed, memory collected")
                    
                    # 30ms后Layer2已经开始覆盖屏幕，准备MainScreen状态 (优化响应速度)
                    prepare_timer = lv.timer_create(
                        lambda t: prepare_mainscreen_after_coverage(),
                        30, None
                    )
                    prepare_timer.set_repeat_count(1)
                    # 跟踪定时器
                    global _active_timers
                    _active_timers.append(prepare_timer)
                    log_with_timestamp("AppDrawer: MainScreen prepare timer created (30ms delay)")
                    
                    # 步骤3: 动画完成后隐藏Layer2
                    def on_animation_complete():
                        global _animation_in_progress
                        log_with_timestamp("AppDrawer: === on_animation_complete (250ms timer) ===")
                        try:
                            if hasattr(display, 'cover_background_hide'):
                                display.cover_background_hide()
                                log_with_timestamp("AppDrawer: Layer2 successfully hidden, MainScreen fully visible")
                            _animation_in_progress = False
                            elapsed = get_timestamp() - _animation_start_time
                            log_with_timestamp(f"AppDrawer: Animation completed, total time: {elapsed}ms, setting _animation_in_progress = False")
                            # 清理定时器并强制内存清理
                            cleanup_timers()
                            force_memory_cleanup()
                            if __debug__:
                                print(f"AppDrawer: Memory after animation complete: {get_memory_info()}")
                        except Exception as error:
                            log_with_timestamp(f"AppDrawer: Error hiding Layer2: {error}")
                    
                    # 等待动画完成后隐藏Layer2（200ms动画时间）
                    completion_timer = lv.timer_create(
                        lambda t: on_animation_complete(),
                        200, None  # 与动画时间匹配
                    )
                    completion_timer.set_repeat_count(1)
                    # 跟踪定时器
                    _active_timers.append(completion_timer)
                else:
                    # 如果没有动画函数，直接切换
                    self.hide_to_mainscreen_fallback()
                    
            except Exception as e:
                global _animation_in_progress
                log_with_timestamp(f"AppDrawer: Error in hide_to_mainscreen: {e}")
                # 出错时使用简单方式
                self.hide_to_mainscreen_fallback()
                _animation_in_progress = False
                log_with_timestamp("AppDrawer: Fallback to simple hide, animation reset")
                
        def hide_to_mainscreen_fallback(self):
            """备用的简单隐藏方法"""
            self.add_flag(lv.obj.FLAG.HIDDEN)
            self.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.visible = False
            
            # 显示MainScreen元素
            self.parent.hidden_others(False)
            if hasattr(self.parent, 'up_arrow'):
                self.parent.up_arrow.clear_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self.parent, 'bottom_tips'):
                self.parent.bottom_tips.clear_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self.parent, "dev_state"):
                self.parent.dev_state.show()
            print("AppDrawer: Hidden via fallback method, MainScreen shown")
            
        def handle_page_gesture(self, _dir):
            """处理翻页手势"""
            if _dir not in [lv.DIR.RIGHT, lv.DIR.LEFT]:
                return
                
            # Check if indicators exist before using them
            if not hasattr(self, 'indicators') or not self.indicators:
                print("AppDrawer: indicators not initialized, skipping page change")
                return
                
            self.indicators[self.current_page].set_active(False)
            page_idx = self.current_page
            if _dir == lv.DIR.LEFT:
                page_idx = (self.current_page + 1) % self.PAGE_SIZE
            elif _dir == lv.DIR.RIGHT:
                page_idx = (self.current_page - 1 + self.PAGE_SIZE) % self.PAGE_SIZE
            self.indicators[page_idx].set_active(True)
            self.show_page(page_idx)

        def show_page(self, index: int):
            if index == self.current_page:
                return
            for item in self.page_items[index]:
                item.clear_flag(lv.obj.FLAG.HIDDEN)
            for item in self.page_items[self.current_page]:
                item.add_flag(lv.obj.FLAG.HIDDEN)
            self.current_page = index

        def hidden_page(self, index: int):
            pass

        def show_anim_start_cb(self, _anim):
            self.parent.hidden_others()
            self.hidden_page(self.current_page)
            self.parent.clear_state(lv.STATE.USER_1)

        def show_anim_del_cb(self, _anim):
            self.show_page(self.current_page)
            self.visible = True
            print("AppDrawer: show_anim_del_cb - animation complete, set visible=True")

        def dismiss_anim_start_cb(self, _anim):
            self.hidden_page(self.current_page)

        def dismiss_anim_del_cb(self, _anim):
            self.parent.hidden_others(False)
            self.add_flag(lv.obj.FLAG.HIDDEN)
            self.visible = False
            self.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            print("AppDrawer: dismiss_anim_del_cb - AppDrawer fully dismissed")

        def show(self):
            """简化的show方法 - 不再使用，改用简化的直接显示方式"""
            print("AppDrawer: show() method called - using simplified display logic instead")
            
        def dismiss(self):
            """简化的dismiss方法 - 不再使用，改用简化的直接隐藏方式"""
            print("AppDrawer: dismiss() method called - using simplified hide logic instead")
        
        def refresh_background(self):
            """刷新AppDrawer的背景图片"""
            homescreen = storage_device.get_appdrawer_background()
            if homescreen:
                self.add_style(
                    StyleWrapper().bg_img_src(homescreen).border_width(0),
                    0,
                )
                print(f"AppDrawer: Background refreshed to {homescreen}")
            else:
                # Clear image background to show black background
                print("AppDrawer: Background set to black (no image)")

        def on_pressed(self, text_key):
            label = self.text_label[text_key]
            label.add_state(lv.STATE.PRESSED)

        def on_released(self, text_key):
            label = self.text_label[text_key]
            label.clear_state(lv.STATE.PRESSED)

        def on_item_click(self, name):
            handlers = {
                "settings": lambda: SettingsScreen(self.parent),
                "guide": lambda: UserGuide(self.parent),
                "nft": lambda: self._create_nft_gallery(),
                "backup": lambda: BackupWallet(self.parent),
                "scan": lambda: ScanScreen(self.parent),
                "connect": lambda: ConnectWalletWays(self.parent),
                "my_address": lambda: ShowAddress(self.parent),
                "passkey": lambda: PasskeysManager(self.parent),
            }
            if name in handlers:
                handlers[name]()
        
        def _create_nft_gallery(self):
            """Create NFT gallery with singleton cleanup"""
            try:
                # Clean up existing NftGallery instance to allow fresh creation
                if hasattr(NftGallery, '_instance'):
                    if __debug__:
                        print("[AppDrawer] Cleaning up existing NftGallery instance")
                    old_instance = NftGallery._instance
                    try:
                        old_instance.delete()
                    except:
                        pass
                    del NftGallery._instance
                    
                # Create new NftGallery instance
                if __debug__:
                    print("[AppDrawer] Creating new NftGallery instance")
                return NftGallery(self.parent)
            except Exception as e:
                if __debug__:
                    print(f"[AppDrawer] Error creating NftGallery: {e}")
                # Fallback to direct creation
                return NftGallery(self.parent)
                
        def test_cover_background(self):
            """Test function for CoverBackground control"""
            print("=== TEST COVER APP CLICKED ===")
            try:
                # Direct access to hardware functions
                from trezorui import Display
                display = Display()
                if hasattr(display, 'cover_background_show'):
                    print("TEST APP: Showing CoverBackground for 3 seconds...")
                    display.cover_background_show()
                    
                    # Auto-hide after 3 seconds
                    def hide_bg():
                        try:
                            display.cover_background_hide() 
                            print("TEST APP: CoverBackground auto-hidden")
                        except Exception as e:
                            print(f"TEST APP: Error hiding: {e}")
                    
                    # Schedule hide
                    import trezor.loop as loop
                    loop.call_later(3000, hide_bg)  # 3 seconds
                    print("TEST APP: CoverBackground shown - will auto-hide in 3s")
                else:
                    print("TEST APP: cover_background_show method not found")
                    
            except Exception as e:
                print(f"TEST APP: Error: {e}")

        def on_click(self, event_obj):
            code = event_obj.code
            if code == lv.EVENT.CLICKED:
                if utils.lcd_resume():
                    return
                # 简化：移除slide检查，因为我们已经简化了状态管理

        def refresh_text(self):
            for text_key, label in self.text_label.items():
                label.set_text(_(text_key))


class PasskeysManager(AnimScreen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            if not self.is_visible():
                if hasattr(self, "banner") and self.banner:
                    self.banner.delete()
                    del self.banner
                if hasattr(self, "learn_more") and self.learn_more:
                    self.learn_more.delete()
                    del self.learn_more
                if hasattr(self, "empty_tips") and self.empty_tips:
                    self.empty_tips.delete()
                    del self.empty_tips
                if hasattr(self, "container") and self.container:
                    self.container.delete()
                    del self.container
                self.fresh_show()
                lv.scr_load(self)
            return
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.FIDO_FIDO_KEYS_LABEL),
            nav_back=True,
            rti_path="A:/res/go2settings.png",
        )

        self.fresh_show()
        self.add_event_cb(self.on_click_event, lv.EVENT.CLICKED, None)
        # self.add_event_cb(self.on_scroll, lv.EVENT.SCROLL_BEGIN, None)

    async def list_credential(self):
        from .app_passkeys import PasskeysListItemBtn

        BATCH_SIZE = 5
        # pyright: off
        stored_credentials = [None] * self.count
        for i, credential in enumerate(self.credentials):
            stored_credentials[i] = (
                credential.app_name(),
                credential.account_name(),
                credential.index,
                credential.creation_time,
            )
            self.overlay.set_value(i + 1)
            if (i < BATCH_SIZE) or ((i + 1) % BATCH_SIZE == 0):
                gc.collect()
                await loop.sleep(10)
        stored_credentials.sort(key=lambda x: x[3])
        for i, credential in enumerate(stored_credentials):
            self.listed_credentials[i] = PasskeysListItemBtn(
                self.container,
                credential[0],
                credential[1] or "",
                credential[2],
            )
            if (i < BATCH_SIZE) or ((i + 1) % BATCH_SIZE == 0):
                gc.collect()
        # pyright: on
        self.container.refresh_self_size()
        del stored_credentials
        self.overlay.del_delayed(10)

    def fresh_show(self):
        from .app_passkeys import (
            get_registered_credentials,
            get_registered_credentials_count,
        )

        if hasattr(self, "container"):
            self.container.refresh_self_size()
            self.count = len(self.listed_credentials)
        else:
            self.count = get_registered_credentials_count()
            self.credentials = get_registered_credentials()
            self.listed_credentials = [None] * self.count

        fido_enabled = storage_device.is_fido_enabled()
        if not hasattr(self, "banner") and not fido_enabled:
            self.banner = Banner(
                self.content_area,
                LEVEL.HIGHLIGHT,
                _(i18n_keys.FIDO_DISABLED_INFO_TEXT),
            )
            self.banner.align(lv.ALIGN.TOP_MID, 0, 116)
        if self.count == 0:
            self.empty_tips = lv.label(self.content_area)
            self.empty_tips.set_text(_(i18n_keys.FIDO_LIST_EMPTY_TEXT))
            self.empty_tips.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE_2)
                .text_letter_space(-1),
                0,
            )
            self.empty_tips.align(lv.ALIGN.TOP_MID, 0, 432)
            if fido_enabled:
                self.learn_more = NormalButton(
                    self, text=_(i18n_keys.ACTION__LEARN_MORE)
                )
        else:
            if not hasattr(self, "container"):
                algin_base = self.title if fido_enabled else self.banner
                self.container = ContainerFlexCol(
                    self.content_area, algin_base, padding_row=2
                )
                workflow.spawn(self.list_credential())

                from .components.overlay import OverlayWithProcessBar

                self.overlay = OverlayWithProcessBar(self, self.count)

    def auto_adjust_scroll(self, item_height):
        scroll_value = self.content_area.get_scroll_y()
        if scroll_value > 0:
            auto_adjust = scroll_value - item_height
            self.content_area.scroll_to(
                0, auto_adjust if auto_adjust > 0 else 0, lv.ANIM.OFF
            )

    async def on_remove(self, i):
        # pyright: off
        credential = self.listed_credentials.pop(i)
        from .app_passkeys import delete_credential

        delete_credential(credential.credential_index)
        item_height = credential.get_height()
        credential.delete()
        # pyright: on
        self.fresh_show()
        self.auto_adjust_scroll(item_height)

    def on_click_event(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            from trezor.lvglui.scrs import app_passkeys

            if hasattr(self, "learn_more") and target == self.learn_more:
                from .app_passkeys import PasskeysRegister

                PasskeysRegister()
            elif target in self.listed_credentials:
                for i, credential in enumerate(self.listed_credentials):
                    if target == credential:
                        # pyright: off
                        workflow.spawn(
                            app_passkeys.request_credential_details(
                                credential.app_name,
                                credential.account_name,
                                on_remove=lambda index=i: self.on_remove(index),
                            )
                        )
                        # pyright: on
            elif hasattr(self, "rti_btn") and target == self.rti_btn:
                FidoKeysSetting(self)

    # def on_scroll(self, event_obj):
    #     code = event_obj.code
    #     if code == lv.EVENT.SCROLL_BEGIN:
    #         if self.count < 5:
    #             self.content_area.clear_flag(lv.obj.FLAG.SCROLL_ELASTIC)

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)


class ShowAddress(AnimScreen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self.prev_session_id = storage.cache.get_session_id()
            if not self.prev_session_id:
                self.curr_session_id = storage.cache.start_session()
                self.prev_session_id = self.curr_session_id
            else:
                self.curr_session_id = storage.cache.start_session()
            self._init = True
            self.current_index = 0
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.TITLE__SELECT_NETWORK),
                "nav_back": True,
            }
            super().__init__(**kwargs)

            self.addr_manager = AddressManager()

            self.init_ui()

        else:
            if not self.is_visible():
                self._load_scr(self)
            # self.container.delete()
            # self.init_ui()
            gc.collect()

    async def _get_passphrase_from_user(self, init=False, prev_scr=None):
        try:
            from apps.bitcoin.get_address import get_address as btc_get_address
            from trezor import messages
            from trezor.enums import InputScriptType

            msg = messages.GetAddress(
                address_n=[0x80000000 + 44, 0x80000000 + 0, 0x80000000 + 0, 0, 0],
                show_display=False,
                script_type=InputScriptType.SPENDADDRESS,
            )
            # pyright: off
            await btc_get_address(wire.QRContext(), msg)
            # pyright: on

        except Exception:
            pass

        if init:
            self._init = True
            self.current_index = 0
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.TITLE__SELECT_NETWORK),
                "nav_back": True,
            }
            super().__init__(**kwargs)

            self.addr_manager = AddressManager()

            self.init_ui()

        self.invalidate()

    def animate_list_items(self):
        # def create_fade_cb_container(obj, item_index):
        #     def cb(value):
        #         self.container.set_style_text_opa(value, 0)

        #         for btn in self.chain_buttons:
        #             btn.set_style_bg_opa(value, 0)
        #             btn.img_left.set_style_img_opa(value, 0)

        #     return cb

        def create_move_cb_container(obj, item_index):
            def cb(value):
                obj.set_style_translate_x(value, 0)
                obj.invalidate()

            return cb

        # container_fade_anim = Anim(
        #     150,
        #     255,
        #     create_fade_cb_container(self.container, 0),
        #     time=110,
        #     delay=0,
        #     path_cb=lv.anim_t.path_ease_out,
        # )

        container_move_anim = Anim(
            50,
            0,
            create_move_cb_container(self.container, 0),
            time=150,
            delay=0,
            path_cb=lv.anim_t.path_ease_out,
        )

        container_move_back_anim = Anim(
            -50,
            0,
            create_move_cb_container(self.container, 0),
            time=150,
            delay=0,
            path_cb=lv.anim_t.path_ease_out,
        )

        # self.animations_next.append(container_fade_anim)
        # container_fade_anim.start()
        self.animations_next.append(container_move_anim)
        # container_move_anim.start()

        # self.animations_prev.append(container_fade_anim)
        self.animations_prev.append(container_move_back_anim)

    def init_ui(self):
        """Initialize UI components"""

        if passphrase.is_enabled() and not passphrase.is_passphrase_pin_enabled():
            from .components.navigation import Navigation

            self.nav_passphrase = Navigation(
                self.content_area,
                btn_bg_img="A:/res/repeat.png",
                nav_btn_align=lv.ALIGN.RIGHT_MID,
                align=lv.ALIGN.TOP_RIGHT,
            )

        # Account button
        self.index_btn = ListItemBtn(
            self.content_area,
            f" Account #{self.current_index + 1}",
            left_img_src="A:/res/wallet.png",
            has_next=False,
            min_height=87,
            pad_ver=5,
        )
        self.index_btn.align_to(self.title, lv.ALIGN.OUT_BOTTOM_MID, 0, 40)
        self.index_btn.set_style_radius(40, 0)
        self.index_btn.add_event_cb(self.on_index_click, lv.EVENT.CLICKED, None)

        self.container = ContainerFlexCol(
            self.content_area, self.title, padding_row=2, pos=(0, 157)
        )
        self.container.align_to(self.index_btn, lv.ALIGN.OUT_BOTTOM_MID, 0, 12)
        self.container.set_style_bg_color(lv_colors.BLACK, 0)
        self.container.set_style_bg_opa(255, 0)

        # Initialize variables
        self.chains = chains_brief_info()
        self.visible_chains_count = 8

        self.is_expanded = False
        self.chain_buttons = []
        self.created_count = 0
        self.current_page = 0
        self.items_per_page = 5
        self.max_pages = 0

        self.chain_buttons = []
        for _i in range(self.items_per_page):
            btn = ListItemBtn(
                self.container,
                "",
                left_img_src="A:/res/btc-btc-48.png",
                min_height=87,
                pad_ver=5,
            )
            self.chain_buttons.append(btn)
            btn.add_flag(lv.obj.FLAG.HIDDEN)

        self._create_visible_chain_buttons()
        self.max_pages = (len(self.chains) - 1) // self.items_per_page

        if self.max_pages > 0:
            self.next_btn = NormalButton(self, "")
            self.next_btn.set_size(224, 98)
            self.next_btn.align(lv.ALIGN.BOTTOM_RIGHT, -12, -8)
            self.next_btn.set_style_bg_img_src("A:/res/arrow-right-2.png", 0)

            self.back_btn = NormalButton(self, "")
            self.back_btn.set_size(224, 98)
            self.back_btn.align(lv.ALIGN.BOTTOM_LEFT, 12, -8)
            self.back_btn.set_style_bg_img_src("A:/res/arrow-left-2.png", 0)

        self.disable_style = (
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK_5)
            .bg_img_recolor(lv_colors.ONEKEY_GRAY_1)
            .bg_img_recolor_opa(lv.OPA.COVER)
        )
        self.enable_style = (
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK_3)
            .bg_opa(lv.OPA.COVER)
            .radius(98)
        )

        self._create_visible_chain_buttons()

        if self.max_pages > 0:
            self.update_page_buttons()
            self.next_btn.add_style(self.enable_style, 0)

        self.animations_next = []
        self.animations_prev = []
        self.list_items = self.chain_buttons

        if storage_device.is_animation_enabled():
            self.animate_list_items()

    def _create_visible_chain_buttons(self):
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.chains))

        for i, btn in enumerate(self.chain_buttons):
            btn.remove_event_cb(None)
            # btn.set_style_opa(0, 0)
            if i < (end_idx - start_idx):
                chain = self.chains[start_idx + i]
                chain_name, chain_icon = chain
                btn.label_left.set_text(chain_name)
                btn.img_left.set_src(chain_icon)
                btn.add_event_cb(
                    lambda e, name=chain_name: self.on_chain_click(e, name),
                    lv.EVENT.CLICKED,
                    None,
                )
                btn.clear_flag(lv.obj.FLAG.HIDDEN)

                if chain_name == "Ethereum" and not hasattr(btn, "img_right"):
                    btn.img_right = lv.img(btn)
                    btn.img_right.set_src("A:/res/stacked-chains.png")
                    btn.img_right.set_align(lv.ALIGN.RIGHT_MID)
                elif chain_name == "Ethereum" and hasattr(btn, "img_right"):
                    btn.img_right.set_style_img_opa(255, 0)
                elif i == 1 and hasattr(btn, "img_right"):
                    btn.img_right.set_style_img_opa(0, 0)
            else:
                btn.add_flag(lv.obj.FLAG.HIDDEN)

    def enable_page_buttons(self, btn):
        btn.add_flag(lv.btn.FLAG.CLICKABLE)
        btn.remove_style(self.disable_style, 0)
        btn.add_style(self.enable_style, 0)

    def disable_page_buttons(self, btn):
        btn.clear_flag(lv.btn.FLAG.CLICKABLE)
        btn.remove_style(self.enable_style, 0)
        btn.add_style(self.disable_style, 0)

    def update_page_buttons(self):
        if self.current_page == 0:
            self.disable_page_buttons(self.back_btn)
            if not self.next_btn.has_flag(lv.btn.FLAG.CLICKABLE):
                self.enable_page_buttons(self.next_btn)

        elif self.current_page == self.max_pages:
            self.disable_page_buttons(self.next_btn)
            if not self.back_btn.has_flag(lv.btn.FLAG.CLICKABLE):
                self.enable_page_buttons(self.back_btn)

        else:
            if not self.next_btn.has_flag(lv.btn.FLAG.CLICKABLE):
                self.enable_page_buttons(self.next_btn)
            if not self.back_btn.has_flag(lv.btn.FLAG.CLICKABLE):
                self.enable_page_buttons(self.back_btn)

    def next_page(self):
        if self.current_page < self.max_pages:
            self.current_page += 1
            self._create_visible_chain_buttons()
            for anim in self.animations_next:
                anim.start()
            self.update_page_buttons()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._create_visible_chain_buttons()
            for anim in self.animations_prev:
                anim.start()
            self.update_page_buttons()

    def on_index_click(self, event):
        """Handle account selection click"""
        IndexSelectionScreen(self)

    def on_chain_click(self, event, name):
        """Handle chain selection click"""
        if utils.lcd_resume():
            return

        workflow.spawn(self.addr_manager.generate_address(name, self.current_index))

    def update_index_btn_text(self):
        """Update account button text"""
        self.index_btn.label_left.set_text(f"Account #{self.current_index + 1}")
        # pass

    # def _load_scr(self, scr: "Screen", back: bool = False) -> None:
    #     lv.scr_load(scr)

    def eventhandler(self, event_obj):
        event = event_obj.code
        target = event_obj.get_target()
        if event == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if isinstance(target, lv.imgbtn):
                if target == self.nav_back.nav_btn:
                    storage.cache.end_current_session()
                    storage.cache.start_session(self.prev_session_id)
                    if self.prev_scr is not None:
                        self.load_screen(self.prev_scr, destroy_self=True)

                elif passphrase.is_enabled() and target == self.nav_passphrase.nav_btn:
                    # enter new passphrase
                    # device.set_passphrase_auto_status(False)
                    storage.cache.end_current_session()
                    self.curr_session_id = storage.cache.start_session()
                    workflow.spawn(self._get_passphrase_from_user(init=False))

            else:
                gc.collect()
                if hasattr(self, "back_btn") and target == self.back_btn:
                    self.prev_page()
                elif hasattr(self, "next_btn") and target == self.next_btn:
                    self.next_page()

    async def _handle_passphrase_change(self, coro):
        await coro
        self.init_ui()


class IndexSelectionScreen(AnimScreen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        super().__init__(
            prev_scr, title=_(i18n_keys.TITLE__SELECT_ACCOUNT), nav_back=True
        )

        from .components.navigation import Navigation

        # # navi
        self.nav_opt = Navigation(
            self.content_area,
            nav_btn_align=lv.ALIGN.RIGHT_MID,
            btn_bg_img="A:/res/general.png",
            align=lv.ALIGN.TOP_RIGHT,
        )

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)

        self.max_account = 1000000000
        self.max_page = (self.max_account - 1) // 5

        self.current_account = self.prev_scr.current_index + 1
        self.current_page = (self.current_account - 1) // 5

        # account select btn
        self.account_btns = []
        for _i in range(5):
            btn = ListItemBtn(
                self.container,
                "",
                has_next=False,
                use_transition=False,
            )
            btn.add_check_img()
            self.account_btns.append(btn)
        self.update_account_buttons()

        self.next_btn = NormalButton(self, "")
        self.next_btn.set_size(224, 98)
        self.next_btn.align(lv.ALIGN.BOTTOM_RIGHT, -12, -8)
        self.next_btn.set_style_bg_img_src("A:/res/arrow-right-2.png", 0)

        self.back_btn = NormalButton(self, "")
        self.back_btn.set_size(224, 98)
        self.back_btn.align(lv.ALIGN.BOTTOM_LEFT, 12, -8)
        self.back_btn.set_style_bg_img_src("A:/res/arrow-left-2.png", 0)

        self.disable_style = (
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK_5)
            .bg_img_recolor(lv_colors.ONEKEY_GRAY_1)
            .bg_img_recolor_opa(lv.OPA.COVER)
        )
        self.enable_style = (
            StyleWrapper().bg_color(lv_colors.ONEKEY_BLACK_3).bg_opa(lv.OPA.COVER)
        )

        self.update_page_buttons()
        self.next_btn.add_style(self.enable_style, 0)
        self.back_btn.add_style(self.enable_style, 0)

        self.animations_next = []
        self.animations_prev = []
        if storage_device.is_animation_enabled():
            self.animate_list_items()

    def animate_list_items(self):
        # def create_fade_cb_container(obj, item_index):
        #     def cb(value):
        #         self.container.set_style_text_opa(value, 0)

        #         for btn in self.chain_buttons:
        #             btn.set_style_bg_opa(value, 0)
        #             # btn.img_left.set_style_img_opa(value, 0)

        #     return cb

        def create_move_cb_container(obj, item_index):
            def cb(value):
                obj.set_style_translate_x(value, 0)
                obj.invalidate()

            return cb

        # container_fade_anim = Anim(
        #     150,
        #     255,
        #     create_fade_cb_container(self.container, 0),
        #     time=110,
        #     delay=0,
        #     path_cb=lv.anim_t.path_ease_out,
        # )

        container_move_anim = Anim(
            50,
            0,
            create_move_cb_container(self.container, 0),
            time=150,
            delay=0,
            path_cb=lv.anim_t.path_ease_out,
        )

        container_move_back_anim = Anim(
            -50,
            0,
            create_move_cb_container(self.container, 0),
            time=150,
            delay=0,
            path_cb=lv.anim_t.path_ease_out,
        )

        # self.animations_next.append(container_fade_anim)
        # container_fade_anim.start()
        self.animations_next.append(container_move_anim)
        container_move_anim.start()

        # self.animations_prev.append(container_fade_anim)
        self.animations_prev.append(container_move_back_anim)

    def get_page_start(self):
        return (self.current_page * 5) + 1

    def update_account_buttons(self):
        page_start = self.get_page_start()
        for i, btn in enumerate(self.account_btns):
            account_num = page_start + i
            btn.label_left.set_text(f"Account #{account_num}")

            if account_num == self.current_account:
                btn.set_checked()
            else:
                btn.set_uncheck()

    def enable_page_buttons(self, btn):
        btn.add_flag(lv.btn.FLAG.CLICKABLE)
        btn.remove_style(self.disable_style, 0)
        btn.add_style(self.enable_style, 0)

    def disable_page_buttons(self, btn):
        btn.clear_flag(lv.btn.FLAG.CLICKABLE)
        btn.remove_style(self.enable_style, 0)
        btn.add_style(self.disable_style, 0)

    def update_page_buttons(self):
        if self.current_page == 0:
            self.disable_page_buttons(self.back_btn)
            if not self.next_btn.has_flag(lv.btn.FLAG.CLICKABLE):
                self.enable_page_buttons(self.next_btn)

        elif self.current_page == self.max_page:
            self.disable_page_buttons(self.next_btn)
            if not self.back_btn.has_flag(lv.btn.FLAG.CLICKABLE):
                self.enable_page_buttons(self.back_btn)

        else:
            if not self.next_btn.has_flag(lv.btn.FLAG.CLICKABLE):
                self.enable_page_buttons(self.next_btn)
            if not self.back_btn.has_flag(lv.btn.FLAG.CLICKABLE):
                self.enable_page_buttons(self.back_btn)
        gc.collect()

    def next_page(self):
        self.current_page += 1
        self.update_account_buttons()
        self.update_page_buttons()
        for anim in self.animations_next:
            anim.start()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_account_buttons()
            self.update_page_buttons()
            for anim in self.animations_prev:
                anim.start()

    def eventhandler(self, event_obj):
        event = event_obj.code
        target = event_obj.get_target()
        if event == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return

            if isinstance(target, lv.imgbtn):
                if target == self.nav_back.nav_btn:
                    if self.prev_scr is not None:
                        self.load_screen(self.prev_scr, destroy_self=True)
                elif target == self.nav_opt.nav_btn:
                    workflow.spawn(self.type_account_index())
            else:
                if target == self.back_btn:
                    self.prev_page()
                elif target == self.next_btn:
                    self.next_page()
                else:
                    for i, btn in enumerate(self.account_btns):
                        if target == btn:
                            for other_btn in self.account_btns:
                                other_btn.set_uncheck()

                            btn.set_checked()

                            self.current_account = self.get_page_start() + i
                            self.prev_scr.current_index = self.current_account - 1
                            self.prev_scr.update_index_btn_text()
                            break

    async def type_account_index(self):
        from trezor.lvglui.scrs.pinscreen import InputNum

        result = None
        while True:
            numscreen = InputNum(
                title=_(i18n_keys.TITLE__SET_INITIAL_ACCOUNT),
                subtitle=_(i18n_keys.TITLE__SET_INITIAL_ACCOUNT_ERROR)
                if result is not None
                else "",
                is_pin=False,
            )
            result = await numscreen.request()

            if not result:  # user cancelled
                return

            account_num = int(result)
            if 1 <= account_num <= self.max_account:
                break

        self.current_account = account_num
        self.current_page = (account_num - 1) // 5
        self.prev_scr.current_index = account_num - 1
        self.prev_scr.update_index_btn_text()

        self.update_account_buttons()
        self.update_page_buttons()


class NftGallery(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.TITLE__NFT_GALLERY),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            if hasattr(self, "overview") and self.overview:
                self.overview.delete()
            if hasattr(self, "container") and self.container:
                self.container.delete()

        nft_counts = 0
        file_name_list = []
        if not utils.EMULATOR:
            for size, _attrs, name in io.fatfs.listdir("1:/res/nfts/zooms"):
                if nft_counts >= 24:
                    break
                if size > 0:
                    nft_counts += 1
                    file_name_list.append(name)
        if nft_counts == 0:
            self.empty()
        else:
            rows_num = math.ceil(nft_counts / 2)
            row_dsc = [238] * rows_num
            row_dsc.append(lv.GRID_TEMPLATE.LAST)
            # 2 columns
            col_dsc = [
                238,
                238,
                lv.GRID_TEMPLATE.LAST,
            ]

            self.overview = lv.label(self.content_area)
            self.overview.set_size(456, lv.SIZE.CONTENT)
            self.overview.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE_2)
                .text_align_left()
                .text_letter_space(-1),
                0,
            )
            self.overview.align_to(self.title, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 32)
            self.overview.set_text(
                _(i18n_keys.CONTENT__STR_ITEMS).format(nft_counts)
                if nft_counts > 1
                else _(i18n_keys.CONTENT__STR_ITEM).format(nft_counts)
            )
            self.container = ContainerGrid(
                self.content_area,
                row_dsc=row_dsc,
                col_dsc=col_dsc,
                align_base=self.title,
                pos=(-12, 74),
                pad_gap=4,
            )
            self.nfts = []
            if not utils.EMULATOR:
                file_name_list.sort(
                    key=lambda name: int(
                        name[5:].split("-")[-1][: -(len(name.split(".")[1]) + 1)]
                    )
                )
                for i, file_name in enumerate(file_name_list):
                    path_dir = "A:1:/res/nfts/zooms/"
                    current_nft = ImgGridItem(
                        self.container,
                        (i) % 2,
                        (i) // 2,
                        file_name,
                        path_dir,
                        is_internal=False,
                    )
                    self.nfts.append(current_nft)

            self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def empty(self):

        self.empty_tips = lv.label(self.content_area)
        self.empty_tips.set_text(_(i18n_keys.CONTENT__NO_ITEMS))
        self.empty_tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular30)
            .text_color(lv_colors.WHITE_2)
            .text_letter_space(-1),
            0,
        )
        self.empty_tips.align(lv.ALIGN.TOP_MID, 0, 372)

        self.tips_bar = Banner(
            self.content_area,
            LEVEL.HIGHLIGHT,
            _(i18n_keys.CONTENT__HOW_TO_COLLECT_NFT__HINT),
        )

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target not in self.nfts:
                return
            for nft in self.nfts:
                if target == nft:
                    file_name_without_ext = nft.file_name.split(".")[0][5:]
                    desc_file_path = f"1:/res/nfts/desc/{file_name_without_ext}.json"
                    metadata = {
                        "header": "",
                        "subheader": "",
                        "network": "",
                        "owner": "",
                    }
                    with io.fatfs.open(desc_file_path, "r") as f:
                        description = bytearray(2048)
                        n = f.read(description)
                        if 0 < n < 2048:
                            try:
                                metadata_load = json.loads(
                                    (description[:n]).decode("utf-8")
                                )
                            except BaseException as e:
                                if __debug__:
                                    print(f"Invalid json {e}")
                            else:
                                if all(
                                    key in metadata_load.keys()
                                    for key in metadata.keys()
                                ):
                                    metadata = metadata_load
                    NftManager(self, metadata, nft.file_name)

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)


class NftManager(AnimScreen):
    def __init__(self, prev_scr, nft_config, file_name):
        self.zoom_path = f"A:1:/res/nfts/zooms/{file_name}"
        self.file_name = file_name.replace("zoom-", "")
        self.img_path = f"A:1:/res/nfts/imgs/{self.file_name}"
        
        super().__init__(
            prev_scr=prev_scr,
            title="Wallpaper",
            nav_back=True,
        )
        self.nft_config = nft_config
        
        # Add trash icon to title bar (right side)
        self.trash_icon = lv.imgbtn(self.content_area)
        self.trash_icon.set_src(lv.imgbtn.STATE.RELEASED, "A:/res/btn-del-white.png", None, None)
        self.trash_icon.set_size(40, 40)
        self.trash_icon.align(lv.ALIGN.TOP_RIGHT, -16, 60)
        self.trash_icon.add_style(StyleWrapper().bg_opa(lv.OPA.TRANSP).border_width(0), 0)
        self.trash_icon.add_flag(lv.obj.FLAG.EVENT_BUBBLE)  # Enable event bubbling
        
        # Main NFT image (456x456 as requested)
        self.nft_image = lv.img(self.content_area)
        self.nft_image.set_src(self.img_path)
        self.nft_image.set_size(456, 456)
        self.nft_image.align_to(self.title, lv.ALIGN.OUT_BOTTOM_MID, 0, 32)
        self.nft_image.add_style(StyleWrapper().radius(20).clip_corner(True), 0)
        
        # Title text below image
        self.nft_title = lv.label(self.content_area)
        self.nft_title.set_text(nft_config["header"] or "Title")
        self.nft_title.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold48)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.LEFT), 0
        )
        self.nft_title.align_to(self.nft_image, lv.ALIGN.OUT_BOTTOM_LEFT, 12, 12)
        
        # Description text below title
        self.nft_description = lv.label(self.content_area)
        self.nft_description.set_text(nft_config["subheader"] or "Type description here.")
        self.nft_description.set_long_mode(lv.label.LONG.WRAP)  # Enable text wrapping
        self.nft_description.set_size(456, lv.SIZE.CONTENT)  # Max width 456px, auto height
        self.nft_description.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular30)
            .text_color(lv_colors.WHITE_2)
            .text_align(lv.TEXT_ALIGN.LEFT), 0
        )
        self.nft_description.align_to(self.nft_title, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 8)
        
        # Set as Lock Screen button (purple) - height 98px as requested
        self.btn_lock_screen = NormalButton(self.content_area)
        self.btn_lock_screen.set_size(456, 98)
        self.btn_lock_screen.enable(lv_colors.ONEKEY_PURPLE, lv_colors.WHITE)
        self.btn_lock_screen.label.set_text("Set as Lock Screen")
        self.btn_lock_screen.align_to(self.nft_description, lv.ALIGN.OUT_BOTTOM_LEFT, -8, 32)
        
        # Set as Home Screen button (gray) - height 98px as requested
        self.btn_home_screen = NormalButton(self.content_area)
        self.btn_home_screen.set_size(456, 98)
        self.btn_home_screen.enable(lv_colors.GRAY_1, lv_colors.WHITE)
        self.btn_home_screen.label.set_text("Set as Home Screen")
        self.btn_home_screen.align_to(self.btn_lock_screen, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 8)

    def del_callback(self):
        io.fatfs.unlink(self.zoom_path[2:])
        io.fatfs.unlink(self.img_path[2:])
        io.fatfs.unlink("1:/res/nfts/desc/" + self.file_name.split(".")[0] + ".json")
        if storage_device.get_homescreen() == self.img_path:
            storage_device.set_appdrawer_background(utils.get_default_wallpaper())
        self.load_screen(self.prev_scr, destroy_self=True)

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if isinstance(target, lv.imgbtn):
                if target == self.nav_back.nav_btn:
                    if self.prev_scr is not None:
                        self.load_screen(self.prev_scr, destroy_self=True)
                elif target == self.trash_icon:
                    # Handle trash icon click - delete NFT
                    from trezor.ui.layouts import confirm_remove_nft
                    from trezor.wire import DUMMY_CONTEXT
                    workflow.spawn(
                        confirm_remove_nft(
                            DUMMY_CONTEXT,
                            self.del_callback,
                            self.zoom_path,
                        )
                    )
            else:
                if target == self.btn_lock_screen:
                    # Navigate to lock screen preview
                    NftLockScreenPreview(self, self.img_path, self.nft_config)
                elif target == self.btn_home_screen:
                    # Navigate to home screen preview
                    NftHomeScreenPreview(self, self.img_path, self.nft_config)

    class ConfirmSetHomeScreen(FullSizeWindow):
        def __init__(self, homescreen):
            super().__init__(
                title=_(i18n_keys.TITLE__SET_AS_HOMESCREEN),
                subtitle=_(i18n_keys.SUBTITLE__SET_AS_HOMESCREEN),
                confirm_text=_(i18n_keys.BUTTON__CONFIRM),
                cancel_text=_(i18n_keys.BUTTON__CANCEL),
            )
            self.homescreen = homescreen

        def eventhandler(self, event_obj):
            code = event_obj.code
            target = event_obj.get_target()
            if code == lv.EVENT.CLICKED:
                if utils.lcd_resume():
                    return
                if target == self.btn_yes:
                    storage_device.set_appdrawer_background(self.homescreen)
                    self.destroy(0)
                    workflow.spawn(utils.internal_reloop())
                elif target == self.btn_no:
                    self.destroy()


class NftLockScreenPreview(AnimScreen):
    def __init__(self, prev_scr, nft_path, nft_config):
        super().__init__(
            prev_scr=prev_scr,
            title="Preview",
            nav_back=True,
            rti_path="A:/res/checkmark.png"
        )
        self.nft_path = nft_path
        self.nft_config = nft_config
        
        if __debug__:
            print(f"[NftLockScreenPreview] Init with nft_path: {nft_path}")
        
        # Main container for the screen
        self.container = lv.obj(self.content_area)
        self.container.set_size(lv.pct(100), lv.pct(100))
        self.container.align(lv.ALIGN.TOP_MID, 0, 0)
        self.container.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP).pad_all(0).border_width(0), 0
        )
        self.container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        
        # Lock screen preview container with image - NFT image 118px from top, 344x574 size
        self.preview_container = lv.obj(self.container)
        self.preview_container.set_size(344, 574)
        self.preview_container.align(lv.ALIGN.TOP_MID, 0, 118)  # 118px from top as requested
        self.preview_container.add_style(
            StyleWrapper()
            .bg_opa(lv.OPA.TRANSP)
            .pad_all(0)
            .border_width(0)
            .radius(40)
            .clip_corner(True), 0
        )
        self.preview_container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.preview_container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        self.preview_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.preview_container.clear_flag(lv.obj.FLAG.SCROLLABLE)
        
        # Lock screen preview image using NFT - fit to container with black background
        # Set container to black background
        self.preview_container.set_style_bg_color(lv.color_hex(0x000000), 0)
        self.preview_container.set_style_bg_opa(lv.OPA.COVER, 0)
        
        self.lockscreen_preview = lv.img(self.preview_container)
        self.lockscreen_preview.set_src(nft_path)
        # Use image's natural size, then scale with zoom to fit container
        self.lockscreen_preview.set_size(lv.SIZE.CONTENT, lv.SIZE.CONTENT)
        
        # Calculate zoom to fit image within 344x574 while maintaining aspect ratio
        # Assume typical NFT size is around 456x456, calculate zoom for both dimensions
        zoom_x = int((344 / 456) * 256)  # Scale to fit width
        zoom_y = int((574 / 456) * 256)  # Scale to fit height
        zoom = min(zoom_x, zoom_y)  # Use smaller zoom to ensure image fits completely
        
        self.lockscreen_preview.set_zoom(zoom)
        self.lockscreen_preview.align(lv.ALIGN.CENTER, 0, 0)
        
        # Device name and bluetooth name overlaid on the image
        device_name = storage_device.get_model() or "OneKey Pro"
        ble_name = storage_device.get_ble_name() or uart.get_ble_name()
        
        # Device name label (overlaid on image)
        self.device_name_label = lv.label(self.preview_container)
        self.device_name_label.set_text(device_name)
        self.device_name_label.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold38)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.CENTER), 0
        )
        self.device_name_label.align_to(self.preview_container, lv.ALIGN.TOP_MID, 0, 49)
        
        # Bluetooth name label (overlaid on image)
        self.bluetooth_label = lv.label(self.preview_container)
        if ble_name and len(ble_name) >= 4:
            self.bluetooth_label.set_text("Pro " + ble_name[-4:])
        else:
            self.bluetooth_label.set_text("Pro")
        self.bluetooth_label.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.CENTER), 0
        )
        self.bluetooth_label.align_to(self.device_name_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 8)

    def eventhandler(self, event_obj):
        event = event_obj.code
        target = event_obj.get_target()
        if event == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if isinstance(target, lv.imgbtn):
                if hasattr(self, "nav_back") and target == self.nav_back.nav_btn:
                    if self.prev_scr is not None:
                        lv.scr_load(self.prev_scr)
                    return
                elif hasattr(self, "rti_btn") and target == self.rti_btn:
                    # Set as lock screen - convert A:1: to A: format for storage
                    lockscreen_path = self.nft_path
                    
                    # Keep NFT paths as A:1: format (like custom wallpapers) - don't convert
                    # if lockscreen_path.startswith("A:1:"):
                    #     lockscreen_path = lockscreen_path.replace("A:1:", "A:")
                    
                    if __debug__:
                        print(f"[NftLockScreenPreview] Original path: {self.nft_path}")
                        print(f"[NftLockScreenPreview] Setting lockscreen to: {lockscreen_path}")
                        
                    # For NFT lockscreens, we need to handle the square format differently
                    # NFTs are 456x456 but lockscreens expect 480x800 (or similar aspect ratio)
                    # For now, let LVGL handle the scaling, but mark it as NFT for special handling
                    if __debug__:
                        print(f"[NftLockScreenPreview] Using NFT path: {lockscreen_path}")
                        print(f"[NftLockScreenPreview] Note: NFT is square format, lockscreen will scale/crop")
                    
                    try:
                        # First, verify the NFT file exists and is accessible
                        test_file_path = lockscreen_path.replace("A:", "1:")
                        try:
                            stat_result = io.fatfs.stat(test_file_path)
                            file_size = stat_result[6] if len(stat_result) > 6 else "unknown"
                            if __debug__:
                                print(f"[NftLockScreenPreview] NFT file verified: {test_file_path}, size: {file_size}")
                        except Exception as file_err:
                            if __debug__:
                                print(f"[NftLockScreenPreview] NFT file access error: {file_err}")
                                print(f"[NftLockScreenPreview] Trying original path: {lockscreen_path}")
                        
                        storage_device.set_homescreen(lockscreen_path)
                        if __debug__:
                            print(f"[NftLockScreenPreview] Lockscreen set successfully")
                            # Verify it was saved
                            saved_path = storage_device.get_homescreen()
                            print(f"[NftLockScreenPreview] Verified saved path: {saved_path}")
                        
                        # Force refresh MainScreen background to apply new lockscreen
                        if hasattr(MainScreen, '_instance') and MainScreen._instance:
                            main_screen = MainScreen._instance
                            # Refresh the background with new lockscreen
                            main_screen.add_style(
                                StyleWrapper().bg_img_src(lockscreen_path),
                                0,
                            )
                            if __debug__:
                                print(f"[NftLockScreenPreview] MainScreen background refreshed")
                            
                            # Also refresh AppDrawer if it exists
                            if hasattr(main_screen, 'apps') and main_screen.apps:
                                main_screen.apps.refresh_background()
                                if __debug__:
                                    print(f"[NftLockScreenPreview] AppDrawer background refreshed")
                        
                        # Force refresh LockScreen if it exists to apply new NFT background
                        try:
                            from .lockscreen import LockScreen
                            if hasattr(LockScreen, '_instance') and LockScreen._instance:
                                lock_screen = LockScreen._instance
                                if __debug__:
                                    print(f"[NftLockScreenPreview] Found LockScreen instance: {lock_screen}")
                                
                                # For NFT lockscreens, try different background image settings
                                style = StyleWrapper().bg_img_src(lockscreen_path).bg_img_opa(lv.OPA._40)
                                
                                # Try to set background image tiling mode for better NFT display
                                try:
                                    # LVGL might support background image recolor or tiling
                                    if hasattr(lv, 'BG_IMG_TILED') or hasattr(lv.style_t, 'set_bg_img_tiled'):
                                        if __debug__:
                                            print(f"[NftLockScreenPreview] Trying tiled background mode")
                                        # This might help with square images
                                except:
                                    pass
                                
                                lock_screen.add_style(style, 0)
                                # Force invalidate to refresh the display
                                lock_screen.invalidate()
                                if __debug__:
                                    print(f"[NftLockScreenPreview] LockScreen refreshed and invalidated")
                            else:
                                if __debug__:
                                    print(f"[NftLockScreenPreview] No LockScreen instance found")
                        except Exception as e:
                            if __debug__:
                                print(f"[NftLockScreenPreview] LockScreen refresh error: {e}")
                        
                    except Exception as e:
                        if __debug__:
                            print(f"[NftLockScreenPreview] Error setting lockscreen: {e}")
                    
                    # Navigate back to MainScreen (AppDrawer) after setting lockscreen
                    # Find the root MainScreen instance
                    main_screen = None
                    if hasattr(MainScreen, '_instance') and MainScreen._instance:
                        main_screen = MainScreen._instance
                    else:
                        main_screen = MainScreen()
                    
                    if __debug__:
                        print(f"[NftLockScreenPreview] Navigating to MainScreen: {main_screen}")
                    
                    # Use AnimScreen's load_screen method for proper navigation
                    self.load_screen(main_screen, destroy_self=True)
                    return


class NftHomeScreenPreview(AnimScreen):
    def __init__(self, prev_scr, nft_path, nft_config):
        super().__init__(
            prev_scr=prev_scr,
            title="Preview",
            nav_back=True,
            rti_path="A:/res/checkmark.png"
        )
        self.nft_path = nft_path
        self.nft_config = nft_config
        self.original_wallpaper_path = nft_path
        self.is_blur_active = False
        
        # Check if blur file exists
        file_name = nft_path.split("/")[-1]
        file_name_without_ext = file_name.split(".")[0]
        blur_path = nft_path.replace(file_name, f"{file_name_without_ext}-blur.jpg")
        self.blur_exists = self._check_blur_exists(blur_path)
        
        # Main container
        self.container = lv.obj(self.content_area)
        self.container.set_size(lv.pct(100), lv.pct(100))
        self.container.align(lv.ALIGN.TOP_MID, 0, 0)
        self.container.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP).pad_all(0).border_width(0), 0
        )
        self.container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        
        # Home screen preview container - NFT image 118px from top, 344x574 size
        self.preview_container = lv.obj(self.container)
        self.preview_container.set_size(344, 574)
        self.preview_container.align(lv.ALIGN.TOP_MID, 0, 118)  # 118px from top as requested
        self.preview_container.add_style(
            StyleWrapper()
            .bg_opa(lv.OPA.TRANSP)
            .pad_all(0)
            .border_width(0)
            .radius(40)
            .clip_corner(True), 0
        )
        self.preview_container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.preview_container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        self.preview_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.preview_container.clear_flag(lv.obj.FLAG.SCROLLABLE)
        
        # Home screen preview image - fit to container with black background
        # Set container to black background
        self.preview_container.set_style_bg_color(lv.color_hex(0x000000), 0)
        self.preview_container.set_style_bg_opa(lv.OPA.COVER, 0)
        
        self.homescreen_preview = lv.img(self.preview_container)
        self.current_wallpaper_path = nft_path
        self.homescreen_preview.set_src(nft_path)
        # Use image's natural size, then scale with zoom to fit container
        self.homescreen_preview.set_size(lv.SIZE.CONTENT, lv.SIZE.CONTENT)
        
        # Calculate zoom to fit image within 344x574 while maintaining aspect ratio
        # Assume typical NFT size is around 456x456, calculate zoom for both dimensions
        zoom_x = int((344 / 456) * 256)  # Scale to fit width
        zoom_y = int((574 / 456) * 256)  # Scale to fit height
        zoom = min(zoom_x, zoom_y)  # Use smaller zoom to ensure image fits completely
        
        self.homescreen_preview.set_zoom(zoom)
        self.homescreen_preview.align(lv.ALIGN.CENTER, 0, 0)
        
        # Add 6 app icons like HomeScreenSetting (3 rows of 2, 100px size)
        self.app_icons = []
        icon_size = 100
        icon_spacing_x = 41  # Horizontal spacing between icons
        icon_spacing_y = 40.3  # Vertical spacing between icons
        start_x = -((icon_size // 2) + (icon_spacing_x // 2))  # Centered
        start_y = 64  # First row distance from top of preview_container
        
        for i in range(6):
            row = i // 2  # 0, 0, 1, 1, 2, 2
            col = i % 2   # 0, 1, 0, 1, 0, 1
            x_pos = int(start_x + col * (icon_size + icon_spacing_x))
            y_pos = int(start_y + row * (icon_size + icon_spacing_y))
            
            # Create image directly without holder to show natural shape
            icon_img = lv.img(self.preview_container)
            icon_img.set_src("A:/res/icon_example.png")
            # Let image use its natural size
            icon_img.set_size(lv.SIZE.CONTENT, lv.SIZE.CONTENT)
            # Position the image
            icon_img.align_to(self.preview_container, lv.ALIGN.TOP_MID, x_pos, y_pos)
            self.app_icons.append(icon_img)
        
        # Create only Blur button for NFT HomeScreen preview (no Change button needed)
        self._create_blur_button()
        
        # Position blur button centered at bottom
        self.blur_button.align_to(self.preview_container, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        self.blur_label.align_to(self.blur_button, lv.ALIGN.OUT_BOTTOM_MID, 0, 4)

    def _create_button_with_label(self, icon_path, text, callback):
        """Create a button with icon and label like HomeScreenSetting"""
        # Create button
        button = lv.btn(self.container)
        button.set_size(64, 64)
        button.align_to(self.preview_container, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        button.add_style(StyleWrapper().border_width(0).radius(40), 0)
        button.add_flag(lv.obj.FLAG.CLICKABLE)
        button.clear_flag(lv.obj.FLAG.EVENT_BUBBLE)
        
        # Create icon
        icon = lv.img(button)
        if icon_path:  # Only set icon if path is not empty
            icon.set_src(icon_path)
        icon.align(lv.ALIGN.CENTER, 0, 0)
        
        # Create label
        label = lv.label(self.container)
        label.set_text(text)
        label.add_style(StyleWrapper()
                       .text_font(font_GeistRegular20)
                       .text_color(lv_colors.WHITE)
                       .text_align(lv.TEXT_ALIGN.CENTER), 0)
        label.align_to(button, lv.ALIGN.OUT_BOTTOM_MID, 0, 4)
        
        # Add event callback
        button.add_event_cb(callback, lv.EVENT.CLICKED, None)
        
        return button, icon, label
    
    def _create_blur_button(self):
        """Create only Blur button like HomeScreenSetting"""
        # Create Blur button with proper icon
        self.blur_button, self.blur_button_icon, self.blur_label = \
            self._create_button_with_label("A:/res/blur_no_selected.png", "Blur", self.on_blur_clicked)
        
        # Initialize blur button state
        self._update_blur_button_state()
    
    def on_select_clicked(self, event_obj):
        """Handle Change button click - navigate to wallpaper selection"""
        # Navigate to WallperChange for wallpaper selection - not needed for NFT preview
        pass
    
    def on_blur_clicked(self, event_obj):
        """Handle Blur button click"""
        if self.blur_exists:
            self._toggle_blur()

    def _check_blur_exists(self, blur_path):
        try:
            # Remove A:1: prefix and check if file exists
            file_path = blur_path.replace("A:1:", "1:")
            if __debug__:
                print(f"[NftHomeScreenPreview] Checking blur file: {blur_path} -> {file_path}")
            with io.fatfs.open(file_path, "r") as f:
                if __debug__:
                    print(f"[NftHomeScreenPreview] Blur file exists: {file_path}")
                return True
        except Exception as e:
            if __debug__:
                print(f"[NftHomeScreenPreview] Blur file not found: {file_path}, error: {e}")
            return False
    
    def _update_blur_button_state(self):
        """Update blur button state exactly like HomeScreenSetting"""
        if not self.blur_exists:
            # Disabled state - no blur version available (matching HomeScreenSetting)
            icon_path = "A:/res/blur_not_available.png"
            self.blur_button.clear_flag(lv.obj.FLAG.CLICKABLE)
            # Make button look disabled
            self.blur_button.set_style_bg_opa(lv.OPA.TRANSP, 0)
            self.blur_button.set_style_border_width(0, 0)
        else:
            # Blur version available - clickable, restore styles
            self.blur_button.add_flag(lv.obj.FLAG.CLICKABLE)
            # Restore button styles
            self.blur_button.set_style_bg_opa(lv.OPA.COVER, 0)
            self.blur_button.set_style_border_width(1, 0)
            
            if getattr(self, 'is_blur_active', False):
                icon_path = "A:/res/blur_selected.png"
            else:
                icon_path = "A:/res/blur_no_selected.png"
        
        # Update the blur button icon
        self.blur_button_icon.set_src(icon_path)
    
    def _toggle_blur(self):
        if not self.blur_exists:
            return
        
        # Get original file name and construct blur path
        file_name = self.nft_path.split("/")[-1]
        file_name_without_ext = file_name.split(".")[0]
        
        # Construct blur path using the same directory structure
        blur_path = self.nft_path.replace(file_name, f"{file_name_without_ext}-blur.jpg")
        
        if self.is_blur_active:
            # Switch to original
            self.current_wallpaper_path = self.original_wallpaper_path
            self.is_blur_active = False
        else:
            # Switch to blur
            self.current_wallpaper_path = blur_path
            self.is_blur_active = True
        
        # Update the preview image
        self.homescreen_preview.set_src(self.current_wallpaper_path)
        # Re-apply zoom after changing source
        scale = int(574 * 256 / 456)  # Scale based on height
        self.homescreen_preview.set_zoom(scale)
        self.homescreen_preview.align(lv.ALIGN.CENTER, 0, 0)
        self._update_blur_button_state()

    def eventhandler(self, event_obj):
        event = event_obj.code
        target = event_obj.get_target()
        if event == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if isinstance(target, lv.imgbtn):
                if hasattr(self, "nav_back") and target == self.nav_back.nav_btn:
                    if self.prev_scr is not None:
                        lv.scr_load(self.prev_scr)
                    return
                elif hasattr(self, "rti_btn") and target == self.rti_btn:
                    # Set as home screen - convert A:1: to A: format for storage
                    wallpaper_path = self.current_wallpaper_path
                    
                    # Keep NFT paths as A:1: format (like custom wallpapers) - don't convert  
                    # if wallpaper_path.startswith("A:1:"):
                    #     wallpaper_path = wallpaper_path.replace("A:1:", "A:")
                    
                    if __debug__:
                        print(f"[NftHomeScreenPreview] Original path: {self.current_wallpaper_path}")
                        print(f"[NftHomeScreenPreview] Setting homescreen to: {wallpaper_path}")
                    
                    try:
                        storage_device.set_appdrawer_background(wallpaper_path)
                        if __debug__:
                            print(f"[NftHomeScreenPreview] Successfully set homescreen")
                            # Verify it was saved
                            saved_path = storage_device.get_homescreen()
                            print(f"[NftHomeScreenPreview] Verified saved path: {saved_path}")
                        
                        # Force refresh MainScreen background to apply new homescreen
                        if hasattr(MainScreen, '_instance') and MainScreen._instance:
                            main_screen = MainScreen._instance
                            # Refresh the background with new homescreen (lockscreen still used for background)
                            lockscreen_path = storage_device.get_homescreen()
                            if lockscreen_path:
                                main_screen.add_style(
                                    StyleWrapper().bg_img_src(lockscreen_path),
                                    0,
                                )
                                if __debug__:
                                    print(f"[NftHomeScreenPreview] MainScreen background refreshed with lockscreen")
                            
                            # Also refresh AppDrawer if it exists  
                            if hasattr(main_screen, 'apps') and main_screen.apps:
                                main_screen.apps.refresh_background()
                                if __debug__:
                                    print(f"[NftHomeScreenPreview] AppDrawer background refreshed")
                        
                    except Exception as e:
                        if __debug__:
                            print(f"[NftHomeScreenPreview] Error setting homescreen: {e}")
                    
                    # Navigate back to MainScreen (AppDrawer) after setting homescreen
                    # Find the root MainScreen instance
                    main_screen = None
                    if hasattr(MainScreen, '_instance') and MainScreen._instance:
                        main_screen = MainScreen._instance
                    else:
                        main_screen = MainScreen()
                    
                    if __debug__:
                        print(f"[NftHomeScreenPreview] Navigating to MainScreen: {main_screen}")
                    
                    # Use AnimScreen's load_screen method for proper navigation
                    self.load_screen(main_screen, destroy_self=True)
                    return
            else:
                # Handle button clicks for Blur button only
                if hasattr(self, 'blur_button') and target == self.blur_button:
                    self.on_blur_clicked(event_obj)


class SettingsScreen(AnimScreen):
    def collect_animation_targets(self) -> list:
        if lv.scr_act() == MainScreen._instance:
            return []
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.TITLE__SETTINGS),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            self.refresh_text()
            if not self.is_visible():
                self._load_scr(self, lv.scr_act() != self)
            return
        # if __debug__:
        #     self.add_style(StyleWrapper().bg_color(lv_colors.ONEKEY_GREEN_1), 0)
        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.general = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__GENERAL),
            left_img_src="A:/res/general.png",
        )
        # self.connect = ListItemBtn(
        #     self.container,
        #     _(i18n_keys.ITEM__CONNECT),
        #     left_img_src="A:/res/connect.png",
        # )
        self.air_gap = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__AIR_GAP_MODE),
            left_img_src="A:/res/connect.png",
        )
        # self.home_scr = ListItemBtn(
        #     self.container,
        #     _(i18n_keys.ITEM__HOMESCREEN),
        #     left_img_src="A:/res/homescreen.png",
        # )
        self.security = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__SECURITY),
            left_img_src="A:/res/security.png",
        )
        self.wallet = ListItemBtn(
            self.container, _(i18n_keys.ITEM__WALLET), left_img_src="A:/res/wallet.png"
        )
        if not utils.BITCOIN_ONLY:
            self.fido_keys = ListItemBtn(
                self.container,
                _(i18n_keys.FIDO_FIDO_KEYS_LABEL),
                left_img_src="A:/res/fido-keys.png",
            )
        self.about = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__ABOUT_DEVICE),
            left_img_src="A:/res/about.png",
        )
        if not utils.PRODUCTION:
            self.fp_test = ListItemBtn(
                self.container,
                "指纹测试",
            )
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def refresh_text(self):
        self.title.set_text(_(i18n_keys.TITLE__SETTINGS))
        self.general.label_left.set_text(_(i18n_keys.ITEM__GENERAL))
        # self.connect.label_left.set_text(_(i18n_keys.ITEM__CONNECT))
        self.air_gap.label_left.set_text(_(i18n_keys.ITEM__AIR_GAP_MODE))
        # self.home_scr.label_left.set_text(_(i18n_keys.ITEM__HOMESCREEN))
        self.security.label_left.set_text(_(i18n_keys.ITEM__SECURITY))
        self.wallet.label_left.set_text(_(i18n_keys.ITEM__WALLET))
        if not utils.BITCOIN_ONLY:
            self.fido_keys.label_left.set_text(_(i18n_keys.FIDO_FIDO_KEYS_LABEL))
        self.about.label_left.set_text(_(i18n_keys.ITEM__ABOUT_DEVICE))

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.general:
                GeneralScreen(self)
            # elif target == self.connect:
            #     ConnectSetting(self)
            # elif target == self.home_scr:
            #     HomeScreenSetting(self)
            elif target == self.security:
                SecurityScreen(self)
            elif target == self.wallet:
                WalletScreen(self)
            elif target == self.about:
                AboutSetting(self)
            # elif target == self.boot_loader:
            #     Go2UpdateMode(self)
            elif target == self.air_gap:
                AirGapSetting(self)
            elif not utils.BITCOIN_ONLY and target == self.fido_keys:
                FidoKeysSetting(self)
            elif not utils.PRODUCTION and target == self.fp_test:
                FingerprintTest(self)


class ConnectWalletWays(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.TITLE__CONNECT_APP_WALLET),
                "subtitle": _(i18n_keys.TITLE__CONNECT_APP_WALLET_DESC),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            if not self.is_visible():
                self._load_scr(self)
            return
        airgap_enabled = storage_device.is_airgap_mode()
        if airgap_enabled:
            self.waring_bar = Banner(
                self.content_area,
                LEVEL.WARNING,
                _(i18n_keys.MSG__BLUETOOTH_AND_USB_HAS_DISABLED_IN_AIR_GAP_MODE),
            )
            self.waring_bar.align_to(self.subtitle, lv.ALIGN.OUT_BOTTOM_MID, 0, 40)
        self.container = ContainerFlexCol(
            self.content_area, self.subtitle, padding_row=2
        )
        if airgap_enabled:
            self.container.align_to(self.waring_bar, lv.ALIGN.OUT_BOTTOM_MID, 0, 8)

        self.by_ble = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__BLUETOOTH),
            left_img_src="A:/res/connect-way-ble-on.png",
        )
        self.by_usb = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__USB),
            left_img_src="A:/res/connect-way-usb-on.png",
        )
        if airgap_enabled:
            self.by_ble.disable()
            self.by_ble.img_left.set_src("A:/res/connect-way-ble-off.png")
            self.by_usb.disable()
            self.by_usb.img_left.set_src("A:/res/connect-way-usb-off.png")

        self.by_qrcode = ListItemBtn(
            self.container,
            _(i18n_keys.BUTTON__QRCODE),
            left_img_src="A:/res/connect-way-qrcode.png",
        )
        self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.by_ble:
                ConnectWalletGuide("ble", self)
            elif target == self.by_usb:
                ConnectWalletGuide("usb", self)
            elif target == self.by_qrcode:
                gc.collect()
                WalletList(self)
            else:
                return

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)


class ConnectWalletGuide(Screen):
    def __init__(self, c_type, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            assert c_type in ["ble", "usb"], "Invalid connection type"
            self.connect_type = c_type
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.TITLE__BLUETOOTH_CONNECT)
                if c_type == "ble"
                else _(i18n_keys.TITLE__USB_CONNECT),
                "subtitle": _(i18n_keys.CONTENT__SELECT_THE_WALLET_YOU_WANT_TO_CONNECT),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            return

        self.container = ContainerFlexCol(
            self.content_area, self.subtitle, padding_row=2
        )

        self.onekey = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__ONEKEY_WALLET),
            "BTC·ETH·TRON·SOL·NEAR ...",
            left_img_src="A:/res/ok-logo-48.png",
        )
        self.onekey.text_layout_vertical(pad_top=17, pad_ver=20)

        self.mm = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__METAMASK_WALLET),
            _(i18n_keys.CONTENT__ETH_AND_EVM_POWERED_NETWORK),
            left_img_src="A:/res/mm-logo-48.png",
        )
        self.mm.text_layout_vertical()
        if self.connect_type == "ble":
            self.mm.add_flag(lv.obj.FLAG.HIDDEN)

        self.okx = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__OKX_WALLET),
            _(i18n_keys.CONTENT__BTC_AND_EVM_COMPATIBLE_NETWORKS),
            left_img_src="A:/res/okx-logo-48.png",
        )
        self.okx.text_layout_vertical(pad_top=17, pad_ver=20)

        self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target not in [self.onekey, self.mm, self.okx]:
                return
            from trezor.lvglui.scrs.template import ConnectWalletTutorial

            if target == self.onekey:
                title = _(i18n_keys.ITEM__ONEKEY_WALLET)
                subtitle = (
                    _(i18n_keys.CONTENT__IOS_ANDROID)
                    if self.connect_type == "ble"
                    else _(i18n_keys.CONTENT__DESKTOP_BROWSER_EXTENSION)
                )
                steps = [
                    (
                        _(i18n_keys.FORM__DOWNLOAD_ONEKEY_APP),
                        _(i18n_keys.FORM__DOWNLOAD_ONEKEY_APP_MOBILE)
                        if self.connect_type == "ble"
                        else _(i18n_keys.FORM__DOWNLOAD_ONEKEY_APP_DESKTOP),
                    ),
                    (
                        _(i18n_keys.FORM__CONNECT_VIA_BLUETOOTH)
                        if self.connect_type == "ble"
                        else _(i18n_keys.FORM__CONNECT_YOUR_DEVICE),
                        _(i18n_keys.FORM__CONNECT_VIA_BLUETOOTH_DESC)
                        if self.connect_type == "ble"
                        else _(i18n_keys.FORM__CONNECT_YOUR_DEVICE_DESC),
                    ),
                    (
                        _(i18n_keys.FORM__PAIR_DEVICES)
                        if self.connect_type == "ble"
                        else _(i18n_keys.FORM__START_THE_CONNECTION),
                        _(i18n_keys.FORM__PAIR_DEVICES_DESC)
                        if self.connect_type == "ble"
                        else _(i18n_keys.FORM__START_THE_CONNECTION_DESC),
                    ),
                ]
                logo = "A:/res/ok-logo-96.png"
                url = (
                    "https://help.onekey.so/hc/articles/9541173629455"
                    if self.connect_type == "ble"
                    else "https://help.onekey.so/hc/articles/9402090066319"
                )
            elif target == self.mm:
                title = _(i18n_keys.ITEM__METAMASK_WALLET)
                subtitle = _(i18n_keys.CONTENT__BROWSER_EXTENSION)
                steps = [
                    (
                        _(i18n_keys.FORM__ACCESS_WALLET),
                        _(i18n_keys.FORM__OPEN_METAMASK_IN_YOUR_BROWSER),
                    ),
                    (
                        _(i18n_keys.FORM__CONNECT_HARDWARE_WALLET),
                        _(i18n_keys.FORM__CONNECT_HARDWARE_WALLET_DESC),
                    ),
                    (
                        _(i18n_keys.FORM__UNLOCK_ACCOUNT),
                        _(i18n_keys.FORM__UNLOCK_ACCOUNT_DESC),
                    ),
                ]
                logo = "A:/res/mm-logo-96.png"
                url = "https://help.onekey.so/hc/articles/8910581291151#tab-item-generated-0"
            else:
                title = _(i18n_keys.ITEM__OKX_WALLET)
                subtitle = (
                    _(i18n_keys.CONTENT__IOS_ANDROID)
                    if self.connect_type == "ble"
                    else _(i18n_keys.CONTENT__BROWSER_EXTENSION)
                )
                steps = [
                    (
                        _(i18n_keys.FORM__ACCESS_WALLET),
                        _(i18n_keys.FORM__ACCESS_WALLET_DESC)
                        if self.connect_type == "ble"
                        else _(i18n_keys.FORM__OPEN_THE_OKX_WALLET_EXTENSION),
                    ),
                    (
                        _(i18n_keys.FORM__CONNECT_VIA_BLUETOOTH)
                        if self.connect_type == "ble"
                        else _(i18n_keys.FORM__INSTALL_ONEKEY_BRIDGE),
                        _(i18n_keys.FORM__CONNECT_VIA_BLUETOOTH_DESC)
                        if self.connect_type == "ble"
                        else _(i18n_keys.FORM__INSTALL_ONEKEY_BRIDGE_DESC),
                    ),
                    (
                        _(i18n_keys.FORM__IMPORT_WALLET_ACCOUNTS),
                        _(i18n_keys.FORM__IMPORT_WALLET_ACCOUNTS_DESC)
                        if self.connect_type == "ble"
                        else _(
                            i18n_keys.FORM__OKX_EXTENSION_IMPORT_WALLET_ACCOUNTS_DESC
                        ),
                    ),
                ]
                logo = "A:/res/okx-logo-96.png"
                url = (
                    "https://help.onekey.so/hc/articles/8925272484111#tab-item-generated-1"
                    if self.connect_type == "ble"
                    else "https://help.onekey.so/hc/articles/8925272484111#tab-item-generated-0"
                )
            ConnectWalletTutorial(title, subtitle, steps, url, logo)

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)


class WalletList(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.TITLE__QR_CODE_CONNECT),
                "subtitle": _(i18n_keys.CONTENT__SELECT_THE_WALLET_YOU_WANT_TO_CONNECT),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            return

        self.container = ContainerFlexCol(
            self.content_area, self.subtitle, padding_row=2
        )

        self.onekey = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__ONEKEY_WALLET),
            _(i18n_keys.CONTENT__BTC_SOL_ETH_N_EVM_NETWORKS),
            left_img_src="A:/res/ok-logo-48.png",
        )
        self.onekey.text_layout_vertical()

        self.mm = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__METAMASK_WALLET),
            _(i18n_keys.CONTENT__ETH_AND_EVM_POWERED_NETWORK),
            left_img_src="A:/res/mm-logo-48.png",
        )
        self.mm.text_layout_vertical(pad_top=17, pad_ver=20)

        self.okx = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__OKX_WALLET),
            # "BTC·ETH·TRON·SOL·NEAR ...",
            _(i18n_keys.CONTENT__COMING_SOON),
            left_img_src="A:/res/okx-logo-48.png",
        )
        self.okx.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_BLACK_5),
            0,
        )
        self.okx.text_layout_vertical(pad_top=17, pad_ver=20)

        self.okx.label_left.set_style_text_color(lv_colors.WHITE_2, 0)
        self.okx.label_right.set_style_text_color(lv_colors.ONEKEY_GRAY_1, 0)

        self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.okx.clear_flag(lv.obj.FLAG.CLICKABLE)

        if (
            not storage_device.is_passphrase_enabled()
            and not passphrase.is_passphrase_pin_enabled()
        ):
            from trezor.qr import gen_hd_key

            if not get_hd_key():
                workflow.spawn(gen_hd_key(self.refresh))
        else:
            retrieval_hd_key()
            retrieval_encoder()

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target not in [self.onekey, self.mm, self.okx]:
                return
            gc.collect()
            if target == self.onekey:
                self.connect_onekey(target)
            elif target == self.mm:
                self.connect_mm(target)
            elif target == self.okx:
                qr_data = b""
                ConnectWallet(
                    _(i18n_keys.ITEM__OKX_WALLET),
                    "Ethereum, Bitcoin, Polygon, Solana, OKT Chain, TRON and other networks.",
                    qr_data,
                    "A:/res/okx-logo-96.png",
                )

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)

    def connect_onekey(self, target):
        from trezor.qr import get_encoder

        if passphrase.is_enabled():
            encoder = retrieval_encoder()
        else:
            encoder = get_encoder()
        if encoder is None:
            from trezor.qr import gen_multi_accounts

            workflow.spawn(
                gen_multi_accounts(
                    lambda: lv.event_send(target, lv.EVENT.CLICKED, None)
                )
            )
            return
        ConnectWallet(
            None,
            None,
            None,
            encoder=encoder,
            subtitle=_(i18n_keys.CONTENT__OPEN_ONEKEY_SCAN_THE_QRCODE),
        )

    def connect_mm(self, target):
        qr_data = (
            retrieval_hd_key()
            if storage_device.is_passphrase_enabled()
            else get_hd_key()
        )
        if qr_data is None:
            from trezor.qr import gen_hd_key

            workflow.spawn(
                gen_hd_key(lambda: lv.event_send(target, lv.EVENT.CLICKED, None))
            )
            return
        ConnectWallet(
            _(i18n_keys.ITEM__METAMASK_WALLET),
            _(i18n_keys.CONTENT__ETH_AND_EVM_POWERED_NETWORK),
            qr_data,
            "A:/res/mm-logo-96.png",
        )


class BackupWallet(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.APP__BACK_UP),
                "subtitle": _(i18n_keys.CONTENT__SELECT_THE_WAY_YOU_WANT_TO_BACK_UP),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            if not self.is_visible():
                self._load_scr(self)
            return

        self.container = ContainerFlexCol(
            self.content_area, self.subtitle, padding_row=2
        )
        from trezor.enums import BackupType

        is_bip39 = storage_device.get_backup_type() == BackupType.Bip39
        self.lite = ListItemBtn(
            self.container,
            "OneKey Lite",
            left_img_src="A:/res/icon-lite-48.png",
        )
        # hide lite backup for now
        # self.lite.add_flag(lv.obj.FLAG.HIDDEN)

        self.keytag = ListItemBtn(
            self.container,
            "OneKey Keytag",
            left_img_src="A:/res/icon-dot-48.png",
        )

        if not is_bip39:
            self.lite.disable()
            self.keytag.disable()

        self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target in [self.lite, self.keytag]:
                from trezor.wire import DUMMY_CONTEXT
                from apps.management.recovery_device import recovery_device
                from trezor.messages import RecoveryDevice

                if target == self.lite:
                    airgap_enabled = storage_device.is_airgap_mode()
                    if airgap_enabled:
                        screen = FullSizeWindow(
                            _(i18n_keys.TITLE__BACKUP_LIMITED),
                            _(i18n_keys.TITLE__BACKUP_LIMITED_DESC),
                            confirm_text=_(i18n_keys.BUTTON__GO_SETTINGS),
                            cancel_text=_(i18n_keys.BUTTON__BACK),
                            anim_dir=0,
                        )
                        screen.btn_layout_ver()
                        if hasattr(screen, "subtitle"):
                            screen.subtitle.set_recolor(True)
                        workflow.spawn(self.handle_airgap_response(screen))
                        return
                    utils.set_backup_lite()
                elif target == self.keytag:
                    utils.set_backup_keytag()
                # pyright: off
                workflow.spawn(
                    recovery_device(
                        DUMMY_CONTEXT,
                        RecoveryDevice(dry_run=True, enforce_wordlist=True),
                    )
                )
                # pyright: on

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)

    async def handle_airgap_response(self, screen):
        from trezor.wire import DUMMY_CONTEXT

        if await DUMMY_CONTEXT.wait(screen.request()):
            screen.destroy()
            AirGapSetting(self)
        else:
            screen.destroy()


class ConnectWallet(FullSizeWindow):
    def __init__(
        self,
        wallet_name,
        support_chains,
        qr_data,
        icon_path=None,
        encoder=None,
        subtitle=None,
    ):
        super().__init__(
            _(i18n_keys.TITLE__CONNECT_STR_WALLET).format(wallet_name)
            if wallet_name
            else None,
            _(i18n_keys.CONTENT__OPEN_STR_WALLET_AND_SCAN_THE_QR_CODE_BELOW).format(
                wallet_name
            )
            if wallet_name
            else subtitle,
            anim_dir=0,
        )
        self.content_area.set_style_max_height(684, 0)
        self.add_nav_back()

        from trezor.lvglui.scrs.components.qrcode import QRCode

        self.encoder = encoder
        data = qr_data if encoder is None else encoder.next_part()
        self.qr = QRCode(
            self.content_area,
            data,
            icon_path=icon_path,
            size=440,
        )
        self.qr.align_to(self.subtitle, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 40)

        if wallet_name and support_chains:
            self.panel = lv.obj(self.content_area)
            self.panel.set_size(456, lv.SIZE.CONTENT)
            self.panel.add_style(
                StyleWrapper()
                .bg_color(lv_colors.ONEKEY_GRAY_3)
                .bg_opa()
                .radius(40)
                .border_width(0)
                .pad_hor(24)
                .pad_ver(12)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.label_top = lv.label(self.panel)
            self.label_top.set_text(_(i18n_keys.LIST_KEY__SUPPORTED_CHAINS))
            self.label_top.add_style(
                StyleWrapper().text_font(font_GeistSemiBold26).pad_ver(4).pad_hor(0), 0
            )
            self.label_top.align(lv.ALIGN.TOP_LEFT, 0, 0)
            self.line = lv.line(self.panel)
            self.line.set_size(408, 1)
            self.line.add_style(
                StyleWrapper().bg_color(lv_colors.ONEKEY_GRAY_2).bg_opa(),
                0,
            )
            self.line.align_to(self.label_top, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 9)
            self.label_bottom = lv.label(self.panel)
            self.label_bottom.set_width(408)
            self.label_bottom.add_style(
                StyleWrapper().text_font(font_GeistRegular26).pad_ver(12).pad_hor(0),
                0,
            )
            # self.content_area.clear_flag(lv.obj.FLAG.SCROLL_ELASTIC)
            # self.content_area.clear_flag(lv.obj.FLAG.SCROLL_MOMENTUM)
            self.content_area.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
            self.label_bottom.set_long_mode(lv.label.LONG.WRAP)
            self.label_bottom.set_text(support_chains)
            self.label_bottom.align_to(self.line, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 0)
            self.panel.align_to(self.qr, lv.ALIGN.OUT_BOTTOM_MID, 0, 32)
        self.nav_back.add_event_cb(self.on_nav_back, lv.EVENT.CLICKED, None)
        self.add_event_cb(self.on_nav_back, lv.EVENT.GESTURE, None)

        if encoder is not None:
            workflow.spawn(self.update_qr())

    # def on_scroll_begin(self, event_obj):
    #     self.scrolling = True

    # def on_scroll_end(self, event_obj):
    #     self.scrolling = False

    def on_nav_back(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.nav_back.nav_btn:
                if self.encoder is not None:
                    self.channel.publish(1)
                else:
                    self.destroy()
        elif code == lv.EVENT.GESTURE:
            _dir = lv.indev_get_act().get_gesture_dir()
            if _dir == lv.DIR.RIGHT:
                lv.event_send(self.nav_back.nav_btn, lv.EVENT.CLICKED, None)

    def destroy(self, delay_ms=10):
        self.del_delayed(delay_ms)

    async def update_qr(self):
        while True:
            stop_single = self.request()
            racer = loop.race(stop_single, loop.sleep(100))
            await racer
            if stop_single in racer.finished:
                self.destroy()
                return
            # if self.scrolling:
            #     await loop.sleep(5000)
            #     continue
            assert self.encoder is not None
            qr_data = self.encoder.next_part()
            self.qr.update(qr_data, len(qr_data))


class ScanScreen(Screen):
    SCAN_STATE_IDLE = 0
    SCAN_STATE_SCANNING = 1
    SCAN_STATE_SUCCESS = 2
    SCAN_STATE_ERROR = 3
    VALID_TRANSITIONS = {
        SCAN_STATE_IDLE: [SCAN_STATE_SCANNING, SCAN_STATE_ERROR],
        SCAN_STATE_SCANNING: [SCAN_STATE_SUCCESS, SCAN_STATE_ERROR],
        SCAN_STATE_SUCCESS: [SCAN_STATE_IDLE],
        SCAN_STATE_ERROR: [SCAN_STATE_IDLE],
    }

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            kwargs = {
                "prev_scr": prev_scr,
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            if not self.is_visible():
                self._load_scr(self)
            return

        self.nav_back.align(lv.ALIGN.TOP_RIGHT, 0, 44)
        self.nav_back.nav_btn.add_style(
            StyleWrapper().bg_img_src("A:/res/nav-close.png"), 0
        )
        self.nav_back.nav_btn.align(lv.ALIGN.RIGHT_MID, 0, 0)

        self.camera_bg = lv.img(self.content_area)
        self.camera_bg.set_src("A:/res/camera-bg.png")
        self.camera_bg.align(lv.ALIGN.TOP_MID, 0, 148)
        # self.camera_bg.add_flag(lv.obj.FLAG.HIDDEN)

        self.btn = NormalButton(self, f"{LV_SYMBOLS.LV_SYMBOL_LIGHTBULB}")
        self.btn.set_size(64, 64)
        self.btn.add_style(StyleWrapper().radius(lv.RADIUS.CIRCLE), 0)
        self.btn.align(lv.ALIGN.TOP_LEFT, 12, 48)
        self.btn.add_state(lv.STATE.CHECKED)
        self.add_event_cb(self.on_event, lv.EVENT.CLICKED, None)
        self.desc = lv.label(self.content_area)
        self.desc.set_size(456, lv.SIZE.CONTENT)
        self.desc.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular30)
            .text_color(lv_colors.LIGHT_GRAY)
            .pad_hor(12)
            .pad_ver(16)
            .text_letter_space(-1)
            .text_align_center(),
            0,
        )
        self.desc.align_to(self.camera_bg, lv.ALIGN.OUT_BOTTOM_MID, 0, 14)
        self.process_bar = lv.bar(self.content_area)
        self.process_bar.set_size(368, 8)
        self.process_bar.add_style(
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_GRAY_2)
            .bg_opa(lv.OPA.COVER)
            .radius(22),
            0,
        )
        self.process_bar.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_GREEN_2),
            lv.PART.INDICATOR | lv.STATE.DEFAULT,
        )
        self.process_bar.align_to(self.desc, lv.ALIGN.OUT_BOTTOM_MID, 0, 32)
        self.process_bar.set_range(0, 100)
        self.process_bar.set_value(0, lv.ANIM.OFF)
        self.process_bar.add_flag(lv.obj.FLAG.HIDDEN)

        self.state = ScanScreen.SCAN_STATE_IDLE
        self._fsm_show()

        scan_qr(self)

    @classmethod
    def notify_close(cls):
        if hasattr(cls, "_instance") and cls._instance._init:
            lv.event_send(cls._instance.nav_back.nav_btn, lv.EVENT.CLICKED, None)

    async def transition_to(self, new_state: int):
        self._can_transition_to(new_state)
        if new_state == ScanScreen.SCAN_STATE_ERROR:
            await self._error_feedback()
            new_state = ScanScreen.SCAN_STATE_IDLE

        self._fsm_show(new_state)
        self.state = new_state

    async def on_process_update(self, process: int):
        if self.state == ScanScreen.SCAN_STATE_IDLE:
            await self.transition_to(ScanScreen.SCAN_STATE_SCANNING)
        workflow.idle_timer.touch()
        self.process_bar.set_value(process, lv.ANIM.OFF)
        if process >= 100:
            await self.transition_to(ScanScreen.SCAN_STATE_SUCCESS)

    def on_event(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.btn:
                if self.btn.has_state(lv.STATE.CHECKED):
                    self.btn.label.set_text(f"{LV_SYMBOLS.LV_SYMBOL_TRFFIC_LIGHT}")
                    self.btn.enable(bg_color=lv_colors.ONEKEY_BLACK)
                    self.btn.clear_state(lv.STATE.CHECKED)
                    uart.flashled_open()
                else:
                    uart.flashled_close()
                    self.btn.label.set_text(f"{LV_SYMBOLS.LV_SYMBOL_LIGHTBULB}")
                    self.btn.enable()
                    self.btn.add_state(lv.STATE.CHECKED)
            elif target == self.nav_back.nav_btn:
                uart.flashled_close()
                close_camera()

    async def _error_feedback(self):
        from trezor.ui.layouts import show_error_no_interact

        await show_error_no_interact(
            _(i18n_keys.TITLE__DATA_FORMAT_NOT_SUPPORT),
            _(i18n_keys.CONTENT__QR_CODE_TYPE_NOT_SUPPORT_PLEASE_TRY_AGAIN),
        )

    def _can_transition_to(self, new_state: int):
        if new_state not in ScanScreen.VALID_TRANSITIONS[self.state]:
            if __debug__:
                raise ValueError(
                    f"Invalid state transition: {self.state} -> {new_state}"
                )
            else:
                self.notify_close()

    def _fsm_show(self, state: int = SCAN_STATE_IDLE):
        if state == ScanScreen.SCAN_STATE_IDLE:
            if self.state == ScanScreen.SCAN_STATE_SCANNING:
                self.process_bar.add_flag(lv.obj.FLAG.HIDDEN)
            elif self.state == ScanScreen.SCAN_STATE_SUCCESS:
                if hasattr(self, "wait_tips"):
                    self.wait_tips.add_flag(lv.obj.FLAG.HIDDEN)

            self.desc.set_text(
                _(i18n_keys.CONTENT__SCAN_THE_QR_CODE_DISPLAYED_ON_THE_APP)
            )
            self.desc.clear_flag(lv.obj.FLAG.HIDDEN)
            self.desc.align_to(self.camera_bg, lv.ALIGN.OUT_BOTTOM_MID, 0, 14)

        elif state == ScanScreen.SCAN_STATE_SCANNING:
            self.desc.set_text(_(i18n_keys.CONTENT__SCANNING_HOLD_STILL))
            self.desc.align_to(self.camera_bg, lv.ALIGN.OUT_BOTTOM_MID, 0, 14)
            if self.process_bar.has_flag(lv.obj.FLAG.HIDDEN):
                self.process_bar.clear_flag(lv.obj.FLAG.HIDDEN)
            self.process_bar.set_value(0, lv.ANIM.OFF)
        elif state == ScanScreen.SCAN_STATE_SUCCESS:
            self.process_bar.add_flag(lv.obj.FLAG.HIDDEN)
            self.desc.add_flag(lv.obj.FLAG.HIDDEN)
            if not hasattr(self, "wait_tips"):
                self.refresh()
                self.wait_tips = lv.label(self.camera_bg)
                self.wait_tips.set_text(_(i18n_keys.TITLE__PLEASE_WAIT))
                self.wait_tips.add_style(
                    StyleWrapper()
                    .text_font(font_GeistRegular30)
                    .text_color(lv_colors.LIGHT_GRAY),
                    0,
                )
                self.wait_tips.align(lv.ALIGN.CENTER, 0, 0)
            else:
                if self.wait_tips.has_flag(lv.obj.FLAG.HIDDEN):
                    self.refresh()
                    self.wait_tips.clear_flag(lv.obj.FLAG.HIDDEN)
            # if not hasattr(self, "success_overlay"):
            #     from .components.overlay import ScanSuccessOverlay

            #     self.success_overlay = ScanSuccessOverlay(
            #         self, _(i18n_keys.TITLE__PLEASE_WAIT)
            #     )
            # else:
            #     if self.success_overlay.has_flag(lv.obj.FLAG.HIDDEN):
            #         self.success_overlay.clear_flag(lv.obj.FLAG.HIDDEN)
        else:
            raise ValueError(f"Invalid state: {state}")

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)


if __debug__:
    from .common import SETTINGS_MOVE_TIME, SETTINGS_MOVE_DELAY

    class UITest(lv.obj):
        def __init__(self) -> None:
            super().__init__(lv.layer_sys())
            self.set_size(lv.pct(100), lv.pct(100))
            self.align(lv.ALIGN.TOP_LEFT, 0, 0)
            self.set_style_bg_color(lv_colors.BLACK, 0)
            self.set_style_pad_all(0, 0)
            self.set_style_border_width(0, 0)
            self.set_style_radius(0, 0)
            self.set_style_bg_img_src("A:/res/wallpaper-test.png", 0)
            self.add_flag(lv.obj.FLAG.CLICKABLE)
            self.clear_flag(lv.obj.FLAG.SCROLLABLE)
            self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

        def on_click(self, _event_obj):
            self.delete()

    class AnimationSettings(Screen):
        def __init__(self, prev_scr=None):
            if not hasattr(self, "_init"):
                self._init = True
                kwargs = {
                    "prev_scr": prev_scr,
                    "nav_back": True,
                }
                super().__init__(**kwargs)
            else:
                return

            # region
            self.app_drawer_up = lv.label(self.content_area)
            self.app_drawer_up.set_size(456, lv.SIZE.CONTENT)
            self.app_drawer_up.add_style(
                StyleWrapper()
                .pad_all(12)
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.app_drawer_up.set_text("主页上滑动画时间:")
            self.app_drawer_up.align_to(self.nav_back, lv.ALIGN.OUT_BOTTOM_LEFT, 12, 20)

            self.slider = lv.slider(self.content_area)
            self.slider.set_size(456, 80)
            self.slider.set_ext_click_area(20)
            self.slider.set_range(20, 400)
            self.slider.set_value(APP_DRAWER_UP_TIME, lv.ANIM.OFF)
            self.slider.align_to(self.app_drawer_up, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20)

            self.slider.add_style(
                StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
            )
            self.slider.add_style(
                StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
            )
            self.slider.add_style(
                StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
            )
            self.percent = lv.label(self.slider)
            self.percent.align(lv.ALIGN.CENTER, 0, 0)
            self.percent.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.BLUE),
                0,
            )
            self.percent.set_text(f"{APP_DRAWER_UP_TIME} ms")
            self.slider.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.slider.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

            self.app_drawer_up_delay = lv.label(self.content_area)
            self.app_drawer_up_delay.set_size(456, lv.SIZE.CONTENT)
            self.app_drawer_up_delay.add_style(
                StyleWrapper()
                .pad_all(12)
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.app_drawer_up_delay.set_text("主页上滑动画延时:")
            self.app_drawer_up_delay.align_to(
                self.slider, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20
            )

            self.slider1 = lv.slider(self.content_area)
            self.slider1.set_size(456, 80)
            self.slider1.set_ext_click_area(20)
            self.slider1.set_range(0, 80)
            self.slider1.set_value(APP_DRAWER_UP_DELAY, lv.ANIM.OFF)
            self.slider1.align_to(
                self.app_drawer_up_delay, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20
            )

            self.slider1.add_style(
                StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
            )
            self.slider1.add_style(
                StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
            )
            self.slider1.add_style(
                StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
            )
            self.percent1 = lv.label(self.slider1)
            self.percent1.align(lv.ALIGN.CENTER, 0, 0)
            self.percent1.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.BLUE),
                0,
            )
            self.percent1.set_text(f"{APP_DRAWER_UP_DELAY} ms")
            self.slider1.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.slider1.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
            # endregion
            # region

            self.app_drawer_down = lv.label(self.content_area)
            self.app_drawer_down.set_size(456, lv.SIZE.CONTENT)
            self.app_drawer_down.add_style(
                StyleWrapper()
                .pad_all(12)
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.app_drawer_down.set_text("主页下滑动画时间:")
            self.app_drawer_down.align_to(self.slider1, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20)

            self.slider2 = lv.slider(self.content_area)
            self.slider2.set_size(456, 80)
            self.slider2.set_ext_click_area(20)
            self.slider2.set_range(20, 400)
            self.slider2.set_value(APP_DRAWER_DOWN_TIME, lv.ANIM.OFF)
            self.slider2.align_to(self.app_drawer_down, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20)

            self.slider2.add_style(
                StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
            )
            self.slider2.add_style(
                StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
            )
            self.slider2.add_style(
                StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
            )
            self.percent2 = lv.label(self.slider2)
            self.percent2.align(lv.ALIGN.CENTER, 0, 0)
            self.percent2.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.BLUE),
                0,
            )
            self.percent2.set_text(f"{APP_DRAWER_DOWN_TIME} ms")
            self.slider2.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.slider2.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

            self.app_drawer_down_delay = lv.label(self.content_area)
            self.app_drawer_down_delay.set_size(456, lv.SIZE.CONTENT)
            self.app_drawer_down_delay.add_style(
                StyleWrapper()
                .pad_all(12)
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.app_drawer_down_delay.set_text("主页下滑动画延时:")
            self.app_drawer_down_delay.align_to(
                self.slider2, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20
            )

            self.slider3 = lv.slider(self.content_area)
            self.slider3.set_size(456, 80)
            self.slider3.set_ext_click_area(20)
            self.slider3.set_range(0, 80)
            self.slider3.set_value(APP_DRAWER_DOWN_DELAY, lv.ANIM.OFF)
            self.slider3.align_to(
                self.app_drawer_down_delay, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20
            )

            self.slider3.add_style(
                StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
            )
            self.slider3.add_style(
                StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
            )
            self.slider3.add_style(
                StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
            )
            self.percent3 = lv.label(self.slider3)
            self.percent3.align(lv.ALIGN.CENTER, 0, 0)
            self.percent3.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.BLUE),
                0,
            )
            self.percent3.set_text(f"{APP_DRAWER_DOWN_DELAY} ms")
            self.slider3.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.slider3.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
            # endregion
            # region
            self.cur_up_path_cb_type = lv.label(self.content_area)
            self.cur_up_path_cb_type.set_size(456, lv.SIZE.CONTENT)
            self.cur_up_path_cb_type.add_style(
                StyleWrapper()
                .pad_all(12)
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.set_cur_path_cb_type(0)
            self.cur_up_path_cb_type.align_to(
                self.slider3, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20
            )

            self.cur_sown_path_cb_type = lv.label(self.content_area)
            self.cur_sown_path_cb_type.set_size(456, lv.SIZE.CONTENT)
            self.cur_sown_path_cb_type.add_style(
                StyleWrapper()
                .pad_all(12)
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.set_cur_path_cb_type(1)
            self.cur_sown_path_cb_type.align_to(
                self.cur_up_path_cb_type, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20
            )

            self.container = ContainerFlexCol(
                self.content_area,
                self.cur_sown_path_cb_type,
                padding_row=2,
                pos=(0, 20),
            )

            from .components.listitem import ListItemWithLeadingCheckbox

            self.path_up = ListItemWithLeadingCheckbox(
                self.container,
                "修改主页上滑动画类型",
            )
            self.path_up.enable_bg_color(False)
            self.path_down.enable_bg_color(False)
            self.path_liner = ListItemBtn(
                self.container,
                "path liner",
            )
            self.path_ease_in = ListItemBtn(
                self.container,
                "path ease in(slow at the beginning)",
            )
            self.path_ease_out = ListItemBtn(
                self.container,
                "path ease out(slow at the end)",
            )
            self.path_ease_in_out = ListItemBtn(
                self.container,
                "path ease in out(slow at the beginning and end)",
            )
            self.path_over_shoot = ListItemBtn(
                self.container,
                "path over shoot(overshoot the end value)",
            )
            self.path_bounce = ListItemBtn(
                self.container,
                "path bounce(bounce back a little from the end value (like hitting a wall))",
            )
            self.path_step = ListItemBtn(
                self.container,
                "path step(change in one step at the end)",
            )
            # endregion

            # region
            self.setting_scr = lv.label(self.content_area)
            self.setting_scr.set_size(456, lv.SIZE.CONTENT)
            self.setting_scr.add_style(
                StyleWrapper()
                .pad_all(12)
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.setting_scr.set_text("设置页面动画时间:")
            self.setting_scr.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 40)

            self.slider4 = lv.slider(self.content_area)
            self.slider4.set_size(456, 80)
            self.slider4.set_ext_click_area(20)
            self.slider4.set_range(20, 400)

            self.slider4.set_value(SETTINGS_MOVE_TIME, lv.ANIM.OFF)
            self.slider4.align_to(self.setting_scr, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20)

            self.slider4.add_style(
                StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
            )
            self.slider4.add_style(
                StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
            )
            self.slider4.add_style(
                StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
            )
            self.percent4 = lv.label(self.slider4)
            self.percent4.align(lv.ALIGN.CENTER, 0, 0)
            self.percent4.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.BLUE),
                0,
            )
            self.percent4.set_text(f"{SETTINGS_MOVE_TIME} ms")
            self.slider4.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.slider4.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

            self.setting_scr_delay = lv.label(self.content_area)
            self.setting_scr_delay.set_size(456, lv.SIZE.CONTENT)
            self.setting_scr_delay.add_style(
                StyleWrapper()
                .pad_all(12)
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.WHITE),
                0,
            )
            self.setting_scr_delay.set_text("设置页面动画延时:")
            self.setting_scr_delay.align_to(
                self.slider4, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20
            )

            self.slider5 = lv.slider(self.content_area)
            self.slider5.set_size(456, 80)
            self.slider5.set_ext_click_area(20)
            self.slider5.set_range(0, 80)
            self.slider5.set_value(SETTINGS_MOVE_DELAY, lv.ANIM.OFF)
            self.slider5.align_to(
                self.setting_scr_delay, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20
            )

            self.slider5.add_style(
                StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
            )
            self.slider5.add_style(
                StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
            )
            self.slider5.add_style(
                StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
            )
            self.percent5 = lv.label(self.slider5)
            self.percent5.align(lv.ALIGN.CENTER, 0, 0)
            self.percent5.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular30)
                .text_color(lv_colors.BLUE),
                0,
            )
            self.percent5.set_text(f"{SETTINGS_MOVE_DELAY} ms")
            self.slider5.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            self.slider5.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
            # endregion

            self.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
            self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

        def on_nav_back(self, event_obj):
            pass

        def on_click(self, event_obj):
            global APP_DRAWER_UP_PATH_CB, APP_DRAWER_DOWN_PATH_CB
            # _code = event_obj.code
            target = event_obj.get_target()
            if target == self.path_liner:
                print("path_liner clicked")
                if self.path_up.checkbox.get_state() & lv.STATE.CHECKED:
                    print("path_up checked")
                    APP_DRAWER_UP_PATH_CB = PATH_LINEAR
                if self.path_down.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_DOWN_PATH_CB = PATH_LINEAR
            elif target == self.path_ease_in:
                print("path_ease_in clicked")
                if self.path_up.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_UP_PATH_CB = PATH_EASE_IN
                if self.path_down.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_DOWN_PATH_CB = PATH_EASE_IN
            elif target == self.path_ease_out:
                print("path_ease_out clicked")
                if self.path_up.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_UP_PATH_CB = PATH_EASE_OUT
                if self.path_down.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_DOWN_PATH_CB = PATH_EASE_OUT
            elif target == self.path_ease_in_out:
                print("path_ease_in_out clicked")
                if self.path_up.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_UP_PATH_CB = PATH_EASE_IN_OUT
                if self.path_down.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_DOWN_PATH_CB = PATH_EASE_IN_OUT
            elif target == self.path_over_shoot:
                print("path_over_shoot clicked")
                if self.path_up.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_UP_PATH_CB = PATH_OVER_SHOOT
                if self.path_down.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_DOWN_PATH_CB = PATH_OVER_SHOOT
            elif target == self.path_bounce:
                print("path_bounce clicked")
                if self.path_up.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_UP_PATH_CB = PATH_BOUNCE
                if self.path_down.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_DOWN_PATH_CB = PATH_BOUNCE
            elif target == self.path_step:
                print("path_step clicked")
                if self.path_up.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_UP_PATH_CB = PATH_STEP
                if self.path_down.checkbox.get_state() & lv.STATE.CHECKED:
                    APP_DRAWER_DOWN_PATH_CB = PATH_STEP

            if self.path_up.checkbox.get_state() & lv.STATE.CHECKED:
                self.set_cur_path_cb_type(0)
                MainScreen._instance.apps.show_anim.set_path_cb(APP_DRAWER_UP_PATH_CB)
            if self.path_down.checkbox.get_state() & lv.STATE.CHECKED:
                self.set_cur_path_cb_type(1)
                MainScreen._instance.apps.dismiss_anim.set_path_cb(
                    APP_DRAWER_DOWN_PATH_CB
                )

        def get_path_cb_str(self, path_cb):
            if path_cb is PATH_LINEAR:
                return "path_linear"
            elif path_cb is PATH_EASE_IN:
                return "path_ease_in"
            elif path_cb is PATH_EASE_OUT:
                return "path_ease_out"
            elif path_cb is PATH_EASE_IN_OUT:
                return "path_ease_in_out"
            elif path_cb is PATH_OVER_SHOOT:
                return "path_overshoot"
            elif path_cb is PATH_BOUNCE:
                return "path_bounce"
            elif path_cb is PATH_STEP:
                return "path_step"
            else:
                return "path_linear"

        def set_cur_path_cb_type(self, type: int):
            global APP_DRAWER_UP_PATH_CB, APP_DRAWER_DOWN_PATH_CB
            if type == 0:
                self.cur_up_path_cb_type.set_text(
                    f"current up anim type : {self.get_path_cb_str(APP_DRAWER_UP_PATH_CB)}"
                )
            elif type == 1:
                self.cur_sown_path_cb_type.set_text(
                    f"current down anim type: {self.get_path_cb_str(APP_DRAWER_DOWN_PATH_CB)}"
                )
            else:
                raise ValueError("type is not valid")

        def on_value_changed(self, event_obj):
            global APP_DRAWER_UP_TIME, APP_DRAWER_UP_DELAY, APP_DRAWER_DOWN_TIME, APP_DRAWER_DOWN_DELAY, SETTINGS_MOVE_TIME, SETTINGS_MOVE_DELAY

            target = event_obj.get_target()
            if target == self.slider:
                value = target.get_value()
                APP_DRAWER_UP_TIME = value
                MainScreen._instance.apps.show_anim.set_time(value)
                self.percent.set_text(f"{value} ms")
            elif target == self.slider1:
                value = target.get_value()
                APP_DRAWER_UP_DELAY = value
                MainScreen._instance.apps.show_anim.set_delay(value)
                self.percent1.set_text(f"{value} ms")
            elif target == self.slider2:
                value = target.get_value()
                APP_DRAWER_DOWN_TIME = value
                MainScreen._instance.apps.dismiss_anim.set_time(value)
                self.percent2.set_text(f"{value} ms")
            elif target == self.slider3:
                value = target.get_value()
                APP_DRAWER_DOWN_DELAY = value
                MainScreen._instance.apps.dismiss_anim.set_delay(value)
                self.percent3.set_text(f"{value} ms")
            elif target == self.slider4:
                value = target.get_value()
                SETTINGS_MOVE_TIME = value
                self.percent4.set_text(f"{value} ms")
            elif target == self.slider5:
                value = target.get_value()
                SETTINGS_MOVE_DELAY = value
                self.percent5.set_text(f"{value} ms")


class FingerprintTest(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            kwargs = {
                "prev_scr": prev_scr,
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            return

        from trezorio import fingerprint

        sensitivity, area = fingerprint.get_sensitivity_and_area()

        self.sensitivity = sensitivity
        self.area = area

        # region
        self.app_drawer_up = lv.label(self.content_area)
        self.app_drawer_up.set_size(456, lv.SIZE.CONTENT)
        self.app_drawer_up.add_style(
            StyleWrapper()
            .pad_all(12)
            .text_font(font_GeistRegular30)
            .text_color(lv_colors.WHITE),
            0,
        )
        self.app_drawer_up.set_text("按压阈值:")
        self.app_drawer_up.align_to(self.nav_back, lv.ALIGN.OUT_BOTTOM_LEFT, 12, 20)

        self.slider = lv.slider(self.content_area)
        self.slider.set_size(456, 80)
        self.slider.set_ext_click_area(20)
        self.slider.set_range(20, 250)
        self.slider.set_value(self.sensitivity, lv.ANIM.OFF)
        self.slider.align_to(self.app_drawer_up, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20)

        self.slider.add_style(
            StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
        )
        self.slider.add_style(
            StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
        )
        self.slider.add_style(
            StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
        )
        self.percent = lv.label(self.slider)
        self.percent.align(lv.ALIGN.CENTER, 0, 0)
        self.percent.add_style(
            StyleWrapper().text_font(font_GeistRegular30).text_color(lv_colors.RED),
            0,
        )
        self.percent.set_text(f"{self.sensitivity}")
        self.slider.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
        self.slider.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

        self.app_drawer_up_delay = lv.label(self.content_area)
        self.app_drawer_up_delay.set_size(456, lv.SIZE.CONTENT)
        self.app_drawer_up_delay.add_style(
            StyleWrapper()
            .pad_all(12)
            .text_font(font_GeistRegular30)
            .text_color(lv_colors.WHITE),
            0,
        )
        self.app_drawer_up_delay.set_text("面积:")
        self.app_drawer_up_delay.align_to(self.slider, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20)

        self.slider1 = lv.slider(self.content_area)
        self.slider1.set_size(456, 80)
        self.slider1.set_ext_click_area(20)
        self.slider1.set_range(1, 12)
        self.slider1.set_value(self.area, lv.ANIM.OFF)
        self.slider1.align_to(self.app_drawer_up_delay, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 20)

        self.slider1.add_style(
            StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
        )
        self.slider1.add_style(
            StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
        )
        self.slider1.add_style(
            StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
        )
        self.percent1 = lv.label(self.slider1)
        self.percent1.align(lv.ALIGN.CENTER, 0, 0)
        self.percent1.add_style(
            StyleWrapper().text_font(font_GeistRegular30).text_color(lv_colors.RED),
            0,
        )
        self.percent1.set_text(f"{self.area}")
        self.slider1.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
        self.slider1.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        # endregion

        self.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        # self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def on_nav_back(self, event_obj):
        pass

    def on_value_changed(self, event_obj):
        from trezorio import fingerprint

        target = event_obj.get_target()
        if target == self.slider:
            value = target.get_value()
            self.sensitivity = value
            self.percent.set_text(f"{value}")
            fingerprint.set_sensitivity_and_area(value, self.area)
        elif target == self.slider1:
            value = target.get_value()
            self.area = value
            self.percent1.set_text(f"{value}")
            fingerprint.set_sensitivity_and_area(self.sensitivity, value)


class GeneralScreen(AnimScreen):
    cur_language = ""

    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        list_btns = ["power"]
        for btn_name in list_btns:
            if hasattr(self, btn_name) and getattr(self, btn_name):
                targets.append(getattr(self, btn_name))
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            if self.cur_language:
                self.language.label_right.set_text(self.cur_language)
            self.refresh_text()
            return
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.TITLE__GENERAL),
            nav_back=True,
            rti_path="A:/res/poweroff-white.png",
        )

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        GeneralScreen.cur_language = langs[
            langs_keys.index(storage_device.get_language())
        ][1]
        self.language = ListItemBtn(
            self.container, _(i18n_keys.ITEM__LANGUAGE), GeneralScreen.cur_language
        )

        self.wallpaper = ListItemBtn(self.container,_(i18n_keys.BUTTON__WALLPAPER))

        self.animation = ListItemBtn(self.container, _(i18n_keys.ITEM__ANIMATIONS))

        self.touch = ListItemBtn(self.container, _(i18n_keys.BUTTON__TOUCH))
        
        self.display = ListItemBtn(self.container, _(i18n_keys.BUTTON__DISPLAY))
       
        
        
        # self.power = ListItemBtn(
        #     self.content_area,
        #     _(i18n_keys.ITEM__POWER_OFF),
        #     left_img_src="A:/res/poweroff.png",
        #     has_next=False,
        # )
        # self.power.label_left.set_style_text_color(lv_colors.ONEKEY_RED_1, 0)
        # self.power.align_to(self.container, lv.ALIGN.OUT_BOTTOM_MID, 0, 12)
        # self.power.set_style_radius(40, 0)
        # self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.content_area.add_event_cb(self.on_click_event, lv.EVENT.CLICKED, None)
        self.load_screen(self)

    def refresh_text(self):
        self.title.set_text(_(i18n_keys.TITLE__GENERAL))
        self.language.label_left.set_text(_(i18n_keys.ITEM__LANGUAGE))
        self.display.label_left.set_text(_(i18n_keys.TITLE__DISPLAY))
        self.wallpaper.label_left.set_text(_(i18n_keys.BUTTON__WALLPAPER))
        self.animation.label_left.set_text(_(i18n_keys.ITEM__ANIMATIONS))
        self.touch.label_left.set_text(_(i18n_keys.BUTTON__TOUCH))
        # self.power.label_left.set_text(_(i18n_keys.ITEM__POWER_OFF))
        self.container.update_layout()
        # self.power.align_to(self.container, lv.ALIGN.OUT_BOTTOM_MID, 0, 12)

    def on_click_event(self, event_obj):
        target = event_obj.get_target()
        if target == self.language:
            LanguageSetting(self)
        elif target == self.display:
            DisplayScreen(self)
        elif target == self.animation:
            AnimationSetting(self)
        elif target == self.touch:
            TouchSetting(self)
        elif target == self.wallpaper:
            WallpaperScreen(self)
        elif target == self.rti_btn:
            PowerOff()
        else:
            pass


class DisplayScreen(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "auto_container") and self.auto_container:
            targets.append(self.auto_container)
        if hasattr(self, "device_info_container") and self.device_info_container:
            targets.append(self.device_info_container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            self.backlight.label_right.set_text(
                brightness2_percent_str(storage_device.get_brightness())
            )
            self.autolock.label_right.set_text(get_autolock_delay_str())
            self.shutdown.label_right.set_text(get_autoshutdown_delay_str())
            # Update switch state based on current storage setting
            current_setting = storage_device.is_device_name_display_enabled()
            if current_setting:
                self.model_name_bt_id.add_state()
            else:
                self.model_name_bt_id.clear_state()
            self.refresh_text()
            return

        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__DISPLAY), nav_back=True
        )

        # 主容器
        self.container = ContainerFlexCol(
            self.content_area, self.title, padding_row=2, pos=(0, 40)
        )
        
        # 亮度控制
        self.backlight = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__BRIGHTNESS),
            brightness2_percent_str(storage_device.get_brightness()),
        )
        
        # 自动锁定和关机容器
        self.auto_container = ContainerFlexCol(
            self.content_area, None, padding_row=2
        )
        self.auto_container.align_to(self.container, lv.ALIGN.OUT_BOTTOM_MID, 0, 12)
        
        self.autolock = ListItemBtn(
            self.auto_container,
            # TITLE__AUTO_LOCK,
            _(i18n_keys.TITLE__AUTO_LOCK),
            get_autolock_delay_str(),
        )
        self.shutdown = ListItemBtn(
            self.auto_container,
            _(i18n_keys.ITEM__SHUTDOWN),
            get_autoshutdown_delay_str(),
        )
        
        # 设备名称与蓝牙ID容器
        self.device_info_container = ContainerFlexCol(
            self.content_area, None, padding_row=2
        )
        self.device_info_container.align_to(self.auto_container, lv.ALIGN.OUT_BOTTOM_MID, 0, 12)
        
        self.model_name_bt_id = ListItemBtnWithSwitch(
            self.device_info_container,
            _(i18n_keys.BUTTON__MODEL_NAME_BLUETOOTH_ID),
        )
        # Fix background color to match other ListItemBtn containers  
        self.model_name_bt_id.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_BLACK_3),
            0,
        )
        
        # Set initial switch state based on storage setting
        # ListItemBtnWithSwitch defaults to CHECKED, so we need to handle both cases
        current_setting = storage_device.is_device_name_display_enabled()
        if current_setting:
            # Keep it checked (already default)
            pass
        else:
            # Clear the default checked state
            self.model_name_bt_id.clear_state()
        
        # Add description text for device name display
        self.device_name_description = lv.label(self.content_area)
        self.device_name_description.set_size(456, lv.SIZE.CONTENT)
        self.device_name_description.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .text_color(lv_colors.GRAY_2)
            .pad_all(16),
            0,
        )
        self.device_name_description.set_text(_(i18n_keys.BUTTON__MODEL_NAME_BLUETOOTH_ID_DESC),)
        self.device_name_description.align_to(self.device_info_container, lv.ALIGN.OUT_BOTTOM_LEFT, 16, 8)
        
        # Disable elastic scrolling to match other pages
        self.content_area.clear_flag(lv.obj.FLAG.SCROLL_ELASTIC)
        
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.auto_container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.device_info_container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        # Also listen for switch value changes to handle direct switch clicks
        self.model_name_bt_id.switch.add_event_cb(self.on_switch_change, lv.EVENT.VALUE_CHANGED, None)
        
        # Add debug for gesture detection
        if __debug__:
            print(f"[DISPLAY] DisplayScreen initialized with nav_back: {hasattr(self, 'nav_back')}")
            if hasattr(self, 'nav_back'):
                print(f"[DISPLAY] nav_back button exists: {self.nav_back.nav_btn}")
            # Add debug gesture handler
            self.add_event_cb(self.debug_gesture, lv.EVENT.GESTURE, None)
        
        self.load_screen(self)
        gc.collect()

    def debug_gesture(self, event_obj):
        """Debug gesture handler to see if gestures are being received"""
        if __debug__:
            code = event_obj.code
            if code == lv.EVENT.GESTURE:
                _dir = lv.indev_get_act().get_gesture_dir()
                print(f"[DISPLAY] Gesture detected: {_dir} (RIGHT={lv.DIR.RIGHT})")
                
    def refresh_text(self):
        self.title.set_text(_(i18n_keys.TITLE__DISPLAY))
        if hasattr(self, 'backlight'):
            self.backlight.label_left.set_text(_(i18n_keys.ITEM__BRIGHTNESS))
        if hasattr(self, 'autolock'):
            self.autolock.label_left.set_text(_(i18n_keys.TITLE__AUTO_LOCK),
)
        if hasattr(self, 'shutdown'):
            self.shutdown.label_left.set_text(_(i18n_keys.ITEM__SHUTDOWN))
        # Note: ListItemBtnWithSwitch doesn't expose label_left as an attribute
        # The text is set during construction and cannot be changed after
        if hasattr(self, 'device_name_description'):
            self.device_name_description.set_text(_(i18n_keys.BUTTON__MODEL_NAME_BLUETOOTH_ID_DESC))

    def on_switch_change(self, event_obj):
        """Handle switch value changes and persist the setting"""
        code = event_obj.code
        if code == lv.EVENT.VALUE_CHANGED:
            # Get the new switch state
            new_switch_checked = (self.model_name_bt_id.switch.get_state() & lv.STATE.CHECKED) != 0
            
            # Update storage to persist the setting
            storage_device.set_device_name_display_enabled(new_switch_checked)
            
            # Debug output
            if __debug__:
                print(f"[DISPLAY] Switch changed to: {new_switch_checked}")
                print(f"[DISPLAY] Storage setting is now: {storage_device.is_device_name_display_enabled()}")
            
            # Update MainScreen display if it exists
            if hasattr(MainScreen, "_instance") and MainScreen._instance:
                main_screen = MainScreen._instance
                real_device_name = storage_device.get_model()
                real_ble_name = storage_device.get_ble_name() or uart.get_ble_name()
                
                if __debug__:
                    print(f"[DISPLAY] Updating MainScreen - show: {new_switch_checked}, device: {real_device_name}, ble: {real_ble_name}")
                    print(f"[DISPLAY] MainScreen title exists: {hasattr(main_screen, 'title')}")
                    print(f"[DISPLAY] MainScreen subtitle exists: {hasattr(main_screen, 'subtitle')}")
                
                if new_switch_checked:
                    # Show device names - ensure title/subtitle exist first
                    if hasattr(main_screen, 'title') and main_screen.title:
                        main_screen.title.set_text(real_device_name)
                        main_screen.title.clear_flag(lv.obj.FLAG.HIDDEN)
                    if hasattr(main_screen, 'subtitle') and main_screen.subtitle:
                        main_screen.subtitle.set_text(real_ble_name)
                        main_screen.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)
                        # Ensure centered alignment
                        main_screen.title.add_style(StyleWrapper().text_align_center(), 0)
                        main_screen.subtitle.add_style(
                            StyleWrapper().text_align_center().text_color(lv_colors.WHITE), 0
                        )
                    if __debug__:
                        print(f"[DISPLAY] MainScreen titles shown (if they exist)")
                else:
                    if __debug__:
                        print(f"[DISPLAY] Attempting to hide MainScreen titles")
                        try:
                            if hasattr(main_screen, 'title') and main_screen.title:
                                current_title = main_screen.title.get_text() if hasattr(main_screen.title, 'get_text') else 'N/A'
                                print(f"[DISPLAY] Title exists: '{current_title}'")
                            else:
                                print(f"[DISPLAY] Title does not exist")
                            if hasattr(main_screen, 'subtitle') and main_screen.subtitle:
                                current_subtitle = main_screen.subtitle.get_text() if hasattr(main_screen.subtitle, 'get_text') else 'N/A'
                                print(f"[DISPLAY] Subtitle exists: '{current_subtitle}'")
                            else:
                                print(f"[DISPLAY] Subtitle does not exist")
                        except:
                            print(f"[DISPLAY] Could not get current text")
                    
                    # Hide device names - only if title/subtitle exist
                    if hasattr(main_screen, 'title') and main_screen.title:
                        main_screen.title.add_flag(lv.obj.FLAG.HIDDEN)
                        main_screen.title.set_text("")
                    if hasattr(main_screen, 'subtitle') and main_screen.subtitle:
                        main_screen.subtitle.add_flag(lv.obj.FLAG.HIDDEN)
                        main_screen.subtitle.set_text("")
                    
                    if __debug__:
                        print(f"[DISPLAY] MainScreen titles hidden (if they existed)")
            else:
                if __debug__:
                    print(f"[DISPLAY] MainScreen instance not found or not available")
            
            # Update LockScreen display if it exists
            from .lockscreen import LockScreen
            if hasattr(LockScreen, "_instance") and LockScreen._instance:
                lock_screen = LockScreen._instance
                real_device_name = storage_device.get_model()
                real_ble_name = storage_device.get_ble_name() or uart.get_ble_name()
                
                if __debug__:
                    print(f"[DISPLAY] Updating LockScreen - show: {new_switch_checked}, device: {real_device_name}, ble: {real_ble_name}")
                    print(f"[DISPLAY] LockScreen title exists: {hasattr(lock_screen, 'title')}")
                    print(f"[DISPLAY] LockScreen subtitle exists: {hasattr(lock_screen, 'subtitle')}")
                
                if new_switch_checked:
                    # Show device names - ensure title/subtitle exist first
                    if hasattr(lock_screen, 'title') and lock_screen.title:
                        lock_screen.title.set_text(real_device_name)
                        lock_screen.title.clear_flag(lv.obj.FLAG.HIDDEN)
                    if hasattr(lock_screen, 'subtitle') and lock_screen.subtitle:
                        lock_screen.subtitle.set_text(real_ble_name)
                        lock_screen.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)
                        # Ensure centered alignment with opacity
                        lock_screen.title.add_style(
                            StyleWrapper().text_align_center().text_opa(int(lv.OPA.COVER * 0.85)), 0
                        )
                        lock_screen.subtitle.add_style(
                            StyleWrapper()
                            .text_align_center()
                            .text_color(lv_colors.WHITE)
                            .text_opa(int(lv.OPA.COVER * 0.85)),
                            0,
                        )
                    if __debug__:
                        print(f"[DISPLAY] LockScreen titles shown (if they exist)")
                else:
                    # Hide device names - only if title/subtitle exist
                    if hasattr(lock_screen, 'title') and lock_screen.title:
                        lock_screen.title.add_flag(lv.obj.FLAG.HIDDEN)
                        lock_screen.title.set_text("")
                    if hasattr(lock_screen, 'subtitle') and lock_screen.subtitle:
                        lock_screen.subtitle.add_flag(lv.obj.FLAG.HIDDEN)
                        lock_screen.subtitle.set_text("")
                    if __debug__:
                        print(f"[DISPLAY] LockScreen titles hidden (if they existed)")
            else:
                if __debug__:
                    print(f"[DISPLAY] LockScreen instance not found or not available")

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.backlight:
                BacklightSetting(self)
            elif target == self.autolock:
                # Go directly to auto-lock specific settings
                AutoLockSetting(self)
            elif target == self.shutdown:
                # Go directly to shutdown specific settings
                ShutdownSetting(self)
            # Note: model_name_bt_id switch changes are handled by on_switch_change method


class AutolockSetting(AnimScreen):
    cur_auto_lock = ""
    cur_auto_lock_ms = 0

    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        AutolockSetting.cur_auto_lock_ms = storage_device.get_autolock_delay_ms()
        AutolockSetting.cur_auto_lock = self.get_str_from_ms(
            AutolockSetting.cur_auto_lock_ms
        )
        if not hasattr(self, "_init"):
            self._init = True
        else:
            if self.cur_auto_lock:
                self.auto_lock.label_right.set_text(AutolockSetting.cur_auto_lock)
            self.refresh_text()
            return

        super().__init__(
            prev_scr=prev_scr, 
            title=_(i18n_keys.TITLE__AUTO_LOCK), 
            nav_back=True
        )

        self.container = ContainerFlexCol(
            self.content_area, self.title, padding_row=2, pos=(0, 40)
        )
        
        self.auto_lock = ListItemBtn(
            self.container,
            _(i18n_keys.TITLE__AUTO_LOCK),
            AutolockSetting.cur_auto_lock,
        )
        
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def get_str_from_ms(self, delay_ms: int) -> str:
        if delay_ms == 0:
            return "从不"
        elif delay_ms < 60000:
            return f"{delay_ms // 1000}秒"
        elif delay_ms < 3600000:
            return f"{delay_ms // 60000}分钟"
        else:
            return f"{delay_ms // 3600000}小时"

    def refresh_text(self):  
        self.title.set_text(_(i18n_keys.TITLE__AUTO_LOCK))
        self.auto_lock.label_left.set_text(_(i18n_keys.TITLE__AUTO_LOCK))

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.auto_lock:
                # Use the existing AutoLockSetting class
                AutoLockSetting(self)


class AppdrawerBackgroundSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None, selected_wallpaper=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            # Even if already initialized, update the wallpaper if a new one is provided
            if selected_wallpaper:
                self.selected_wallpaper = selected_wallpaper
                self.current_wallpaper_path = selected_wallpaper
                if hasattr(self, 'lockscreen_preview'):
                    # Use the selected wallpaper path directly (already in correct format)
                    self.lockscreen_preview.set_src(selected_wallpaper)
                    if __debug__:
                        print(f"AppdrawerBackgroundSetting: Updated wallpaper to {selected_wallpaper}")
            self.refresh_text()
            return
        
        self.selected_wallpaper = selected_wallpaper
        
        super().__init__(
            prev_scr=prev_scr,
            nav_back=True,
            rti_path="A:/res/checkmark.png"
        )
        
        if __debug__:
            print("LockScreenSetting initialized")
            print(f"Has nav_back: {hasattr(self, 'nav_back')}")
            print(f"Has rti_btn: {hasattr(self, 'rti_btn')}")
            if hasattr(self, 'nav_back'):
                print(f"nav_back: {self.nav_back}")
            if hasattr(self, 'rti_btn'):
                print(f"rti_btn: {self.rti_btn}")
        
        # Main container for the screen
        self.container = lv.obj(self.content_area)
        self.container.set_size(lv.pct(100), lv.pct(100))
        self.container.align(lv.ALIGN.TOP_MID, 0, 0)
        self.container.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP).pad_all(0).border_width(0), 0
        )
        # Don't capture click events - let them pass through to buttons
        self.container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        
        
        # Lock screen preview container with image
        self.preview_container = lv.obj(self.container)
        self.preview_container.set_size(344, 574)  # Larger preview size
        self.preview_container.align(lv.ALIGN.TOP_MID, 0, 105)  # Below status bar
        self.preview_container.add_style(
            StyleWrapper()
            .bg_opa(lv.OPA.TRANSP)
            .pad_all(0)
            .border_width(0)
            , 0
        )
        # Don't capture click events - let them pass through to buttons
        self.preview_container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.preview_container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        
        # Lock screen preview image
        self.lockscreen_preview = lv.img(self.preview_container)
        
        # Use selected wallpaper if provided, otherwise use current lock screen
        if self.selected_wallpaper:
            self.current_wallpaper_path = self.selected_wallpaper
            # Use selected wallpaper path directly - LVGL supports A:1: format
            display_path = self.selected_wallpaper
            if __debug__:
                print(f"AppdrawerBackgroundSetting: Setting lockscreen preview")
                print(f"AppdrawerBackgroundSetting: Original path: {self.selected_wallpaper}")
                print(f"AppdrawerBackgroundSetting: Display path: {display_path}")
                # Check if file exists using same method as HomeScreenSetting
                try:
                    # Convert path for file system check
                    if display_path.startswith("A:1:/res/wallpapers/"):
                        file_check_path = display_path.replace("A:1:/res/wallpapers/", "1:/res/wallpapers/")
                    elif display_path.startswith("A:/res/wallpapers/"):
                        file_check_path = display_path.replace("A:/res/wallpapers/", "1:/res/wallpapers/")
                    else:
                        file_check_path = display_path
                    
                    stat_info = io.fatfs.stat(file_check_path)
                    file_size = stat_info[0]  # First element is file size
                    print(f"AppdrawerBackgroundSetting: File exists, size: {file_size} bytes")
                except Exception as e:
                    print(f"AppdrawerBackgroundSetting: File check failed: {e}")
            self.lockscreen_preview.set_src(display_path)
            if __debug__:
                print(f"AppdrawerBackgroundSetting: Preview src set, current_wallpaper_path: {self.current_wallpaper_path}")
        else:
            # Get current lock screen image from storage
            lockscreen_path = storage_device.get_homescreen()
            if lockscreen_path:
                self.current_wallpaper_path = lockscreen_path
                self.lockscreen_preview.set_src(lockscreen_path)
            else:
                # Use default wallpaper if no custom lockscreen is set
                self.current_wallpaper_path = "A:/res/wallpaper-2.jpg"
                self.lockscreen_preview.set_src("A:/res/wallpaper-2.jpg")
        
        self.lockscreen_preview.set_size(344, 574)
        self.lockscreen_preview.align(lv.ALIGN.CENTER, 0, 0)
        
        # Device name and bluetooth name overlaid on the image
        device_name = storage_device.get_model() or "OneKey Pro"
        ble_name = storage_device.get_ble_name() or uart.get_ble_name()

        # Device name label (overlaid on image, horizontally centered, 距离上边缘49px)
        self.device_name_label = lv.label(self.preview_container)
        self.device_name_label.set_text(device_name)
        self.device_name_label.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold38)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.CENTER), 0
        )
        # device_name 距离 preview_container 上边缘49px，水平居中（不垂直居中）
        self.device_name_label.align_to(self.preview_container, lv.ALIGN.TOP_MID, 0, 49)

        # Bluetooth name label (overlaid on image, placed below device_name_label)
        self.bluetooth_label = lv.label(self.preview_container)
        if ble_name and len(ble_name) >= 4:
            self.bluetooth_label.set_text("Pro " + ble_name[-4:])
        else:
            self.bluetooth_label.set_text("Pro")
        self.bluetooth_label.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.CENTER), 0
        )
        # bluetooth_label 距离 device_name_label 下边缘 8px，水平居中（不垂直居中）
        self.bluetooth_label.align_to(self.device_name_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 8)
        self.change_button = lv.btn(self.container)
        self.change_button.set_size(64, 64)
        self.change_button.align_to(self.preview_container, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        # Remove border from the button_icon (icon itself is an image, so no border by default)
        # But to be sure, also remove border from the button itself
        self.change_button.add_style(
            StyleWrapper()
            .border_width(0)
            .radius(40), 0
        )

        # Icon in the button - using landscape icon as shown in the image
        self.button_icon = lv.img(self.change_button)
        self.button_icon.set_src("A:/res/wallper.png")  # Landscape icon for wallpaper selection
        self.button_icon.align(lv.ALIGN.CENTER, 0, 0)

        # "Change" text below button
        self.change_label = lv.label(self.container)
        self.change_label.set_text(_(i18n_keys.BUTTON__CHANGE))
        self.change_label.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular20)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.CENTER), 0
        )
        self.change_label.align_to(self.change_button, lv.ALIGN.OUT_BOTTOM_MID, 0, 4)

        # Add event handlers
        self.change_button.add_event_cb(self.on_select_clicked, lv.EVENT.CLICKED, None)
        # Don't make the preview image clickable

        # Add event handler for button_icon: click to go to HomeScreenSetting
        def _on_button_icon_clicked(e):
            self.load_screen(WallperChange(self), destroy_self=True)
        self.button_icon.add_flag(lv.obj.FLAG.CLICKABLE)
        self.button_icon.add_event_cb(_on_button_icon_clicked, lv.EVENT.CLICKED, None)

        self.load_screen(self)
        gc.collect()

    

    def on_select_clicked(self, event_obj):
        """Handle select button click - open wallpaper selection"""
        target = event_obj.get_target()
        if target == self.change_button:
            # Navigate to WallperChange for wallpaper selection
            WallperChange(self)

    def on_wallpaper_clicked(self, event_obj):
        """Handle wallpaper image click - same as select button"""
        self.cycle_wallpaper()

    def cycle_wallpaper(self):
        """Cycle through available wallpapers for demo"""
        wallpapers = [
            "A:/res/wallpaper-1.jpg",
            "A:/res/wallpaper-2.jpg", 
            "A:/res/wallpaper-3.jpg",
            "A:/res/wallpaper-4.jpg"
        ]
        
        current_src = self.lockscreen_preview.get_src()
        try:
            current_index = wallpapers.index(current_src)
            next_index = (current_index + 1) % len(wallpapers)
        except ValueError:
            next_index = 0
            
        self.lockscreen_preview.set_src(wallpapers[next_index])
        
        # TODO: Save selected wallpaper to storage
        # storage_device.set_lock_screen_wallpaper(wallpapers[next_index])

    def refresh_text(self):
        """Refresh display when returning to this screen"""
        # TODO: Load current wallpaper from storage and update preview
        pass

    def eventhandler(self, event_obj):
        """Override event handler to ensure clicks are handled"""
        event = event_obj.code
        target = event_obj.get_target()
        
        if __debug__:
            print(f"LockScreenSetting eventhandler: event={event}, target={target}, type={type(target)}")
            
        if event == lv.EVENT.CLICKED:
            if __debug__:
                print("CLICKED event detected")
            if utils.lcd_resume():
                return
                
            # Check if target is imgbtn (direct button click)
            if isinstance(target, lv.imgbtn):
                if __debug__:
                    print("Target is imgbtn!")
                if hasattr(self, "nav_back") and target == self.nav_back.nav_btn:
                    if __debug__:
                        print("Back button clicked!")
                    if self.prev_scr is not None:
                        self.load_screen(self.prev_scr, destroy_self=True)
                    return
                elif hasattr(self, "rti_btn") and target == self.rti_btn:
                    if __debug__:
                        print("Checkmark button clicked!")
                    self.on_click_ext(target)
                    return
                    
            # Check if target is the navigation container (back button area)
            if hasattr(self, "nav_back") and target == self.nav_back:
                if __debug__:
                    print("Navigation container clicked - going back!")
                if self.prev_scr is not None:
                    self.load_screen(self.prev_scr, destroy_self=True)
                return
                    
            # Only call parent eventhandler for specific unhandled cases
            # Don't call for general container clicks to avoid duplicate WallpaperChange creation
            if isinstance(target, (lv.btn, lv.imgbtn)) and not hasattr(target, '_processed'):
                if __debug__:
                    print("Calling parent eventhandler for button")
                super().eventhandler(event_obj)
            else:
                if __debug__:
                    print(f"Skipping parent eventhandler for target type: {type(target)}")

    def on_click_ext(self, target):
        """Handle checkmark icon click in the upper right corner"""
        if __debug__:
            print(f"on_click_ext called with target: {target}")
            print(f"Has rti_btn: {hasattr(self, 'rti_btn')}")
            if hasattr(self, 'rti_btn'):
                print(f"rti_btn: {self.rti_btn}")
                print(f"target == rti_btn: {target == self.rti_btn}")
        
        if hasattr(self, "rti_btn") and target == self.rti_btn:
            # Use the stored wallpaper path instead of get_src()
            current_wallpaper = getattr(self, 'current_wallpaper_path', None)
            if __debug__:
                print(f"AppdrawerBackgroundSetting: Checkmark clicked! Current wallpaper: {current_wallpaper}")
                print(f"AppdrawerBackgroundSetting: selected_wallpaper: {getattr(self, 'selected_wallpaper', None)}")
                print(f"AppdrawerBackgroundSetting: About to save lockscreen: {current_wallpaper}")
            if current_wallpaper:
                # Save the wallpaper path
                try:
                    storage_device.set_homescreen(current_wallpaper)
                    if __debug__:
                        print(f"AppdrawerBackgroundSetting: Lockscreen wallpaper saved successfully: {current_wallpaper}")
                        # Verify it was saved correctly
                        saved_path = storage_device.get_homescreen()
                        print(f"AppdrawerBackgroundSetting: Verified saved path: {saved_path}")
                except Exception as e:
                    if __debug__:
                        print(f"AppdrawerBackgroundSetting: Error saving lockscreen: {e}")
            # Go back to previous screen
            if self.prev_scr is not None:
                if __debug__:
                    print("AppdrawerBackgroundSetting: Going back to previous screen")
                self.load_screen(self.prev_scr, destroy_self=True)



class WallperChange(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "wps"):
            for wp in self.wps:
                targets.append(wp)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            super().__init__(
                prev_scr=prev_scr, title=_(i18n_keys.TITLE__CHANGE_WALLPAPER), nav_back=True
            )
        else:
            self.container.delete()
        
        # Initialize edit mode state
        self.edit_mode = False
        self.marked_for_deletion = set()  # Track which files are marked for deletion

        # Get custom wallpapers
        file_name_list = []
        if not utils.EMULATOR:
            if __debug__:
                print("WallpaperChange: Scanning for custom wallpapers in 1:/res/wallpapers")
            try:
                file_count = 0
                zoom_count = 0
                all_files = []
                
                for size, _attrs, name in io.fatfs.listdir("1:/res/wallpapers"):
                    file_count += 1
                    all_files.append(name + " (size:" + str(size) + ")")
                    
                    if __debug__:
                        print("WallpaperChange: Found file:", name, "size:", size)
                        print(f"WallpaperChange: File analysis - starts with zoom-: {name.startswith('zoom-')}, starts with wp-: {name.startswith('wp-')}, ends with blur: {name.endswith('-blur.jpeg') or name.endswith('-blur.jpg')}")
                    
                    if size > 0 and (name.startswith("zoom-") or (name.startswith("wp-") and not name.endswith("-blur.jpeg") and not name.endswith("-blur.jpg"))):
                        zoom_count += 1
                        file_name_list.append(name)
                        if __debug__:
                            if name.startswith("zoom-"):
                                print("WallpaperChange: Added zoom file:", name)
                            else:
                                print("WallpaperChange: Added wp file:", name)
                    elif __debug__ and name.startswith("wp-"):
                        print(f"WallpaperChange: Skipped wp file (likely blur version): {name}")
                
                if __debug__:
                    print("WallpaperChange: Directory scan results:")
                    print("  - Total files found:", file_count)
                    print("  - Zoom files added:", zoom_count)
                    print("  - All files:", all_files)
                    
            except Exception as e:
                if __debug__:
                    print("WallpaperChange: Error accessing 1:/res/wallpapers:", e)
                    print("WallpaperChange: Exception type:", type(e))
            
            # Also check alternative paths and file patterns
            if __debug__ and len(file_name_list) == 0:
                print("WallpaperChange: No zoom files found, checking alternative locations and patterns...")
                
                # Check other common paths
                for alt_path in ["0:/res/wallpapers", "A:/res/wallpapers", "1:/res", "A:/res"]:
                    try:
                        alt_files = list(io.fatfs.listdir(alt_path))
                        if len(alt_files) > 0:
                            print("WallpaperChange: Found", len(alt_files), "files in", alt_path, ":", alt_files)
                            # Check if any files match wallpaper patterns
                            wallpaper_files = []
                            for f in alt_files:
                                if 'wallpaper' in f.lower() or 'zoom' in f.lower() or '.jpg' in f.lower() or '.png' in f.lower():
                                    wallpaper_files.append(f)
                            if wallpaper_files:
                                print("WallpaperChange: Potential wallpaper files in", alt_path, ":", wallpaper_files)
                    except:
                        pass
                
                # Also try scanning 1:/res/wallpapers with different patterns
                try:
                    all_wallpaper_files = list(io.fatfs.listdir("1:/res/wallpapers"))
                    print("WallpaperChange: All files in 1:/res/wallpapers:", all_wallpaper_files)
                    if all_wallpaper_files:
                        # Try different naming patterns
                        zoom_patterns = ['zoom', 'wallpaper', '.jpg', '.png']
                        for pattern in zoom_patterns:
                            matching = []
                            for f in all_wallpaper_files:
                                if pattern in f.lower():
                                    matching.append(f)
                            if matching:
                                print("WallpaperChange: Files matching", pattern, ":", matching)
                except:
                    pass
        else:
            if __debug__:
                print("WallpaperChange: Emulator mode - skipping custom wallpaper scan")
        
        if __debug__:
            print("WallpaperChange: Total custom wallpapers found:", len(file_name_list))
            print("WallpaperChange: Custom wallpaper list:", file_name_list)
            print("WallpaperChange: Current wp_cnts:", storage_device.get_wp_cnts())
            
            # If we found custom wallpapers but wp_cnts is 0, update the count to prevent deletion
            if len(file_name_list) > 0 and storage_device.get_wp_cnts() == 0:
                storage_device.increase_wp_cnts()
                if __debug__:
                    print("WallpaperChange: Updated wp_cnts to prevent file deletion:", storage_device.get_wp_cnts())
        
        if file_name_list:
            file_name_list.sort(
                key=lambda name: int(
                    name[5:].split("-")[-1][: -(len(name.split(".")[1]) + 1)]
                )
            )

        # Calculate grid layout
        internal_wp_nums = 7
        custom_wp_nums = len(file_name_list)
        
        # Calculate rows needed: Custom header + custom images (if any) + Pro header + pro images
        custom_rows = math.ceil(custom_wp_nums / 3) if custom_wp_nums > 0 else 0
        pro_rows = math.ceil(internal_wp_nums / 3)
        
        # Build row description: Custom header + custom rows + Pro header + pro rows
        row_dsc = [60]  # Custom header
        if custom_rows > 0:
            row_dsc.extend([GRID_CELL_SIZE_ROWS] * custom_rows)  # Custom images
        else:
            row_dsc.append(178)  # Empty state text container (with 56px spacing to Collection)
        row_dsc.append(60)  # Pro header  
        row_dsc.extend([GRID_CELL_SIZE_ROWS] * pro_rows)  # Pro images
        row_dsc.append(lv.GRID_TEMPLATE.LAST)
        
        # 3 columns
        col_dsc = [
            GRID_CELL_SIZE_COLS,
            GRID_CELL_SIZE_COLS, 
            GRID_CELL_SIZE_COLS,
            lv.GRID_TEMPLATE.LAST,
        ]
        
        self.container = ContainerGrid(
            self.content_area,
            row_dsc=row_dsc,
            col_dsc=col_dsc,
            pad_gap=12,
        )
        self.container.align_to(self.nav_back, lv.ALIGN.OUT_BOTTOM_LEFT, -6, 20)
        
        # Enable event bubbling for the container
        self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        
        current_row = 0
        
        # Custom section header container
        self.custom_header_container = lv.obj(self.container)
        self.custom_header_container.set_size(lv.pct(100), 60)
        self.custom_header_container.clear_flag(lv.obj.FLAG.SCROLLABLE)
        self.custom_header_container.set_style_bg_opa(lv.OPA.TRANSP, 0)
        self.custom_header_container.set_style_border_opa(lv.OPA.TRANSP, 0)
        self.custom_header_container.set_style_pad_all(0, 0)
        self.custom_header_container.set_grid_cell(lv.GRID_ALIGN.STRETCH, 0, 3, lv.GRID_ALIGN.START, current_row, 1)
        
        # Custom text on the left
        self.custom_header = lv.label(self.custom_header_container)
        self.custom_header.set_text(_(i18n_keys.OPTION__CUSTOM__INSERT))
        self.custom_header.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold30)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.LEFT), 0
        )
        self.custom_header.align(lv.ALIGN.LEFT_MID, 0, 0)
        
        # Edit/Done button on the right (only show if there are custom wallpapers)
        if file_name_list:
            self.edit_button = lv.btn(self.custom_header_container)
            self.edit_button.set_size(60, 30)
            self.edit_button.add_style(StyleWrapper().bg_opa(lv.OPA.TRANSP).border_opa(lv.OPA.TRANSP), 0)
            self.edit_button.align(lv.ALIGN.RIGHT_MID, -12, 0)
            
            self.edit_button_label = lv.label(self.edit_button)
            self.edit_button_label.set_text(_(i18n_keys.BUTTON__EDIT))
            self.edit_button_label.add_style(
                StyleWrapper()
                .text_font(font_GeistSemiBold26)
                .text_color(lv.color_hex(0xD2D2D2)), 0
            )
            self.edit_button_label.center()
            
            # Add click handler for edit button
            self.edit_button.add_event_cb(self.on_edit_button_clicked, lv.EVENT.CLICKED, None)
        
        current_row += 1
        
        # Custom wallpapers
        self.wps = []
        self.custom_wps = []  # Track custom wallpapers separately
        if file_name_list:
            for i, file_name in enumerate(file_name_list):
                path_dir = "A:1:/res/wallpapers/"
                current_wp = ImgGridItem(
                    self.container,
                    i % 3,
                    current_row + (i // 3),
                    file_name,
                    path_dir,
                    is_internal=True,
                )
                self.wps.append(current_wp)
                self.custom_wps.append(current_wp)
                
                # Create remove icon for each custom wallpaper (initially hidden)
                # Use remove_icon.png directly with 44px hot area
                remove_icon = lv.btn(self.container)
                remove_icon.set_size(44, 44)  # 44px hot area
                remove_icon.clear_flag(lv.obj.FLAG.SCROLLABLE)
                remove_icon.add_flag(lv.obj.FLAG.HIDDEN)  # Initially hidden
                remove_icon.add_flag(lv.obj.FLAG.CLICKABLE)
                
                # Style the button - transparent background for hot area
                remove_icon.set_style_bg_opa(lv.OPA.TRANSP, 0)
                remove_icon.set_style_border_opa(lv.OPA.TRANSP, 0)
                remove_icon.set_style_shadow_opa(lv.OPA.TRANSP, 0)
                
                # Use remove_icon.png image directly
                remove_icon_img = lv.img(remove_icon)
                remove_icon_img.set_src("A:/res/remove_icon.png")
                remove_icon_img.set_size(40, 40)  # Display size 40x40 as specified
                remove_icon_img.center()  # Center in the 44px hot area
                remove_icon_img.clear_flag(lv.obj.FLAG.CLICKABLE)  # Not clickable, parent handles events
                
                # Position relative to wallpaper - slightly overlapping the rounded corner
                remove_icon.align_to(current_wp, lv.ALIGN.TOP_RIGHT, 14, -14)  # Slightly inside to overlap rounded corner
                remove_icon.move_foreground()
                
                # Add independent event handler for the button
                remove_icon.add_event_cb(lambda e, wp=current_wp: self.on_remove_icon_clicked(e, wp), lv.EVENT.CLICKED, None)
                
                # Store remove icon reference in the wallpaper object
                current_wp.remove_icon = remove_icon
                
                if __debug__:
                    print(f"WallperChange: Added custom wp {i}: {current_wp}, img_path: {current_wp.img_path}")
                    print(f"WallperChange: Created remove_icon {remove_icon} for wp {i}")
            current_row += custom_rows
        else:
            # No custom wallpapers - show instructional text
            self.empty_state_container = lv.obj(self.container)
            self.empty_state_container.set_size(lv.pct(100), 139)  # Height for title + description + spacing
            self.empty_state_container.clear_flag(lv.obj.FLAG.SCROLLABLE)
            self.empty_state_container.set_style_bg_opa(lv.OPA.TRANSP, 0)
            self.empty_state_container.set_style_border_opa(lv.OPA.TRANSP, 0)
            self.empty_state_container.set_style_pad_all(0, 0)
            self.empty_state_container.set_grid_cell(lv.GRID_ALIGN.STRETCH, 0, 3, lv.GRID_ALIGN.START, current_row, 1)
            
            # Title: "Add Wallpaper from OneKey App"
            self.empty_title = lv.label(self.empty_state_container)
            self.empty_title.set_text(_(i18n_keys.TITLE__ADD_WALLPAPER_FROM_ONEKEY_APP))
            self.empty_title.add_style(
                StyleWrapper()
                .text_font(font_GeistSemiBold26)
                .text_color(lv_colors.WHITE)
                .text_align(lv.TEXT_ALIGN.LEFT)
                .text_letter_space(-1), 0  # 缩小字间距
            )
            self.empty_title.align(lv.ALIGN.TOP_LEFT, 4, 10)  # 距离左边框更大一点
            # Description: "Upload an image in My OneKey > Select your OneKey device > Wallpaper."
            self.empty_desc = lv.label(self.empty_state_container)
            self.empty_desc.set_text(_(i18n_keys.TITLE__ADD_WALLPAPER_FROM_ONEKEY_APP_DESC))
            self.empty_desc.set_long_mode(lv.label.LONG.WRAP)  # Enable text wrapping
            self.empty_desc.set_size(lv.pct(100), lv.SIZE.CONTENT)  # Full width, auto height
            self.empty_desc.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular26)
                .text_color(lv_colors.ONEKEY_GRAY_1)
                .text_align(lv.TEXT_ALIGN.LEFT)
                .text_letter_space(-2), 0  # 缩小字间距
            )
            self.empty_desc.align_to(self.empty_title, lv.ALIGN.OUT_BOTTOM_LEFT, 2, 16)
            self.empty_desc.add_style(
                StyleWrapper()
                .text_font(font_GeistRegular26)
                .text_color(lv_colors.ONEKEY_GRAY_1)
                .text_align(lv.TEXT_ALIGN.LEFT), 0
            )
            
            current_row += 1

        # Pro section header
        self.pro_header = lv.label(self.container)
        self.pro_header.set_text(_(i18n_keys.TITLE__COLLECTION))
        self.pro_header.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold26)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.LEFT), 0
        )
        self.pro_header.set_grid_cell(lv.GRID_ALIGN.START, 0, 3, lv.GRID_ALIGN.START, current_row, 1)
        current_row += 1

        # Pro wallpapers (built-in)
        for i in range(internal_wp_nums):
            path_dir = "A:/res/"
            file_name = f"zoom-wallpaper-{i+1}.jpg"

            current_wp = ImgGridItem(
                self.container,
                i % 3,
                current_row + (i // 3),
                file_name,
                path_dir,
                is_internal=True,
            )
            self.wps.append(current_wp)
            if __debug__:
                print(f"WallperChange: Added pro wp {i}: {current_wp}, img_path: {current_wp.img_path}")
            
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        
        # Override the AnimScreen base class event handler to use our custom one
        # This is necessary to handle navigation button clicks safely
        self.remove_event_cb(None)  # Remove all existing event callbacks
        self.add_event_cb(self.eventhandler, lv.EVENT.CLICKED, None)  # Add our custom handler
        
        self.load_screen(self)
        
        # Schedule a refresh to fix initial rendering artifacts
        try:
            import trezor.loop
            trezor.loop.schedule(self._refresh_previews_after_load())
        except (ImportError, AttributeError):
            # Fallback: immediate refresh
            self._refresh_previews_immediate()
        
        gc.collect()

    async def _refresh_previews_after_load(self):
        """Refresh preview images after a short delay to fix initial rendering artifacts"""
        import utime
        utime.sleep_ms(100)  # Small delay to ensure layout is complete
        self._refresh_previews_immediate()

    def _refresh_previews_immediate(self):
        """Force refresh all preview images to fix rendering artifacts"""
        if __debug__:
            print("WallperChange: Refreshing all preview images to fix initial rendering")
        
        if hasattr(self, 'wps'):
            for wp in self.wps:
                try:
                    wp.invalidate()
                except:
                    pass
        
        # Also refresh the container
        if hasattr(self, 'container'):
            try:
                self.container.invalidate()
            except:
                pass

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if __debug__:
            print(f"WallperChange: on_click called, code: {code}, target: {target}")
            print(f"WallperChange: prev_scr: {self.prev_scr}")
            print(f"WallperChange: prev_scr.__class__: {self.prev_scr.__class__ if hasattr(self.prev_scr, '__class__') else 'No class'}")
            print(f"WallperChange: prev_scr.__class__.__name__: {self.prev_scr.__class__.__name__ if hasattr(self.prev_scr, '__class__') else 'No name'}")
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
                
            # Check if clicked target is a remove icon
            if self.edit_mode and hasattr(self, 'custom_wps'):
                if __debug__:
                    print(f"WallperChange: Edit mode active, checking remove icons. Target: {target}")
                for i, wp in enumerate(self.custom_wps):
                    if hasattr(wp, 'remove_icon'):
                        if __debug__:
                            print(f"WallperChange: Checking wp[{i}] remove_icon: {wp.remove_icon}, target: {target}, match: {target == wp.remove_icon}")
                        # Check if target is the button or its child label
                        if target == wp.remove_icon or (hasattr(wp.remove_icon, 'get_child') and target == wp.remove_icon.get_child(0)):
                            if __debug__:
                                print(f"WallperChange: Remove icon clicked for {wp.img_path}")
                            self.on_remove_icon_clicked(event_obj, wp)
                            return
                    else:
                        if __debug__:
                            print(f"WallperChange: wp[{i}] has no remove_icon attribute")
            
            if __debug__:
                print(f"WallperChange: Checking if target in wps, target: {target}")
                print(f"WallperChange: wps length: {len(self.wps) if hasattr(self, 'wps') else 'No wps'}")
                if hasattr(self, 'wps'):
                    for i, wp in enumerate(self.wps):
                        print(f"WallperChange: wps[{i}]: {wp}")
            # Skip wallpaper selection if in edit mode
            if self.edit_mode:
                return
                
            if target not in self.wps:
                if __debug__:
                    print("WallperChange: target not in wps, returning")
                return
            for wp in self.wps:
                if target == wp:
                    if __debug__:
                        print(f"WallperChange: Found matching wp, img_path: {wp.img_path}")
                        print(f"WallperChange: prev_scr type: {self.prev_scr.__class__.__name__ if hasattr(self.prev_scr, '__class__') else 'Unknown'}")
                    # Navigate back to the original setting screen and update wallpaper
                    if hasattr(self.prev_scr, '__class__'):
                        if self.prev_scr.__class__.__name__ == "HomeScreenSetting":
                            if __debug__:
                                print("WallperChange: Navigating to HomeScreenSetting")
                            # Preserve blur state when switching wallpapers
                            current_blur_state = getattr(self.prev_scr, 'is_blur_active', False)
                            if __debug__:
                                print(f"WallperChange: Preserving blur state: {current_blur_state}")
                            # Check if we're selecting the same wallpaper and can reuse the existing screen
                            current_wallpaper = getattr(self.prev_scr, 'current_wallpaper_path', '')
                            selected_wallpaper_base = wp.img_path.replace('zoom-', '').replace('A:/res/', '').replace('A:1:/res/', '')
                            current_wallpaper_base = current_wallpaper.replace('A:/res/', '').replace('A:1:/res/', '').replace('-blur', '')
                            
                            if __debug__:
                                print(f"WallperChange: Comparing wallpapers - selected_base: {selected_wallpaper_base}, current_base: {current_wallpaper_base}")
                            
                            if selected_wallpaper_base == current_wallpaper_base:
                                # Same wallpaper selected, just go back to existing screen
                                if __debug__:
                                    print("WallperChange: Same wallpaper selected, returning to existing screen")
                                    print(f"WallperChange: Current prev_scr: {self.prev_scr}")
                                    print(f"WallperChange: prev_scr type: {type(self.prev_scr)}")
                                    print(f"WallperChange: prev_scr class name: {self.prev_scr.__class__.__name__ if hasattr(self.prev_scr, '__class__') else 'Unknown'}")
                                    if hasattr(self.prev_scr, 'prev_scr'):
                                        print(f"WallperChange: HomeScreenSetting.prev_scr is: {self.prev_scr.prev_scr}")
                                        print(f"WallperChange: HomeScreenSetting.prev_scr type: {type(self.prev_scr.prev_scr)}")
                                    else:
                                        print("WallperChange: prev_scr has no prev_scr attribute")
                                        
                                # Make sure the navigation chain is preserved
                                # The issue might be that prev_scr gets corrupted during navigation
                                try:
                                    # Use direct LVGL loading instead of load_screen with destroy_self=True
                                    lv.scr_load(self.prev_scr)
                                    # Clean up singleton instance properly
                                    try:
                                        del self.__class__._instance
                                    except AttributeError:
                                        pass
                                    self.del_delayed(100)
                                except Exception as nav_error:
                                    if __debug__:
                                        print(f"WallperChange: Failed to navigate back to same screen: {nav_error}")
                                    # Fallback: Try to create a new HomeScreenSetting with correct navigation
                                    try:
                                        # Get the original parent screen (should be WallpaperScreen)
                                        original_parent = getattr(self.prev_scr, 'prev_scr', None)
                                        if original_parent:
                                            new_screen = HomeScreenSetting(original_parent)
                                            lv.scr_load(new_screen)
                                            # Clean up singleton instance properly
                                            try:
                                                del self.__class__._instance
                                            except AttributeError:
                                                pass
                                            self.del_delayed(100)
                                        else:
                                            # Final fallback
                                            fallback_screen = WallpaperScreen()
                                            lv.scr_load(fallback_screen)
                                            # Clean up singleton instance properly
                                            try:
                                                del self.__class__._instance
                                            except AttributeError:
                                                pass
                                            self.del_delayed(100)
                                    except Exception as fallback_error:
                                        if __debug__:
                                            print(f"WallperChange: All fallbacks failed: {fallback_error}")
                            else:
                                # Different wallpaper selected, create new screen
                                if __debug__:
                                    print("WallperChange: Different wallpaper selected, creating new screen")
                                    print(f"WallperChange: Creating HomeScreenSetting with:")
                                    print(f"  - prev_scr: {self.prev_scr.prev_scr}")
                                    print(f"  - selected_wallpaper: {wp.img_path}")
                                    print(f"  - preserve_blur_state: {current_blur_state}")
                                new_screen = HomeScreenSetting(self.prev_scr.prev_scr, selected_wallpaper=wp.img_path, preserve_blur_state=current_blur_state)
                                lv.scr_load(new_screen)
                                # Clean up singleton instance properly
                                try:
                                    del self.__class__._instance
                                except AttributeError:
                                    pass
                                self.del_delayed(100)
                        else:  # AppdrawerBackgroundSetting
                            if __debug__:
                                print("WallperChange: Navigating to AppdrawerBackgroundSetting")
                                print(f"WallperChange: Passing img_path to AppdrawerBackgroundSetting: {wp.img_path}")
                            new_screen = AppdrawerBackgroundSetting(self.prev_scr.prev_scr, selected_wallpaper=wp.img_path)
                            lv.scr_load(new_screen)
                            # Clean up singleton instance properly
                            try:
                                del self.__class__._instance
                            except AttributeError:
                                pass
                            self.del_delayed(100)

    def on_select_clicked(self, event_obj):
        """Handle select button click - open wallpaper selection"""
        target = event_obj.get_target()
        if target == self.change_button:
            # Navigate to WallperChange for wallpaper selection
            WallperChange(self)

    def on_wallpaper_clicked(self, event_obj):
        """Handle wallpaper image click - same as select button"""
        self.cycle_wallpaper()

    def cycle_wallpaper(self):
        """Cycle through available wallpapers for demo"""
        wallpapers = [
            "A:/res/wallpaper-1.jpg",
            "A:/res/wallpaper-2.jpg", 
            "A:/res/wallpaper-3.jpg",
            "A:/res/wallpaper-4.jpg"
        ]
        
        current_src = self.lockscreen_preview.get_src()
        try:
            current_index = wallpapers.index(current_src)
            next_index = (current_index + 1) % len(wallpapers)
        except ValueError:
            next_index = 0
            
        self.lockscreen_preview.set_src(wallpapers[next_index])
        
        # TODO: Save selected wallpaper to storage
        # storage_device.set_lock_screen_wallpaper(wallpapers[next_index])

    def refresh_text(self):
        """Refresh display when returning to this screen"""
        # TODO: Load current wallpaper from storage and update preview
        pass


    def on_edit_button_clicked(self, event_obj):
        """Handle Edit/Done button click"""
        if __debug__:
            print(f"WallpaperChange: Edit button clicked, current edit_mode: {self.edit_mode}")
            
        self.edit_mode = not self.edit_mode
        
        if self.edit_mode:
            # Switch to edit mode
            self.edit_button_label.set_text("Done")
            # Show remove icons for all custom wallpapers
            for i, wp in enumerate(self.custom_wps):
                if hasattr(wp, 'remove_icon'):
                    wp.remove_icon.clear_flag(lv.obj.FLAG.HIDDEN)
                    # Ensure remove icon stays on top
                    wp.remove_icon.move_foreground()
                    if __debug__:
                        print(f"WallpaperChange: Showing remove_icon {wp.remove_icon} for wp[{i}]")
                else:
                    if __debug__:
                        print(f"WallpaperChange: wp[{i}] has no remove_icon attribute")
            if __debug__:
                print("WallpaperChange: Entered edit mode - showing remove icons")
        else:
            # Switch to normal mode and perform deletions
            self.edit_button_label.set_text(_(i18n_keys.BUTTON__EDIT))
            # Hide remove icons
            for wp in self.custom_wps:
                if hasattr(wp, 'remove_icon'):
                    wp.remove_icon.add_flag(lv.obj.FLAG.HIDDEN)
            
            # Delete marked files
            if self.marked_for_deletion:
                if __debug__:
                    print(f"WallpaperChange: Exiting edit mode - deleting {len(self.marked_for_deletion)} files")
                self.delete_marked_files()
            else:
                if __debug__:
                    print("WallpaperChange: Exiting edit mode - no files to delete")
    
    def on_remove_icon_clicked(self, event_obj, wallpaper):
        """Handle remove icon click"""
        if __debug__:
            print(f"WallpaperChange: Remove icon clicked for {wallpaper.img_path}")
            
        # Mark wallpaper for deletion and hide it immediately
        self.marked_for_deletion.add(wallpaper)
        
        # Hide the entire wallpaper item immediately
        wallpaper.add_flag(lv.obj.FLAG.HIDDEN)
        
        # Also hide the remove icon
        if hasattr(wallpaper, 'remove_icon'):
            wallpaper.remove_icon.add_flag(lv.obj.FLAG.HIDDEN)
        
        if __debug__:
            print(f"WallpaperChange: Marked {wallpaper.img_path} for deletion, total marked: {len(self.marked_for_deletion)}")
            print(f"WallpaperChange: Wallpaper {wallpaper.img_path} hidden immediately")
    
    def delete_marked_files(self):
        """Delete files marked for deletion"""
        from trezor import io
        import storage.device as storage_device
        
        if __debug__:
            print(f"WallpaperChange: Starting deletion of {len(self.marked_for_deletion)} files")
        
        marked_count = len(self.marked_for_deletion)
        
        for wallpaper in self.marked_for_deletion:
            try:
                # Extract file name from img_path
                img_path = wallpaper.img_path
                if "A:1:/res/wallpapers/" in img_path:
                    # Custom wallpaper path format: A:1:/res/wallpapers/filename.ext (without zoom- prefix)
                    filename = img_path.replace("A:1:/res/wallpapers/", "")
                    
                    # Delete original file first
                    original_path = f"1:/res/wallpapers/{filename}"
                    if __debug__:
                        print(f"WallpaperChange: Deleting original file: {original_path}")
                    try:
                        io.fatfs.unlink(original_path)
                    except:
                        if __debug__:
                            print(f"WallpaperChange: Original file {original_path} not found or already deleted")
                    
                    # Delete zoom file (add zoom- prefix)
                    zoom_filename = f"zoom-{filename}"
                    zoom_path = f"1:/res/wallpapers/{zoom_filename}"
                    if __debug__:
                        print(f"WallpaperChange: Deleting zoom file: {zoom_path}")
                    try:
                        io.fatfs.unlink(zoom_path)
                    except:
                        if __debug__:
                            print(f"WallpaperChange: Zoom file {zoom_path} not found or already deleted")
                    
                    # Delete blur file if it exists
                    blur_filename = filename.replace('.jpg', '-blur.jpg').replace('.png', '-blur.png')
                    blur_path = f"1:/res/wallpapers/{blur_filename}"
                    if __debug__:
                        print(f"WallpaperChange: Attempting to delete blur file: {blur_path}")
                    try:
                        io.fatfs.unlink(blur_path)
                        if __debug__:
                            print(f"WallpaperChange: Successfully deleted blur file: {blur_path}")
                    except:
                        if __debug__:
                            print(f"WallpaperChange: Blur file {blur_path} not found or already deleted")
                    
                    # Check if this wallpaper is currently in use and replace it
                    self.replace_if_in_use(img_path)
                    
                    if __debug__:
                        print(f"WallpaperChange: Successfully deleted {img_path}")
                        
            except Exception as e:
                if __debug__:
                    print(f"WallpaperChange: Error deleting {wallpaper.img_path}: {e}")
        
        # Clear the marked for deletion set
        self.marked_for_deletion.clear()
        
        # Decrease wallpaper count
        for _ in range(marked_count):
            storage_device.decrease_wp_cnts()
        
        # Refresh the screen to show updated wallpaper list
        if __debug__:
            print("WallpaperChange: Refreshing screen after deletions")
        self.__init__(self.prev_scr)
    
    def replace_if_in_use(self, deleted_path):
        """Replace deleted wallpaper with wallpaper-7.jpg if it's currently in use"""
        import storage.device as storage_device
        
        try:
            current_homescreen = storage_device.get_homescreen()
            current_lockscreen = storage_device.get_homescreen()
            replacement_path = "A:/res/wallpaper-7.jpg"
            
            # Check homescreen
            if current_homescreen and deleted_path in current_homescreen:
                if __debug__:
                    print(f"WallpaperChange: Replacing homescreen wallpaper with {replacement_path}")
                storage_device.set_appdrawer_background(replacement_path)
            
            # Check lockscreen  
            if current_lockscreen and deleted_path in current_lockscreen:
                if __debug__:
                    print(f"WallpaperChange: Replacing lockscreen wallpaper with {replacement_path}")
                storage_device.set_homescreen(replacement_path)
                
        except Exception as e:
            if __debug__:
                print(f"WallpaperChange: Error checking/replacing wallpapers in use: {e}")

    def eventhandler(self, event_obj):
        """Override eventhandler to handle navigation safely"""
        event = event_obj.code
        target = event_obj.get_target()
        if __debug__:
            print(f"WallperChange: Custom eventhandler called - event={event}, target={target}")
        if event == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if isinstance(target, lv.imgbtn):
                if hasattr(self, "nav_back") and target == self.nav_back.nav_btn:
                    if __debug__:
                        print("WallperChange: Back button clicked - navigating to previous screen")
                    if self.prev_scr is not None:
                        # Get the class name for creating a proper fallback
                        prev_class_name = self.prev_scr.__class__.__name__ if hasattr(self.prev_scr, '__class__') else 'Unknown'
                        
                        # Use a different approach - avoid destroy_self=True to prevent singleton issues
                        try:
                            if __debug__:
                                print(f"WallperChange: Attempting safe navigation to {prev_class_name}")
                            
                            # Instead of using load_screen with destroy_self=True, 
                            # use direct screen loading without singleton conflicts
                            if prev_class_name == "HomeScreenSetting":
                                # Get the grandparent (should be WallpaperScreen)
                                grandparent = getattr(self.prev_scr, 'prev_scr', None)
                                if __debug__:
                                    print(f"WallperChange: Creating new HomeScreenSetting with grandparent: {grandparent}")
                                new_screen = HomeScreenSetting(grandparent)
                                # Use direct LVGL screen loading instead of load_screen
                                lv.scr_load(new_screen)
                                # Clean up this screen manually with singleton cleanup
                                try:
                                    del self.__class__._instance
                                except AttributeError:
                                    pass
                                self.del_delayed(100)
                            elif prev_class_name == "AppdrawerBackgroundSetting":
                                # Get the grandparent (should be WallpaperScreen) 
                                grandparent = getattr(self.prev_scr, 'prev_scr', None)
                                if __debug__:
                                    print(f"WallperChange: Creating new AppdrawerBackgroundSetting with grandparent: {grandparent}")
                                new_screen = AppdrawerBackgroundSetting(grandparent)
                                # Use direct LVGL screen loading instead of load_screen
                                lv.scr_load(new_screen)
                                # Clean up this screen manually with singleton cleanup
                                try:
                                    del self.__class__._instance
                                except AttributeError:
                                    pass
                                self.del_delayed(100)
                            else:
                                # Unknown previous screen type, use WallpaperScreen as safe fallback
                                if __debug__:
                                    print("WallperChange: Unknown prev_scr type, using WallpaperScreen as fallback")
                                fallback_screen = WallpaperScreen()
                                lv.scr_load(fallback_screen)
                                # Clean up this screen manually with singleton cleanup
                                try:
                                    del self.__class__._instance
                                except AttributeError:
                                    pass
                                self.del_delayed(100)
                            return
                        except Exception as fallback_error:
                            if __debug__:
                                print(f"WallperChange: Safe navigation failed: {fallback_error}")
                        
                        # Final fallback: just try to go back to WallpaperScreen using direct LVGL
                        try:
                            if __debug__:
                                print("WallperChange: Using final fallback - direct WallpaperScreen creation")
                            fallback_screen = WallpaperScreen()
                            lv.scr_load(fallback_screen)
                            # Clean up this screen manually with singleton cleanup
                            try:
                                del self.__class__._instance
                            except AttributeError:
                                pass
                            self.del_delayed(100)
                        except Exception as final_error:
                            if __debug__:
                                print(f"WallperChange: All fallbacks failed: {final_error}")
                            # Last resort: just destroy this screen with singleton cleanup
                            try:
                                del self.__class__._instance
                            except AttributeError:
                                pass
                            self.del_delayed(100)
                    return
                elif hasattr(self, "rti_btn") and target == self.rti_btn:
                    self.on_click_ext(target)
                    return
        
        # For all other events (like wallpaper selection), handle them directly
        # Don't call super().eventhandler() to avoid the singleton instance issues
        if event == lv.EVENT.CLICKED:
            # This should trigger the on_click method for wallpaper selections
            self.on_click(event_obj)


class ShutdownSetting(AnimScreen):
    cur_auto_shutdown = ""
    cur_auto_shutdown_ms = 0

    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        ShutdownSetting.cur_auto_shutdown_ms = storage_device.get_autoshutdown_delay_ms()
        ShutdownSetting.cur_auto_shutdown = self.get_str_from_ms(
            ShutdownSetting.cur_auto_shutdown_ms
        )
        if not hasattr(self, "_init"):
            self._init = True
        else:
            if self.cur_auto_shutdown:
                self.auto_shutdown.label_right.set_text(ShutdownSetting.cur_auto_shutdown)
            self.refresh_text()
            return

        super().__init__(
            prev_scr=prev_scr, 
            title="自动关机", 
            nav_back=True
        )

        self.container = ContainerFlexCol(
            self.content_area, self.title, padding_row=2, pos=(0, 40)
        )
        
        self.auto_shutdown = ListItemBtn(
            self.container,
            "自动关机",
            ShutdownSetting.cur_auto_shutdown,
        )
        
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def get_str_from_ms(self, delay_ms: int) -> str:
        if delay_ms == 0:
            return "从不"
        elif delay_ms < 60000:
            return f"{delay_ms // 1000}秒"
        elif delay_ms < 3600000:
            return f"{delay_ms // 60000}分钟"
        else:
            return f"{delay_ms // 3600000}小时"

    def refresh_text(self):
        self.title.set_text("自动关机")
        self.auto_shutdown.label_left.set_text("自动关机")

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.auto_shutdown:
                # Use the original auto-lock setting screen
                Autolock_and_ShutingDown(self)


def get_autolock_delay_str() -> str:
    """Get auto-lock delay as formatted string"""
    delay_ms = storage_device.get_autolock_delay_ms()
    if delay_ms == 0:
        return "从不"
    elif delay_ms < 60000:
        return f"{delay_ms // 1000}秒"
    elif delay_ms < 3600000:
        return f"{delay_ms // 60000}分钟"
    else:
        return f"{delay_ms // 3600000}小时"


def get_autoshutdown_delay_str() -> str:
    """Get auto-shutdown delay as formatted string"""
    delay_ms = storage_device.get_autoshutdown_delay_ms()
    if delay_ms == 0:
        return "从不"
    elif delay_ms < 60000:
        return f"{delay_ms // 1000}秒"
    elif delay_ms < 3600000:
        return f"{delay_ms // 60000}分钟"
    else:
        return f"{delay_ms // 3600000}小时"


class Animations(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            self.refresh_text()
            return

        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__ANIMATIONS), nav_back=True
        )

        self.container = ContainerFlexCol(
            self.content_area, self.title, padding_row=2, pos=(0, 40)
        )
        GeneralScreen.cur_language = langs[
            langs_keys.index(storage_device.get_language())
        ][1]
        self.animation = ListItemBtn(self.container, _(i18n_keys.ITEM__ANIMATIONS))
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def refresh_text(self):
        self.title.set_text(_(i18n_keys.TITLE__ANIMATIONS))
        self.animation.label_left.set_text(_(i18n_keys.ITEM__ANIMATIONS))

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.animation:
                AnimationSetting(self)


class Autolock_and_ShutingDown(AnimScreen):
    cur_auto_lock = ""
    cur_auto_lock_ms = 0
    cur_auto_shutdown = ""
    cur_auto_shutdown_ms = 0

    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        Autolock_and_ShutingDown.cur_auto_lock_ms = (
            storage_device.get_autolock_delay_ms()
        )
        Autolock_and_ShutingDown.cur_auto_shutdown_ms = (
            storage_device.get_autoshutdown_delay_ms()
        )
        Autolock_and_ShutingDown.cur_auto_lock = self.get_str_from_ms(
            Autolock_and_ShutingDown.cur_auto_lock_ms
        )
        Autolock_and_ShutingDown.cur_auto_shutdown = self.get_str_from_ms(
            Autolock_and_ShutingDown.cur_auto_shutdown_ms
        )

        if not hasattr(self, "_init"):
            self._init = True
        else:
            if self.cur_auto_lock:
                self.auto_lock.label_right.set_text(
                    Autolock_and_ShutingDown.cur_auto_lock
                )
            if self.cur_auto_shutdown:
                self.auto_shutdown.label_right.set_text(
                    Autolock_and_ShutingDown.cur_auto_shutdown
                )
            self.refresh_text()
            return

        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.ITEM__AUTO_LOCK_AND_SHUTDOWN),
            nav_back=True,
        )
        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.auto_lock = ListItemBtn(
            self.container, _(i18n_keys.ITEM__AUTO_LOCK), self.cur_auto_lock
        )
        self.auto_shutdown = ListItemBtn(
            self.container, _(i18n_keys.ITEM__SHUTDOWN), self.cur_auto_shutdown
        )
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def refresh_text(self):
        self.title.set_text(_(i18n_keys.ITEM__AUTO_LOCK_AND_SHUTDOWN))
        self.auto_lock.label_left.set_text(_(i18n_keys.ITEM__AUTO_LOCK))
        self.auto_shutdown.label_left.set_text(_(i18n_keys.ITEM__SHUTDOWN))

    def get_str_from_ms(self, time_ms) -> str:
        if time_ms == storage_device.AUTOLOCK_DELAY_MAXIMUM:
            return _(i18n_keys.ITEM__STATUS__NEVER)
        auto_lock_time = time_ms / 1000 // 60
        if auto_lock_time > 60:
            value = str(auto_lock_time // 60).split(".")[0]
            text = _(
                i18n_keys.OPTION__STR_HOUR
                if value == "1"
                else i18n_keys.OPTION__STR_HOURS
            ).format(value)
        elif auto_lock_time < 1:
            value = str(time_ms // 1000).split(".")[0]
            text = _(i18n_keys.OPTION__STR_SECONDS).format(value)
        else:
            value = str(auto_lock_time).split(".")[0]
            text = _(
                i18n_keys.OPTION__STR_MINUTE
                if value == "1"
                else i18n_keys.OPTION__STR_MINUTES
            ).format(value)
        return text

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.auto_lock:
                AutoLockSetting(self)
            elif target == self.auto_shutdown:
                AutoShutDownSetting(self)
            else:
                pass


# pyright: off
class AutoLockSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "tips") and self.tips:
            targets.append(self.tips)
        return targets

    # TODO: i18n
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__AUTO_LOCK), nav_back=True
        )

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.setting_items = [0.5, 1, 2, 5, 10, 30, "Never", None]
        has_custom = True
        self.checked_index = 0
        self.btns: [ListItemBtn] = [None] * (len(self.setting_items))
        for index, item in enumerate(self.setting_items):
            if item is None:
                break
            if not item == "Never":  # last item
                if item == 0.5:
                    item = _(i18n_keys.OPTION__STR_SECONDS).format(int(item * 60))
                else:
                    item = _(
                        i18n_keys.ITEM__STATUS__STR_MINUTES
                        if item != 1
                        else i18n_keys.OPTION__STR_MINUTE
                    ).format(item)
            else:
                item = _(i18n_keys.ITEM__STATUS__NEVER)
            self.btns[index] = ListItemBtn(
                self.container, item, has_next=False, use_transition=False
            )
            # self.btns[index].label_left.add_style(
            #     StyleWrapper().text_font(font_GeistRegular30), 0
            # )
            self.btns[index].add_check_img()
            if item == Autolock_and_ShutingDown.cur_auto_lock:
                has_custom = False
                self.btns[index].set_checked()
                self.checked_index = index

        if has_custom:
            self.custom = storage_device.get_autolock_delay_ms()
            self.btns[-1] = ListItemBtn(
                self.container,
                f"{Autolock_and_ShutingDown.cur_auto_lock}({_(i18n_keys.OPTION__CUSTOM__INSERT)})",
                has_next=False,
                use_transition=False,
            )
            self.btns[-1].add_check_img()
            self.btns[-1].set_checked()
            self.btns[-1].label_left.add_style(
                StyleWrapper().text_font(font_GeistRegular30), 0
            )
            self.checked_index = -1
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.tips = lv.label(self.content_area)
        self.tips.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 0)
        self.tips.set_long_mode(lv.label.LONG.WRAP)
        self.fresh_tips()
        self.tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .width(448)
            .text_color(lv_colors.WHITE_2)
            .text_align_left()
            .text_letter_space(-1)
            .pad_ver(16),
            0,
        )
        self.load_screen(self)
        gc.collect()

    def fresh_tips(self):
        item_text = self.btns[self.checked_index].label_left.get_text()
        if self.setting_items[self.checked_index] is None:
            item_text = item_text.split("(")[0]
        if self.setting_items[self.checked_index] == "Never":
            self.tips.set_text(
                _(i18n_keys.CONTENT__SETTINGS_GENERAL_AUTO_LOCK_OFF_HINT)
            )
        else:
            self.tips.set_text(
                _(i18n_keys.CONTENT__SETTINGS_GENERAL_AUTO_LOCK_ON_HINT).format(
                    item_text or Autolock_and_ShutingDown.cur_auto_lock[:1]
                )
            )

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target in self.btns:
                for index, item in enumerate(self.btns):
                    if item == target and self.checked_index != index:
                        item.set_checked()
                        self.btns[self.checked_index].set_uncheck()
                        self.checked_index = index
                        if index == 6:
                            auto_lock_time = storage_device.AUTOLOCK_DELAY_MAXIMUM
                        elif index == 7:
                            auto_lock_time = self.custom
                        else:
                            auto_lock_time = self.setting_items[index] * 60 * 1000
                        storage_device.set_autolock_delay_ms(int(auto_lock_time))
                        Autolock_and_ShutingDown.cur_auto_lock_ms = auto_lock_time
                        self.fresh_tips()
                        from apps.base import reload_settings_from_storage

                        reload_settings_from_storage()


# pyright: on
class LanguageSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__LANGUAGE), nav_back=True
        )

        self.check_index = 0
        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.lang_buttons = []
        for idx, lang in enumerate(langs):
            lang_button = ListItemBtn(
                self.container, lang[1], has_next=False, use_transition=False
            )
            # lang_button.label_left.add_style(StyleWrapper().text_font(font_GeistRegular30), 0)
            lang_button.add_check_img()
            self.lang_buttons.append(lang_button)
            if GeneralScreen.cur_language == lang[1]:
                lang_button.set_checked()
                self.check_index = idx
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

        self.load_screen(self)
        gc.collect()

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            last_checked = self.check_index
            for idx, button in enumerate(self.lang_buttons):
                if target != button and idx == last_checked:
                    button.set_uncheck()
                if target == button and idx != last_checked:
                    storage_device.set_language(langs_keys[idx])
                    GeneralScreen.cur_language = langs[idx][1]
                    i18n_refresh()
                    self.title.set_text(_(i18n_keys.TITLE__LANGUAGE))
                    self.check_index = idx
                    button.set_checked()


class BacklightSetting(AnimScreen):
    @classmethod
    def page_is_visible(cls) -> bool:
        try:
            if cls._instance is not None and cls._instance.is_visible():
                return True
        except Exception:
            pass
        return False

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__BRIGHTNESS), nav_back=True
        )

        self.current_brightness = storage_device.get_brightness()
        self.temp_brightness = self.current_brightness
        self.container = ContainerFlexCol(self.content_area, self.title)
        self.slider = lv.slider(self.container)
        self.slider.set_size(456, 94)
        self.slider.set_ext_click_area(100)
        self.slider.set_range(style.BACKLIGHT_MIN, style.BACKLIGHT_MAX)
        self.slider.set_value(self.current_brightness, lv.ANIM.OFF)
        self.slider.add_style(
            StyleWrapper().border_width(0).radius(40).bg_color(lv_colors.GRAY_1), 0
        )
        self.slider.add_style(
            StyleWrapper().bg_color(lv_colors.WHITE).pad_all(-50), lv.PART.KNOB
        )
        self.slider.add_style(
            StyleWrapper().radius(0).bg_color(lv_colors.WHITE), lv.PART.INDICATOR
        )
        self.percent = lv.label(self.container)
        self.percent.add_style(
            StyleWrapper().text_font(font_GeistRegular30).text_color(lv_colors.BLACK), 0
        )
        self.percent.set_text(brightness2_percent_str(self.current_brightness))
        self.slider.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.slider.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
        self.load_screen(self)
        gc.collect()

    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def on_value_changed(self, event_obj):
        target = event_obj.get_target()
        if target == self.slider:
            value = target.get_value()
            self.temp_brightness = value
            display.backlight(value)
            self.percent.set_text(brightness2_percent_str(value))

    def eventhandler(self, event_obj):
        event = event_obj.code
        target = event_obj.get_target()
        if event == lv.EVENT.CLICKED:
            if isinstance(target, lv.imgbtn):
                if target == self.nav_back.nav_btn:
                    if self.temp_brightness != self.current_brightness:
                        storage_device.set_brightness(self.temp_brightness)
            super().eventhandler(event_obj)


class KeyboardHapticSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "tips") and self.tips:
            targets.append(self.tips)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.TITLE__VIBRATION_AND_HAPTIC),
            nav_back=True,
        )
        self.container = ContainerFlexCol(
            self.content_area,
            self.title,
        )

        self.keyboard = ListItemBtnWithSwitch(
            self.container, _(i18n_keys.ITEM__KEYBOARD_HAPTIC), is_haptic_feedback=True
        )
        self.tips = lv.label(self.content_area)
        self.tips.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)
        self.tips.set_long_mode(lv.label.LONG.WRAP)
        self.tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .width(448)
            .text_color(lv_colors.WHITE_2)
            .text_align_left(),
            0,
        )
        self.tips.set_text(_(i18n_keys.CONTENT__VIBRATION_HAPTIC__HINT))
        if storage_device.keyboard_haptic_enabled():
            self.keyboard.add_state()
        else:
            self.keyboard.clear_state()

        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.load_screen(self)
        gc.collect()

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.keyboard.switch:
                if target.has_state(lv.STATE.CHECKED):
                    storage_device.toggle_keyboard_haptic(True)
                else:
                    storage_device.toggle_keyboard_haptic(False)


class AnimationSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "tips") and self.tips:
            targets.append(self.tips)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.TITLE__ANIMATIONS),
            nav_back=True,
        )

        self.container = ContainerFlexCol(self.content_area, self.title)
        self.item = ListItemBtnWithSwitch(self.container, _(i18n_keys.ITEM__ANIMATIONS))
        self.tips = lv.label(self.content_area)
        self.tips.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)
        self.tips.set_long_mode(lv.label.LONG.WRAP)
        self.tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .width(448)
            .text_color(lv_colors.WHITE_2)
            .text_align_left(),
            0,
        )
        if storage_device.is_animation_enabled():
            self.item.add_state()
            self.tips.set_text(_(i18n_keys.CONTENT__ANIMATIONS__ENABLED_HINT))
        else:
            self.item.clear_state()
            self.tips.set_text(_(i18n_keys.CONTENT__ANIMATIONS__DISABLED_HINT))

        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.load_screen(self)
        gc.collect()

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.item.switch:
                if target.has_state(lv.STATE.CHECKED):
                    storage_device.set_animation_enable(True)
                    self.tips.set_text(_(i18n_keys.CONTENT__ANIMATIONS__ENABLED_HINT))
                else:
                    storage_device.set_animation_enable(False)
                    self.tips.set_text(_(i18n_keys.CONTENT__ANIMATIONS__DISABLED_HINT))


class TouchSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "keyboard_tips") and self.keyboard_tips:
            targets.append(self.keyboard_tips)
        if hasattr(self, "container2") and self.container2:
            targets.append(self.container2)
        if hasattr(self, "description") and self.description:
            targets.append(self.description)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__LOCK_SCREEN), nav_back=True
        )

        # First container for keyboard haptic
        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.keyboard = ListItemBtnWithSwitch(
            self.container, _(i18n_keys.ITEM__KEYBOARD_HAPTIC), is_haptic_feedback=True
        )
        
        # Keyboard haptic description
        self.keyboard_tips = lv.label(self.content_area)
        self.keyboard_tips.set_size(456, lv.SIZE.CONTENT)
        self.keyboard_tips.set_long_mode(lv.label.LONG.WRAP)
        self.keyboard_tips.set_style_text_color(lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT)
        self.keyboard_tips.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)
        self.keyboard_tips.set_style_text_line_space(3, 0)
        self.keyboard_tips.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)
        self.keyboard_tips.set_text(_(i18n_keys.CONTENT__VIBRATION_HAPTIC__HINT))
        
        # Second container for tap awake
        self.container2 = ContainerFlexCol(self.content_area, self.keyboard_tips, padding_row=2)
        self.container2.align_to(self.keyboard_tips, lv.ALIGN.OUT_BOTTOM_LEFT, -8, 24)
        self.tap_awake = ListItemBtnWithSwitch(
            self.container2, _(i18n_keys.ITEM__TAP_TO_WAKE)
        )
        
        # Tap awake description
        self.description = lv.label(self.content_area)
        self.description.set_size(456, lv.SIZE.CONTENT)
        self.description.set_long_mode(lv.label.LONG.WRAP)
        self.description.set_style_text_color(lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT)
        self.description.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)
        self.description.set_style_text_line_space(3, 0)
        self.description.align_to(self.tap_awake, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)

        # Set keyboard haptic state
        if storage_device.keyboard_haptic_enabled():
            self.keyboard.add_state()
        else:
            self.keyboard.clear_state()
        
        # Set tap awake state
        if storage_device.is_tap_awake_enabled():
            self.tap_awake.add_state()
            self.description.set_text(_(i18n_keys.CONTENT__TAP_TO_WAKE_ENABLED__HINT))
        else:
            self.tap_awake.clear_state()
            self.description.set_text(_(i18n_keys.CONTENT__TAP_TO_WAKE_DISABLED__HINT))
        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.container2.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.load_screen(self)
        gc.collect()

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.keyboard.switch:
                if target.has_state(lv.STATE.CHECKED):
                    storage_device.toggle_keyboard_haptic(True)
                else:
                    storage_device.toggle_keyboard_haptic(False)
            elif target == self.tap_awake.switch:
                if target.has_state(lv.STATE.CHECKED):
                    self.description.set_text(
                        _(i18n_keys.CONTENT__TAP_TO_WAKE_ENABLED__HINT)
                    )
                    storage_device.set_tap_awake_enable(True)
                else:
                    self.description.set_text(
                        _(i18n_keys.CONTENT__TAP_TO_WAKE_DISABLED__HINT)
                    )
                    storage_device.set_tap_awake_enable(False)



class AutoShutDownSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "tips") and self.tips:
            targets.append(self.tips)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__SHUTDOWN), nav_back=True
        )

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.setting_items = [1, 2, 5, 10, "Never", None]
        has_custom = True
        self.checked_index = 0
        # pyright: off
        self.btns: [ListItemBtn] = [None] * (len(self.setting_items))
        for index, item in enumerate(self.setting_items):
            if item is None:
                break
            if not item == "Never":  # last item
                item = _(
                    i18n_keys.ITEM__STATUS__STR_MINUTES
                    if item != 1
                    else i18n_keys.OPTION__STR_MINUTE
                ).format(item)
            else:
                item = _(i18n_keys.ITEM__STATUS__NEVER)
            self.btns[index] = ListItemBtn(
                self.container, item, has_next=False, use_transition=False
            )
            # self.btns[index].label_left.add_style(
            #     StyleWrapper().text_font(font_GeistRegular30), 0
            # )
            self.btns[index].add_check_img()
            if item == Autolock_and_ShutingDown.cur_auto_shutdown:
                has_custom = False
                self.btns[index].set_checked()
                self.checked_index = index

        if has_custom:
            self.custom = storage_device.get_autoshutdown_delay_ms()
            self.btns[-1] = ListItemBtn(
                self.container,
                f"{Autolock_and_ShutingDown.cur_auto_shutdown}({_(i18n_keys.OPTION__CUSTOM__INSERT)})",
                has_next=False,
                has_bgcolor=False,
            )
            self.btns[-1].add_check_img()
            self.btns[-1].set_checked()
            self.checked_index = -1
        # pyright: on
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.tips = lv.label(self.content_area)
        self.tips.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 0)
        self.tips.set_long_mode(lv.label.LONG.WRAP)
        self.fresh_tips()
        self.tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .width(448)
            .text_color(lv_colors.WHITE_2)
            .text_align_left()
            .text_letter_space(-1)
            .pad_ver(16),
            0,
        )
        self.load_screen(self)
        gc.collect()

    def fresh_tips(self):
        item_text = self.btns[self.checked_index].label_left.get_text()
        if self.setting_items[self.checked_index] is None:
            item_text = item_text.split("(")[0]

        if self.setting_items[self.checked_index] == "Never":
            self.tips.set_text(_(i18n_keys.CONTENT__SETTINGS_GENERAL_SHUTDOWN_OFF_HINT))
        else:
            self.tips.set_text(
                _(i18n_keys.CONTENT__SETTINGS_GENERAL_SHUTDOWN_ON_HINT).format(
                    item_text or Autolock_and_ShutingDown.cur_auto_shutdown[:1]
                )
            )

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target in self.btns:
                for index, item in enumerate(self.btns):
                    if item == target and self.checked_index != index:
                        item.set_checked()
                        self.btns[self.checked_index].set_uncheck()
                        self.checked_index = index
                        if index == 4:
                            auto_shutdown_time = (
                                storage_device.AUTOSHUTDOWN_DELAY_MAXIMUM
                            )
                        elif index == 5:
                            auto_shutdown_time = self.custom
                        else:
                            auto_shutdown_time = self.setting_items[index] * 60 * 1000
                        storage_device.set_autoshutdown_delay_ms(auto_shutdown_time)
                        GeneralScreen.cur_auto_shutdown_ms = auto_shutdown_time
                        self.fresh_tips()
                        from apps.base import reload_settings_from_storage

                        reload_settings_from_storage()


class PinMapSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "tips") and self.tips:
            targets.append(self.tips)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__PIN_KEYPAD), nav_back=True
        )

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.order = ListItemBtn(
            self.container,
            _(i18n_keys.OPTION__DEFAULT),
            has_next=False,
            use_transition=False,
        )
        self.order.add_check_img()
        self.random = ListItemBtn(
            self.container,
            _(i18n_keys.OPTION__RANDOMIZED),
            has_next=False,
            use_transition=False,
        )
        self.random.add_check_img()
        self.tips = lv.label(self.content_area)
        self.tips.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 12, 0)
        self.tips.set_long_mode(lv.label.LONG.WRAP)
        self.fresh_tips()
        self.tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .width(448)
            .text_color(lv_colors.WHITE_2)
            .text_letter_space(-1)
            .text_align_left()
            .pad_ver(16),
            0,
        )

        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def fresh_tips(self):
        if storage_device.is_random_pin_map_enabled():
            self.random.set_checked()
            self.tips.set_text(
                _(i18n_keys.CONTENT__SECURITY_PIN_KEYPAD_LAYOUT_RANDOMIZED__HINT)
            )
        else:
            self.order.set_checked()
            self.tips.set_text(
                _(i18n_keys.CONTENT__SECURITY_PIN_KEYPAD_LAYOUT_DEFAULT__HINT)
            )

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.random:
                self.random.set_checked()
                self.order.set_uncheck()
                if not storage_device.is_random_pin_map_enabled():
                    storage_device.set_random_pin_map_enable(True)
            elif target == self.order:
                self.random.set_uncheck()
                self.order.set_checked()
                if storage_device.is_random_pin_map_enabled():
                    storage_device.set_random_pin_map_enable(False)
            else:
                return
            self.fresh_tips()


class ConnectSetting(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__CONNECT), nav_back=True
        )

        self.container = ContainerFlexCol(self.content_area, self.title)
        self.ble = ListItemBtnWithSwitch(self.container, _(i18n_keys.ITEM__BLUETOOTH))

        self.description = lv.label(self.content_area)
        self.description.set_size(456, lv.SIZE.CONTENT)
        self.description.set_long_mode(lv.label.LONG.WRAP)
        self.description.set_style_text_color(lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT)
        self.description.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)
        self.description.set_style_text_line_space(3, 0)
        self.description.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)

        if uart.is_ble_opened():
            self.ble.add_state()
            self.description.set_text(
                _(i18n_keys.CONTENT__CONNECT_BLUETOOTH_ENABLED__HINT).format(
                    storage_device.get_ble_name()
                )
            )
        else:
            self.ble.clear_state()
            self.description.set_text(
                _(i18n_keys.CONTENT__CONNECT_BLUETOOTH_DISABLED__HINT)
            )
        # self.usb = ListItemBtnWithSwitch(self.container, _(i18n_keys.ITEM__USB))
        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:

            if target == self.ble.switch:
                if target.has_state(lv.STATE.CHECKED):
                    self.description.set_text(
                        self.description.set_text(
                            _(
                                i18n_keys.CONTENT__CONNECT_BLUETOOTH_ENABLED__HINT
                            ).format(storage_device.get_ble_name())
                        )
                    )
                    uart.ctrl_ble(enable=True)
                else:
                    self.description.set_text(
                        _(i18n_keys.CONTENT__CONNECT_BLUETOOTH_DISABLED__HINT)
                    )
                    uart.ctrl_ble(enable=False)
            # else:
            #     if target.has_state(lv.STATE.CHECKED):
            #         print("USB is on")
            #     else:
            #         print("USB is off")


class AirGapSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "description") and self.description:
            targets.append(self.description)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            air_gap_enabled = storage_device.is_airgap_mode()
            if air_gap_enabled:
                self.air_gap.add_state()
                self.description.set_text(
                    _(
                        i18n_keys.CONTENT__BLUETOOTH_USB_AND_NFT_TRANSFER_FUNCTIONS_HAVE_BEEN_DISABLED
                    )
                )
            else:
                self.air_gap.clear_state()
                self.description.set_text(
                    _(
                        i18n_keys.CONTENT__AFTER_ENABLING_THE_AIRGAP_BLUETOOTH_USB_AND_NFC_TRANSFER_WILL_BE_DISABLED_SIMULTANEOUSLY
                    )
                )
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.ITEM__AIR_GAP_MODE), nav_back=True
        )

        self.container = ContainerFlexCol(self.content_area, self.title)
        self.air_gap = ListItemBtnWithSwitch(self.container, _(i18n_keys.ITEM__AIR_GAP))

        self.description = lv.label(self.content_area)
        self.description.set_size(456, lv.SIZE.CONTENT)
        self.description.set_long_mode(lv.label.LONG.WRAP)
        self.description.set_style_text_color(lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT)
        self.description.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)
        self.description.set_style_text_line_space(3, 0)
        self.description.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)
        air_gap_enabled = storage_device.is_airgap_mode()
        if air_gap_enabled:
            self.air_gap.add_state()
            self.description.set_text(
                _(
                    i18n_keys.CONTENT__BLUETOOTH_USB_AND_NFT_TRANSFER_FUNCTIONS_HAVE_BEEN_DISABLED
                )
            )
        else:
            self.air_gap.clear_state()
            self.description.set_text(
                _(
                    i18n_keys.CONTENT__AFTER_ENABLING_THE_AIRGAP_BLUETOOTH_USB_AND_NFC_TRANSFER_WILL_BE_DISABLED_SIMULTANEOUSLY
                )
            )
        # self.usb = ListItemBtnWithSwitch(self.container, _(i18n_keys.ITEM__USB))
        self.add_event_cb(self.on_event, lv.EVENT.VALUE_CHANGED, None)
        self.add_event_cb(self.on_event, lv.EVENT.READY, None)
        self.add_event_cb(self.on_event, lv.EVENT.CANCEL, None)
        self.load_screen(self)
        gc.collect()

    def on_event(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.air_gap.switch:
                from trezor.lvglui.scrs.template import AirGapToggleTips

                if target.has_state(lv.STATE.CHECKED):
                    AirGapToggleTips(
                        enable=True,
                        callback_obj=self,
                    )
                else:
                    AirGapToggleTips(
                        enable=False,
                        callback_obj=self,
                    )
        elif code == lv.EVENT.READY:
            if not storage_device.is_airgap_mode():
                self.description.set_text(
                    _(
                        i18n_keys.CONTENT__BLUETOOTH_USB_AND_NFT_TRANSFER_FUNCTIONS_HAVE_BEEN_DISABLED
                    )
                )
                utils.enable_airgap_mode()
            else:
                self.description.set_text(
                    _(
                        i18n_keys.CONTENT__AFTER_ENABLING_THE_AIRGAP_BLUETOOTH_USB_AND_NFC_TRANSFER_WILL_BE_DISABLED_SIMULTANEOUSLY
                    )
                )
                utils.disable_airgap_mode()
        elif code == lv.EVENT.CANCEL:
            if storage_device.is_airgap_mode():
                self.air_gap.add_state()
            else:
                self.air_gap.clear_state()


class AboutSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "firmware_update") and self.firmware_update:
            targets.append(self.firmware_update)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        preloaded_info = DeviceInfoManager.instance().get_info()
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__ABOUT_DEVICE), nav_back=True
        )
        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=0)
        self.container.add_dummy()
        self.model = DisplayItemWithFont_30(
            self.container, _(i18n_keys.ITEM__MODEL), preloaded_info["model"]
        )
        self.ble_mac = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.ITEM__BLUETOOTH_NAME),
            preloaded_info["ble_name"],
        )
        self.version = DisplayItemWithFont_30(
            self.container, _(i18n_keys.ITEM__SYSTEM_VERSION), preloaded_info["version"]
        )
        self.ble_version = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.ITEM__BLUETOOTH_VERSION),
            preloaded_info["ble_version"],
        )
        self.boot_version = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.ITEM__BOOTLOADER_VERSION),
            preloaded_info["boot_version"],
        )
        self.board_version = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.ITEM__BOARDLOADER_VERSION),
            preloaded_info["board_version"],
        )
        se_firmware_content_pairs = [
            ("01:", preloaded_info["onekey_se01_version"]),
            ("02:", preloaded_info["onekey_se02_version"]),
            ("03:", preloaded_info["onekey_se03_version"]),
            ("04:", preloaded_info["onekey_se04_version"]),
        ]
        self.se_firmware = DisplayItemWithFont_TextPairs(
            self.container,
            _(i18n_keys.ITEM__SE_FIRMWARE),
            se_firmware_content_pairs,
        )
        se_boot_content_pairs = [
            ("01:", preloaded_info["onekey_se01_boot_version"]),
            ("02:", preloaded_info["onekey_se02_boot_version"]),
            ("03:", preloaded_info["onekey_se03_boot_version"]),
            ("04:", preloaded_info["onekey_se04_boot_version"]),
        ]
        self.se_bootloader = DisplayItemWithFont_TextPairs(
            self.container,
            "SE Bootloader",
            se_boot_content_pairs,
        )

        self.serial = DisplayItemWithFont_30(
            self.container, _(i18n_keys.ITEM__SERIAL_NUMBER), preloaded_info["serial"]
        )
        self.serial.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

        self.fcc_id = DisplayItemWithFont_30(self.container, "FCC ID", "2BB8VP1")
        self.fcc_id.set_style_pad_right(0, 0)
        self.fcc_icon = lv.img(self.fcc_id)
        self.fcc_icon.set_src("A:/res/icon-fcc.png")
        self.fcc_icon.align(lv.ALIGN.RIGHT_MID, 0, 0)

        self.mic_id = DisplayItemWithFont_30(self.container, "MIC ID", "211-240720")
        self.mic_id.set_style_pad_right(0, 0)
        self.mic_icon = lv.img(self.mic_id)
        self.mic_icon.set_src("A:/res/icon-mic.png")
        self.mic_icon.align(lv.ALIGN.RIGHT_MID, 0, 0)

        self.anatel_id = DisplayItemWithFont_30(
            self.container, "ANATEL ID", "02335-25-16343"
        )
        self.anatel_id.set_style_pad_right(0, 0)
        self.anatel_icon = lv.img(self.anatel_id)
        self.anatel_icon.set_src("A:/res/icon-anatel.png")
        self.anatel_icon.align(lv.ALIGN.RIGHT_MID, 0, 0)

        self.container.add_dummy()

        self.firmware_update = NormalButton(
            self.content_area, _(i18n_keys.BUTTON__SYSTEM_UPDATE)
        )

        self.firmware_update.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 8)
        self.serial.add_event_cb(self.on_long_pressed, lv.EVENT.LONG_PRESSED, None)
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.firmware_update.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def on_click(self, event_obj):
        target = event_obj.get_target()
        # if target == self.board_loader:
        #     GO2BoardLoader()
        if target == self.firmware_update:
            Go2UpdateMode(self)

    def on_long_pressed(self, event_obj):
        target = event_obj.get_target()
        if target == self.serial:
            # if self.board_loader.has_flag(lv.obj.FLAG.HIDDEN):
            #     self.board_loader.clear_flag(lv.obj.FLAG.HIDDEN)
            # else:
            #     self.board_loader.add_flag(lv.obj.FLAG.HIDDEN)
            GO2BoardLoader()


class TrezorModeToggle(FullSizeWindow):
    def __init__(self, callback_obj, enable=False):
        super().__init__(
            title=_(
                i18n_keys.TITLE__RESTORE_TREZOR_COMPATIBILITY
                if enable
                else i18n_keys.TITLE__DISABLE_TREZOR_COMPATIBILITY
            ),
            subtitle=_(
                i18n_keys.SUBTITLE__RESTORE_TREZOR_COMPATIBILITY
                if enable
                else i18n_keys.SUBTITLE__DISABLE_TREZOR_COMPATIBILITY
            ),
            confirm_text=_(i18n_keys.BUTTON__RESTART),
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
        )
        self.enable = enable
        self.callback_obj = callback_obj
        if not enable:
            self.btn_yes.enable(
                bg_color=lv_colors.ONEKEY_YELLOW, text_color=lv_colors.BLACK
            )
            self.tips_bar = Banner(
                self.content_area,
                LEVEL.WARNING,
                _(i18n_keys.MSG__DO_NOT_CHANGE_THIS_SETTING),
            )
            self.tips_bar.align(lv.ALIGN.TOP_LEFT, 8, 8)
            self.title.align_to(self.tips_bar, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)
            self.subtitle.align_to(self.title, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.btn_no:
                self.callback_obj.reset_switch()
                self.destroy(200)
            elif target == self.btn_yes:

                async def restart_delay():
                    await loop.sleep(1000)
                    utils.reset()

                storage_device.enable_trezor_compatible(self.enable)
                workflow.spawn(restart_delay())


class GO2BoardLoader(FullSizeWindow):
    def __init__(self):
        super().__init__(
            title=_(i18n_keys.TITLE__ENTERING_BOARDLOADER),
            subtitle=_(i18n_keys.SUBTITLE__SWITCH_TO_BOARDLOADER_RECONFIRM),
            confirm_text=_(i18n_keys.BUTTON__RESTART),
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
            # icon_path="A:/res/warning.png",
        )

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.btn_yes:
                utils.reboot2boardloader()
            elif target == self.btn_no:
                self.destroy(100)


class Go2UpdateMode(Screen):
    def __init__(self, prev_scr):
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.TITLE__SYSTEM_UPDATE),
            subtitle=_(i18n_keys.SUBTITLE__SWITCH_TO_UPDATE_MODE_RECONFIRM),
            # icon_path="A:/res/update-green.png",
        )
        self.btn_yes = NormalButton(self.content_area, _(i18n_keys.BUTTON__RESTART))
        self.btn_yes.set_size(231, 98)
        self.btn_yes.align(lv.ALIGN.BOTTOM_RIGHT, -8, -8)
        self.btn_yes.enable(lv_colors.ONEKEY_GREEN, lv_colors.BLACK)
        self.btn_no = NormalButton(self.content_area, _(i18n_keys.BUTTON__CANCEL))
        self.btn_no.set_size(231, 98)
        self.btn_no.align(lv.ALIGN.BOTTOM_LEFT, 8, -8)

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.btn_yes:
                utils.reboot_to_bootloader()
            elif target == self.btn_no:
                self.load_screen(self.prev_scr, destroy_self=True)


class PowerOff(FullSizeWindow):
    IS_ACTIVE = False

    def __init__(self, re_loop: bool = False):
        if PowerOff.IS_ACTIVE:
            return
        PowerOff.IS_ACTIVE = True
        super().__init__(
            title=_(i18n_keys.TITLE__POWER_OFF),
            confirm_text=_(i18n_keys.BUTTON__POWER_OFF),
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
            subtitle=_(i18n_keys.CONTENT__POWER_OFF_LOW_BATTERY_DESC)
            if utils.is_low_battery()
            else None,
        )
        self.btn_yes.enable(lv_colors.ONEKEY_RED_1, text_color=lv_colors.BLACK)
        self.re_loop = re_loop
        from trezor import config

        self.has_pin = config.has_pin()
        if self.has_pin and storage_device.is_initialized():
            # from trezor.lvglui.scrs import fingerprints

            # if fingerprints.is_available() and fingerprints.is_unlocked():
            #         fingerprints.lock()
            # else:
            #     config.lock()
            config.lock()

            if passphrase.is_passphrase_pin_enabled():
                storage.cache.end_current_session()

    def back(self):
        PowerOff.IS_ACTIVE = False
        self.destroy(100)

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.btn_yes:
                ShutingDown()
            elif target == self.btn_no:
                if (
                    not utils.is_initialization_processing()
                    and self.has_pin
                    and storage_device.is_initialized()
                ):
                    from apps.common.request_pin import verify_user_pin

                    workflow.spawn(
                        verify_user_pin(
                            re_loop=self.re_loop,
                            allow_cancel=False,
                            callback=self.back,
                            allow_fingerprint=False,
                            pin_use_type=2,
                        )
                    )
                else:
                    self.back()


class ShutingDown(FullSizeWindow):
    def __init__(self):
        super().__init__(
            title=_(i18n_keys.TITLE__SHUTTING_DOWN), subtitle=None, anim_dir=0
        )

        async def shutdown_delay():
            await loop.sleep(3000)
            uart.ctrl_power_off()

        workflow.spawn(shutdown_delay())



class WallpaperScreen(AnimScreen):
    cur_language = ""

    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            self.refresh_text()
            return
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.TITLE__WALLPAPER),
            nav_back=True,
        )

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)        
        self.lock_screen = ListItemBtn(self.container, _(i18n_keys.ITEM__LOCK_SCREEN))
        self.home_screen = ListItemBtn(self.container, _(i18n_keys.ITEM__HOME_SCREEN))
        self.content_area.add_event_cb(self.on_click_event, lv.EVENT.CLICKED, None)
        self.load_screen(self)

    def refresh_text(self):
        self.lock_screen.label_left.set_text(_(i18n_keys.ITEM__LOCK_SCREEN))
        self.home_screen.label_left.set_text(_(i18n_keys.ITEM__HOME_SCREEN))
        # self.power.align_to(self.container, lv.ALIGN.OUT_BOTTOM_MID, 0, 12)

    def on_click_event(self, event_obj):
        target = event_obj.get_target()
        if target == self.lock_screen:
            # LanguageSetting(self)
            AppdrawerBackgroundSetting(self)
        elif target == self.home_screen:
            HomeScreenSetting(self)
        else:
            pass





class HomeScreenSetting(AnimScreen):
    # 类变量：追踪所有活跃的实例以便于批量刷新
    _active_instances = []
    
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None, selected_wallpaper=None, preserve_blur_state=None):
        if __debug__:
            print(f"[HomeScreenSetting.__init__] called, prev_scr={prev_scr}, selected_wallpaper={selected_wallpaper}, preserve_blur_state={preserve_blur_state}")
            print(f"[HomeScreenSetting.__init__] Current stored homescreen: {storage_device.get_homescreen()}")
            print(f"[HomeScreenSetting.__init__] Current stored appdrawer_background: {storage_device.get_appdrawer_background()}")
        
        if not hasattr(self, "_init"):
            self._init = True
        else:
            # Even if already initialized, update the wallpaper if a new one is provided
            if selected_wallpaper:
                if __debug__:
                    print(f"[HomeScreenSetting.__init__] Updating existing instance with selected_wallpaper: {selected_wallpaper}")
                
                self.selected_wallpaper = selected_wallpaper
                self.original_wallpaper_path = selected_wallpaper
                
                # Convert path if needed for custom wallpapers
                display_path = selected_wallpaper
                if selected_wallpaper and "/res/wallpapers/" in selected_wallpaper:
                    if selected_wallpaper.startswith("A:/res/wallpapers/"):
                        display_path = selected_wallpaper.replace("A:/res/wallpapers/", "A:1:/res/wallpapers/")
                    if __debug__:
                        print(f"[HomeScreenSetting.__init__] Converted path for display: {display_path}")
                
                # Handle blur state preservation
                self.is_blur_active = False  # Default to original
                final_display_path = display_path
                
                # If we should preserve blur state and it was active, check for blur version
                if preserve_blur_state and preserve_blur_state is True:
                    blur_path = self._get_blur_wallpaper_path(display_path)
                    if blur_path and self._blur_wallpaper_exists(blur_path):
                        if __debug__:
                            print(f"[HomeScreenSetting.__init__] Blur version exists, using blur: {blur_path}")
                        final_display_path = blur_path
                        self.is_blur_active = True
                    else:
                        if __debug__:
                            print(f"[HomeScreenSetting.__init__] No blur version available for new wallpaper, showing original")
                
                self.current_wallpaper_path = final_display_path
                
                # Update the preview if it exists
                if hasattr(self, 'homescreen_preview'):
                    self.homescreen_preview.set_src(final_display_path)
                    if __debug__:
                        blur_status = "blur" if self.is_blur_active else "original"
                        print(f"[HomeScreenSetting.__init__] Updated preview to {blur_status} version: {final_display_path}")
                
                # Update blur button state
                if hasattr(self, 'blur_button'):
                    self._update_blur_button_state()
                    if __debug__:
                        print("[HomeScreenSetting.__init__] Updated blur button state")
                
            return
        
        # 将当前实例加入活跃列表
        if self not in HomeScreenSetting._active_instances:
            HomeScreenSetting._active_instances.append(self)

        self.selected_wallpaper = selected_wallpaper

        if __debug__:
            print("[HomeScreenSetting.__init__] First time initialization")
        super().__init__(
            prev_scr=prev_scr,
            nav_back=True,
            rti_path="A:/res/checkmark.png"
        )

        # Disable scrollbar for this screen
        self.content_area.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

        # Main container for the screen
        self.container = lv.obj(self.content_area)
        self.container.set_size(lv.pct(100), lv.pct(100))
        self.container.align(lv.ALIGN.TOP_MID, 0, 0)
        self.container.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP).pad_all(0).border_width(0), 0
        )
        # Don't capture click events - let them pass through to buttons
        self.container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

        # Home screen preview container with image (same size as LockScreenSetting)
        self.preview_container = lv.obj(self.container)
        self.preview_container.set_size(344, 574)  # Same as LockScreenSetting
        self.preview_container.align(lv.ALIGN.TOP_MID, 0, 105)  # Below status bar
        self.preview_container.add_style(
            StyleWrapper()
            .bg_opa(lv.OPA.TRANSP)
            .pad_all(0)
            .border_width(0), 0
        )
        # Don't capture click events - let them pass through to buttons
        self.preview_container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.preview_container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

        # Home screen preview image
        self.homescreen_preview = lv.img(self.preview_container)
        if __debug__:
            print(f"[HomeScreenSetting.__init__] Created homescreen_preview: {self.homescreen_preview}")
            print(f"[HomeScreenSetting.__init__] Preview container: {self.preview_container}")

        # Initialize blur cache first
        self._blur_cache = {}

        # Use selected wallpaper if provided, otherwise load blur state from storage
        if self.selected_wallpaper:
            if __debug__:
                print(f"[HomeScreenSetting.__init__] Using selected_wallpaper: {self.selected_wallpaper}")
                print(f"[HomeScreenSetting.__init__] preserve_blur_state: {preserve_blur_state}")
            self.original_wallpaper_path = self.selected_wallpaper
            
            # 对于Custom wallpapers，需要转换路径用于显示
            display_path = self.selected_wallpaper
            if self.selected_wallpaper and "/res/wallpapers/" in self.selected_wallpaper:
                # 使用A:1:前缀（之前可以工作）
                if self.selected_wallpaper.startswith("A:/res/wallpapers/"):
                    display_path = self.selected_wallpaper.replace("A:/res/wallpapers/", "A:1:/res/wallpapers/")
                if __debug__:
                    print(f"[HomeScreenSetting.__init__] Converted path for display: {display_path}")
            
            # Handle blur state preservation
            self.is_blur_active = False  # Default to original
            final_display_path = display_path
            
            # If we should preserve blur state and it was active, check for blur version
            if preserve_blur_state and preserve_blur_state is True:
                blur_path = self._get_blur_wallpaper_path(display_path)
                if blur_path and self._blur_wallpaper_exists(blur_path):
                    if __debug__:
                        print(f"[HomeScreenSetting.__init__] Blur version exists, using blur: {blur_path}")
                    final_display_path = blur_path
                    self.is_blur_active = True
                else:
                    if __debug__:
                        print(f"[HomeScreenSetting.__init__] No blur version available for new wallpaper, showing original")
            
            self.current_wallpaper_path = final_display_path
            self.homescreen_preview.set_src(final_display_path)
            if __debug__:
                blur_status = "blur" if self.is_blur_active else "original"
                print(f"[HomeScreenSetting.__init__] Set preview src to {blur_status} version: {final_display_path}")
                print(f"[HomeScreenSetting.__init__] Preview object: {self.homescreen_preview}")
        else:
            if __debug__:
                print("[HomeScreenSetting.__init__] No selected_wallpaper, loading blur state from storage")
            # Load blur state from storage - this sets all wallpaper paths and blur state
            self._load_blur_state()
            # Set preview to current wallpaper (might be blur or original)
            if __debug__:
                print(f"[HomeScreenSetting.__init__] Setting preview src to: {self.current_wallpaper_path}")
                print(f"[HomeScreenSetting.__init__] Testing filesystem before set_src...")
                # 测试直接文件访问
                try:
                    file_path = self.current_wallpaper_path[2:] if self.current_wallpaper_path.startswith('A:/') else self.current_wallpaper_path
                    stat_result = io.fatfs.stat(file_path)
                    print(f"[HomeScreenSetting.__init__] File {file_path} exists, size: {stat_result[6]}")
                except Exception as file_error:
                    print(f"[HomeScreenSetting.__init__] File access error: {file_error}")
                
                # 测试简单图片创建
                try:
                    test_img = lv.img(None)
                    test_img.set_src("A:/res/up-home.png")  # PNG测试
                    test_src = test_img.get_src()
                    print(f"[HomeScreenSetting.__init__] PNG test: {test_src}, type: {type(test_src)}")
                    test_img.delete()
                    
                    test_img2 = lv.img(None)
                    test_img2.set_src("A:/res/wallpaper-2.jpg")  # JPG测试
                    test_src2 = test_img2.get_src()
                    print(f"[HomeScreenSetting.__init__] JPG test: {test_src2}, type: {type(test_src2)}")
                    test_img2.delete()
                except Exception as test_error:
                    print(f"[HomeScreenSetting.__init__] Simple test error: {test_error}")
                    
            self.homescreen_preview.set_src(self.current_wallpaper_path)
            if __debug__:
                print(f"[HomeScreenSetting.__init__] Preview src set successfully")
                # 检查初始设置后的状态
                try:
                    initial_src = self.homescreen_preview.get_src()
                    print(f"[HomeScreenSetting.__init__] After initial set_src - actual src: {initial_src}")
                    print(f"[HomeScreenSetting.__init__] After initial set_src - actual type: {type(initial_src)}")
                    
                    # Blob对象实际上是正常的！检查是否为null
                    if initial_src is None:
                        print(f"[HomeScreenSetting.__init__] Image source is null - this indicates a real problem")
                        # 如果真的是null，再尝试一次
                        self.homescreen_preview.set_src(self.current_wallpaper_path)
                        retry_src = self.homescreen_preview.get_src()
                        print(f"[HomeScreenSetting.__init__] After retry - src: {retry_src}")
                    else:
                        print(f"[HomeScreenSetting.__init__] Image source loaded successfully (Blob is normal data)")
                except Exception as e:
                    print(f"[HomeScreenSetting.__init__] Error checking initial src state: {e}")

        self.homescreen_preview.set_size(344, 574)
        self.homescreen_preview.align(lv.ALIGN.CENTER, 0, 0)

       
        self.app_icons = []
        icon_size = 110
        icon_spacing_x = 41  # Horizontal spacing between icons
        icon_spacing_y = 40.3  # Vertical spacing between icons
        start_x = -((icon_size // 2) + (icon_spacing_x // 2))  # Centered
        start_y = 64  # First row distance from top of preview_container

        for i in range(6):
            row = i // 2  # 0, 0, 1, 1, 2, 2
            col = i % 2   # 0, 1, 0, 1, 0, 1

            # Position the icon
            x_pos = int(start_x + col * (icon_size + icon_spacing_x))
            y_pos = int(start_y + row * (icon_size + icon_spacing_y))

            # Create image directly without holder to show natural shape
            icon_img = lv.img(self.preview_container)
            icon_img.set_src("A:/res/icon_example.png")
            # Let image use its natural size
            icon_img.set_size(lv.SIZE.CONTENT, lv.SIZE.CONTENT)
            # Position the image
            icon_img.align_to(self.preview_container, lv.ALIGN.TOP_MID, x_pos, y_pos)

            self.app_icons.append(icon_img)
        # 创建按钮组
        if __debug__:
            print("[HomeScreenSetting.__init__] Creating buttons")
        self._create_buttons()

        # 简化按钮定位 - 使用相对位置而不是绝对位置
        # Change按钮左对齐，Blur按钮右对齐
        self.change_button.align_to(self.preview_container, lv.ALIGN.OUT_BOTTOM_LEFT, 50, 10)
        self.blur_button.align_to(self.preview_container, lv.ALIGN.OUT_BOTTOM_RIGHT, -50, 10)

        # 重新对齐标签
        self.change_label.align_to(self.change_button, lv.ALIGN.OUT_BOTTOM_MID, 0, 4)
        self.blur_label.align_to(self.blur_button, lv.ALIGN.OUT_BOTTOM_MID, 0, 4)

        if __debug__:
            print("[HomeScreenSetting.__init__] Loading screen and collecting garbage")
        self.load_screen(self)
        gc.collect()

    def _create_button_with_label(self, icon_path, text, callback):
        """创建一个带图标和标签的按钮"""
        if __debug__:
            print(f"[HomeScreenSetting._create_button_with_label] Creating button with text='{text}', icon='{icon_path}'")

        # 创建按钮
        button = lv.btn(self.container)
        button.set_size(64, 64)
        button.align_to(self.preview_container, lv.ALIGN.OUT_BOTTOM_MID, 0, 8)
        button.add_style(StyleWrapper().border_width(0).radius(40), 0)
        button.add_flag(lv.obj.FLAG.CLICKABLE)
        button.clear_flag(lv.obj.FLAG.EVENT_BUBBLE)

        # 为了测试，给按钮添加背景色
        if __debug__:
            button.add_style(StyleWrapper().bg_color(lv.palette_main(lv.PALETTE.BLUE)).bg_opa(lv.OPA._50), 0)

        # 创建图标
        icon = lv.img(button)
        if icon_path:  # 只有当路径不为空时才设置图标
            icon.set_src(icon_path)
            
            # 验证图标是否真的加载成功
            if __debug__:
                try:
                    actual_icon_src = icon.get_src()
                    print(f"[HomeScreenSetting._create_button_with_label] Icon src: {actual_icon_src}, type: {type(actual_icon_src)}")
                    # Blob对象实际上是正常的！不是错误！
                    if actual_icon_src is not None:
                        print(f"[HomeScreenSetting._create_button_with_label] Button icon loaded (Blob is normal!)")
                    else:
                        print(f"[HomeScreenSetting._create_button_with_label] Button icon failed - null source")
                except Exception as icon_error:
                    print(f"[HomeScreenSetting._create_button_with_label] Icon verification error: {icon_error}")
        icon.align(lv.ALIGN.CENTER, 0, 0)

        # 创建标签
        label = lv.label(self.container)
        label.set_text(text)
        label.add_style(StyleWrapper()
                       .text_font(font_GeistRegular20)
                       .text_color(lv_colors.WHITE)
                       .text_align(lv.TEXT_ALIGN.CENTER), 0)
        label.align_to(button, lv.ALIGN.OUT_BOTTOM_MID, 0, 4)

        # 添加事件回调
        button.add_event_cb(callback, lv.EVENT.CLICKED, None)

        if __debug__:
            print(f"[HomeScreenSetting._create_button_with_label] Button created successfully, callback added")

        return button, icon, label

    def _create_buttons(self):
        """创建 Change 和 Blur 按钮"""
        if __debug__:
            print("[HomeScreenSetting._create_buttons] Starting to create buttons...")

        # 创建 Change 按钮
        self.change_button, self.button_icon, self.change_label = \
            self._create_button_with_label("A:/res/change-wallper.png", _(i18n_keys.BUTTON__CHANGE), self.on_select_clicked)

        # 创建 Blur 按钮
        self.blur_button, self.blur_button_icon, self.blur_label = \
            self._create_button_with_label("", _(i18n_keys.BUTTON__BLUR), self.on_blur_clicked)

        # 初始化模糊按钮状态
        self._update_blur_button_state()

        if __debug__:
            print(f"[HomeScreenSetting._create_buttons] Buttons created - Change: {self.change_button}, Blur: {self.blur_button}")

    def _update_wallpaper(self, wallpaper_path, preserve_blur_state=None):
        """简化的壁纸更新方法"""
        if __debug__:
            print(f"[HomeScreenSetting._update_wallpaper] Updating wallpaper to {wallpaper_path}, preserve_blur_state: {preserve_blur_state}")
        self.selected_wallpaper = wallpaper_path
        self.original_wallpaper_path = wallpaper_path
        
        # 对于Custom wallpapers，需要转换路径用于显示
        display_path = wallpaper_path
        if wallpaper_path and "/res/wallpapers/" in wallpaper_path:
            # 使用A:1:前缀（之前可以工作）
            if wallpaper_path.startswith("A:/res/wallpapers/"):
                display_path = wallpaper_path.replace("A:/res/wallpapers/", "A:1:/res/wallpapers/")
            if __debug__:
                print(f"[HomeScreenSetting._update_wallpaper] Converted path for display: {display_path}")
        
        # Handle blur state preservation
        self.is_blur_active = False  # Default to original
        final_display_path = display_path
        
        # If we should preserve blur state and it was active, check for blur version
        if preserve_blur_state and preserve_blur_state is True:
            blur_path = self._get_blur_wallpaper_path(display_path)
            if blur_path and self._blur_wallpaper_exists(blur_path):
                if __debug__:
                    print(f"[HomeScreenSetting._update_wallpaper] Blur version exists, using blur: {blur_path}")
                final_display_path = blur_path
                self.is_blur_active = True
            else:
                if __debug__:
                    print(f"[HomeScreenSetting._update_wallpaper] No blur version available for new wallpaper, showing original")
        
        self.current_wallpaper_path = final_display_path
        if hasattr(self, 'homescreen_preview'):
            if __debug__:
                blur_status = "blur" if self.is_blur_active else "original" 
                print(f"[HomeScreenSetting._update_wallpaper] Before set_src - preview: {self.homescreen_preview}")
                print(f"[HomeScreenSetting._update_wallpaper] Setting src to {blur_status} version: {final_display_path}")
            self.homescreen_preview.set_src(final_display_path)
            if __debug__:
                print(f"[HomeScreenSetting._update_wallpaper] After set_src - done")
        if hasattr(self, '_update_blur_button_state'):
            self._update_blur_button_state()

    def on_select_clicked(self, event_obj):
        """Handle Change button click - navigate to wallpaper selection"""
        if __debug__:
            print("[HomeScreenSetting.on_select_clicked] Change button clicked - navigating to wallpaper selection")
        # Navigate to WallperChange for wallpaper selection - pass self as prev_scr
        WallperChange(prev_scr=self)

    def eventhandler(self, event_obj):
        """简化的事件处理"""
        event = event_obj.code
        target = event_obj.get_target()
        if __debug__:
            print(f"[HomeScreenSetting.eventhandler] Event: {event}, Target: {target}")

        if event == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                if __debug__:
                    print("[HomeScreenSetting.eventhandler] LCD resume, returning")
                return

            # 处理导航按钮
            if isinstance(target, lv.imgbtn):
                if hasattr(self, "nav_back") and target == self.nav_back.nav_btn:
                    if __debug__:
                        print("[HomeScreenSetting.eventhandler] Back button clicked")
                        print(f"[HomeScreenSetting.eventhandler] prev_scr: {self.prev_scr}")
                        print(f"[HomeScreenSetting.eventhandler] prev_scr class: {self.prev_scr.__class__.__name__ if hasattr(self.prev_scr, '__class__') else 'Unknown'}")
                    
                    if self.prev_scr is not None:
                        try:
                            self.load_screen(self.prev_scr, destroy_self=True)
                        except Exception as e:
                            if __debug__:
                                print(f"[HomeScreenSetting.eventhandler] Error loading previous screen: {e}")
                            # Fallback: Try to go to WallpaperScreen
                            try:
                                fallback_screen = WallpaperScreen()
                                if __debug__:
                                    print("[HomeScreenSetting.eventhandler] Using fallback: WallpaperScreen")
                                self.load_screen(fallback_screen, destroy_self=True)
                            except Exception as fallback_error:
                                if __debug__:
                                    print(f"[HomeScreenSetting.eventhandler] Fallback also failed: {fallback_error}")
                    else:
                        if __debug__:
                            print("[HomeScreenSetting.eventhandler] No previous screen to return to!")
                    return
                elif hasattr(self, "rti_btn") and target == self.rti_btn:
                    if __debug__:
                        print("[HomeScreenSetting.eventhandler] RTI button clicked")
                    self.on_click_ext(target)
                    return

        # 其他事件交给父类处理
        if __debug__:
            print("[HomeScreenSetting.eventhandler] Passing event to super")
        super().eventhandler(event_obj)

    def refresh_text(self):
        """Refresh text elements when language changes"""
        if __debug__:
            print("[HomeScreenSetting.refresh_text] Refreshing text")
        if hasattr(self, 'change_label'):
            self.change_label.set_text(_(i18n_keys.BUTTON__CHANGE))
            
    def refresh_images_after_animation(self):
        """
        AppDrawer动画后强制刷新图片以解决Blob问题
        这个方法会被 AppDrawer 的 on_animation_complete 回调调用
        """
        if __debug__:
            print(f"[HomeScreenSetting.refresh_images_after_animation] Starting refresh for instance {id(self)}")
            
        try:
            if hasattr(self, 'homescreen_preview') and self.homescreen_preview:
                # 检查当前图片源状态
                current_src = self.homescreen_preview.get_src()
                if __debug__:
                    print(f"[HomeScreenSetting.refresh_images_after_animation] Current src: {current_src}, type: {type(current_src)}")
                
                # 如果返回了Blob对象，说明需要重建图片对象
                if str(current_src).lower() == "blob" or current_src is None or current_src == "":
                    if __debug__:
                        print(f"[HomeScreenSetting.refresh_images_after_animation] Detected Blob/null source, rebuilding image object...")
                    
                    self._rebuild_image_object()
                else:
                    if __debug__:
                        print(f"[HomeScreenSetting.refresh_images_after_animation] Source OK, no refresh needed")
                        
        except Exception as e:
            if __debug__:
                print(f"[HomeScreenSetting.refresh_images_after_animation] Error during refresh: {e}")
                
    def __del__(self):
        """清理时从活跃列表中移除"""
        try:
            if self in HomeScreenSetting._active_instances:
                HomeScreenSetting._active_instances.remove(self)
        except:
            pass
    
    def _rebuild_image_object(self):
        """
        使用与按钮图标相同的方式重新创建图片显示
        """
        if __debug__:
            print(f"[HomeScreenSetting._rebuild_image_object] Using button-style image creation...")
            
        try:
            if hasattr(self, 'homescreen_preview') and hasattr(self, 'preview_container'):
                target_path = getattr(self, 'current_wallpaper_path', 'A:/res/wallpaper-2.jpg')
                
                # 删除旧的预览对象
                if self.homescreen_preview:
                    self.homescreen_preview.delete()
                gc.collect()
                
                # 创建一个按钮容器来承载图片（模仿按钮图标的成功模式）
                self.preview_button = lv.btn(self.preview_container)
                self.preview_button.set_size(344, 574)
                self.preview_button.align(lv.ALIGN.CENTER, 0, 0)
                self.preview_button.remove_style_all()
                self.preview_button.add_style(
                    StyleWrapper()
                    .bg_opa(lv.OPA.TRANSP)
                    .border_width(0)
                    .pad_all(0),
                    0
                )
                self.preview_button.clear_flag(lv.obj.FLAG.CLICKABLE)  # 不响应点击
                
                # 在按钮内创建图片（和按钮图标完全相同的方式）
                self.homescreen_preview = lv.img(self.preview_button)
                self.homescreen_preview.set_size(344, 574)
                self.homescreen_preview.align(lv.ALIGN.CENTER, 0, 0)
                
                # 使用和按钮图标相同的set_src调用方式
                self.homescreen_preview.set_src(target_path)
                
                if __debug__:
                    print(f"[HomeScreenSetting._rebuild_image_object] Button-style image created for: {target_path}")
                    # 验证结果（如果可能）
                    try:
                        test_src = self.homescreen_preview.get_src()
                        print(f"[HomeScreenSetting._rebuild_image_object] Result: {test_src}, type: {type(test_src)}")
                        if str(test_src).lower() != "blob":
                            print(f"[HomeScreenSetting._rebuild_image_object] SUCCESS! Image loaded properly!")
                        else:
                            print(f"[HomeScreenSetting._rebuild_image_object] Still Blob - deeper issue")
                    except Exception as verify_error:
                        print(f"[HomeScreenSetting._rebuild_image_object] Verify error: {verify_error}")
                    
        except Exception as e:
            if __debug__:
                print(f"[HomeScreenSetting._rebuild_image_object] Button-style creation error: {e}")
        if hasattr(self, 'blur_label'):
            self.blur_label.set_text("Blur")

    def on_click_ext(self, target):
        """Handle right navigation button (checkmark) click"""
        if __debug__:
            print("[HomeScreenSetting.on_click_ext] Right button clicked (checkmark)")
            print(f"[HomeScreenSetting.on_click_ext] Current blur state: is_blur_active={getattr(self, 'is_blur_active', False)}")
            print(f"[HomeScreenSetting.on_click_ext] Original wallpaper path: {getattr(self, 'original_wallpaper_path', 'None')}")
            print(f"[HomeScreenSetting.on_click_ext] Current wallpaper path: {getattr(self, 'current_wallpaper_path', 'None')}")
        # Save current wallpaper and return to previous screen
        if hasattr(self, 'current_wallpaper_path') and self.current_wallpaper_path:
            storage_device.set_appdrawer_background(self.current_wallpaper_path)
            if __debug__:
                print(f"[HomeScreenSetting.on_click_ext] Saved homescreen wallpaper: {self.current_wallpaper_path}")
                # Verify what was actually saved - check both storage locations
                appdrawer_path = storage_device.get_appdrawer_background()
                homescreen_path = storage_device.get_homescreen()
                print(f"[HomeScreenSetting.on_click_ext] Verified appdrawer_background: {appdrawer_path}")
                print(f"[HomeScreenSetting.on_click_ext] Verified homescreen: {homescreen_path}")
                print(f"[HomeScreenSetting.on_click_ext] Appdrawer path contains -blur: {'-blur.' in str(appdrawer_path) if appdrawer_path else False}")
                print(f"[HomeScreenSetting.on_click_ext] Homescreen path contains -blur: {'-blur.' in str(homescreen_path) if homescreen_path else False}")

        # Return to previous screen
        if self.prev_scr is not None:
            if __debug__:
                print(f"[HomeScreenSetting.on_click_ext] Returning to previous screen: {self.prev_scr}")
                print(f"[HomeScreenSetting.on_click_ext] Previous screen class: {self.prev_scr.__class__.__name__ if hasattr(self.prev_scr, '__class__') else 'Unknown'}")
                # Check if the previous screen is still valid
                try:
                    if hasattr(self.prev_scr, 'is_deleted') and callable(self.prev_scr.is_deleted):
                        is_deleted = self.prev_scr.is_deleted()
                        print(f"[HomeScreenSetting.on_click_ext] Previous screen is_deleted: {is_deleted}")
                except Exception as e:
                    print(f"[HomeScreenSetting.on_click_ext] Error checking prev_scr validity: {e}")
            
            # Try to load the previous screen
            try:
                self.load_screen(self.prev_scr, destroy_self=True)
            except Exception as e:
                if __debug__:
                    print(f"[HomeScreenSetting.on_click_ext] Error loading previous screen: {e}")
                # Fallback: Try to go to main wallpaper settings screen
                try:
                    # Create a new WallpaperScreen instance
                    fallback_screen = WallpaperScreen()
                    if __debug__:
                        print("[HomeScreenSetting.on_click_ext] Using fallback: WallpaperScreen")
                    self.load_screen(fallback_screen, destroy_self=True)
                except Exception as fallback_error:
                    if __debug__:
                        print(f"[HomeScreenSetting.on_click_ext] Fallback also failed: {fallback_error}")
        else:
            if __debug__:
                print("[HomeScreenSetting.on_click_ext] No previous screen to return to!")

    def _get_blur_wallpaper_path(self, original_path):
        """Generate the blur version path from original wallpaper path"""
        if __debug__:
            print(f"[HomeScreenSetting._get_blur_wallpaper_path] original_path={original_path}")
        if not original_path:
            return None

        # Split the path at the last dot to separate name and extension
        if '.' in original_path:
            path_without_ext, ext = original_path.rsplit('.', 1)
            blur_path = f"{path_without_ext}-blur.{ext}"
        else:
            blur_path = f"{original_path}-blur"

        if __debug__:
            print(f"[HomeScreenSetting._get_blur_wallpaper_path] blur_path={blur_path}")
        return blur_path

    def _blur_wallpaper_exists(self, blur_path):
        """简单检查模糊壁纸是否存在"""
        if __debug__:
            print(f"[HomeScreenSetting._blur_wallpaper_exists] blur_path={blur_path}")
        if not blur_path:
            return False

        try:
            # 统一处理路径格式
            if blur_path.startswith("A:/res/wallpapers/"):
                # Custom wallpapers: A:/res/wallpapers/ -> 1:/res/wallpapers/ (文件系统访问)
                file_path = blur_path.replace("A:/res/wallpapers/", "1:/res/wallpapers/")
            elif blur_path.startswith("A:/res/"):
                # Built-in Pro wallpapers: A:/res/ -> /res/ (直接访问)
                file_path = blur_path[2:]  # 去掉 "A:/" 前缀
            elif blur_path.startswith("A:1:/"):
                # Legacy format: A:1:/res/ -> 1:/res/ (文件系统访问)
                file_path = blur_path[2:]  # 去掉 "A:" 前缀，保留 "1:/"
            else:
                file_path = blur_path

            # 直接检查文件是否存在
            io.fatfs.stat(file_path)
            if __debug__:
                print(f"[HomeScreenSetting._blur_wallpaper_exists] Blur file exists: {file_path}")
            return True

        except Exception as e:
            if __debug__:
                print(f"[HomeScreenSetting._blur_wallpaper_exists] Blur file does not exist: {blur_path}, error: {e}")
            # 文件不存在或其他错误
            return False

    def _update_blur_button_state(self):
        """更新模糊按钮状态"""
        if __debug__:
            print("[HomeScreenSetting._update_blur_button_state] Updating blur button state")
        if not hasattr(self, 'original_wallpaper_path'):
            if __debug__:
                print("[HomeScreenSetting._update_blur_button_state] No original_wallpaper_path")
            return

        blur_path = self._get_blur_wallpaper_path(self.original_wallpaper_path)
        blur_exists = self._blur_wallpaper_exists(blur_path) if blur_path else False

        # 根据状态设置图标和可点击状态
        if not blur_exists:
            # 没有blur版本：不可点击，无样式
            icon_path = "A:/res/blur_not_available.png"
            self.blur_button.clear_flag(lv.obj.FLAG.CLICKABLE)
            # 移除可能的样式，使其看起来平淡
            self.blur_button.set_style_bg_opa(lv.OPA.TRANSP, 0)
            self.blur_button.set_style_border_width(0, 0)
            if __debug__:
                print("[HomeScreenSetting._update_blur_button_state] Blur not available - disabled button")
        else:
            # 有blur版本：可点击，恢复样式
            self.blur_button.add_flag(lv.obj.FLAG.CLICKABLE)
            # 恢复按钮样式
            self.blur_button.set_style_bg_opa(lv.OPA.COVER, 0)
            self.blur_button.set_style_border_width(1, 0)
            
            if getattr(self, 'is_blur_active', False):
                icon_path = "A:/res/blur_selected.png"
                if __debug__:
                    print("[HomeScreenSetting._update_blur_button_state] Blur active - selected state")
            else:
                icon_path = "A:/res/blur_no_selected.png"
                if __debug__:
                    print("[HomeScreenSetting._update_blur_button_state] Blur available - unselected state")

        if __debug__:
            print(f"[HomeScreenSetting._update_blur_button_state] Setting blur_button_icon to {icon_path}")
        self.blur_button_icon.set_src(icon_path)

    def on_blur_clicked(self, event_obj):
        """模糊按钮点击 - 切换原图和模糊图"""
        if __debug__:
            print("[HomeScreenSetting.on_blur_clicked] Blur button clicked")

        blur_path = self._get_blur_wallpaper_path(self.original_wallpaper_path)

        if not blur_path or not self._blur_wallpaper_exists(blur_path):
            if __debug__:
                print("[HomeScreenSetting.on_blur_clicked] No blur version available")
            return  # 没有模糊版本，直接返回

        # 切换状态
        self.is_blur_active = not getattr(self, 'is_blur_active', False)
        
        # 根据blur状态选择正确的图片路径
        test_path = blur_path if self.is_blur_active else self.original_wallpaper_path
        
        # 对于Custom wallpapers，需要特殊处理路径
        if test_path and "/res/wallpapers/" in test_path:
            # 非blur文件保持A:1:前缀（之前可以工作）
            if not "-blur." in test_path:
                # 确保使用A:1:前缀
                if test_path.startswith("A:/res/wallpapers/"):
                    test_path = test_path.replace("A:/res/wallpapers/", "A:1:/res/wallpapers/")
                elif test_path.startswith("1:/res/wallpapers/"):
                    test_path = test_path.replace("1:/res/wallpapers/", "A:1:/res/wallpapers/")
                if __debug__:
                    print(f"[HomeScreenSetting.on_blur_clicked] Using A:1: prefix for ORIGINAL (non-blur): {test_path}")
            else:
                # blur文件使用A:1:前缀（与原图一致）
                if test_path.startswith("A:/res/wallpapers/"):
                    test_path = test_path.replace("A:/res/wallpapers/", "A:1:/res/wallpapers/")
                elif test_path.startswith("1:/res/wallpapers/"):
                    test_path = test_path.replace("1:/res/wallpapers/", "A:1:/res/wallpapers/")
                if __debug__:
                    print(f"[HomeScreenSetting.on_blur_clicked] Using A:1: prefix for blur (same as original): {test_path}")
        
        if __debug__:
            blur_status = "blur" if self.is_blur_active else "original"
            print(f"[HomeScreenSetting.on_blur_clicked] Switching to {blur_status} image: {test_path}")
            
        self.current_wallpaper_path = test_path
        print(f"[HomeScreenSetting.on_blur_clicked] current_wallpaper_path: {self.current_wallpaper_path}") 
        
        # 添加详细日志
        if __debug__:
            print(f"[HomeScreenSetting.on_blur_clicked] Before set_src - preview object: {self.homescreen_preview}")
            print(f"[HomeScreenSetting.on_blur_clicked] Before set_src - preview parent: {self.homescreen_preview.get_parent()}")
            print(f"[HomeScreenSetting.on_blur_clicked] Before set_src - preview size: {self.homescreen_preview.get_width()}x{self.homescreen_preview.get_height()}")
            
            # 检查文件是否存在并获取详细信息
            try:
                if self.current_wallpaper_path.startswith("A:/res/wallpapers/"):
                    # A:/res/wallpapers/xxx -> 1:/res/wallpapers/xxx
                    file_path = self.current_wallpaper_path.replace("A:/res/wallpapers/", "1:/res/wallpapers/")
                elif self.current_wallpaper_path.startswith("A:1:/res/wallpapers/"):
                    # A:1:/res/wallpapers/xxx -> 1:/res/wallpapers/xxx  
                    file_path = self.current_wallpaper_path.replace("A:1:/res/wallpapers/", "1:/res/wallpapers/")
                else:
                    file_path = self.current_wallpaper_path
                
                stat_info = io.fatfs.stat(file_path)
                file_size = stat_info[0]  # 第一个元素是文件大小
                print(f"[HomeScreenSetting.on_blur_clicked] File check passed - path: {file_path}, size: {file_size}")
                
                # 对于blur文件，跳过文件头检查（文件已确认存在）
                if "-blur." in file_path:
                    print(f"[HomeScreenSetting.on_blur_clicked] Blur file found and accessible")
                        
            except Exception as e:
                print(f"[HomeScreenSetting.on_blur_clicked] File exists check FAILED for: {file_path}, error: {e}")
            
        # 由于可能已经变成label，需要检查类型
        if hasattr(self.homescreen_preview, 'set_src'):
            # 直接使用set_src，不需要重新创建对象
            if __debug__:
                print(f"[HomeScreenSetting.on_blur_clicked] Setting image src to: {self.current_wallpaper_path}")
            self.homescreen_preview.set_src(self.current_wallpaper_path)
            
            # 添加显示层面的调试信息
            if __debug__:
                print(f"[HomeScreenSetting.on_blur_clicked] Preview object after set_src: {self.homescreen_preview}")
                print(f"[HomeScreenSetting.on_blur_clicked] Preview parent: {self.homescreen_preview.get_parent()}")
                print(f"[HomeScreenSetting.on_blur_clicked] Preview has HIDDEN flag: {self.homescreen_preview.has_flag(lv.obj.FLAG.HIDDEN)}")
                print(f"[HomeScreenSetting.on_blur_clicked] Preview opacity: {self.homescreen_preview.get_style_opa(0)}")
                
                # 检查容器状态
                if hasattr(self, 'preview_container'):
                    print(f"[HomeScreenSetting.on_blur_clicked] Container has HIDDEN flag: {self.preview_container.has_flag(lv.obj.FLAG.HIDDEN)}")
                    print(f"[HomeScreenSetting.on_blur_clicked] Container size: {self.preview_container.get_width()}x{self.preview_container.get_height()}")
                
                # 强制刷新显示
                try:
                    self.homescreen_preview.invalidate()
                    if hasattr(self, 'preview_container'):
                        self.preview_container.invalidate()
                    print(f"[HomeScreenSetting.on_blur_clicked] Display refresh triggered")
                except Exception as refresh_error:
                    print(f"[HomeScreenSetting.on_blur_clicked] Refresh error: {refresh_error}")
        else:
            # 已经是label，更新文本
            filename = self.current_wallpaper_path.split('/')[-1] if '/' in self.current_wallpaper_path else self.current_wallpaper_path
            display_text = f"Wallpaper\n{filename}\n\n(LVGL filesystem\ndamaged after\nAppDrawer animation)"
            self.homescreen_preview.set_text(display_text)
        
        if __debug__:
            print(f"[HomeScreenSetting.on_blur_clicked] Set preview to: {self.current_wallpaper_path}")
            # 检查设置后的实际状态
            try:
                actual_src = self.homescreen_preview.get_src()
                print(f"[HomeScreenSetting.on_blur_clicked] After set_src - actual src: {actual_src}")
                print(f"[HomeScreenSetting.on_blur_clicked] After set_src - actual type: {type(actual_src)}")
                
                # Blob是正常的，不需要重建
                if actual_src is not None:
                    print(f"[HomeScreenSetting.on_blur_clicked] Image source set successfully (Blob is normal)")
                else:
                    print(f"[HomeScreenSetting.on_blur_clicked] WARNING: Image source is null")
            except Exception as e:
                print(f"[HomeScreenSetting.on_blur_clicked] Error checking src state: {e}")
            
        self.invalidate()

        if __debug__:
            print(f"[HomeScreenSetting.on_blur_clicked] Switched to {'blur' if self.is_blur_active else 'original'} wallpaper: {self.current_wallpaper_path}")
            print(f"[HomeScreenSetting.on_blur_clicked] NOTE: This change will be saved when user clicks the checkmark button")

        # 更新按钮状态
        self._update_blur_button_state()

    def _load_blur_state(self):
        """Load blur state by analyzing the current homescreen path"""
        try:
            # Get current homescreen from storage - use get_appdrawer_background since we save with set_appdrawer_background
            current_homescreen = storage_device.get_appdrawer_background() or storage_device.get_homescreen() or "A:/res/wallpaper-2.jpg"

            if __debug__:
                print(f"[HomeScreenSetting._load_blur_state] Loading blur state from appdrawer_background: {storage_device.get_appdrawer_background()}")
                print(f"[HomeScreenSetting._load_blur_state] Loading blur state from homescreen: {storage_device.get_homescreen()}")
                print(f"[HomeScreenSetting._load_blur_state] Using final path: {current_homescreen}")
                print(f"[HomeScreenSetting._load_blur_state] Path contains -blur: {'-blur.' in current_homescreen}")

            # Check if current homescreen is a blur version (contains '-blur')
            if '-blur.' in current_homescreen:
                # Currently showing blur version
                self.is_blur_active = True
                self.current_wallpaper_path = current_homescreen
                # Get original path by removing '-blur' more carefully
                # Split by '.' to get extension, then remove '-blur' from the name part
                path_parts = current_homescreen.rsplit('.', 1)
                if len(path_parts) == 2:
                    name_part, ext = path_parts
                    if name_part.endswith('-blur'):
                        self.original_wallpaper_path = name_part[:-5] + '.' + ext  # Remove '-blur' (5 chars)
                    else:
                        self.original_wallpaper_path = current_homescreen  # Fallback
                else:
                    self.original_wallpaper_path = current_homescreen  # Fallback
                if __debug__:
                    print(f"[HomeScreenSetting._load_blur_state] Detected blur mode")
                    print(f"[HomeScreenSetting._load_blur_state] Current (blur): {current_homescreen}")
                    print(f"[HomeScreenSetting._load_blur_state] Original: {self.original_wallpaper_path}")
            else:
                # Currently showing original version
                self.is_blur_active = False
                self.original_wallpaper_path = current_homescreen
                self.current_wallpaper_path = current_homescreen
                if __debug__:
                    print(f"[HomeScreenSetting._load_blur_state] Detected original mode - path: {self.original_wallpaper_path}")

        except Exception as e:
            if __debug__:
                print(f"[HomeScreenSetting._load_blur_state] Error loading blur state: {e}")
            # Fallback to safe defaults
            current_homescreen = "A:/res/wallpaper-2.jpg"
            self.original_wallpaper_path = current_homescreen
            self.current_wallpaper_path = current_homescreen
            self.is_blur_active = False

    def set_wallpaper(self, wallpaper_path):
        """Set wallpaper and update blur button state"""
        if __debug__:
            print(f"[HomeScreenSetting.set_wallpaper] Setting wallpaper to {wallpaper_path}")
        if wallpaper_path:
            self.original_wallpaper_path = wallpaper_path
            self.current_wallpaper_path = wallpaper_path
            self.is_blur_active = False
            self.homescreen_preview.set_src(wallpaper_path)
            self._update_blur_button_state()
            if __debug__:
                print(f"[HomeScreenSetting.set_wallpaper] Wallpaper set to {wallpaper_path}")


class WallPaperManage(Screen):
    def __init__(
        self,
        prev_scr=None,
        img_path: str = "",
        zoom_path: str = "",
        is_internal: bool = False,
    ):
        super().__init__(
            prev_scr,
            icon_path=zoom_path,
            title=_(i18n_keys.TITLE__MANAGE_WALLPAPER),
            subtitle=_(i18n_keys.SUBTITLE__MANAGE_WALLPAPER),
            nav_back=True,
        )
        self.img_path = img_path
        self.zoom_path = zoom_path

        self.btn_yes = NormalButton(self.content_area, _(i18n_keys.BUTTON__SET))
        self.btn_yes.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_GREEN).text_color(lv_colors.BLACK),
            0,
        )
        if not is_internal:
            # self.icon.add_style(StyleWrapper().radius(40).clip_corner(True), 0)
            # self.icon.set_style_radius(40, 0)
            # self.icon.set_style_clip_corner(True, 0)
            self.btn_yes.set_size(224, 98)
            self.btn_yes.align_to(self.content_area, lv.ALIGN.BOTTOM_RIGHT, -12, -8)
            self.btn_del = NormalButton(self.content_area, "")
            self.btn_del.set_size(224, 98)
            self.btn_del.align(lv.ALIGN.BOTTOM_LEFT, 12, -8)

            self.panel = lv.obj(self.btn_del)
            self.panel.remove_style_all()
            self.panel.set_size(lv.SIZE.CONTENT, lv.SIZE.CONTENT)
            self.panel.clear_flag(lv.obj.FLAG.CLICKABLE)

            self.btn_del_img = lv.img(self.panel)
            self.btn_del_img.set_src("A:/res/btn-del.png")
            self.btn_label = lv.label(self.panel)
            self.btn_label.set_text(_(i18n_keys.BUTTON__DELETE))
            self.btn_label.align_to(self.btn_del_img, lv.ALIGN.OUT_RIGHT_MID, 4, 1)

            self.panel.add_style(
                StyleWrapper()
                .bg_color(lv_colors.ONEKEY_BLACK)
                .text_color(lv_colors.ONEKEY_RED_1)
                .bg_opa(lv.OPA.TRANSP)
                .border_width(0)
                .align(lv.ALIGN.CENTER),
                0,
            )

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)

    def del_callback(self):
        io.fatfs.unlink(self.img_path[2:])
        io.fatfs.unlink(self.zoom_path[2:])
        if storage_device.get_homescreen() == self.img_path:
            storage_device.set_appdrawer_background(utils.get_default_wallpaper())
        self.load_screen(self.prev_scr, destroy_self=True)

    # def cancel_callback(self):
    #     self.btn_del.clear_flag(lv.obj.FLAG.HIDDEN)

    def eventhandler(self, event_obj):
        event = event_obj.code
        target = event_obj.get_target()
        if event == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if isinstance(target, lv.imgbtn):
                if target == self.nav_back.nav_btn:
                    if self.prev_scr is not None:
                        self.prev_scr.from_wallpaper = True
                        self.load_screen(self.prev_scr, destroy_self=True)
                        self.prev_scr.from_wallpaper = False
            else:
                if target == self.btn_yes:
                    storage_device.set_appdrawer_background(self.img_path)
                    self.prev_scr.from_wallpaper = True
                    self.load_screen(self.prev_scr, destroy_self=True)
                    self.prev_scr.from_wallpaper = False
                elif hasattr(self, "btn_del") and target == self.btn_del:
                    from trezor.ui.layouts import confirm_del_wallpaper
                    from trezor.wire import DUMMY_CONTEXT

                    workflow.spawn(
                        confirm_del_wallpaper(DUMMY_CONTEXT, self.del_callback)
                    )


class SecurityScreen(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            utils.mark_collecting_fingerprint_done()
            return
        super().__init__(prev_scr, title=_(i18n_keys.TITLE__SECURITY), nav_back=True)

        # self.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)

        self.container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.container.set_scroll_dir(lv.DIR.NONE)

        self.device_auth = ListItemBtn(
            self.container,
            _(i18n_keys.TITLE__SECURITY_CHECK),
        )
        self.pin_map_type = ListItemBtn(self.container, _(i18n_keys.ITEM__PIN_KEYPAD))
        self.fingerprint = ListItemBtn(self.container, _(i18n_keys.TITLE__FINGERPRINT))
        self.usb_lock = ListItemBtn(self.container, _(i18n_keys.ITEM__USB_LOCK))
        self.change_pin = ListItemBtn(self.container, _(i18n_keys.ITEM__CHANGE_PIN))
        self.safety_check = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__SAFETY_CHECKS),
        )
        self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        # pyright: off
        if code == lv.EVENT.CLICKED:
            from trezor.wire import DUMMY_CONTEXT

            if utils.lcd_resume():
                return
            if target == self.change_pin:
                from apps.management.change_pin import change_pin
                from trezor.messages import ChangePin

                workflow.spawn(change_pin(DUMMY_CONTEXT, ChangePin(remove=False)))
            elif target == self.pin_map_type:
                PinMapSetting(self)
            elif target == self.usb_lock:
                UsbLockSetting(self)
            elif target == self.fingerprint:
                # from trezor.lvglui.scrs import fingerprints

                # if fingerprints.has_fingerprints():
                #     # from trezor import config

                #     # if config.has_pin():
                #     #     config.lock()
                from apps.common.request_pin import verify_user_pin

                workflow.spawn(
                    verify_user_pin(
                        re_loop=False,
                        allow_cancel=True,
                        callback=lambda: FingerprintSetting(self),
                        allow_fingerprint=False,
                        standy_wall_only=True,
                        pin_use_type=1,
                    )
                )
                # else:

                #     workflow.spawn(
                #         fingerprints.add_fingerprint(
                #             0, callback=lambda: FingerprintSetting(self)
                #         )
                #     )
            elif target == self.device_auth:
                DeviceAuthScreen(self)
            elif target == self.safety_check:
                SafetyCheckSetting(self)
            else:
                if __debug__:
                    print("unknown")
        # pyright: on


class DeviceAuthScreen(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "btn") and self.btn:
            targets.append(self.btn)
        return targets

    def __init__(self, prev_scr=None) -> None:
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        from binascii import hexlify

        super().__init__(
            prev_scr,
            title=_(i18n_keys.TITLE__SECURITY_CHECK),
            nav_back=True,
        )
        firmware_version = storage_device.get_firmware_version()
        firmware_build_id = utils.BUILD_ID[-7:].decode()
        firmware_hash_str = hexlify(utils.onekey_firmware_hash()).decode()[:7]
        version_str = f"{firmware_version} ({firmware_build_id}-{firmware_hash_str})"

        ble_version = uart.get_ble_version()
        ble_build_id = uart.get_ble_build_id()
        ble_hash_str = hexlify(uart.get_ble_hash()).decode()[:7]
        ble_version_str = f"{ble_version} ({ble_build_id}-{ble_hash_str})"

        boot_version = utils.boot_version()
        boot_build_id = utils.boot_build_id()
        boot_hash_str = hexlify(utils.boot_hash()).decode()[:7]
        boot_version_str = f"{boot_version} ({boot_build_id}-{boot_hash_str})"
        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=0)
        self.container.add_dummy()

        self.ser_num = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.ITEM__SERIAL_NUMBER),
            storage_device.get_serial(),
        )
        self.version = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.ITEM__SYSTEM_VERSION),
            version_str,
            url=f"https://github.com/OneKeyHQ/firmware-pro/releases/tag/v{firmware_version}",
        )
        self.ble_version = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.ITEM__BLUETOOTH_VERSION),
            ble_version_str,
            url=f"https://github.com/OneKeyHQ/bluetooth-firmware-pro/releases/tag/v{ble_version}",
        )
        self.boot_version = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.ITEM__BOOTLOADER_VERSION),
            boot_version_str,
            url=f"https://github.com/OneKeyHQ/firmware-pro/releases/tag/bootloader-v{boot_version}",
        )
        self.container.add_dummy()
        self.btn = NormalButton(self, _(i18n_keys.ACTION_VERIFY_NOW))
        self.btn.enable(lv_colors.ONEKEY_GREEN, text_color=lv_colors.BLACK)
        self.load_screen(self)
        gc.collect()

    def on_click(self, target):
        if target == self.btn:
            DeviceAuthTutorial(self)


class DeviceAuthTutorial(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "warning_banner") and self.warning_banner:
            targets.append(self.warning_banner)
        return targets

    def __init__(self, prev_scr=None) -> None:
        super().__init__(
            prev_scr,
            title=_(i18n_keys.TITLE__VEIRIFY_DEVICE),
            nav_back=True,
        )
        from trezor.lvglui.scrs.components.listitem import CardHeader, DisplayItem

        self.container = ContainerFlexCol(self.content_area, self.title, pos=(0, 40))
        steps = [
            (
                _(i18n_keys.FORM__DOWNLOAD_ONEKEY_APP),
                _(i18n_keys.FORM__DOWNLOAD_APP_FROM_DOWNLOAD_CENTER),
            ),
            (
                _(i18n_keys.TITLE__VEIRIFY_DEVICE),
                _(i18n_keys.VERIFY_DEVICE_CONNECT_DEVICE_DESC),
            ),
        ]
        for i, step in enumerate(steps):
            self.group = ContainerFlexCol(
                self.container,
                None,
                padding_row=0,
                no_align=True,
            )
            self.item_group_header = CardHeader(
                self.group,
                step[0],
                f"A:/res/group-icon-num-{i+1}.png",
            )
            self.item_group_body = DisplayItem(
                self.group,
                None,
                step[1],
            )
            self.item_group_body.label.add_style(
                StyleWrapper().text_color(lv_colors.ONEKEY_GRAY_4),
                0,
            )
            self.group.add_dummy()

        self.warning_banner = Banner(
            self.content_area,
            LEVEL.HIGHLIGHT,
            _(i18n_keys.VERIFY_DEVICE_HELP_CENTER_TEXT),
            title=_(i18n_keys.ACTION__LEARN_MORE),
        )
        self.warning_banner.set_style_text_color(lv_colors.LIGHT_GRAY, 0)
        self.warning_banner.align_to(self.container, lv.ALIGN.OUT_BOTTOM_MID, 0, 8)
        self.load_screen(self)
        gc.collect()


class UsbLockSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "description") and self.description:
            targets.append(self.description)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__USB_LOCK), nav_back=True
        )

        self.container = ContainerFlexCol(self.content_area, self.title)
        self.usb_lock = ListItemBtnWithSwitch(
            self.container, _(i18n_keys.ITEM__USB_LOCK)
        )

        self.description = lv.label(self.content_area)
        self.description.set_size(456, lv.SIZE.CONTENT)
        self.description.set_long_mode(lv.label.LONG.WRAP)
        self.description.set_style_text_color(lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT)
        self.description.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)
        self.description.set_style_text_line_space(3, 0)
        self.description.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)

        if storage_device.is_usb_lock_enabled():
            self.usb_lock.add_state()
            self.description.set_text(_(i18n_keys.CONTENT__USB_LOCK_ENABLED__HINT))
        else:
            self.usb_lock.clear_state()
            self.description.set_text(_(i18n_keys.CONTENT__USB_LOCK_DISABLED__HINT))
        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.load_screen(self)
        gc.collect()

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.usb_lock.switch:
                if target.has_state(lv.STATE.CHECKED):
                    self.description.set_text(
                        _(i18n_keys.CONTENT__USB_LOCK_ENABLED__HINT)
                    )
                    storage_device.set_usb_lock_enable(True)
                else:
                    self.description.set_text(
                        _(i18n_keys.CONTENT__USB_LOCK_DISABLED__HINT)
                    )
                    storage_device.set_usb_lock_enable(False)


class FingerprintSetting(AnimScreen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        from trezor import config

        config.fingerprint_data_read_remaining()

        from trezorio import fingerprint

        fingerprint.clear_template_cache(True)

        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.TITLE__FINGERPRINT), nav_back=True
        )

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.fresh_show()
        self.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def fresh_show(self):
        self.container.clean()
        if hasattr(self, "container_fun"):
            self.container_fun.delete()

        from . import fingerprints

        self.fingerprint_list = fingerprints.get_fingerprint_list()
        counter = fingerprints.get_fingerprint_count()
        group_data = fingerprints.get_fingerprint_group()
        self.data_new_version = fingerprints.data_version_is_new()

        valid_fps = [fp for fp in self.fingerprint_list if fp is not None]

        if __debug__:
            print(f"fingerprint_list: {self.fingerprint_list}")
            print(f"group_data: {group_data}")
            print(f"valid_fps: {valid_fps}")
            print(f"counter: {counter}")

        def _filter_and_pad_group(grp, valid_fps):
            if not grp:
                return None
            filtered = [idx for idx in grp["indexes"] if idx in valid_fps]
            if not filtered:
                return None
            while len(filtered) < 3:
                filtered.append(0xFF)
            return {"group_id": grp["group_id"], "indexes": filtered}

        groups = []
        if self.data_new_version:
            g1 = self._parse_group_data(group_data[0:4])
            g2 = self._parse_group_data(group_data[4:8])

            g1 = _filter_and_pad_group(g1, valid_fps)
            g2 = _filter_and_pad_group(g2, valid_fps)

            for g in (g1, g2):
                if g is not None:
                    groups.append(g)

            in_group = {idx for g in groups for idx in g["indexes"] if idx != 0xFF}
            not_in_group = [idx for idx in valid_fps if idx not in in_group]

            if len(groups) < 2 and not_in_group:
                new_idx = not_in_group[:]
                while len(new_idx) < 3:
                    new_idx.append(0xFF)
                groups.append({"group_id": not_in_group[0], "indexes": new_idx})

            counter = len(groups)
            self.groups = groups

        else:
            if len(valid_fps) == 1:
                idx = valid_fps[0]
                indexes = [idx]
                while len(indexes) < 3:
                    indexes.append(0xFF)
                self.groups = [{"group_id": idx, "indexes": indexes}]
            else:
                self.groups = []

        if __debug__:
            print(f"groups: {self.groups}")

        self.added_fingerprints = []
        if not self.data_new_version:
            for idx in self.fingerprint_list:
                self.added_fingerprints.append(
                    ListItemBtn(
                        self.container,
                        _(i18n_keys.FORM__FINGER_STR).format(idx + 1),
                        left_img_src="A:/res/settings-fingerprint.png",
                        has_next=False,
                    )
                    if idx is not None
                    else None
                )
        else:
            for group in self.groups:
                self.added_fingerprints.append(
                    ListItemBtn(
                        self.container,
                        _(i18n_keys.FORM__FINGER_STR).format(group["group_id"] + 1),
                        left_img_src="A:/res/settings-fingerprint.png",
                        has_next=False,
                    )
                )

        self.add_fingerprint = None

        if counter < 2:
            self.add_fingerprint = ListItemBtn(
                self.container,
                _(i18n_keys.BUTTON__ADD_FINGERPRINT),
                left_img_src="A:/res/settings-plus.png",
                has_next=False,
            )

        self.container_fun = ContainerFlexCol(
            self.content_area, self.container, pos=(0, 12), padding_row=1
        )
        self.unlock = ListItemBtnWithSwitch(
            self.container_fun, _(i18n_keys.FORM__UNLOCK_DEVICE)
        )

        if not storage_device.is_fingerprint_unlock_enabled():
            self.unlock.clear_state()

    def _parse_group_data(self, data):
        if data and data[0] != 0xFF:
            return {"group_id": data[0], "indexes": data[1:4]}
        return None

    async def on_remove(self, fp_id):
        from trezorio import fingerprint

        fingerprint.remove(fp_id)

        self.fresh_show()

    async def on_remove_group(self, group):
        from trezorio import fingerprint

        group_bytes = bytes([group["group_id"]]) + bytes(group["indexes"])
        fingerprint.remove_group(group_bytes)
        self.fresh_show()

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            from trezor.lvglui.scrs import fingerprints

            if target == self.add_fingerprint:
                if not self.groups:
                    group_id = 0
                else:
                    current_group_id = self.groups[0]["group_id"]
                    if current_group_id not in (0, 1):
                        group_id = 0
                    else:
                        group_id = 1 - current_group_id
                workflow.spawn(
                    fingerprints.add_fingerprint(
                        group_id=group_id,
                        callback=lambda: self.fresh_show(),
                    )
                )
            elif target in self.added_fingerprints:
                for i, item in enumerate(self.added_fingerprints):
                    if target == item:
                        if self.data_new_version:
                            group = self.groups[i]
                            prompt = _(i18n_keys.FORM__FINGER_STR).format(
                                group["group_id"] + 1
                            )
                            workflow.spawn(
                                fingerprints.request_delete_fingerprint(
                                    prompt,
                                    on_remove=lambda: self.on_remove_group(group),
                                )
                            )
                        else:
                            fp_id = self.fingerprint_list[i]
                            prompt = _(i18n_keys.FORM__FINGER_STR).format(i + 1)
                            workflow.spawn(
                                fingerprints.request_delete_fingerprint(
                                    prompt, on_remove=lambda: self.on_remove(fp_id)
                                )
                            )

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.unlock.switch:

                if target.has_state(lv.STATE.CHECKED):
                    storage_device.enable_fingerprint_unlock(True)
                else:
                    storage_device.enable_fingerprint_unlock(False)


class SafetyCheckSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "description") and self.description:
            targets.append(self.description)
        if hasattr(self, "warning_desc") and self.warning_desc:
            targets.append(self.warning_desc)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.TITLE__SAFETY_CHECKS),
            nav_back=True,
        )

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        # self.strict = ListItemBtn(
        #     self.container, _(i18n_keys.ITEM__STATUS__STRICT), has_next=False
        # )
        # self.strict.add_check_img()
        # self.prompt = ListItemBtn(
        #     self.container, _(i18n_keys.ITEM__STATUS__PROMPT), has_next=False
        # )
        self.safety_check = ListItemBtnWithSwitch(
            self.container, _(i18n_keys.ITEM__SAFETY_CHECKS)
        )
        # self.prompt.add_check_img()
        self.description = lv.label(self.content_area)
        self.description.set_size(456, lv.SIZE.CONTENT)
        self.description.set_long_mode(lv.label.LONG.WRAP)
        self.description.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)
        self.description.set_style_text_line_space(3, 0)
        self.description.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)
        self.description.set_recolor(True)
        # self.set_checked()
        self.retrieval_state()

        self.container.add_event_cb(self.on_click, lv.EVENT.VALUE_CHANGED, None)
        self.add_event_cb(self.on_click, lv.EVENT.READY, None)
        self.load_screen(self)
        gc.collect()

    def retrieval_state(self):
        if safety_checks.is_strict():
            self.safety_check.add_state()
            self.description.set_text(_(i18n_keys.CONTENT__SAFETY_CHECKS_STRICT__HINT))
            self.description.set_style_text_color(
                lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT
            )
            self.clear_warning_desc()
        else:
            self.safety_check.clear_state()
            if safety_checks.is_prompt_always():
                self.description.set_text(
                    _(i18n_keys.CONTENT__SAFETY_CHECKS_PERMANENTLY_PROMPT__HINT)
                )
                self.add_warning_desc(LEVEL.DANGER)
            else:
                self.description.set_text(
                    _(i18n_keys.CONTENT__SAFETY_CHECKS_TEMPORARILY_PROMPT__HINT)
                )
                self.add_warning_desc(LEVEL.WARNING)

    def add_warning_desc(self, level):
        if not hasattr(self, "warning_desc"):
            self.warning_desc = Banner(
                self.content_area, level, _(i18n_keys.MSG__SAFETY_CHECKS_PROMPT_WARNING)
            )

    def clear_warning_desc(self):
        if hasattr(self, "warning_desc"):
            self.warning_desc.delete()
            del self.warning_desc

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.safety_check.switch:
                if target.has_state(lv.STATE.CHECKED):
                    SafetyCheckStrictConfirm(self)
                else:
                    SafetyCheckPromptConfirm(self)
        elif code == lv.EVENT.READY:
            self.retrieval_state()


class SafetyCheckStrictConfirm(FullSizeWindow):
    def __init__(self, callback_obj):
        super().__init__(
            _(i18n_keys.TITLE__ENABLE_SAFETY_CHECKS),
            _(i18n_keys.SUBTITLE__ENABLE_SAFETY_CHECKS),
            confirm_text=_(i18n_keys.BUTTON__CONFIRM),
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
            # icon_path="A:/res/warning.png",
        )
        self.callback = callback_obj

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.btn_yes:
                safety_checks.apply_setting(SafetyCheckLevel.Strict)
            elif target != self.btn_no:
                return
            lv.event_send(self.callback, lv.EVENT.READY, None)
            self.destroy(0)


class SafetyCheckPromptConfirm(FullSizeWindow):
    def __init__(self, callback_obj):
        super().__init__(
            _(i18n_keys.TITLE__DISABLE_SAFETY_CHECKS),
            _(i18n_keys.SUBTITLE__SET_SAFETY_CHECKS_TO_PROMPT),
            confirm_text=_(i18n_keys.BUTTON__SLIDE_TO_DISABLE),
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
            # icon_path="A:/res/warning.png",
            hold_confirm=True,
            anim_dir=0,
        )
        self.slider.change_knob_style(1)
        # self.status_bar = lv.obj(self)
        # self.status_bar.remove_style_all()
        # self.status_bar.set_size(lv.pct(100), 44)
        # self.status_bar.add_style(
        #     StyleWrapper()
        #     .bg_opa()
        #     .align(lv.ALIGN.TOP_LEFT)
        #     .bg_img_src("A:/res/warning_bar.png"),
        #     0,
        # )
        self.callback = callback_obj

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.btn_no.click_mask:
                self.destroy(100)
        elif code == lv.EVENT.READY:
            if target == self.slider:
                safety_checks.apply_setting(SafetyCheckLevel.PromptTemporarily)
                self.destroy(0)
        lv.event_send(self.callback, lv.EVENT.READY, None)


class WalletScreen(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "rest_device") and self.rest_device:
            targets.append(self.rest_device)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(prev_scr, title=_(i18n_keys.TITLE__WALLET), nav_back=True)

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.check_mnemonic = ListItemBtn(
            self.container, _(i18n_keys.ITEM__CHECK_RECOVERY_PHRASE)
        )
        from apps.common import backup_types

        if backup_types.is_extendable_backup_type(storage_device.get_backup_type()):
            self.mul_share_bk = ListItemBtn(
                self.container, _(i18n_keys.BUTTON__CREATE_MULTI_SHARE_BACKUP)
            )
        self.passphrase = ListItemBtn(self.container, _(i18n_keys.ITEM__PASSPHRASE))
        self.turbo_mode = ListItemBtn(self.container, _(i18n_keys.TITLE__TURBO_MODE))
        self.trezor_mode = ListItemBtnWithSwitch(
            self.container, _(i18n_keys.ITEM__COMPATIBLE_WITH_TREZOR)
        )
        self.trezor_mode.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_BLACK_3).bg_opa(lv.OPA.COVER), 0
        )
        if not storage_device.is_trezor_compatible():
            self.trezor_mode.clear_state()
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.trezor_mode.add_event_cb(
            self.on_value_changed, lv.EVENT.VALUE_CHANGED, None
        )
        self.rest_device = ListItemBtn(
            self.content_area,
            _(i18n_keys.ITEM__RESET_DEVICE),
            has_next=False,
        )
        self.rest_device.label_left.set_style_text_color(lv_colors.ONEKEY_RED_1, 0)
        self.rest_device.align_to(self.trezor_mode, lv.ALIGN.OUT_BOTTOM_MID, 0, 12)
        self.rest_device.set_style_radius(40, 0)
        self.rest_device.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            from trezor.wire import DUMMY_CONTEXT

            if target == self.check_mnemonic:
                from apps.management.recovery_device import recovery_device
                from trezor.messages import RecoveryDevice

                utils.set_backup_none()
                # pyright: off
                workflow.spawn(
                    recovery_device(
                        DUMMY_CONTEXT,
                        RecoveryDevice(dry_run=True, enforce_wordlist=True),
                    )
                )
                # pyright: on
            elif hasattr(self, "mul_share_bk") and target == self.mul_share_bk:
                from apps.management.recovery_device.create_mul_shares import (
                    create_multi_share_backup,
                )

                workflow.spawn(create_multi_share_backup())
            elif target == self.passphrase:
                PassphraseScreen(self)
            elif target == self.turbo_mode:
                TurboModeScreen(self)
            elif target == self.rest_device:
                from apps.management.wipe_device import wipe_device
                from trezor.messages import WipeDevice

                workflow.spawn(wipe_device(DUMMY_CONTEXT, WipeDevice()))

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.trezor_mode.switch:
                TrezorModeToggle(self, not storage_device.is_trezor_compatible())

    def reset_switch(self):
        if storage_device.is_trezor_compatible():
            self.trezor_mode.add_state()
        else:
            self.trezor_mode.clear_state()


class FidoKeysSetting(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "description") and self.description:
            targets.append(self.description)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            if not self.is_visible():
                self._load_scr(self)
            return
        super().__init__(
            prev_scr=prev_scr, title=_(i18n_keys.FIDO_FIDO_KEYS_LABEL), nav_back=True
        )

        self.container = ContainerFlexCol(self.content_area, self.title)
        self.fido = ListItemBtnWithSwitch(
            self.container, _(i18n_keys.SECURITY__ENABLE_FIDO_KEYS)
        )
        self.description = lv.label(self.content_area)
        self.description.set_size(456, lv.SIZE.CONTENT)
        self.description.set_long_mode(lv.label.LONG.WRAP)
        self.description.set_style_text_color(lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT)
        self.description.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)
        self.description.set_style_text_line_space(3, 0)
        self.description.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)

        self.reset_state()
        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.load_screen(self)

    def reset_state(self):
        if storage_device.is_fido_enabled():
            self.fido.add_state()
            self.description.set_text(_(i18n_keys.SECURITY__ENABLE_FIDO_KEYS_DESC))
        else:
            self.fido.clear_state()
            self.description.set_text(_(i18n_keys.FIDO_DISABLED_INFO_TEXT))

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.fido.switch:
                FidoKeysToggle(self, not storage_device.is_fido_enabled())


class FidoKeysToggle(FullSizeWindow):
    def __init__(self, callback_obj, enable=False):
        super().__init__(
            title=_(
                i18n_keys.SECURITY__ENABLE_FIDO_KEYS
                if enable
                else i18n_keys.SECURITY__DISABLE_FIDO_KEYS
            ),
            subtitle=_(i18n_keys.SUBTITLE__RESTORE_TREZOR_COMPATIBILITY),
            confirm_text=_(i18n_keys.BUTTON__RESTART),
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
        )
        self.enable = enable
        self.callback_obj = callback_obj

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.btn_no:
                self.callback_obj.reset_state()
                self.destroy(200)
            elif target == self.btn_yes:

                async def restart_delay():
                    await loop.sleep(1000)
                    utils.reset()

                loop.pop_tasks_on_iface(io.UART | io.POLL_READ)
                storage_device.set_fido_enable(self.enable)
                workflow.spawn(restart_delay())


class PassphraseScreen(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "description") and self.description:
            targets.append(self.description)
        if hasattr(self, "advance_label") and self.advance_label:
            targets.append(self.advance_label)
        if hasattr(self, "attach_to_pin") and self.attach_to_pin:
            targets.append(self.attach_to_pin)
        if hasattr(self, "pin_description") and self.pin_description:
            targets.append(self.pin_description)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            if not self.is_visible():
                self._load_scr(self, lv.scr_act() != self)
            return
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.TITLE__PASSPHRASE),
            nav_back=True,
        )

        self.container = ContainerFlexCol(self.content_area, self.title)
        self.passphrase = ListItemBtnWithSwitch(
            self.container, _(i18n_keys.ITEM__PASSPHRASE)
        )

        self.description = lv.label(self.content_area)
        self.description.set_size(456, lv.SIZE.CONTENT)
        self.description.set_long_mode(lv.label.LONG.WRAP)
        self.description.set_style_text_color(lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT)
        self.description.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)
        self.description.set_style_text_line_space(3, 0)
        self.description.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)

        self.advance_label = lv.label(self.content_area)
        self.advance_label.set_text(_(i18n_keys.PASSPHRASE__ADVANCE))
        self.advance_label.set_style_text_color(lv_colors.WHITE, lv.STATE.DEFAULT)
        self.advance_label.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)

        self.attach_to_pin = ListItemBtn(
            self.content_area,
            _(i18n_keys.PASSPHRASE__ATTACH_TO_PIN),
            left_img_src="A:/res/icon-attach-to-pin.png",
        )
        self.attach_to_pin.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_GRAY_3).bg_opa(lv.OPA.COVER), 0
        )
        self.attach_to_pin.set_style_radius(40, 0)

        self.pin_description = lv.label(self.content_area)
        self.pin_description.set_text(_(i18n_keys.PASSPHRASE__ATTACH_TO_PIN_DESC))
        self.pin_description.set_size(456, lv.SIZE.CONTENT)
        self.pin_description.set_long_mode(lv.label.LONG.WRAP)
        self.pin_description.set_style_text_color(
            lv_colors.ONEKEY_GRAY, lv.STATE.DEFAULT
        )
        self.pin_description.set_style_text_font(font_GeistRegular26, lv.STATE.DEFAULT)

        passphrase_enable = storage_device.is_passphrase_enabled()
        if passphrase_enable:
            self.passphrase.add_state()
            self.description.set_text(_(i18n_keys.PASSPHRASE__ENABLE_DESC))
            self.advance_label.clear_flag(lv.obj.FLAG.HIDDEN)
            self.attach_to_pin.clear_flag(lv.obj.FLAG.HIDDEN)
            self.pin_description.clear_flag(lv.obj.FLAG.HIDDEN)
        else:
            self.passphrase.clear_state()
            self.description.set_text(_(i18n_keys.CONTENT__PASSPHRASE_DISABLED__HINT))
            self.advance_label.add_flag(lv.obj.FLAG.HIDDEN)
            self.attach_to_pin.add_flag(lv.obj.FLAG.HIDDEN)
            self.pin_description.add_flag(lv.obj.FLAG.HIDDEN)

        self._update_layout()

        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.attach_to_pin.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.add_event_cb(self.on_value_changed, lv.EVENT.READY, None)
        self.add_event_cb(self.on_value_changed, lv.EVENT.CANCEL, None)
        self.load_screen(self)
        gc.collect()

    def _update_layout(self):
        self.description.refresh_self_size()

        lv.timer_handler()

        advance_y_offset = 40

        self.advance_label.align_to(
            self.description, lv.ALIGN.OUT_BOTTOM_LEFT, 0, advance_y_offset
        )

        self.attach_to_pin.align_to(
            self.advance_label, lv.ALIGN.OUT_BOTTOM_LEFT, -8, 12
        )

        self.pin_description.align_to(
            self.attach_to_pin, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 8
        )

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.passphrase.switch:
                if target.has_state(lv.STATE.CHECKED):
                    screen = PassphraseTipsConfirm(
                        _(i18n_keys.TITLE__ENABLE_PASSPHRASE),
                        _(i18n_keys.SUBTITLE__ENABLE_PASSPHRASE),
                        _(i18n_keys.BUTTON__ENABLE),
                        self,
                        primary_color=lv_colors.ONEKEY_YELLOW,
                    )
                    screen.btn_yes.enable(lv_colors.ONEKEY_YELLOW, lv_colors.BLACK)
                else:
                    subtitle = None
                    from trezor.crypto import se_thd89
                    from apps.common.pin_constants import AttachCommon

                    current_space = se_thd89.get_pin_passphrase_space()
                    if current_space < AttachCommon.MAX_PASSPHRASE_PIN_NUM:
                        subtitle = _(i18n_keys.TITLE__DISABLE_PASSPHRASE_DESC)
                    else:
                        subtitle = _(i18n_keys.SUBTITLE__DISABLE_PASSPHRASE)

                    PassphraseTipsConfirm(
                        _(i18n_keys.TITLE__DISABLE_PASSPHRASE),
                        subtitle,
                        _(i18n_keys.BUTTON__DISABLE),
                        self,
                        icon_path="",
                    )
            elif target == self.attach_to_pin.switch:

                storage_device.set_passphrase_always_on_device(
                    target.has_state(lv.STATE.CHECKED)
                )

        elif code == lv.EVENT.READY:
            if self.passphrase.switch.has_state(lv.STATE.CHECKED):
                self.description.set_text(_(i18n_keys.PASSPHRASE__ENABLE_DESC))
                storage_device.set_passphrase_enabled(True)
                storage_device.set_passphrase_always_on_device(False)
                self.advance_label.clear_flag(lv.obj.FLAG.HIDDEN)
                self.attach_to_pin.clear_flag(lv.obj.FLAG.HIDDEN)
                self.pin_description.clear_flag(lv.obj.FLAG.HIDDEN)
                self._update_layout()
            else:
                self.description.set_text(
                    _(i18n_keys.CONTENT__PASSPHRASE_DISABLED__HINT)
                )
                storage_device.set_passphrase_enabled(False)
                if storage_device.is_passphrase_pin_enabled():
                    from apps.base import lock_device_if_unlocked

                    storage_device.set_passphrase_pin_enabled(False)
                    lock_device_if_unlocked()
                    return

                self.advance_label.add_flag(lv.obj.FLAG.HIDDEN)
                self.attach_to_pin.add_flag(lv.obj.FLAG.HIDDEN)
                self.pin_description.add_flag(lv.obj.FLAG.HIDDEN)

                self._update_layout()

        elif code == lv.EVENT.CANCEL:
            if self.passphrase.switch.has_state(lv.STATE.CHECKED):
                self.passphrase.clear_state()
                self.advance_label.add_flag(lv.obj.FLAG.HIDDEN)
                self.attach_to_pin.add_flag(lv.obj.FLAG.HIDDEN)
                self.pin_description.add_flag(lv.obj.FLAG.HIDDEN)
                self._update_layout()
            else:
                self.passphrase.add_state()
                self.attach_to_pin.clear_flag(lv.obj.FLAG.HIDDEN)
                self.advance_label.clear_flag(lv.obj.FLAG.HIDDEN)
                self.attach_to_pin.clear_flag(lv.obj.FLAG.HIDDEN)
                self.pin_description.clear_flag(lv.obj.FLAG.HIDDEN)
                self._update_layout()

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.attach_to_pin:
                global _attach_to_pin_task_running

                _attach_to_pin_task_running = True

                async def handle_attach_to_pin():
                    try:
                        from trezor.ui.layouts.lvgl.attach_to_pin import (
                            show_attach_to_pin_window,
                        )

                        ctx = wire.DUMMY_CONTEXT
                        result = await show_attach_to_pin_window(ctx)

                        if result:
                            self.load_screen(self)

                        return result
                    except Exception:
                        self.load_screen(self)
                        return False
                    finally:
                        global _attach_to_pin_task_running
                        _attach_to_pin_task_running = False

                workflow.spawn(handle_attach_to_pin())


class PassphraseTipsConfirm(FullSizeWindow):
    def __init__(
        self,
        title: str,
        subtitle: str,
        confirm_text: str,
        callback_obj,
        icon_path="A:/res/warning.png",
        primary_color=lv_colors.ONEKEY_GREEN,
    ):
        super().__init__(
            title,
            subtitle,
            confirm_text,
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
            icon_path=icon_path,
            anim_dir=2,
            primary_color=primary_color,
        )
        self.callback_obj = callback_obj

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            elif target == self.btn_no:
                lv.event_send(self.callback_obj, lv.EVENT.CANCEL, None)
            elif target == self.btn_yes:
                lv.event_send(self.callback_obj, lv.EVENT.READY, None)
            else:
                return
            self.show_dismiss_anim()


class CryptoScreen(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(prev_scr, title=_(i18n_keys.TITLE__CRYPTO), nav_back=True)

        self.container = ContainerFlexCol(self, self.title, padding_row=2)
        self.ethereum = ListItemBtn(self.container, _(i18n_keys.TITLE__ETHEREUM))
        self.solana = ListItemBtn(self.container, _(i18n_keys.TITLE__SOLANA))
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.ethereum:
                EthereumSetting(self)
            elif target == self.solana:
                SolanaSetting(self)


class TurboModeScreen(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        if hasattr(self, "tips") and self.tips:
            targets.append(self.tips)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(prev_scr, title=_(i18n_keys.TITLE__TURBO_MODE), nav_back=True)

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)

        self.turbo_mode = ListItemBtnWithSwitch(
            self.container, _(i18n_keys.TITLE__TURBO_MODE)
        )
        self.turbo_mode.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_BLACK_3).bg_opa(lv.OPA.COVER), 0
        )
        if not storage_device.is_turbomode_enabled():
            self.turbo_mode.clear_state()

        self.tips = lv.label(self.content_area)
        self.tips.align_to(self.container, lv.ALIGN.OUT_BOTTOM_LEFT, 8, 16)
        self.tips.set_long_mode(lv.label.LONG.WRAP)
        self.tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .width(448)
            .text_color(lv_colors.WHITE_2)
            .text_align_left(),
            0,
        )
        self.tips.set_text(
            _(
                i18n_keys.CONTENT__SIGN_TRANSACTIONS_WITH_ONE_CLICK_ONLY_EVM_NETWORK_AND_SOLANA
            )
        )

        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.turbo_mode.add_event_cb(
            self.on_value_changed, lv.EVENT.VALUE_CHANGED, None
        )

        self.load_screen(self)
        gc.collect()

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.turbo_mode.switch:
                if not storage_device.is_turbomode_enabled():
                    TurboModeConfirm(self, True)
                    self.turbo_mode.add_state()
                else:
                    self.turbo_mode.clear_state()
                    storage_device.set_turbomode_enable(False)

    def reset_switch(self):
        self.turbo_mode.clear_state()


class TurboModeConfirm(FullSizeWindow):
    def __init__(self, callback_obj, enable=False):
        if enable:
            super().__init__(
                title=_(i18n_keys.TITLE__ENABLE_TURBO_MODE),
                subtitle=_(i18n_keys.CONTENT__SIGN_TRANSACTIONS_WITH_ONE_CLICK),
                confirm_text=_(i18n_keys.ACTION__SLIDE_TO_ENABLE),
                cancel_text=_(i18n_keys.BUTTON__CANCEL),
                hold_confirm=True,
            )
            self.container = ContainerFlexCol(
                self.content_area, self.subtitle, padding_row=2
            )
            self.item1 = ListItemWithLeadingCheckbox(
                self.container,
                _(
                    i18n_keys.ACTION__ONCE_ENABLED_THE_DEVICE_WILL_OMIT_DETAILS_WHEN_REVIEWING_TRANSACTIONS_I_KNOW_THE_RISKS
                ),
                radius=40,
            )

            self.enable = enable
            self.callback_obj = callback_obj

        self.slider_enable(False)
        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)

    def eventhandler(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.btn_no.click_mask:
                self.callback_obj.reset_switch()
                self.destroy(200)
        elif code == lv.EVENT.READY and self.hold_confirm:
            if target == self.slider:
                storage_device.set_turbomode_enable(self.enable)
                self.destroy(200)

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.item1.checkbox:
                if target.get_state() & lv.STATE.CHECKED:
                    self.item1.enable_bg_color()
                    self.slider_enable()
                else:
                    self.item1.enable_bg_color(False)
                    self.slider_enable(False)

    def slider_enable(self, enable: bool = True):
        if enable:
            self.slider.add_flag(lv.obj.FLAG.CLICKABLE)
            self.slider.enable()
            self.slider.set_style_bg_color(
                lv_colors.WHITE, lv.PART.KNOB | lv.STATE.DEFAULT
            )
        else:
            self.slider.clear_flag(lv.obj.FLAG.CLICKABLE)
            self.slider.enable(False)


class EthereumSetting(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(prev_scr, title=_(i18n_keys.TITLE__ETHEREUM), nav_back=True)

        self.container = ContainerFlexCol(self, self.title, padding_row=2)
        self.blind_sign = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__BLIND_SIGNING),
            right_text=_(i18n_keys.ITEM__STATUS__OFF),
        )
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.blind_sign:
                BlindSign(self, coin_type=_(i18n_keys.TITLE__ETHEREUM))


class SolanaSetting(Screen):
    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            return
        super().__init__(prev_scr, title=_(i18n_keys.TITLE__SOLANA), nav_back=True)

        self.container = ContainerFlexCol(self, self.title, padding_row=2)
        self.blind_sign = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__BLIND_SIGNING),
            right_text=_(i18n_keys.ITEM__STATUS__OFF),
        )
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.blind_sign:
                BlindSign(self, coin_type=_(i18n_keys.TITLE__SOLANA))


class BlindSign(Screen):
    def __init__(self, prev_scr=None, coin_type: str = _(i18n_keys.TITLE__ETHEREUM)):
        if not hasattr(self, "_init"):
            self._init = True
        else:
            self.coin_type = coin_type
            return
        super().__init__(
            prev_scr, title=_(i18n_keys.TITLE__BLIND_SIGNING), nav_back=True
        )

        self.coin_type = coin_type
        self.container = ContainerFlexCol(self, self.title, padding_row=2)
        self.blind_sign = ListItemBtnWithSwitch(
            self.container, f"{coin_type} Blind Signing"
        )
        self.blind_sign.clear_state()
        self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
        self.popup = None

    def on_value_changed(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.VALUE_CHANGED:
            if target == self.blind_sign.switch:
                if target.has_state(lv.STATE.CHECKED):
                    from .components.popup import Popup

                    self.popup = Popup(
                        self,
                        _(i18n_keys.TITLE__ENABLE_STR_BLIND_SIGNING).format(
                            self.coin_type
                        ),
                        _(i18n_keys.SUBTITLE_SETTING_CRYPTO_BLIND_SIGN_ENABLED),
                        icon_path="A:/res/warning.png",
                        btn_text=_(i18n_keys.BUTTON__ENABLE),
                    )
                else:
                    pass


class UserGuide(AnimScreen):
    def collect_animation_targets(self) -> list:
        if lv.scr_act() == MainScreen._instance:
            return []
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            self.from_appdrawer = True
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.APP__USER_GUIDE),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            if not self.is_visible():
                self._load_scr(self, lv.scr_act() != self)
            self.from_appdrawer = False
            self.refresh_text()
            return

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.base_tutorial = ListItemBtn(
            self.container, _(i18n_keys.ITEM__BASIC_TUTORIAL)
        )
        self.security_protection = ListItemBtn(
            self.container, _(i18n_keys.ITEM__SECURITY_PROTECTION)
        )
        self.need_help = ListItemBtn(self.container, _(i18n_keys.ITEM__NEED_HELP))
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)

    def refresh_text(self):
        self.title.set_text(_(i18n_keys.APP__USER_GUIDE))
        self.base_tutorial.label_left.set_text(_(i18n_keys.ITEM__BASIC_TUTORIAL))
        self.security_protection.label_left.set_text(
            _(i18n_keys.ITEM__SECURITY_PROTECTION)
        )
        self.need_help.label_left.set_text(_(i18n_keys.ITEM__NEED_HELP))

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.base_tutorial:
                BaseTutorial(self)
            elif target == self.security_protection:
                SecurityProtection(self)
            elif target == self.need_help:
                HelpDetails()
            else:
                if __debug__:
                    print("Unknown")

    def _load_scr(self, scr: "AnimScreen", back: bool = False) -> None:
        if self.from_appdrawer:
            scr.set_pos(0, 0)
            lv.scr_load(scr)
        else:
            super()._load_scr(scr, back)


class BaseTutorial(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            self.from_appdrawer = True
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.APP__USER_GUIDE),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            self.from_appdrawer = False
            self.refresh_text()
            return

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.app_tutorial = ListItemBtn(
            self.container, _(i18n_keys.ITEM__ONEKEY_APP_TUTORIAL)
        )
        self.power_off = ListItemBtn(
            self.container,
            _(i18n_keys.TITLE__POWER_ON_OFF__GUIDE),
        )
        self.recovery_phrase = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__WHAT_IS_RECOVERY_PHRASE),
        )
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)
        gc.collect()

    def refresh_text(self):
        self.title.set_text(_(i18n_keys.APP__USER_GUIDE))
        self.app_tutorial.label_left.set_text(_(i18n_keys.ITEM__ONEKEY_APP_TUTORIAL))
        self.power_off.label_left.set_text(_(i18n_keys.TITLE__POWER_ON_OFF__GUIDE))
        self.recovery_phrase.label_left.set_text(
            _(i18n_keys.ITEM__WHAT_IS_RECOVERY_PHRASE)
        )

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.app_tutorial:
                from trezor.lvglui.scrs import app_guide

                app_guide.GuideAppDownload()
            elif target == self.power_off:
                PowerOnOffDetails()
            elif target == self.recovery_phrase:
                RecoveryPhraseDetails()
            else:
                if __debug__:
                    print("Unknown")


class SecurityProtection(AnimScreen):
    def collect_animation_targets(self) -> list:
        targets = []
        if hasattr(self, "container") and self.container:
            targets.append(self.container)
        return targets

    def __init__(self, prev_scr=None):
        if not hasattr(self, "_init"):
            self._init = True
            self.from_appdrawer = True
            kwargs = {
                "prev_scr": prev_scr,
                "title": _(i18n_keys.APP__USER_GUIDE),
                "nav_back": True,
            }
            super().__init__(**kwargs)
        else:
            self.from_appdrawer = False
            self.refresh_text()
            return

        self.container = ContainerFlexCol(self.content_area, self.title, padding_row=2)
        self.pin_protection = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__ENABLE_PIN_PROTECTION),
        )
        self.fingerprint = ListItemBtn(
            self.container,
            _(i18n_keys.TITLE__FINGERPRINT),
        )
        self.hardware_wallet = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__HOW_HARDWARE_WALLET_WORKS),
        )
        self.passphrase = ListItemBtn(
            self.container,
            _(i18n_keys.ITEM__PASSPHRASE_ACCESS_HIDDEN_WALLETS),
        )
        self.attach_to_pin = ListItemBtn(
            self.container, _(i18n_keys.PASSPHRASE__ATTACH_TO_PIN)
        )
        self.passkeys = ListItemBtn(
            self.container,
            _(i18n_keys.FIDO_FIDO_KEYS_LABEL),
        )
        self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.load_screen(self)

    def refresh_text(self):
        self.title.set_text(_(i18n_keys.APP__USER_GUIDE))
        self.pin_protection.label_left.set_text(
            _(i18n_keys.ITEM__ENABLE_PIN_PROTECTION)
        )
        self.fingerprint.label_left.set_text(_(i18n_keys.TITLE__FINGERPRINT))
        self.hardware_wallet.label_left.set_text(
            _(i18n_keys.ITEM__HOW_HARDWARE_WALLET_WORKS)
        )
        self.passphrase.label_left.set_text(
            _(i18n_keys.ITEM__PASSPHRASE_ACCESS_HIDDEN_WALLETS)
        )
        self.attach_to_pin.label_left.set_text(_(i18n_keys.PASSPHRASE__ATTACH_TO_PIN))
        self.passkeys.label_left.set_text(_(i18n_keys.FIDO_FIDO_KEYS_LABEL))

    def on_click(self, event_obj):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.pin_protection:
                PinProtectionDetails()
            elif target == self.hardware_wallet:
                HardwareWalletDetails()
            elif target == self.passphrase:
                PassphraseDetails()
            elif target == self.fingerprint:
                FingerprintDetails()
            elif target == self.attach_to_pin:
                AttachToPinDetails()
            elif target == self.passkeys:
                from .app_passkeys import PasskeysRegister

                PasskeysRegister()
            else:
                if __debug__:
                    print("Unknown")


class AttachToPinDetails(FullSizeWindow):
    def __init__(self):
        super().__init__(
            None,
            None,
            cancel_text=_(i18n_keys.BUTTON__CLOSE),
            icon_path="A:/res/attach-to-pin-guide.png",
        )
        self.container = ContainerFlexCol(self.content_area, self.icon, pos=(0, 24))
        self.item = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.PASSPHRASE__ATTACH_TO_PIN),
            _(i18n_keys.ITEM__ATTACH_TO_PIN_DESC),
        )
        self.item.label_top.set_style_text_color(lv_colors.WHITE, 0)
        self.item.label.set_style_text_color(lv_colors.WHITE_2, 0)
        self.item.label.align_to(self.item.label_top, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)
        self.item.label.set_long_mode(lv.label.LONG.WRAP)


class PowerOnOffDetails(FullSizeWindow):
    def __init__(self):
        super().__init__(
            None,
            None,
            cancel_text=_(i18n_keys.BUTTON__CLOSE),
            icon_path="A:/res/power-on-off.png",
        )
        self.container = ContainerFlexCol(self.content_area, self.icon, pos=(0, 24))
        self.item = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.TITLE__POWER_ON_OFF__GUIDE),
            _(i18n_keys.SUBTITLE__POWER_ON_OFF__GUIDE),
        )
        self.item.label_top.set_style_text_color(lv_colors.WHITE, 0)
        self.item.label.set_style_text_color(lv_colors.WHITE_2, 0)
        self.item.label.set_long_mode(lv.label.LONG.WRAP)

    # def destroy(self, _delay):
    #     return self.delete()


class RecoveryPhraseDetails(FullSizeWindow):
    def __init__(self):
        super().__init__(
            None,
            None,
            cancel_text=_(i18n_keys.BUTTON__CLOSE),
            icon_path="A:/res/recovery-phrase.png",
        )
        self.container = ContainerFlexCol(self.content_area, self.icon, pos=(0, 24))
        self.item = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.TITLE__WHAT_IS_RECOVERY_PHRASE__GUIDE),
            _(i18n_keys.SUBTITLE__WHAT_IS_RECOVERY_PHRASE__GUIDE),
        )
        self.item.label_top.set_style_text_color(lv_colors.WHITE, 0)
        self.item.label.set_style_text_color(lv_colors.WHITE_2, 0)
        self.item.label.align_to(self.item.label_top, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)
        self.item.label.set_long_mode(lv.label.LONG.WRAP)

    # def destroy(self, _delay):
    #     return self.delete()


class PinProtectionDetails(FullSizeWindow):
    def __init__(self):
        super().__init__(
            None,
            None,
            cancel_text=_(i18n_keys.BUTTON__CLOSE),
            icon_path="A:/res/pin-protection.png",
        )
        self.container = ContainerFlexCol(self.content_area, self.icon, pos=(0, 24))
        self.item = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.TITLE__ENABLE_PIN_PROTECTION__GUIDE),
            _(i18n_keys.SUBTITLE__ENABLE_PIN_PROTECTION__GUIDE),
        )
        self.item.label_top.set_style_text_color(lv_colors.WHITE, 0)
        self.item.label.set_style_text_color(lv_colors.WHITE_2, 0)
        self.item.label.align_to(self.item.label_top, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)
        self.item.label.set_long_mode(lv.label.LONG.WRAP)

    # def destroy(self, _delay):
    #     return self.delete()


class FingerprintDetails(FullSizeWindow):
    def __init__(self):
        super().__init__(
            None,
            None,
            cancel_text=_(i18n_keys.BUTTON__CLOSE),
            icon_path="A:/res/power-on-off.png",
        )
        self.container = ContainerFlexCol(self.content_area, self.icon, pos=(0, 24))
        self.item = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.TITLE__FINGERPRINT),
            _(
                i18n_keys.CONTENT__AFTER_SETTING_UP_FINGERPRINT_YOU_CAN_USE_IT_TO_UNLOCK_THE_DEVICE
            ),
        )
        self.item.label_top.set_style_text_color(lv_colors.WHITE, 0)
        self.item.label.set_style_text_color(lv_colors.WHITE_2, 0)
        self.item.label.set_long_mode(lv.label.LONG.WRAP)


class HardwareWalletDetails(FullSizeWindow):
    def __init__(self):
        super().__init__(
            None,
            None,
            cancel_text=_(i18n_keys.BUTTON__CLOSE),
            icon_path="A:/res/hardware-wallet-works-way.png",
        )
        self.container = ContainerFlexCol(self.content_area, self.icon, pos=(0, 24))
        self.item = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.TITLE__HOW_HARDWARE_WALLET_WORKS__GUIDE),
            _(i18n_keys.SUBTITLE__HOW_HARDWARE_WALLET_WORKS__GUIDE),
        )
        self.item.label_top.set_style_text_color(lv_colors.WHITE, 0)
        self.item.label.set_style_text_color(lv_colors.WHITE_2, 0)
        self.item.label.align_to(self.item.label_top, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)
        self.item.label.set_long_mode(lv.label.LONG.WRAP)

    # def destroy(self, _delay):
    #     return self.delete()


class PassphraseDetails(FullSizeWindow):
    def __init__(self):
        super().__init__(
            None,
            None,
            cancel_text=_(i18n_keys.BUTTON__CLOSE),
            icon_path="A:/res/hidden-wallet.png",
        )
        self.container = ContainerFlexCol(self.content_area, self.icon, pos=(0, 24))
        self.item = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.TITLE__ACCESS_HIDDEN_WALLET),
            _(i18n_keys.SUBTITLE__PASSPHRASE_ACCESS_HIDDEN_WALLETS__GUIDE),
        )
        self.item.label_top.set_style_text_color(lv_colors.WHITE, 0)
        self.item.label.set_style_text_color(lv_colors.WHITE_2, 0)
        self.item.label.align_to(self.item.label_top, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)
        self.item.label.set_long_mode(lv.label.LONG.WRAP)

    # def destroy(self, _delay):
    #     return self.delete()


class HelpDetails(FullSizeWindow):
    def __init__(self):
        super().__init__(
            None,
            None,
            cancel_text=_(i18n_keys.BUTTON__CLOSE),
            icon_path="A:/res/onekey-help.png",
        )
        self.container = ContainerFlexCol(self.content_area, self.icon, pos=(0, 24))
        self.item = DisplayItemWithFont_30(
            self.container,
            _(i18n_keys.TITLE__NEED_HELP__GUIDE),
            _(i18n_keys.SUBTITLE__NEED_HELP__GUIDE),
        )
        self.item.label_top.set_style_text_color(lv_colors.WHITE, 0)
        self.item.label.set_style_text_color(lv_colors.WHITE_2, 0)
        self.item.label.set_long_mode(lv.label.LONG.WRAP)
        self.item.label.align_to(self.item.label_top, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 16)

        self.website = lv.label(self.item)
        self.website.set_style_text_font(font_GeistRegular30, 0)
        self.website.set_style_text_color(lv_colors.WHITE_2, 0)
        self.website.set_style_text_line_space(3, 0)
        self.website.set_style_text_letter_space(-1, 0)
        self.website.set_text("help.onekey.so/hc")
        self.website.align_to(self.item.label, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 0)
        self.underline = lv.line(self.item)
        self.underline.set_points(
            [
                {"x": 0, "y": 2},
                {"x": 245, "y": 2},
            ],
            2,
        )
        self.underline.set_style_line_color(lv_colors.WHITE_2, 0)
        self.underline.align_to(self.website, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 0)

    # def destroy(self, _delay):
    #     return self.delete()
