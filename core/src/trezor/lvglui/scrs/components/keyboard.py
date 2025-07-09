from storage import device
from trezor import motor, utils
from trezor.crypto import bip39, random
from trezor.lvglui.i18n import gettext as _, keys as i18n_keys

from .. import (
    font_GeistMono28,
    font_GeistRegular20,
    font_GeistRegular26,
    font_GeistSemiBold30,
    font_GeistSemiBold38,
    font_GeistSemiBold48,
    lv,
    lv_colors,
)
from ..widgets.style import StyleWrapper
from .transition import BtnClickTransition

# from .transition import DefaultTransition


def compute_mask(text: str) -> int:
    mask = 0
    for c in text:
        shift = ord(c) - 97  # ord('a') == 97
        if shift < 0:
            continue
        mask |= 1 << shift
    return mask


def change_key_bg(
    dsc: lv.obj_draw_part_dsc_t,
    id1: int,
    id2: int,
    enabled: bool,
    all_enabled: bool = True,
    allow_empty: bool = False,
) -> None:
    if dsc.id in (id1, id2):
        dsc.label_dsc.font = font_GeistSemiBold48
    if enabled:
        if dsc.id == id1:
            dsc.rect_dsc.bg_color = lv_colors.ONEKEY_RED_1
        elif dsc.id == id2:
            if all_enabled:
                dsc.rect_dsc.bg_color = lv_colors.ONEKEY_GREEN
                dsc.label_dsc.color = lv_colors.BLACK
            else:
                dsc.rect_dsc.bg_color = lv_colors.ONEKEY_BLACK_1
                dsc.label_dsc.color = lv_colors.ONEKEY_GRAY_1
    else:
        if dsc.id in (id1, id2):
            dsc.rect_dsc.bg_color = lv_colors.ONEKEY_BLACK_1
            if dsc.id == id2:
                dsc.label_dsc.color = (
                    lv_colors.ONEKEY_GRAY_1 if not allow_empty else lv_colors.BLACK
                )


