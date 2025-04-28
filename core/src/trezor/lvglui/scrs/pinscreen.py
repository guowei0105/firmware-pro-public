from trezor import utils

from ..i18n import gettext as _, keys as i18n_keys
from . import font_GeistRegular26, font_GeistSemiBold48
from .common import FullSizeWindow, lv, lv_colors  # noqa: F401,F403
from .components.button import NormalButton
from .components.container import ContainerFlexCol
from .components.keyboard import IndexKeyboard, NumberKeyboard
from .components.listitem import ListItemWithLeadingCheckbox
from .widgets.style import StyleWrapper


class PinTip(FullSizeWindow):
    def __init__(self):
        super().__init__(
            _(i18n_keys.TITLE__SETUP_CREATE_ENABLE_PIN_PROTECTION),
            _(i18n_keys.SUBTITLE__SETUP_CREATE_ENABLE_PIN_PROTECTION),
            anim_dir=0,
        )
        self.container = ContainerFlexCol(
            self.content_area,
            self.subtitle,
            pos=(0, 30),
            padding_row=10,
            clip_corner=False,
        )
        # self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        self.item1 = ListItemWithLeadingCheckbox(
            self.container,
            _(i18n_keys.CHECK__SETUP_SET_A_PIN__1),
            radius=40,
        )
        self.item2 = ListItemWithLeadingCheckbox(
            self.container,
            _(i18n_keys.CHECK__SETUP_SET_A_PIN__2),
            radius=40,
        )
        self.btn = NormalButton(self, _(i18n_keys.BUTTON__CONTINUE), False)
        self.container.add_event_cb(self.eventhandler, lv.EVENT.VALUE_CHANGED, None)
        self.cb_cnt = 0

    def eventhandler(self, event_obj: lv.event_t):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if utils.lcd_resume():
                return
            if target == self.btn:
                self.channel.publish(1)
                self.destroy()
        elif code == lv.EVENT.VALUE_CHANGED:
            if target == self.item1.checkbox:
                if target.get_state() & lv.STATE.CHECKED:
                    self.item1.enable_bg_color()
                    self.cb_cnt += 1
                else:
                    self.item1.enable_bg_color(False)
                    self.cb_cnt -= 1
            elif target == self.item2.checkbox:
                if target.get_state() & lv.STATE.CHECKED:
                    self.item2.enable_bg_color()
                    self.cb_cnt += 1
                else:
                    self.item2.enable_bg_color(False)
                    self.cb_cnt -= 1
            if self.cb_cnt == 2:
                self.btn.enable(
                    bg_color=lv_colors.ONEKEY_GREEN, text_color=lv_colors.BLACK
                )
            elif self.cb_cnt < 2:
                self.btn.disable()


class InputNum(FullSizeWindow):
    _instance = None

    @classmethod
    def get_window_if_visible(cls) -> "InputNum" | None:
        try:
            if cls._instance is not None and cls._instance.is_visible():
                return cls._instance
        except Exception:
            pass
        return None

    def __init__(self, **kwargs):
        super().__init__(
            title=kwargs.get("title") or _(i18n_keys.TITLE__ENTER_PIN),
            subtitle=kwargs.get("subtitle", ""),
            anim_dir=0,
        )
        self.__class__._instance = self

        self.title.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold48)
            .text_align_center()
            .text_letter_space(0),
            0,
        )
        self.title.align(lv.ALIGN.TOP_MID, 0, 24)

        if self.subtitle.get_text() != "":
            self.subtitle.add_style(
                StyleWrapper().text_font(font_GeistRegular26)
                # .max_width(310)
                .max_width(368)
                .text_color(lv_colors.WHITE)
                .bg_color(lv_colors.ONEKEY_RED_2)
                .bg_opa(lv.OPA.COVER)
                .pad_hor(8)
                .pad_ver(16)
                .radius(40)
                .text_align_center(),
                0,
            )
            # self.subtitle.add_style(
            #     StyleWrapper()
            #     .text_font(font_GeistRegular26)
            #     .max_width(368)
            #     .text_color(lv_colors.ONEKEY_RED_1)
            #     .text_align_center(),
            #     0,
            # )

            title_height = self.title.get_height()
            subtitle_y = 40 if title_height > 60 else 70
            self.subtitle.align_to(self.title, lv.ALIGN.OUT_BOTTOM_MID, 0, subtitle_y)
            self.subtitle.move_foreground()

        self.clear_flag(lv.obj.FLAG.SCROLLABLE)
        self.keyboard = IndexKeyboard(
            self, min_len=1, max_len=11, is_pin=kwargs.get("is_pin", True)
        )
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.READY, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.CANCEL, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.VALUE_CHANGED, None)

        self.keyboard.ta.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP),
            0,
        )

    def on_event(self, event_obj):
        code = event_obj.code
        if code == lv.EVENT.VALUE_CHANGED:
            utils.lcd_resume()
            if self.keyboard.ta.get_text() != "":
                self.subtitle.set_text("")
                self.subtitle.remove_style_all()

            return
        elif code == lv.EVENT.READY:
            input = self.keyboard.ta.get_text()
            if input.startswith("#"):
                input = input[1:]
            if len(input) < 1:
                return
            self.channel.publish(input)
        elif code == lv.EVENT.CANCEL:
            self.channel.publish(0)

        self.clean()
        self.destroy(500)


