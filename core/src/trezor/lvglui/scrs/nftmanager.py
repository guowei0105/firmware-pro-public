import ujson as json
import math
from typing import Callable, Dict, TYPE_CHECKING

import storage.device as storage_device
from trezor import io as trezor_io, uart, utils, workflow
from trezor.lvglui.i18n import gettext as _, keys as i18n_keys
from trezor.lvglui.lv_colors import lv_colors

from . import (
    font_GeistRegular20,
    font_GeistRegular26,
    font_GeistRegular30,
    font_GeistSemiBold38,
    font_GeistSemiBold48,
)
from .common import AnimScreen, FullSizeWindow, Screen, lv
from .components.banner import LEVEL, Banner
from .components.button import NormalButton
from .components.container import ContainerGrid
from .components.listitem import ImgGridItem
from .widgets.style import StyleWrapper

if TYPE_CHECKING:
    from .homescreen import MainScreen


def _style_cache() -> Dict[str, StyleWrapper]:
    from . import homescreen as homescreen_module

    return homescreen_module._cached_styles


def _cached_style(name: str, factory: Callable[[], StyleWrapper]) -> StyleWrapper:
    cache = _style_cache()
    if name not in cache:
        cache[name] = factory()
    return cache[name]


def _safe_wallpaper_src(path: str | None, context: str = "") -> str:
    from . import homescreen as homescreen_module

    return homescreen_module._lvgl_safe_wallpaper_src(path, context)


