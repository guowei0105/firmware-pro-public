from storage import device
from trezor import ui, utils
from trezor.lvglui.i18n import gettext as _, keys as i18n_keys

from . import font_GeistRegular26
from .common import Screen, lv, lv_colors
from .components.doubleclick import DoubleClickDetector
from .widgets.style import StyleWrapper

ANIM_TIME = 20
ANIM_PLAYBACK_TIME = 20
ANIM_PLAYBACK_DELAY = 5


class LockScreen(Screen):
    _lock_count = 0  # Class variable to track number of times LockScreen is instantiated

    def _ensure_background_style(self):
        if not hasattr(self, "_background_style"):
            self._background_style = StyleWrapper().bg_img_opa(lv.OPA._40).border_width(0)
            self.add_style(self._background_style, 0)
        return self._background_style

    def set_background_image(self, image_src: str) -> None:
        style = self._ensure_background_style()
        style.bg_img_src(image_src)
        try:
            self.invalidate()
        except Exception:
            pass

    @classmethod
    def retrieval(cls) -> tuple[bool, "LockScreen" | None]:
        try:
            if cls._instance.is_visible():
                return True, cls._instance
        except Exception:
            pass
        return False, None

    def __init__(self, device_name, ble_name="", dev_state=None):
        import gc

        # Increment lock counter for tracking
        LockScreen._lock_count += 1
        current_count = LockScreen._lock_count

        # Memory tracking at start
        mem_free_start = gc.mem_free()
        mem_alloc_start = gc.mem_alloc()

        lockscreen = device.get_homescreen()
        show_device_names = device.is_device_name_display_enabled()

        if not hasattr(self, "_init"):

            self._init = True

            # ✓ CRITICAL FIX: Reuse saved DoubleClickDetector from class level if available
            # This prevents memory leak caused by LVGL destroying screen objects during screen switching
            if hasattr(LockScreen, '_saved_double_click'):
                self.double_click = LockScreen._saved_double_click
                del LockScreen._saved_double_click
            else:
                self.double_click = DoubleClickDetector(click_timeout=800, click_dist=50)

            super().__init__(title=device_name, subtitle=ble_name)
            if hasattr(self, "title") and self.title:
                self.title.add_style(
                    StyleWrapper()
                    .text_align_center()
                    .text_opa(int(lv.OPA.COVER * 0.85)),
                    0,
                )
                if not show_device_names:
                    self.title.set_text("")
                    self.title.add_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self, "subtitle") and self.subtitle:
                self.subtitle.add_style(
                    StyleWrapper()
                    .text_align_center()
                    .text_color(lv_colors.WHITE)
                    .text_opa(int(lv.OPA.COVER * 0.85)),
                    0,
                )
                if not show_device_names:
                    self.subtitle.set_text("")
                    self.subtitle.add_flag(lv.obj.FLAG.HIDDEN)
        else:
            self.set_background_image(lockscreen)
            if hasattr(self, "title") and self.title:
                if show_device_names:
                    self.title.set_text(device_name)
                    self.title.clear_flag(lv.obj.FLAG.HIDDEN)
                else:
                    self.title.set_text("")
                    self.title.add_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self, "subtitle") and self.subtitle:
                if show_device_names:
                    self.subtitle.set_text(ble_name)
                    self.subtitle.clear_flag(lv.obj.FLAG.HIDDEN)
                else:
                    self.subtitle.set_text("")
                    self.subtitle.add_flag(lv.obj.FLAG.HIDDEN)
            self.show_tips()

            # Force GC after reuse to clean up any temporary objects
            gc.collect()

            mem_free_end = gc.mem_free()
            mem_diff = mem_free_end - mem_free_start

            return
        self.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        if hasattr(self, "title") and self.title:
            self.title.align_to(self.content_area, lv.ALIGN.TOP_MID, 0, 76)
        if hasattr(self, "subtitle") and self.subtitle:
            self.subtitle.align_to(self.title, lv.ALIGN.OUT_BOTTOM_MID, 0, 16)
        self.set_background_image(lockscreen)
        self.tap_tip = lv.label(self.content_area)
        self.tap_tip.set_long_mode(lv.label.LONG.WRAP)
        self.show_tips()
        self.lock_state = lv.img(self.content_area)
        self.lock_state.set_src("A:/res/lock.png")
        self.lock_state.set_style_img_opa(int(lv.OPA.COVER * 0.85), 0)
        self.lock_state.align_to(self.tap_tip, lv.ALIGN.OUT_TOP_MID, 0, -16)
        self.add_event_cb(self.on_slide_up, lv.EVENT.GESTURE, None)

        # Force GC after full initialization
        gc.collect()

        mem_free_end = gc.mem_free()
        mem_diff = mem_free_end - mem_free_start

    def show_tips(self, level: int = 0):
        if level:
            if level == 1:
                text = _(i18n_keys.MSG__FINGERPRINT_NOT_RECOGNIZED_TRY_AGAIN)
                self.tap_tip.set_text(text)
            elif level == 2:
                text = _(
                    i18n_keys.MSG__YOUR_PIN_CODE_REQUIRED_TO_ENABLE_FINGERPRINT_UNLOCK
                )
                self.tap_tip.set_text(text)
            elif level == 3:
                text = _(i18n_keys.MSG__PUT_FINGER_ON_THE_FINGERPRINT)
                self.tap_tip.set_text(text)
            elif level == 4:
                text = _(i18n_keys.MSG__CLEAN_FINGERPRINT_SENSOR_AND_TRY_AGAIN)
                self.tap_tip.set_text(text)
            if hasattr(self, "lock_state"):
                self.lock_state.align_to(self.tap_tip, lv.ALIGN.OUT_TOP_MID, 0, -16)
        else:
            from trezor.lvglui.scrs import fingerprints

            if fingerprints.is_available():
                self.tap_tip.set_text(
                    _(i18n_keys.MSG__USE_FINGERPRINT_OR_TAP_TO_UNLOCK)
                )
                # self._show_fingerprint_prompt_if_necessary()
            else:
                self.tap_tip.set_text(_(i18n_keys.LOCKED_TEXT__TAP_TO_UNLOCK))

        self.tap_tip.set_size(456, lv.SIZE.CONTENT)
        self.tap_tip.align(lv.ALIGN.BOTTOM_MID, 0, 0)
        self.tap_tip.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .text_letter_space(-1)
            .max_width(456)
            .text_align_center()
            .text_opa(int(lv.OPA.COVER * 0.85)),
            0,
        )

    def show_finger_mismatch_anim(self):
        # ✓ FIX: Clean up old animation objects before creating new ones
        # This prevents memory leak from accumulating animation objects
        if hasattr(self, 'anim_right'):
            try:
                del self.anim_right
            except Exception:
                pass
        if hasattr(self, 'anim_left'):
            try:
                del self.anim_left
            except Exception:
                pass

        self.anim_right = lv.anim_t()
        self.anim_right.init()
        self.anim_right.set_var(self.lock_state)
        self.anim_right.set_values(220, 230)
        self.anim_right.set_time(ANIM_TIME)
        self.anim_right.set_playback_delay(ANIM_PLAYBACK_DELAY)
        self.anim_right.set_playback_time(ANIM_PLAYBACK_TIME)
        self.anim_right.set_repeat_delay(5)
        self.anim_right.set_repeat_count(1)
        self.anim_right.set_path_cb(lv.anim_t.path_ease_in)
        self.anim_right.set_custom_exec_cb(lambda _a, val: self.anim_set_x(val))

        self.anim_left = lv.anim_t()
        self.anim_left.init()
        self.anim_left.set_var(self.lock_state)
        self.anim_left.set_values(220, 210)
        self.anim_left.set_time(ANIM_TIME)
        self.anim_left.set_playback_delay(ANIM_PLAYBACK_DELAY)
        self.anim_left.set_playback_time(ANIM_PLAYBACK_TIME)
        self.anim_left.set_repeat_delay(5)
        self.anim_left.set_repeat_count(1)
        self.anim_left.set_path_cb(lv.anim_t.path_ease_in)
        self.anim_left.set_custom_exec_cb(lambda _a, val: self.anim_set_x(val))
        self.anim_left.set_deleted_cb(lambda _a: lv.anim_t.start(self.anim_right))

        lv.anim_t.start(self.anim_left)

    def anim_set_x(self, x):
        try:
            self.lock_state.set_x(x)
        except Exception:
            pass

    def _show_fingerprint_prompt_if_necessary(self):
        if device.has_prompted_fingerprint():
            if hasattr(self, "fingerprint_prompt"):
                self.fingerprint_prompt.delete()
            return
        self.fingerprint_prompt = lv.img(self.content_area)
        self.fingerprint_prompt.set_src("A:/res/fingerprint-prompt.png")
        self.fingerprint_prompt.set_pos(424, 28)
        device.set_fingerprint_prompted()

    def eventhandler(self, event_obj: lv.event_t):
        code = event_obj.code
        if code == lv.EVENT.CLICKED:
            if self.channel.takers:
                self.channel.publish("clicked")
            else:
                if not ui.display.backlight():
                    if not device.is_tap_awake_enabled():
                        return
                    else:
                        indev = lv.indev_get_act()
                        point = lv.point_t()
                        indev.get_point(point)
                        is_double = self.double_click.handle_click(point)
                        if not is_double:
                            return

                if utils.turn_on_lcd_if_possible():
                    return
                from trezor import workflow
                from apps.base import unlock_device
                import storage.cache

                workflow.spawn(unlock_device())
                storage.cache.start_session()

    def on_slide_up(self, event_obj: lv.event_t):
        code = event_obj.code
        if code == lv.EVENT.GESTURE:
            _dir = lv.indev_get_act().get_gesture_dir()
            if _dir == lv.DIR.TOP:
                if not ui.display.backlight():
                    return
                from trezor import workflow
                from apps.base import unlock_device
                import storage.cache

                workflow.spawn(unlock_device())
                storage.cache.start_session()

    def _load_scr(self, scr: "Screen", back: bool = False) -> None:
        lv.scr_load(scr)