class InputPin(FullSizeWindow):
    # InputPin类，继承自FullSizeWindow，用于PIN码输入界面

    _instance = None  # 类变量，用于存储当前实例

    @classmethod
    def get_window_if_visible(cls) -> "InputPin" | None:
        # 类方法，获取当前可见的InputPin实例，如果存在的话
        try:
            if cls._instance is not None and cls._instance.is_visible():
                return cls._instance
        except Exception:
            pass
        return None

    def __init__(self, **kwargs):
        # 初始化方法，设置PIN输入界面
        subtitle = kwargs.get("subtitle", "")  # 获取副标题，默认为空字符串
        super().__init__(
            title=kwargs.get("title") or _(i18n_keys.TITLE__ENTER_PIN),  # 设置标题，如果没有提供则使用默认值
            subtitle=subtitle,  # 设置副标题
            anim_dir=0,  # 设置动画方向为0
        )
        self.__class__._instance = self  # 将当前实例存储到类变量中
        self.allow_fingerprint = kwargs.get("allow_fingerprint", True)  # 是否允许指纹解锁，默认为True
        self.title.add_style(
            StyleWrapper()  # 设置标题样式
            .text_font(font_GeistSemiBold48)  # 设置字体
            .text_align_center()  # 居中对齐
            .text_letter_space(0),  # 字符间距为0
            0,
        )
        self.title.align(lv.ALIGN.TOP_MID, 0, 24)  # 将标题对齐到顶部中间位置

        self.subtitle.add_style(
            StyleWrapper()  # 设置副标题样式
            .text_font(font_GeistRegular26)  # 设置字体
            .max_width(368)  # 最大宽度
            .text_color(lv_colors.WHITE)  # 文字颜色为白色
            .bg_color(lv_colors.ONEKEY_RED_2 if subtitle else lv_colors.BLACK)  # 如果有副标题则背景为红色，否则为黑色
            .bg_opa(lv.OPA.COVER)  # 背景不透明度为完全不透明
            .pad_hor(8)  # 水平内边距
            .pad_ver(16)  # 垂直内边距
            .radius(40)  # 圆角半径
            .text_align_center(),  # 文字居中对齐
            0,
        )

        title_height = self.title.get_height()  # 获取标题高度
        subtitle_y = 40 if title_height > 60 else 70  # 根据标题高度确定副标题的Y坐标
        self.subtitle.align_to(self.title, lv.ALIGN.OUT_BOTTOM_MID, 0, subtitle_y)  # 将副标题对齐到标题下方

        self._show_fingerprint_prompt_if_necessary()  # 如果需要，显示指纹提示
        self.clear_flag(lv.obj.FLAG.SCROLLABLE)  # 清除可滚动标志
        self.keyboard = NumberKeyboard(self)  # 创建数字键盘
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.READY, None)  # 添加READY事件回调
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.CANCEL, None)  # 添加CANCEL事件回调
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.VALUE_CHANGED, None)  # 添加VALUE_CHANGED事件回调

        self.keyboard.ta.add_style(
            StyleWrapper().bg_opa(lv.OPA.TRANSP),  # 设置键盘文本区域背景为透明
            0,
        )

    def change_subtitle(self, subtitle: str):
        # 更改副标题的方法
        self.subtitle.set_style_bg_color(
            lv_colors.ONEKEY_RED_2 if subtitle else lv_colors.BLACK, 0  # 如果有副标题则背景为红色，否则为黑色
        )
        self.subtitle.set_text(subtitle)  # 设置副标题文本
        keyboard_text = self.keyboard.ta.get_text()  # 获取键盘文本
        if keyboard_text:  # 如果有键盘文本
            if subtitle:  # 如果有副标题
                self.keyboard.ta.align_to(self.subtitle, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)  # 将键盘文本区域对齐到副标题下方
            else:
                self.keyboard.ta.align(lv.ALIGN.TOP_MID, 0, 188)  # 将键盘文本区域对齐到顶部中间位置

    def _show_fingerprint_prompt_if_necessary(self):
        # 如果需要，显示指纹提示的方法
        from . import fingerprints  # 导入指纹模块

        if self.allow_fingerprint and fingerprints.is_available():  # 如果允许指纹且指纹可用
            self.fingerprint_prompt = lv.img(self.content_area)  # 创建指纹提示图像
            self.fingerprint_prompt.set_src("A:/res/fingerprint-prompt.png")  # 设置图像源
            self.fingerprint_prompt.set_pos(414, 30)  # 设置图像位置
            self.anim = lv.anim_t()  # 创建动画对象
            self.anim.init()  # 初始化动画
            self.anim.set_var(self.fingerprint_prompt)  # 设置动画变量
            self.anim.set_values(414, 404)  # 设置动画值范围
            self.anim.set_time(100)  # 设置动画时间
            self.anim.set_playback_delay(10)  # 设置回放延迟
            self.anim.set_playback_time(100)  # 设置回放时间
            self.anim.set_repeat_delay(20)  # 设置重复延迟
            self.anim.set_repeat_count(2)  # 设置重复次数
            self.anim.set_path_cb(lv.anim_t.path_ease_in_out)  # 设置动画路径回调
            self.anim.set_custom_exec_cb(lambda _a, val: self.anim_set_x(val))  # 设置自定义执行回调

    def anim_set_x(self, val):
        # 设置动画X坐标的方法
        try:
            self.fingerprint_prompt.set_x(val)  # 设置指纹提示图像的X坐标
        except Exception:
            pass  # 忽略异常

    def refresh_fingerprint_prompt(self):
        # 刷新指纹提示的方法
        if hasattr(self, "fingerprint_prompt"):  # 如果有指纹提示属性
            try:
                self.fingerprint_prompt.delete()  # 删除指纹提示图像
                del self.fingerprint_prompt  # 删除指纹提示属性
                del self.anim  # 删除动画属性
                self.change_subtitle("")  # 清空副标题
            except Exception:
                pass  # 忽略异常

    def show_fp_failed_prompt(self, level: int = 0):
        # 显示指纹失败提示的方法
        if level:  # 如果有级别
            if level == 1:
                subtitle = _(i18n_keys.MSG__FINGERPRINT_NOT_RECOGNIZED_TRY_AGAIN)  # 指纹未识别，请重试
            elif level == 2:
                subtitle = _(
                    i18n_keys.MSG__YOUR_PIN_CODE_REQUIRED_TO_ENABLE_FINGERPRINT_UNLOCK  # 需要PIN码来启用指纹解锁
                )
            elif level == 3:
                subtitle = _(i18n_keys.MSG__PUT_FINGER_ON_THE_FINGERPRINT)  # 请将手指放在指纹传感器上
            elif level == 4:
                subtitle = _(i18n_keys.MSG__CLEAN_FINGERPRINT_SENSOR_AND_TRY_AGAIN)  # 清洁指纹传感器并重试
            else:
                subtitle = ""  # 空副标题
            self.change_subtitle(subtitle)  # 更改副标题
        if hasattr(self, "fingerprint_prompt"):  # 如果有指纹提示属性
            lv.anim_t.start(self.anim)  # 启动动画

    def on_event(self, event_obj):
        # 事件处理方法
        code = event_obj.code  # 获取事件代码
        if code == lv.EVENT.VALUE_CHANGED:  # 如果是值改变事件
            utils.lcd_resume()  # 恢复LCD
            if self.keyboard.ta.get_text() != "":  # 如果键盘文本不为空
                self.change_subtitle("")  # 清空副标题
            return
        elif code == lv.EVENT.READY:  # 如果是准备就绪事件
            input_text = self.keyboard.ta.get_text()  # 获取键盘文本
            if len(input_text) < 4:  # 如果文本长度小于4
                return  # 返回，不处理
            self.channel.publish(input_text)  # 发布输入文本
        elif code == lv.EVENT.CANCEL:  # 如果是取消事件
            self.channel.publish(0)  # 发布0

        self.clean()  # 清理
        self.destroy(500)  # 销毁界面，延迟500毫秒