def _get_main_screen_cls():
    from .homescreen import MainScreen

    return MainScreen


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

            # Keep right scrollbar but remove bottom scrollbar
            self.content_area.set_scroll_dir(lv.DIR.VER)
            self.content_area.set_width(480)
            self.content_area.clear_flag(lv.obj.FLAG.SCROLL_CHAIN)
            self.content_area.clear_flag(lv.obj.FLAG.SCROLL_MOMENTUM)
            self.content_area.clear_flag(lv.obj.FLAG.SCROLL_ELASTIC)
        else:
            if hasattr(self, "overview") and self.overview:
                self.overview.delete()
            if hasattr(self, "container") and self.container:
                self.container.delete()

        nft_counts = 0
        file_name_list = []
        if not utils.EMULATOR:
            for size, _attrs, name in trezor_io.fatfs.listdir("1:/res/nfts/zooms"):
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
            # Use zero horizontal padding to keep the gallery within the viewport and avoid horizontal scrollbar.
            self.container = ContainerGrid(
                self.content_area,
                row_dsc=row_dsc,
                col_dsc=col_dsc,
                align_base=self.title,
                pos=(0, 74),
                pad_gap=4,
                pad_hor=0,
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
                        style_type="nft",  # Use NFT style - no clipping, full image display
                    )
                    self.nfts.append(current_nft)

            self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)

    def on_nav_back(self, event_obj):
        """Disable swipe-back gesture while keeping the back button active."""
        return

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
                    with trezor_io.fatfs.open(desc_file_path, "r") as f:
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
            title=_(i18n_keys.TITLE__WALLPAPER),
            nav_back=True,
        )
        self.nft_config = nft_config

        # Disable horizontal scrolling and keep only the vertical scrollbar.
        self.content_area.set_scroll_dir(lv.DIR.VER)
        self.content_area.set_width(480)
        self.content_area.clear_flag(lv.obj.FLAG.SCROLL_CHAIN)
        self.content_area.clear_flag(lv.obj.FLAG.SCROLL_MOMENTUM)
        self.content_area.clear_flag(lv.obj.FLAG.SCROLL_ELASTIC)

        # Add trash icon to title bar (right side)
        self.trash_icon = lv.imgbtn(self.content_area)
        self.trash_icon.set_src(
            lv.imgbtn.STATE.RELEASED, "A:/res/btn-del-white.png", None, None
        )
        self.trash_icon.set_size(40, 40)
        self.trash_icon.align(lv.ALIGN.TOP_RIGHT, -16, 60)
        self.trash_icon.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP).border_width(0), 0
        )
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
            .text_align(lv.TEXT_ALIGN.LEFT),
            0,
        )
        self.nft_title.align_to(self.nft_image, lv.ALIGN.OUT_BOTTOM_LEFT, 12, 12)

        # Description text below title
        self.nft_description = lv.label(self.content_area)
        self.nft_description.set_text(
            nft_config["subheader"] or "Type description here."
        )
        self.nft_description.set_long_mode(lv.label.LONG.WRAP)  # Enable text wrapping
        self.nft_description.set_size(
            456, lv.SIZE.CONTENT
        )  # Max width 456px, auto height
        self.nft_description.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular30)
            .text_color(lv_colors.WHITE_2)
            .text_align(lv.TEXT_ALIGN.LEFT),
            0,
        )
        self.nft_description.align_to(self.nft_title, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 8)

        # Set as Lock Screen button (purple) - height 98px as requested
        self.btn_lock_screen = NormalButton(self.content_area)
        self.btn_lock_screen.set_size(456, 98)
        self.btn_lock_screen.enable(lv_colors.ONEKEY_PURPLE, lv_colors.WHITE)
        self.btn_lock_screen.label.set_text(
            _(i18n_keys.BUTTON__SET_AS_LOCK_SCREEN)
        )
        self.btn_lock_screen.align_to(
            self.nft_description, lv.ALIGN.OUT_BOTTOM_LEFT, -8, 32
        )

        # Set as Home Screen button (gray) - height 98px as requested
        self.btn_home_screen = NormalButton(self.content_area)
        self.btn_home_screen.set_size(456, 98)
        self.btn_home_screen.enable(lv_colors.GRAY_1, lv_colors.WHITE)
        self.btn_home_screen.label.set_text(
            _(i18n_keys.BUTTON__SET_AS_HOME_SCREEN)
        )
        self.btn_home_screen.align_to(
            self.btn_lock_screen, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 8
        )

    def del_callback(self):
        trezor_io.fatfs.unlink(self.zoom_path[2:])
        trezor_io.fatfs.unlink(self.img_path[2:])
        trezor_io.fatfs.unlink(
            "1:/res/nfts/desc/" + self.file_name.split(".")[0] + ".json"
        )

        try:
            replacement_path = "A:/res/wallpaper-7.jpg"
            deleted_name = self.img_path.split("/")[-1]

            current_home = storage_device.get_appdrawer_background()
            current_lock = storage_device.get_homescreen()

            if current_home and (
                current_home == self.img_path or current_home.endswith("/" + deleted_name)
            ):
                storage_device.set_appdrawer_background(replacement_path)

            if current_lock and (
                current_lock == self.img_path or current_lock.endswith("/" + deleted_name)
            ):
                storage_device.set_homescreen(replacement_path)

            try:
                from .homescreen import _last_jpeg_loaded  # type: ignore
            except Exception:
                pass
            else:
                try:
                    import trezor.lvglui.scrs.homescreen as hs_mod
                    hs_mod._last_jpeg_loaded = None
                except Exception:
                    pass
        except Exception:
            pass

        self.load_screen(self.prev_scr, destroy_self=True)

    def on_nav_back(self, event_obj):
        """Disable swipe gesture navigation while keeping back button functional."""
        return

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
            title=_(i18n_keys.TITLE__PREVIEW),
            nav_back=True,
            rti_path="A:/res/checkmark.png",
        )
        self.nft_path = nft_path
        self.nft_config = nft_config

        # Disable scrollbars on content_area (inherited from AnimScreen)
        self.content_area.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.content_area.clear_flag(lv.obj.FLAG.SCROLLABLE)
        # Remove bottom padding to prevent content overflow (800 - 24 = 776 vs container 800)
        self.content_area.set_style_pad_bottom(0, 0)

        # Main container for the screen
        self.container = lv.obj(self.content_area)
        self.container.set_size(lv.pct(100), lv.pct(100))
        self.container.align(lv.ALIGN.TOP_MID, 0, 0)
        self.container.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP).pad_all(0).border_width(0), 0
        )
        self.container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        # Disable scrollbars on the main container
        self.container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.container.clear_flag(lv.obj.FLAG.SCROLLABLE)

        # Lock screen preview container with image - NFT image 118px from top, 344x574 size
        self.preview_container = lv.obj(self.container)
        self.preview_container.set_size(344, 574)
        self.preview_container.align(
            lv.ALIGN.TOP_MID, 0, 118
        )  # 118px from top as requested
        # Use cached style to avoid memory issues during frequent scrolling
        self.preview_container.add_style(
            _cached_style(
                "nft_preview_container",
                lambda: StyleWrapper()
                .bg_opa(lv.OPA.TRANSP)
                .pad_all(0)
                .border_width(0)
                .radius(40)
                .clip_corner(True),
            ),
            0,
        )
        self.preview_container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.preview_container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        self.preview_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.preview_container.clear_flag(lv.obj.FLAG.SCROLLABLE)

        self.preview_container.set_style_bg_color(lv.color_hex(0x000000), 0)
        self.preview_container.set_style_bg_opa(lv.OPA.COVER, 0)

        self.lockscreen_preview = lv.img(self.preview_container)
        self.lockscreen_preview.set_src(nft_path)
        # Use image's natural size, then scale with zoom to fit container
        self.lockscreen_preview.set_size(lv.SIZE.CONTENT, lv.SIZE.CONTENT)
        # Disable scrollbars on the image itself
        self.lockscreen_preview.clear_flag(lv.obj.FLAG.SCROLLABLE)

        base_width, base_height = 480, 800
        zoom_x = int((344 / base_width) * 256)  # Scale to fit width
        zoom_y = int((574 / base_height) * 256)  # Scale to fit height
        zoom = min(zoom_x, zoom_y)  # Use smaller zoom to ensure image fits completely

        self.lockscreen_preview.set_zoom(zoom)
        self.lockscreen_preview.set_antialias(True)  # Enable anti-aliasing for smooth scaling
        self.lockscreen_preview.align(lv.ALIGN.CENTER, 0, 0)

        # Device name and bluetooth name overlaid on the image
        device_name = storage_device.get_label() or "OneKey Pro"
        ble_name = storage_device.get_ble_name() or uart.get_ble_name()

        # Device name label (overlaid on image)
        self.device_name_label = lv.label(self.preview_container)
        self.device_name_label.set_text(device_name)

        # Use cached style to avoid memory issues during frequent scrolling
        self.device_name_label.add_style(
            _cached_style(
                "nft_device_name",
                lambda: StyleWrapper()
                .text_font(font_GeistSemiBold38)
                .text_color(lv_colors.WHITE)
                .text_align(lv.TEXT_ALIGN.CENTER),
            ),
            0,
        )

        self.device_name_label.align_to(self.preview_container, lv.ALIGN.TOP_MID, 0, 49)

        # Bluetooth name label (overlaid on image)
        self.bluetooth_label = lv.label(self.preview_container)
        if ble_name and len(ble_name) >= 4:
            self.bluetooth_label.set_text("Pro " + ble_name[-4:])
        else:
            self.bluetooth_label.set_text("Pro")

        # Use cached style to avoid memory issues during frequent scrolling
        self.bluetooth_label.add_style(
            _cached_style(
                "nft_bluetooth_name",
                lambda: StyleWrapper()
                .text_font(font_GeistRegular26)
                .text_color(lv_colors.WHITE)
                .text_align(lv.TEXT_ALIGN.CENTER),
            ),
            0,
        )

        self.bluetooth_label.align_to(
            self.device_name_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 8
        )

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
                    lockscreen_path = self.nft_path
                    MainScreen = _get_main_screen_cls()

                    try:
                        storage_device.set_homescreen(lockscreen_path)


                        # Force refresh MainScreen background to apply new lockscreen
                        main_screen = None
                        if hasattr(MainScreen, "_instance") and MainScreen._instance:
                            main_screen = MainScreen._instance
                        safe_unlock_path = _safe_wallpaper_src(
                            lockscreen_path, "NftLockScreenPreview.MainScreen"
                        )
                        # Refresh the background with new lockscreen
                        if main_screen:
                            main_screen.add_style(
                                StyleWrapper().bg_img_src(safe_unlock_path),
                                0,
                            )

                            # Also refresh AppDrawer if it exists
                            if hasattr(main_screen, "apps") and main_screen.apps:
                                main_screen.apps.refresh_background()


                        # Force refresh LockScreen if it exists to apply new NFT background
                        try:
                            from .lockscreen import LockScreen

                            if (
                                hasattr(LockScreen, "_instance")
                                and LockScreen._instance
                            ):
                                lock_screen = LockScreen._instance
                                # For NFT lockscreens, try different background image settings
                                style = (
                                    StyleWrapper()
                                    .bg_img_src(
                                        _safe_wallpaper_src(
                                            lockscreen_path,
                                            "NftLockScreenPreview.LockScreen",
                                        )
                                    )
                                    .bg_img_opa(lv.OPA._40)
                                )
                                lock_screen.add_style(style, 0)
                                lock_screen.invalidate()
                        except Exception as e:
                            if __debug__:
                                print(
                                    f"[NftLockScreenPreview] LockScreen refresh error: {e}"
                                )

                    except Exception as e:
                        if __debug__:
                            print(
                                f"[NftLockScreenPreview] Error setting lockscreen: {e}"
                            )

                    main_screen = (
                        MainScreen._instance
                        if hasattr(MainScreen, "_instance") and MainScreen._instance
                        else MainScreen()
                    )
                    self.load_screen(main_screen, destroy_self=True)
                    return