class BIP39Keyboard(lv.keyboard):
    """character keyboard with textarea."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.ta = lv.textarea(parent)
        self.ta.align(lv.ALIGN.TOP_LEFT, 12, 177)
        self.ta.set_size(456, lv.SIZE.CONTENT)
        self.ta.add_style(
            StyleWrapper()
            .border_width(1)
            .border_color(lv_colors.ONEKEY_GRAY_2)
            .radius(40)
            .min_height(288)
            .pad_all(24)
            .bg_color(lv_colors.ONEKEY_BLACK_3)
            .text_font(font_GeistSemiBold48)
            .text_color(lv_colors.WHITE)
            .text_align_left(),
            0,
        )
        self.ta.set_max_length(11)
        self.ta.set_one_line(True)
        self.ta.set_accepted_chars("abcdefghijklmnopqrstuvwxyz")
        self.ta.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.ta.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

        self.remove_style_all()
        self.btnm_map = [
            "q",
            "w",
            "e",
            "r",
            "t",
            "y",
            "u",
            "i",
            "o",
            "p",
            "\n",
            " ",
            "a",
            "s",
            "d",
            "f",
            "g",
            "h",
            "j",
            "k",
            "l",
            " ",
            "\n",
            lv.SYMBOL.BACKSPACE,
            "z",
            "x",
            "c",
            "v",
            "b",
            "n",
            "m",
            lv.SYMBOL.OK,
            "",
        ]
        self.keys = [
            "q",
            "w",
            "e",
            "r",
            "t",
            "y",
            "u",
            "i",
            "o",
            "p",
            "",  # ignore placeholder
            "a",
            "s",
            "d",
            "f",
            "g",
            "h",
            "j",
            "k",
            "l",
            "",  # ignore placeholder
            "",  # ignore backspace
            "z",
            "x",
            "c",
            "v",
            "b",
            "n",
            "m",
            "READY",
        ]
        self.ctrl_map = [
            lv.btnmatrix.CTRL.NO_REPEAT
            | lv.btnmatrix.CTRL.CLICK_TRIG
            | lv.btnmatrix.CTRL.POPOVER
        ] * 10
        self.ctrl_map.append(2 | lv.btnmatrix.CTRL.HIDDEN)
        self.ctrl_map.extend(
            [
                7
                | lv.btnmatrix.CTRL.NO_REPEAT
                | lv.btnmatrix.CTRL.POPOVER
                | lv.btnmatrix.CTRL.CLICK_TRIG
                | lv.btnmatrix.CTRL.POPOVER
            ]
            * 9
        )

        self.ctrl_map.append(2 | lv.btnmatrix.CTRL.HIDDEN)
        self.ctrl_map.extend(
            [4 | lv.btnmatrix.CTRL.DISABLED | lv.btnmatrix.CTRL.CLICK_TRIG]
        )
        self.ctrl_map.extend(
            [
                3
                | lv.btnmatrix.CTRL.NO_REPEAT
                | lv.btnmatrix.CTRL.POPOVER
                | lv.btnmatrix.CTRL.CLICK_TRIG
                | lv.btnmatrix.CTRL.POPOVER
            ]
            * 7
        )
        self.ctrl_map.extend(
            [
                4
                | lv.btnmatrix.CTRL.NO_REPEAT
                | lv.btnmatrix.CTRL.DISABLED
                | lv.btnmatrix.CTRL.CLICK_TRIG
            ]
        )
        self.dummy_ctl_map = []
        self.dummy_ctl_map.extend(self.ctrl_map)
        # delete button
        self.dummy_ctl_map[21] &= self.dummy_ctl_map[21] ^ lv.btnmatrix.CTRL.DISABLED
        self.set_map(lv.keyboard.MODE.TEXT_LOWER, self.btnm_map, self.ctrl_map)
        self.set_mode(lv.keyboard.MODE.TEXT_LOWER)
        self.set_width(lv.pct(100))

        self.add_style(
            StyleWrapper()
            .bg_color(lv_colors.BLACK)
            .pad_gap(2)
            .pad_top(8)
            .pad_bottom(1)
            .height(229),
            0,
        )
        self.add_style(
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK_3)
            .bg_opa()
            .text_font(font_GeistMono28)
            .radius(16),
            lv.PART.ITEMS | lv.STATE.DEFAULT,
        )
        self.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_GRAY_3),
            lv.PART.ITEMS | lv.STATE.PRESSED,
        )
        self.add_style(
            StyleWrapper()
            .bg_grad_color(lv_colors.ONEKEY_BLACK_1)
            .text_color(lv_colors.GRAY_1),
            lv.PART.ITEMS | lv.STATE.DISABLED,
        )
        # self.set_height(229)
        self.align(lv.ALIGN.BOTTOM_MID, 0, 0)
        self.set_popovers(True)
        self.set_textarea(self.ta)
        self.add_event_cb(self.event_cb, lv.EVENT.DRAW_PART_BEGIN, None)
        self.add_event_cb(self.event_cb, lv.EVENT.VALUE_CHANGED, None)
        self.mnemonic_prompt = lv.obj(parent)
        self.mnemonic_prompt.set_size(lv.pct(100), 74)
        self.mnemonic_prompt.align_to(self, lv.ALIGN.OUT_TOP_LEFT, 0, 0)
        self.mnemonic_prompt.add_style(
            StyleWrapper()
            .border_width(0)
            .bg_color(lv_colors.BLACK)
            .pad_hor(1)
            .pad_ver(4)
            .bg_opa()
            .radius(16)
            .pad_column(2),
            0,
        )
        self.mnemonic_prompt.set_flex_flow(lv.FLEX_FLOW.ROW)
        self.mnemonic_prompt.set_flex_align(
            lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.END
        )
        self.mnemonic_prompt.set_scrollbar_mode(lv.SCROLLBAR_MODE.ACTIVE)
        self.mnemonic_prompt.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
        self.move_foreground()

    def tip_submitted(self):
        self.tip_panel = lv.obj(self.parent)
        self.tip_panel.remove_style_all()
        self.tip_panel.set_size(lv.pct(80), lv.SIZE.CONTENT)
        self.tip_img = lv.img(self.tip_panel)
        self.tip_img.set_align(lv.ALIGN.LEFT_MID)
        self.tip_img.set_src("A:/res/feedback-correct.png")
        self.tip = lv.label(self.tip_panel)
        self.tip.set_recolor(True)
        self.tip.align_to(self.tip_img, lv.ALIGN.OUT_RIGHT_MID, 4, 0)
        self.tip_panel.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular26)
            .text_color(lv_colors.ONEKEY_GREEN)
            .text_align_left(),
            0,
        )
        self.tip_panel.align_to(self.ta, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 24)
        self.tip.set_text(f"{_(i18n_keys.MSG__SUBMITTED)}")

    def on_click(self, event_obj):
        target = event_obj.get_target()
        child = target.get_child(0)
        if isinstance(child, lv.label):
            text = child.get_text()
            if text:
                self.ta.set_text(text)
            self.mnemonic_prompt.clean()
            for i, key in enumerate(self.keys):
                if key:
                    self.dummy_ctl_map[i] |= lv.btnmatrix.CTRL.DISABLED
            self.dummy_ctl_map[-1] &= (
                self.dummy_ctl_map[-1] ^ lv.btnmatrix.CTRL.DISABLED
            )
            self.completed = True
            self.set_map(lv.keyboard.MODE.TEXT_LOWER, self.btnm_map, self.dummy_ctl_map)
            lv.event_send(self, lv.EVENT.READY, None)

    def event_cb(self, event):
        if event.code == lv.EVENT.DRAW_PART_BEGIN:
            txt_input = self.ta.get_text()
            dsc = lv.obj_draw_part_dsc_t.__cast__(event.get_param())
            if len(txt_input) > 0:
                change_key_bg(dsc, 21, 29, True, self.completed)
            else:
                change_key_bg(dsc, 21, 29, False)
            # if dsc.id in (10, 20):
            #     dsc.rect_dsc.bg_color = lv_colors.BLACK
        elif event.code == lv.EVENT.VALUE_CHANGED:
            utils.lcd_resume()
            # btn_id = event.target.get_selected_btn()
            # text = event.target.get_btn_text(btn_id)
            # if text == " ":
            #     if btn_id in (10, 21):
            #         event.target.set_selected_btn(btn_id + 1)
            #     return
            motor.vibrate()
            self.mnemonic_prompt.clean()
            txt_input = self.ta.get_text()
            if len(txt_input) > 0:
                words = bip39.complete_word(txt_input) or ""
                mask = bip39.word_completion_mask(txt_input)
                candidates = words.rstrip().split() if words else []
                btn_style_default = (
                    StyleWrapper()
                    .bg_color(lv_colors.ONEKEY_BLACK_3)
                    .bg_opa()
                    .pad_all(16)
                    .radius(16)
                    .text_font(font_GeistSemiBold30)
                    .text_color(lv_colors.WHITE)
                )
                btn_style_pressed = (
                    StyleWrapper()
                    .bg_color(lv_colors.ONEKEY_GRAY_3)
                    .bg_opa()
                    .text_color(lv_colors.WHITE_2)
                    .transform_height(-2)
                    .transform_width(-2)
                    .transition(BtnClickTransition())
                )
                for candidate in candidates:
                    btn = lv.btn(self.mnemonic_prompt)
                    btn.remove_style_all()
                    btn.add_style(btn_style_default, 0)
                    btn.add_style(btn_style_pressed, lv.PART.MAIN | lv.STATE.PRESSED)
                    btn.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
                    label = lv.label(btn)
                    label.set_text(candidate)
                for i, key in enumerate(self.keys):
                    if key and compute_mask(key) & mask:
                        self.dummy_ctl_map[i] &= (
                            self.dummy_ctl_map[i] ^ lv.btnmatrix.CTRL.DISABLED
                        )
                    else:
                        if key:
                            self.dummy_ctl_map[i] |= lv.btnmatrix.CTRL.DISABLED
                if txt_input in candidates:
                    self.dummy_ctl_map[-1] &= (
                        self.dummy_ctl_map[-1] ^ lv.btnmatrix.CTRL.DISABLED
                    )
                    self.completed = True
                else:
                    self.completed = False
                self.set_map(
                    lv.keyboard.MODE.TEXT_LOWER, self.btnm_map, self.dummy_ctl_map
                )
            else:
                self.set_map(lv.keyboard.MODE.TEXT_LOWER, self.btnm_map, self.ctrl_map)


class NumberKeyboard(lv.keyboard):
    """number keyboard with textarea."""

    def __init__(self, parent, max_len: int = 50, min_len: int = 4) -> None:
        super().__init__(parent)
        self.ta = lv.textarea(parent)
        self.ta.align(lv.ALIGN.TOP_MID, 0, 188)

        self.ta.add_style(
            StyleWrapper()
            .bg_color(lv_colors.BLACK)
            .border_width(0)
            .width(lv.SIZE.CONTENT)
            .max_width(432)
            .text_font(font_GeistSemiBold48)
            .text_color(lv_colors.WHITE)
            .text_letter_space(6)
            .text_align_center(),
            0,
        )
        self.ta.set_one_line(True)
        self.ta.set_accepted_chars("0123456789")
        self.ta.set_max_length(max_len)
        self.max_len = max_len
        self.min_len = min_len
        self.ta.set_password_mode(True)
        self.ta.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.ta.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.nums = [i for i in range(10)]
        if device.is_random_pin_map_enabled():
            random.shuffle(self.nums)
        self.btnm_map = [
            str(self.nums[1]),
            str(self.nums[2]),
            str(self.nums[3]),
            "\n",
            str(self.nums[4]),
            str(self.nums[5]),
            str(self.nums[6]),
            "\n",
            str(self.nums[7]),
            str(self.nums[8]),
            str(self.nums[9]),
            "\n",
            lv.SYMBOL.BACKSPACE,
            str(self.nums[0]),
            lv.SYMBOL.OK,
            "",
        ]
        self.dummy_btnm_map = [
            str(self.nums[1]),
            str(self.nums[2]),
            str(self.nums[3]),
            "\n",
            str(self.nums[4]),
            str(self.nums[5]),
            str(self.nums[6]),
            "\n",
            str(self.nums[7]),
            str(self.nums[8]),
            str(self.nums[9]),
            "\n",
            lv.SYMBOL.CLOSE,
            str(self.nums[0]),
            lv.SYMBOL.OK,
            "",
        ]
        self.ctrl_map = [
            lv.btnmatrix.CTRL.NO_REPEAT
            | lv.btnmatrix.CTRL.CLICK_TRIG
            | lv.btnmatrix.CTRL.POPOVER
        ] * 12
        self.ctrl_map[-1] = (
            lv.btnmatrix.CTRL.NO_REPEAT
            | lv.btnmatrix.CTRL.DISABLED
            | lv.btnmatrix.CTRL.CLICK_TRIG
            | lv.btnmatrix.CTRL.POPOVER
        )
        self.set_map(lv.keyboard.MODE.NUMBER, self.dummy_btnm_map, self.ctrl_map)
        self.set_mode(lv.keyboard.MODE.NUMBER)
        self.set_size(lv.pct(100), 472)

        self.add_style(
            StyleWrapper().bg_color(lv_colors.BLACK).pad_hor(4).pad_gap(4), 0
        )
        self.add_style(
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK)
            .radius(40)
            .text_font(font_GeistSemiBold48),
            lv.PART.ITEMS | lv.STATE.DEFAULT,
        )
        self.add_style(StyleWrapper(), 0)
        self.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_GRAY_3)
            # .transform_height(-2)
            # .transform_width(-2)
            # .transition(DefaultTransition())
            ,
            lv.PART.ITEMS | lv.STATE.PRESSED,
        )
        self.add_style(
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK_1)
            .text_color(lv_colors.ONEKEY_GRAY),
            lv.PART.ITEMS | lv.STATE.DISABLED,
        )

        self.set_popovers(True)
        self.align(lv.ALIGN.BOTTOM_MID, 0, -4)
        self.set_textarea(self.ta)

        self.input_count_tips = lv.label(parent)
        self.input_count_tips.align(lv.ALIGN.BOTTOM_MID, 0, -512)
        self.input_count_tips.add_style(
            StyleWrapper()
            .text_font(font_GeistRegular20)
            .text_letter_space(1)
            .text_color(lv_colors.LIGHT_GRAY),
            0,
        )
        self.input_count_tips.add_flag(lv.obj.FLAG.HIDDEN)

        self.add_event_cb(self.event_cb, lv.EVENT.DRAW_PART_BEGIN, None)
        self.add_event_cb(self.event_cb, lv.EVENT.VALUE_CHANGED, None)
        self.add_event_cb(self.event_cb, lv.EVENT.READY, None)
        self.add_event_cb(self.event_cb, lv.EVENT.CANCEL, None)
        self.previous_input_len = 0

    def update_count_tips(self):
        """Update/show tips only when input length larger than 10"""
        input_len = len(self.ta.get_text())
        if input_len >= (self.max_len // 5 if self.max_len != 6 else 0):
            self.input_count_tips.set_text(f"{len(self.ta.get_text())}/{self.max_len}")
            if self.input_count_tips.has_flag(lv.obj.FLAG.HIDDEN):
                self.input_count_tips.clear_flag(lv.obj.FLAG.HIDDEN)
        else:
            if not self.input_count_tips.has_flag(lv.obj.FLAG.HIDDEN):
                self.input_count_tips.add_flag(lv.obj.FLAG.HIDDEN)

    def toggle_number_input_keys(self, enable: bool):
        if enable:
            self.dummy_ctl_map = []
            self.dummy_ctl_map.extend(self.ctrl_map)
            if self.input_len > 3:
                self.dummy_ctl_map[-1] &= (
                    self.dummy_ctl_map[-1] ^ lv.btnmatrix.CTRL.DISABLED
                )
            if self.input_len > 1:
                self.dummy_ctl_map[-3] = (
                    lv.btnmatrix.CTRL.CLICK_TRIG | lv.btnmatrix.CTRL.POPOVER
                )
            else:
                if self.previous_input_len > self.input_len:
                    self.ta.add_flag(lv.obj.FLAG.HIDDEN)
            self.set_map(lv.keyboard.MODE.NUMBER, self.btnm_map, self.dummy_ctl_map)

        else:
            self.dummy_ctl_map = []
            self.dummy_ctl_map.extend(self.ctrl_map)
            for i in range(12):
                if i not in (9, 11):
                    self.dummy_ctl_map[i] |= lv.btnmatrix.CTRL.DISABLED
                elif i == 11:
                    self.dummy_ctl_map[-1] &= (
                        self.dummy_ctl_map[-1] ^ lv.btnmatrix.CTRL.DISABLED
                    )
            self.set_map(lv.keyboard.MODE.NUMBER, self.btnm_map, self.dummy_ctl_map)

    def event_cb(self, event):
        code = event.code
        input_len = len(self.ta.get_text())
        self.input_len = input_len
        self.ta.clear_flag(lv.obj.FLAG.HIDDEN)
        if code == lv.EVENT.DRAW_PART_BEGIN:
            dsc = lv.obj_draw_part_dsc_t.__cast__(event.get_param())
            if input_len >= self.min_len:
                change_key_bg(dsc, 9, 11, True)
            elif input_len > 0:
                change_key_bg(dsc, 9, 11, True, False)
            else:
                change_key_bg(dsc, 9, 11, False)
                if dsc.id == 9:
                    dsc.rect_dsc.bg_color = lv_colors.ONEKEY_RED_1
                    # dsc.rect_dsc.bg_img_src = "A:/res/keyboard-close.png"
        elif code == lv.EVENT.VALUE_CHANGED:
            utils.lcd_resume()
            motor.vibrate()
            # if input_len > 10:
            #     self.ta.set_cursor_pos(lv.TEXTAREA_CURSOR.LAST)
            if input_len >= self.max_len:
                # disable number keys
                self.toggle_number_input_keys(False)
            elif input_len > 0:
                # enable number keys
                self.toggle_number_input_keys(True)
            else:
                self.set_map(
                    lv.keyboard.MODE.NUMBER, self.dummy_btnm_map, self.ctrl_map
                )
            self.update_count_tips()
            self.previous_input_len = input_len
        elif code in (lv.EVENT.READY, lv.EVENT.CANCEL):
            motor.vibrate()


class IndexKeyboard(lv.keyboard):
    """number keyboard with textarea for account index."""

    def __init__(
        self, parent, max_len: int = 50, min_len: int = 4, is_pin: bool = True
    ) -> None:
        super().__init__(parent)
        self.is_pin = is_pin
        self.ta = lv.textarea(parent)
        self.ta.align(lv.ALIGN.TOP_MID, 0, 188)

        self.ta.add_style(
            StyleWrapper()
            .bg_color(lv_colors.BLACK)
            .border_width(0)
            .width(lv.SIZE.CONTENT)
            .max_width(432)
            .text_font(font_GeistSemiBold48)
            .text_color(lv_colors.WHITE)
            .text_letter_space(6)
            .text_align_center(),
            0,
        )
        self.ta.set_one_line(True)
        if self.is_pin:
            self.ta.set_accepted_chars("0123456789")
        else:
            self.ta.set_accepted_chars("#0123456789")
        self.ta.set_max_length(max_len)
        self.max_len = max_len
        self.min_len = min_len
        self.ta.set_password_mode(is_pin)
        self.ta.clear_flag(lv.obj.FLAG.CLICKABLE)
        self.ta.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.nums = [i for i in range(10)]
        if device.is_random_pin_map_enabled():
            random.shuffle(self.nums)
        self.btnm_map = [
            str(self.nums[1]),
            str(self.nums[2]),
            str(self.nums[3]),
            "\n",
            str(self.nums[4]),
            str(self.nums[5]),
            str(self.nums[6]),
            "\n",
            str(self.nums[7]),
            str(self.nums[8]),
            str(self.nums[9]),
            "\n",
            lv.SYMBOL.BACKSPACE,
            str(self.nums[0]),
            lv.SYMBOL.OK,
            "",
        ]
        self.dummy_btnm_map = [
            str(self.nums[1]),
            str(self.nums[2]),
            str(self.nums[3]),
            "\n",
            str(self.nums[4]),
            str(self.nums[5]),
            str(self.nums[6]),
            "\n",
            str(self.nums[7]),
            str(self.nums[8]),
            str(self.nums[9]),
            "\n",
            lv.SYMBOL.CLOSE,
            str(self.nums[0]),
            lv.SYMBOL.OK,
            "",
        ]
        self.ctrl_map = [
            lv.btnmatrix.CTRL.NO_REPEAT
            | lv.btnmatrix.CTRL.CLICK_TRIG
            | lv.btnmatrix.CTRL.POPOVER
        ] * 12
        self.ctrl_map[-1] = (
            lv.btnmatrix.CTRL.NO_REPEAT
            | lv.btnmatrix.CTRL.DISABLED
            | lv.btnmatrix.CTRL.CLICK_TRIG
            | lv.btnmatrix.CTRL.POPOVER
        )
        self.set_map(lv.keyboard.MODE.NUMBER, self.dummy_btnm_map, self.ctrl_map)
        self.set_mode(lv.keyboard.MODE.NUMBER)
        self.set_size(lv.pct(100), 472)

        self.add_style(
            StyleWrapper().bg_color(lv_colors.BLACK).pad_hor(4).pad_gap(4), 0
        )
        self.add_style(
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK)
            .radius(40)
            .text_font(font_GeistSemiBold48),
            lv.PART.ITEMS | lv.STATE.DEFAULT,
        )
        self.add_style(StyleWrapper(), 0)
        self.add_style(
            StyleWrapper().bg_color(lv_colors.ONEKEY_GRAY_3)
            # .transform_height(-2)
            # .transform_width(-2)
            # .transition(DefaultTransition())
            ,
            lv.PART.ITEMS | lv.STATE.PRESSED,
        )
        self.add_style(
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK_1)
            .text_color(lv_colors.ONEKEY_GRAY),
            lv.PART.ITEMS | lv.STATE.DISABLED,
        )

        self.set_popovers(True)
        self.align(lv.ALIGN.BOTTOM_MID, 0, -4)
        self.set_textarea(self.ta)

        # self.input_count_tips = lv.label(parent)
        # self.input_count_tips.align(lv.ALIGN.BOTTOM_MID, 0, -512)
        # self.input_count_tips.add_style(
        #     StyleWrapper()
        #     .text_font(font_GeistRegular20)
        #     .text_letter_space(1)
        #     .text_color(lv_colors.LIGHT_GRAY),
        #     0,
        # )
        # self.input_count_tips.add_flag(lv.obj.FLAG.HIDDEN)

        self.add_event_cb(self.event_cb, lv.EVENT.DRAW_PART_BEGIN, None)
        self.add_event_cb(self.event_cb, lv.EVENT.VALUE_CHANGED, None)
        self.add_event_cb(self.event_cb, lv.EVENT.READY, None)
        self.add_event_cb(self.event_cb, lv.EVENT.CANCEL, None)
        self.previous_input_len = 0

    # def update_count_tips(self):
    #     """Update/show tips only when input length larger than 10"""
    #     input_len = len(self.ta.get_text())
    #     if input_len >= (self.max_len // 5 if self.max_len != 6 else 0):
    #         self.input_count_tips.set_text(f"{len(self.ta.get_text())}/{self.max_len}")
    #         if self.input_count_tips.has_flag(lv.obj.FLAG.HIDDEN):
    #             self.input_count_tips.clear_flag(lv.obj.FLAG.HIDDEN)
    #     else:
    #         if not self.input_count_tips.has_flag(lv.obj.FLAG.HIDDEN):
    #             self.input_count_tips.add_flag(lv.obj.FLAG.HIDDEN)

    def toggle_number_input_keys(self, enable: bool):
        if enable:
            self.dummy_ctl_map = []
            self.dummy_ctl_map.extend(self.ctrl_map)

            if self.is_pin:
                if self.input_len >= self.min_len:
                    self.dummy_ctl_map[-1] &= (
                        self.dummy_ctl_map[-1] ^ lv.btnmatrix.CTRL.DISABLED
                    )
            else:
                if self.input_len > 0:
                    self.dummy_ctl_map[-1] &= (
                        self.dummy_ctl_map[-1] ^ lv.btnmatrix.CTRL.DISABLED
                    )

            if self.input_len > 0 or (
                not self.is_pin and self.ta.get_text().startswith("#")
            ):
                self.dummy_ctl_map[-3] = (
                    lv.btnmatrix.CTRL.CLICK_TRIG | lv.btnmatrix.CTRL.POPOVER
                )
            else:
                self.set_map(
                    lv.keyboard.MODE.NUMBER, self.dummy_btnm_map, self.ctrl_map
                )
                return

            self.set_map(lv.keyboard.MODE.NUMBER, self.btnm_map, self.dummy_ctl_map)
        else:
            self.dummy_ctl_map = []
            self.dummy_ctl_map.extend(self.ctrl_map)
            for i in range(12):
                if i not in (9, 11):
                    self.dummy_ctl_map[i] |= lv.btnmatrix.CTRL.DISABLED
                elif i == 11:
                    self.dummy_ctl_map[-1] &= (
                        self.dummy_ctl_map[-1] ^ lv.btnmatrix.CTRL.DISABLED
                    )
            self.set_map(lv.keyboard.MODE.NUMBER, self.btnm_map, self.dummy_ctl_map)

    def event_cb(self, event):
        code = event.code
        text = self.ta.get_text()
        if not self.is_pin and text.startswith("#"):
            input_len = len(text) - 1
        else:
            input_len = len(text)
        self.input_len = input_len
        self.ta.clear_flag(lv.obj.FLAG.HIDDEN)

        if code == lv.EVENT.DRAW_PART_BEGIN:
            dsc = lv.obj_draw_part_dsc_t.__cast__(event.get_param())
            if self.is_pin:
                if input_len >= self.min_len:
                    change_key_bg(dsc, 9, 11, True)
                elif input_len > 0:
                    change_key_bg(dsc, 9, 11, True, False)
                else:
                    change_key_bg(dsc, 9, 11, False)
                    if dsc.id == 9:
                        dsc.rect_dsc.bg_color = lv_colors.ONEKEY_RED_1
            else:
                if input_len > 0:
                    change_key_bg(dsc, 9, 11, True)
                else:
                    change_key_bg(dsc, 9, 11, False)
                    if dsc.id == 9:
                        dsc.rect_dsc.bg_color = lv_colors.ONEKEY_RED_1

        elif code == lv.EVENT.VALUE_CHANGED:
            utils.lcd_resume()
            motor.vibrate()

            if not self.is_pin:
                if text and not text.startswith("#"):
                    self.ta.set_text("#" + text)
                elif text == "":
                    self.ta.set_text("")

            if input_len + 1 >= self.max_len:
                self.toggle_number_input_keys(False)
            elif input_len > 0:
                self.toggle_number_input_keys(True)
            else:
                self.set_map(
                    lv.keyboard.MODE.NUMBER, self.dummy_btnm_map, self.ctrl_map
                )

            # self.update_count_tips()
            self.previous_input_len = input_len


class PassphraseKeyboard(lv.btnmatrix):  # 密码短语键盘类，继承自按钮矩阵
    def __init__(self, parent, max_len, min_len=0) -> None:  # 初始化方法，接收父对象、最大长度和最小长度参数
        super().__init__(parent)  # 调用父类初始化方法
        self.min_len = min_len  # 保存最小长度
        self.ta = lv.textarea(parent)  # 创建文本输入区域
        self.ta.align(lv.ALIGN.TOP_MID, 0, 177)  # 设置文本区域对齐方式为顶部中间，偏移177像素
        self.ta.set_size(456, lv.SIZE.CONTENT)  # 设置文本区域大小，宽度456像素，高度自适应内容
        self.ta.add_style(  # 为文本区域添加样式
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK_3)  # 设置背景颜色为黑色3
            .bg_opa()  # 设置背景不透明度
            .border_width(1)  # 设置边框宽度为1像素
            .border_color(lv_colors.ONEKEY_GRAY_2)  # 设置边框颜色为灰色2
            .text_font(font_GeistSemiBold38)  # 设置文本字体为GeistSemiBold38
            .text_color(lv_colors.WHITE)  # 设置文本颜色为白色
            .text_align_left()  # 设置文本左对齐
            .min_height(288)  # 设置最小高度为288像素
            .radius(40)  # 设置圆角半径为40像素
            .pad_all(24),  # 设置所有方向内边距为24像素
            0,
        )
        # self.ta.set_one_line(True)  # 注释：设置为单行模式
        # include NBSP  # 注释：包含不间断空格
        self.ta.set_accepted_chars(  # 设置可接受的字符集
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_<>.:@/|*#\\!()+%&-[]?{},'`;\"~$^= "
        )
        self.ta.set_max_length(max_len)  # 设置最大输入长度
        # self.ta.set_password_mode(True)  # 注释：设置密码模式
        # self.ta.clear_flag(lv.obj.FLAG.CLICKABLE)  # 注释：清除可点击标志
        self.ta.set_cursor_click_pos(True)  # 设置光标可点击定位
        self.ta.add_state(lv.STATE.FOCUSED)  # 添加焦点状态，使光标可见
        self.ta.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)  # 关闭滚动条
        self.btn_map_text_lower = [  # 小写字母键盘布局
            "q",
            "w",
            "e",
            "r",
            "t",
            "y",
            "u",
            "i",
            "o",
            "p",
            "\n",  # 换行符，表示新的一行
            " ",  # 空格占位符
            "a",
            "s",
            "d",
            "f",
            "g",
            "h",
            "j",
            "k",
            "l",
            " ",  # 空格占位符
            "\n",  # 换行符
            " ",  # 空格占位符
            "ABC",  # 切换到大写字母
            "z",
            "x",
            "c",
            "v",
            "b",
            "n",
            "m",
            " ",  # 空格占位符
            "\n",  # 换行符
            lv.SYMBOL.BACKSPACE,  # 退格键符号
            "123",  # 切换到数字键盘
            " ",  # 空格占位符
            lv.SYMBOL.OK,  # 确认键符号
            "",  # 结束标记
        ]
        self.btn_map_text_upper = [  # 大写字母键盘布局
            "Q",
            "W",
            "E",
            "R",
            "T",
            "Y",
            "U",
            "I",
            "O",
            "P",
            "\n",  # 换行符
            " ",  # 空格占位符
            "A",
            "S",
            "D",
            "F",
            "G",
            "H",
            "J",
            "K",
            "L",
            " ",  # 空格占位符
            "\n",  # 换行符
            " ",  # 空格占位符
            "abc",  # 切换到小写字母
            "Z",
            "X",
            "C",
            "V",
            "B",
            "N",
            "M",
            " ",  # 空格占位符
            "\n",  # 换行符
            lv.SYMBOL.BACKSPACE,  # 退格键符号
            "123",  # 切换到数字键盘
            " ",  # 空格占位符
            lv.SYMBOL.OK,  # 确认键符号
            "",  # 结束标记
        ]
        self.btn_map_text_special = [  # 特殊字符键盘布局1
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "0",
            "\n",  # 换行符
            " ",  # 空格占位符
            "^",
            "_",
            "[",
            "]",
            "@",
            "$",
            "%",
            "{",
            "}",
            " ",  # 空格占位符
            "\n",  # 换行符
            " ",  # 空格占位符
            "#*<",  # 切换到特殊字符2
            "`",
            "-",
            "/",
            ",",
            ".",
            ":",
            ";",
            " ",  # 空格占位符
            "\n",  # 换行符
            lv.SYMBOL.BACKSPACE,  # 退格键符号
            "abc",  # 切换到字母键盘
            " ",  # 空格占位符
            lv.SYMBOL.OK,  # 确认键符号
            "",  # 结束标记
        ]
        self.btn_map_text_special1 = [  # 特殊字符键盘布局2
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "0",
            "\n",  # 换行符
            " ",  # 空格占位符
            "!",
            "?",
            "#",
            "~",
            "&",
            '"',
            "'",
            "(",
            ")",
            " ",  # 空格占位符
            "\n",  # 换行符
            " ",  # 空格占位符
            "123",  # 切换到特殊字符1
            "+",
            "=",
            "<",
            ">",
            "\\",
            "|",
            "*",
            " ",  # 空格占位符
            "\n",  # 换行符
            lv.SYMBOL.BACKSPACE,  # 退格键符号
            "abc",  # 切换到字母键盘
            " ",  # 空格占位符
            lv.SYMBOL.OK,  # 确认键符号
            "",  # 结束标记
        ]
        # line1  # 第一行按钮控制设置
        self.ctrl_map = [
            lv.btnmatrix.CTRL.NO_REPEAT | lv.btnmatrix.CTRL.POPOVER
        ] * 10  # 设置前10个按钮为不重复且有弹出效果
        # line2  # 第二行按钮控制设置
        self.ctrl_map.extend([3 | lv.btnmatrix.CTRL.NO_REPEAT])  # 添加宽度为3的不重复按钮
        self.ctrl_map.extend(  # 扩展控制映射
            [7 | lv.btnmatrix.CTRL.NO_REPEAT | lv.btnmatrix.CTRL.POPOVER]
            * 9  # 9个宽度为7的不重复弹出按钮
        )
        self.ctrl_map.extend([3 | lv.btnmatrix.CTRL.NO_REPEAT])  # 添加宽度为3的不重复按钮
        # line3  # 第三行按钮控制设置
        self.ctrl_map.extend([2 | lv.btnmatrix.CTRL.NO_REPEAT])  # 添加宽度为2的不重复按钮
        self.ctrl_map.extend(  # 扩展控制映射
            [
                7 | lv.btnmatrix.CTRL.NO_REPEAT | lv.btnmatrix.CTRL.CLICK_TRIG
            ]  # 宽度为7的不重复点击触发按钮
        )
        self.ctrl_map.extend(  # 扩展控制映射
            [5 | lv.btnmatrix.CTRL.NO_REPEAT | lv.btnmatrix.CTRL.POPOVER]
            * 7  # 7个宽度为5的不重复弹出按钮
        )
        self.ctrl_map.extend([4 | lv.btnmatrix.CTRL.NO_REPEAT])  # 添加宽度为4的不重复按钮
        # line4  # 第四行按钮控制设置
        self.ctrl_map.extend([3])  # 添加宽度为3的按钮
        self.ctrl_map.extend(  # 扩展控制映射
            [
                2 | lv.btnmatrix.CTRL.NO_REPEAT | lv.btnmatrix.CTRL.CLICK_TRIG
            ]  # 宽度为2的不重复点击触发按钮
        )
        self.ctrl_map.extend(  # 扩展控制映射
            [
                7 | lv.btnmatrix.CTRL.NO_REPEAT | lv.btnmatrix.CTRL.CLICK_TRIG
            ]  # 宽度为7的不重复点击触发按钮
        )
        self.ctrl_map.extend(  # 扩展控制映射
            [
                3 | lv.btnmatrix.CTRL.NO_REPEAT | lv.btnmatrix.CTRL.CLICK_TRIG
            ]  # 宽度为3的不重复点击触发按钮
        )
        self.set_map(self.btn_map_text_lower)  # 设置键盘映射为小写字母布局
        self.set_ctrl_map(self.ctrl_map)  # 设置控制映射
        self.set_size(lv.pct(100), 294)  # 设置键盘大小，宽度100%，高度294像素
        self.align(lv.ALIGN.BOTTOM_MID, 0, -1)  # 对齐到底部中间，向上偏移1像素
        self.add_style(  # 添加键盘整体样式
            StyleWrapper()
            .bg_color(lv_colors.BLACK)  # 设置背景颜色为黑色
            .border_width(0)  # 设置边框宽度为0
            .pad_all(0)  # 设置所有方向内边距为0
            .pad_gap(2),  # 设置按钮间隙为2像素
            0,
        )
        self.add_style(  # 添加按钮项样式
            StyleWrapper()
            .bg_color(lv_colors.ONEKEY_BLACK_3)  # 设置按钮背景颜色
            .radius(16)  # 设置按钮圆角半径为16像素
            .text_font(font_GeistMono28)  # 设置按钮文本字体
            .text_letter_space(-1),  # 设置字母间距为-1
            lv.PART.ITEMS | lv.STATE.DEFAULT,  # 应用到按钮项的默认状态
        )
        self.add_style(  # 添加按钮按下状态样式
            StyleWrapper().bg_color(lv_colors.ONEKEY_GRAY_3),  # 设置按下时的背景颜色
            lv.PART.ITEMS | lv.STATE.PRESSED,  # 应用到按钮项的按下状态
        )

        self.input_count_tips = lv.label(parent)  # 创建输入计数提示标签
        self.input_count_tips.set_size(lv.pct(100), 38)  # 设置标签大小，宽度100%，高度38像素
        self.input_count_tips.align_to(self, lv.ALIGN.OUT_TOP_MID, 0, 0)  # 对齐到键盘顶部中间外侧
        self.input_count_tips.add_style(  # 添加计数提示样式
            StyleWrapper()
            .text_font(font_GeistRegular20)  # 设置字体
            .text_letter_space(1)  # 设置字母间距为1
            .pad_all(8)  # 设置所有方向内边距为8像素
            .text_align_center()  # 设置文本居中对齐
            .text_color(lv_colors.LIGHT_GRAY),  # 设置文本颜色为浅灰色
            0,
        )

        self.update_count_tips()  # 更新计数提示

        self.add_event_cb(self.event_cb, lv.EVENT.DRAW_PART_BEGIN, None)  # 添加绘制开始事件回调
        self.add_event_cb(self.event_cb, lv.EVENT.VALUE_CHANGED, None)  # 添加值改变事件回调
        self.ta.add_event_cb(self.event_cb, lv.EVENT.FOCUSED, None)  # 为文本区域添加焦点事件回调
        self.move_foreground()  # 移动到前景

        # 在最后添加初始状态检查  # 注释：初始化时检查OK按钮状态
        self.update_ok_button_state()  # 更新OK按钮状态

    def update_count_tips(self):  # 更新计数提示方法
        self.input_count_tips.set_text(
            f"{len(self.ta.get_text())}/50"
        )  # 设置计数提示文本，显示当前长度/50

    def update_ok_button_state(self):  # 更新OK按钮状态方法
        """根据当前输入长度更新OK按钮状态"""  # 方法说明注释
        current_text = self.ta.get_text()  # 获取当前文本内容
        current_len = len(current_text)  # 计算当前文本长度

        # 检查是否满足最小长度要求  # 注释：长度验证
        if current_len >= self.min_len:  # 如果当前长度大于等于最小长度
            # 启用OK按钮 - 恢复原有的控制设置  # 注释：启用按钮
            self.clear_btn_ctrl(34, lv.btnmatrix.CTRL.DISABLED)  # 清除第34个按钮的禁用控制
            # 确保有点击触发控制  # 注释：设置点击触发
            self.set_btn_ctrl(
                34, lv.btnmatrix.CTRL.NO_REPEAT | lv.btnmatrix.CTRL.CLICK_TRIG
            )  # 设置按钮为不重复且点击触发
        else:  # 否则
            # 禁用OK按钮  # 注释：禁用按钮
            self.set_btn_ctrl(34, lv.btnmatrix.CTRL.DISABLED)  # 设置第34个按钮为禁用状态
            self.clear_btn_ctrl(34, lv.btnmatrix.CTRL.CLICK_TRIG)  # 清除按钮的点击触发控制

    def event_cb(self, event):  # 事件回调方法
        code = event.code  # 获取事件代码
        target = event.get_target()  # 获取事件目标对象
        if code == lv.EVENT.DRAW_PART_BEGIN:  # 如果是绘制开始事件
            txt_input = self.ta.get_text()  # 获取文本输入内容
            dsc = lv.obj_draw_part_dsc_t.__cast__(event.get_param())  # 获取绘制描述符
            if len(txt_input) > 0:  # 如果有输入内容
                change_key_bg(dsc, 31, 34, True)  # 改变按键背景，启用状态
            else:  # 否则
                change_key_bg(dsc, 31, 34, False, allow_empty=True)  # 改变按键背景，禁用状态，允许空值

            # 根据最小长度要求设置OK按钮颜色  # 注释：OK按钮颜色设置
            if dsc.id == 34:  # 如果是第34个按钮（OK按钮）
                if len(txt_input) >= self.min_len:  # 如果输入长度满足最小要求
                    dsc.rect_dsc.bg_color = lv_colors.ONEKEY_GREEN  # 设置背景颜色为绿色
                else:  # 否则
                    dsc.rect_dsc.bg_color = lv_colors.GRAY  # 设置背景颜色为灰色（禁用状态）
            elif dsc.id in (10, 20, 21, 30):  # 如果是占位符按钮
                dsc.rect_dsc.bg_color = lv_colors.BLACK  # 设置背景颜色为黑色
        elif code == lv.EVENT.VALUE_CHANGED:  # 如果是值改变事件
            if isinstance(target, lv.btnmatrix):  # 如果目标是按钮矩阵
                utils.lcd_resume()  # 恢复LCD显示
                btn_id = target.get_selected_btn()  # 获取选中的按钮ID
                text = target.get_btn_text(btn_id)  # 获取按钮文本
                if text == "":  # 如果文本为空
                    return  # 直接返回
                if text == " ":  # 如果是空格占位符
                    if btn_id in (10, 21):  # 如果是特定位置的占位符
                        target.set_selected_btn(btn_id + 1)  # 选择下一个按钮
                        return  # 返回
                    elif btn_id in (20, 30):  # 如果是其他位置的占位符
                        target.set_selected_btn(btn_id - 1)  # 选择上一个按钮
                        return  # 返回
                motor.vibrate()  # 触发震动反馈
                if text == "ABC":  # 如果点击大写字母切换
                    self.set_map(self.btn_map_text_upper)  # 设置为大写字母布局
                    self.set_ctrl_map(self.ctrl_map)  # 设置控制映射
                    return  # 返回
                elif text == "123":  # 如果点击数字切换
                    self.set_map(self.btn_map_text_special)  # 设置为特殊字符布局1
                    self.set_ctrl_map(self.ctrl_map)  # 设置控制映射
                    return  # 返回
                elif text == "abc":  # 如果点击小写字母切换
                    self.set_map(self.btn_map_text_lower)  # 设置为小写字母布局
                    self.set_ctrl_map(self.ctrl_map)  # 设置控制映射
                    return  # 返回
                elif text == "#*<":  # 如果点击特殊字符切换
                    self.set_map(self.btn_map_text_special1)  # 设置为特殊字符布局2
                    self.set_ctrl_map(self.ctrl_map)  # 设置控制映射
                    return  # 返回
                elif text == lv.SYMBOL.BACKSPACE:  # 如果点击退格键
                    self.ta.del_char()  # 删除一个字符
                    self.update_count_tips()  # 更新计数提示
                    self.update_ok_button_state()  # 更新OK按钮状态
                    return  # 返回
                elif text == lv.SYMBOL.OK:  # 如果点击确认键
                    if len(self.ta.get_text()) >= self.min_len:  # 如果输入长度满足最小要求
                        lv.event_send(self, lv.EVENT.READY, None)  # 发送准备就绪事件
                    return  # 返回
                self.ta.add_text(text)  # 添加文本到输入区域
                self.update_count_tips()  # 更新计数提示
                self.update_ok_button_state()  # 更新OK按钮状态
        elif code == lv.EVENT.FOCUSED and target == self.ta:  # 如果是文本区域获得焦点事件
            utils.lcd_resume()  # 恢复LCD显示