class InputLitePin(FullSizeWindow):
    def __init__(self):
        super().__init__(
            title=_(i18n_keys.TITLE__ENTER_ONEKEY_LITE_PIN),
            subtitle=None,
            anim_dir=0,
        )
        self.title.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold48)
            .text_align_center()
            .text_letter_space(0),
            0,
        )
        self.title.align(lv.ALIGN.TOP_MID, 0, 24)
        self.clear_flag(lv.obj.FLAG.SCROLLABLE)
        self.keyboard = NumberKeyboard(self, max_len=6, min_len=6)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.READY, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.CANCEL, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.VALUE_CHANGED, None)

    def on_event(self, event_obj):
        code = event_obj.code
        if code == lv.EVENT.VALUE_CHANGED:
            utils.lcd_resume()
            return
        elif code == lv.EVENT.READY:
            input = self.keyboard.ta.get_text()
            if len(input) < 6:
                return
            self.channel.publish(input)
        elif code == lv.EVENT.CANCEL:
            self.channel.publish(0)

        self.clean()
        self.destroy()


class InputLitePinConfirm(FullSizeWindow):
    def __init__(self, title):
        super().__init__(
            title=title,
            subtitle=None,
            anim_dir=0,
        )
        self.title.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold48)
            .text_align_center()
            .text_letter_space(0),
            0,
        )
        self.title.align(lv.ALIGN.TOP_MID, 0, 24)
        self.clear_flag(lv.obj.FLAG.SCROLLABLE)
        self.keyboard = NumberKeyboard(self, max_len=6, min_len=6)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.READY, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.CANCEL, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.VALUE_CHANGED, None)
        self.input_result = None

    def on_event(self, event_obj):
        code = event_obj.code
        if code == lv.EVENT.VALUE_CHANGED:
            utils.lcd_resume()
            return
        elif code == lv.EVENT.READY:
            input = self.keyboard.ta.get_text()
            if len(input) < 6:
                return
            self.input_result = input
            self.channel.publish(self.input_result)
        elif code == lv.EVENT.CANCEL:
            self.channel.publish(0)

        self.clean()
        self.destroy()