class NftHomeScreenPreview(AnimScreen):
    def __init__(self, prev_scr, nft_path, nft_config):
        super().__init__(
            prev_scr=prev_scr,
            title=_(i18n_keys.TITLE__PREVIEW),
            nav_back=True,
            rti_path="A:/res/checkmark.png",
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

        # Disable scrollbars on content_area (inherited from AnimScreen)
        self.content_area.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.content_area.clear_flag(lv.obj.FLAG.SCROLLABLE)
        # Remove bottom padding to prevent content overflow (800 - 24 = 776 vs container 800)
        self.content_area.set_style_pad_bottom(0, 0)

        # Main container
        self.container = lv.obj(self.content_area)
        self.container.set_size(lv.pct(100), lv.pct(100))
        self.container.align(lv.ALIGN.TOP_MID, 0, 0)
        self.container.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP).pad_all(0).border_width(0), 0
        )
        self.container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        # Disable scrollbars on the main container
        self.container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.container.clear_flag(lv.obj.FLAG.SCROLLABLE)

        # Home screen preview container - NFT image 118px from top, 344x574 size
        self.preview_container = lv.obj(self.container)
        self.preview_container.set_size(344, 574)
        self.preview_container.align(
            lv.ALIGN.TOP_MID, 0, 118
        )  # 118px from top as requested
        # Use cached style to avoid memory issues during frequent scrolling
        self.preview_container.add_style(
            _cached_style(
                "nft_preview_container",
                lambda: StyleWrapper()
                .bg_opa(lv.OPA.TRANSP)
                .pad_all(0)
                .border_width(0)
                .radius(40)
                .clip_corner(True),
            ),
            0,
        )
        self.preview_container.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.preview_container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        self.preview_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.preview_container.clear_flag(lv.obj.FLAG.SCROLLABLE)

        self.preview_container.set_style_bg_color(lv.color_hex(0x000000), 0)
        self.preview_container.set_style_bg_opa(lv.OPA.COVER, 0)

        self.homescreen_preview = lv.img(self.preview_container)
        self.current_wallpaper_path = nft_path
        self.homescreen_preview.set_src(nft_path)
        # Use image's natural size, then scale with zoom to fit container
        self.homescreen_preview.set_size(lv.SIZE.CONTENT, lv.SIZE.CONTENT)
        # Disable scrollbars on the image itself
        self.homescreen_preview.clear_flag(lv.obj.FLAG.SCROLLABLE)
        base_width, base_height = 480, 800
        zoom_x = int((344 / base_width) * 256)  # Scale to fit width
        zoom_y = int((574 / base_height) * 256)  # Scale to fit height
        zoom = min(zoom_x, zoom_y)  # Use smaller zoom to ensure image fits completely

        self.homescreen_preview.set_zoom(zoom)
        self.homescreen_preview.set_antialias(True)  # Enable anti-aliasing for smooth scaling
        self.homescreen_preview.align(lv.ALIGN.CENTER, 0, 0)

        # Add 4 app icons matching AppDrawer desktop layout (2 rows x 2 cols)
        self.app_icons = []
        scale_x = 343.0 / 480.0  # ≈ 0.71458
        scale_y = 572.0 / 800.0  # ≈ 0.715
        offset_x = 0.5
        offset_y = 1.0

        # Desktop icon positions in absolute screen coordinates
        desktop_positions = [
            (64, 164),   # Left-Top
            (272, 164),  # Right-Top
            (64, 442),   # Left-Bottom
            (272, 442),  # Right-Bottom
        ]

        for i in range(4):
            screen_x, screen_y = desktop_positions[i]

            # Map desktop screen coordinates to preview coordinates
            x_pos = int(screen_x * scale_x + offset_x)
            y_pos = int(screen_y * scale_y + offset_y)

            # Create image directly without holder to show natural shape
            icon_img = lv.img(self.preview_container)
            icon_img.set_src("A:/res/icon_example.png")
            # Let image use its natural size
            icon_img.set_size(lv.SIZE.CONTENT, lv.SIZE.CONTENT)
            # Use set_pos for absolute positioning (left-top corner)
            icon_img.set_pos(x_pos, y_pos)
            self.app_icons.append(icon_img)

        # Create only Blur button for NFT HomeScreen preview (no Change button needed)
        self._create_blur_button()

        # Position blur button centered at bottom
        self.blur_button.align_to(
            self.preview_container, lv.ALIGN.OUT_BOTTOM_MID, 0, 10
        )
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

        # Create label - make it clickable to expand click area
        label = lv.label(self.container)
        label.set_text(text)
        label.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular20)
            .text_color(lv_colors.WHITE)
            .text_align(lv.TEXT_ALIGN.CENTER),
            0,
        )
        label.align_to(button, lv.ALIGN.OUT_BOTTOM_MID, 0, 4)
        # Make label clickable so text can also be clicked
        label.add_flag(lv.obj.FLAG.CLICKABLE)
        label.add_event_cb(callback, lv.EVENT.CLICKED, None)

        # Add event callback to button
        button.add_event_cb(callback, lv.EVENT.CLICKED, None)

        return button, icon, label

    def _create_blur_button(self):
        """Create only Blur button like HomeScreenSetting"""
        # Create Blur button with proper icon
        (
            self.blur_button,
            self.blur_button_icon,
            self.blur_label,
        ) = self._create_button_with_label(
            "A:/res/blur_no_selected.png", "Blur", self.on_blur_clicked
        )

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
            with trezor_io.fatfs.open(file_path, "r") as f:
                return True
        except Exception as e:
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

            if getattr(self, "is_blur_active", False):
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
        blur_path = self.nft_path.replace(
            file_name, f"{file_name_without_ext}-blur.jpg"
        )

        if self.is_blur_active:
            # Switch to original
            self.current_wallpaper_path = self.original_wallpaper_path
            self.is_blur_active = False
        else:
            # Switch to blur
            self.current_wallpaper_path = blur_path
            self.is_blur_active = True

        self.homescreen_preview.set_src(self.current_wallpaper_path)
        base_width, base_height = 480, 800
        zoom_x = int((344 / base_width) * 256)
        zoom_y = int((574 / base_height) * 256)
        scale = min(zoom_x, zoom_y)
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
                    MainScreen = _get_main_screen_cls()

                    try:
                        storage_device.set_appdrawer_background(wallpaper_path)
                        # Force refresh MainScreen background to apply new homescreen
                        main_screen = None
                        if hasattr(MainScreen, "_instance") and MainScreen._instance:
                            main_screen = MainScreen._instance
                        if main_screen:
                            # Refresh the background with new homescreen (lockscreen still used for background)
                            lockscreen_path = storage_device.get_homescreen()
                            if lockscreen_path:
                                safe_lock_path = _safe_wallpaper_src(
                                    lockscreen_path,
                                    "NftHomeScreenPreview.MainScreen",
                                )
                                main_screen.add_style(
                                    StyleWrapper().bg_img_src(safe_lock_path),
                                    0,
                                )

                            # Also refresh AppDrawer if it exists
                            if hasattr(main_screen, "apps") and main_screen.apps:
                                main_screen.apps.refresh_background()

                    except Exception as e:
                        if __debug__:
                            print(
                                f"[NftHomeScreenPreview] Error setting homescreen: {e}"
                            )

                    # Navigate back to MainScreen (AppDrawer) after setting homescreen
                    # Find the root MainScreen instance
                    main_screen = (
                        MainScreen._instance
                        if hasattr(MainScreen, "_instance") and MainScreen._instance
                        else MainScreen()
                    )

                    # Use AnimScreen's load_screen method for proper navigation
                    self.load_screen(main_screen, destroy_self=True)
                    return
            else:
                # Handle button clicks for Blur button only
                if hasattr(self, "blur_button") and target == self.blur_button:
                    self.on_blur_clicked(event_obj)