async def pin_mismatch(ctx) -> None:
    from trezor.ui.layouts import show_warning

    await show_warning(
        ctx=ctx,
        br_type="pin_not_match",
        header=_(i18n_keys.TITLE__NOT_MATCH),
        content=_(
            i18n_keys.CONTENT__THE_TWO_ONEKEY_LITE_USED_FOR_CONNECTION_ARE_NOT_THE_SAME
        ),
        icon="A:/res/danger.png",
        btn_yes_bg_color=lv_colors.ONEKEY_BLACK,
    )


async def request_lite_pin(ctx, prompt: str) -> str:
    pin_screen = InputLitePinConfirm(prompt)
    pin = await ctx.wait(pin_screen.request())
    return pin


async def request_lite_pin_confirm(ctx) -> str:
    while True:
        pin1 = await request_lite_pin(ctx, _(i18n_keys.TITLE__SET_ONEKEY_LITE_PIN))
        if pin1 == 0:
            return pin1
        pin2 = await request_lite_pin(ctx, _(i18n_keys.TITLE__CONFIRM_ONEKEY_LITE_PIN))
        if pin2 == 0:
            return pin2
        if pin1 == pin2:
            return pin1
        await pin_mismatch(ctx)


class InputPassphrasePinConfirm(FullSizeWindow):
    def __init__(self, title):
        super().__init__(
            title=title,
            subtitle=None,
            anim_dir=0,
        )
        self.title.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold48)
            .text_align_center()
            .text_letter_space(0),
            0,
        )
        self.title.align(lv.ALIGN.TOP_MID, 0, 24)
        self.clear_flag(lv.obj.FLAG.SCROLLABLE)
        self.keyboard = NumberKeyboard(self, max_len=50, min_len=6)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.READY, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.CANCEL, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.VALUE_CHANGED, None)
        self.input_result = None

    def on_event(self, event_obj):
        code = event_obj.code
        if code == lv.EVENT.VALUE_CHANGED:
            utils.lcd_resume()
            return
        elif code == lv.EVENT.READY:
            input = self.keyboard.ta.get_text()
            if len(input) < 6:
                return
            self.input_result = input
            self.channel.publish(self.input_result)
        elif code == lv.EVENT.CANCEL:
            self.channel.publish(0)

        self.clean()
        self.destroy()


async def pin_mismatch(ctx) -> None:
    from trezor.ui.layouts import show_warning

    await show_warning(
        ctx=ctx,
        br_type="pin_not_match",
        header=_(i18n_keys.TITLE__NOT_MATCH),
        content=_(
            i18n_keys.CONTENT__THE_TWO_ONEKEY_LITE_USED_FOR_CONNECTION_ARE_NOT_THE_SAME
        ),
        icon="A:/res/danger.png",
        btn_yes_bg_color=lv_colors.ONEKEY_BLACK,
    )


async def request_passphrase_pin(ctx, prompt: str) -> str:
    pin_screen = InputPassphrasePinConfirm(prompt)
    pin = await ctx.wait(pin_screen.request())
    return pin


async def request_passphrase_pin_confirm(ctx) -> str:
    while True:
        pin1 = await request_passphrase_pin(ctx, _(i18n_keys.PASSPHRASE__SET_PASSPHRASE_PIN))
        if pin1 == 0:
            return pin1
        
        
        pin2 = await request_passphrase_pin(ctx, _(i18n_keys.PASSPHRASE__RE_ENTER_PIN))
        if pin2 == 0:
            return pin2
        if pin1 == pin2:
            return pin1
        await pin_mismatch(ctx)


class SetupComplete(FullSizeWindow):
    def __init__(self, subtitle=""):
        super().__init__(
            title=_(i18n_keys.TITLE__WALLET_IS_READY),
            subtitle=subtitle,
            confirm_text=_(i18n_keys.BUTTON__CONTINUE),
            icon_path="A:/res/success.png",
            anim_dir=0,
        )

    def eventhandler(self, event_obj: lv.event_t):
        code = event_obj.code
        target = event_obj.get_target()
        if code == lv.EVENT.CLICKED:
            if target == self.btn_yes:
                self.channel.publish(1)
                self.destroy()
                lv.scr_act().del_delayed(500)
                from apps.base import set_homescreen

                set_homescreen()




class InputMainPin(FullSizeWindow):
    def __init__(self):
        super().__init__(
            title=_(i18n_keys.PASSPHRASE_ENTER_MAIN_PIN),
            subtitle=None,
            anim_dir=0,
        )
        self.title.add_style(
            StyleWrapper()
            .text_font(font_GeistSemiBold48)
            .text_align_center()
            .text_letter_space(0),
            0,
        )
        self.title.align(lv.ALIGN.TOP_MID, 0, 24)
        self.clear_flag(lv.obj.FLAG.SCROLLABLE)
        self.keyboard = NumberKeyboard(self, max_len=50, min_len=4)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.READY, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.CANCEL, None)
        self.keyboard.add_event_cb(self.on_event, lv.EVENT.VALUE_CHANGED, None)

    def on_event(self, event_obj):
        code = event_obj.code
        if code == lv.EVENT.VALUE_CHANGED:
            utils.lcd_resume()
            return
        elif code == lv.EVENT.READY:
            input = self.keyboard.ta.get_text()
            if len(input) < 6:
                return
            self.channel.publish(input)
        elif code == lv.EVENT.CANCEL:
            self.channel.publish(0)

        self.clean()
        self.destroy()
