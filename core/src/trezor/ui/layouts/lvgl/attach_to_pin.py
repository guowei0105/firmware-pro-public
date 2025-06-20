from trezor import wire, loop
from trezor.lvglui.scrs.common import FullSizeWindow
from trezor.lvglui.scrs.components.container import ContainerFlexCol
from trezor.lvglui.scrs.components.listitem import ListItemWithLeadingCheckbox
from trezor.lvglui.i18n import gettext as _, keys as i18n_keys
from trezor.lvglui.scrs.common import lv
from trezor.lvglui.lv_colors import lv_colors
from trezor import config
from trezor.lvglui.scrs import (
    font_GeistRegular30,
    font_GeistSemiBold64,
    lv_colors,
)
from apps.base import lock_device_if_unlocked
async def show_attach_to_pin_window(ctx: wire.Context):
    from trezor.lvglui.scrs.pinscreen import request_passphrase_pin_confirm,request_passphrase_pin
    try:
        from trezor.crypto import se_thd89
        from apps.common.request_pin import (
                        error_pin_invalid,
                        request_pin_and_sd_salt,
                        request_pin_confirm,
                        error_pin_used,
                    )
        pin_screen_result = await show_pin_input_screen(ctx)
        if not pin_screen_result:  
            print("Detected cancel action, returning False")
            return False  
        ####输入主pin
        # from trezor.ui.layouts import request_pin_on_device
        curpin, salt = await request_pin_and_sd_salt(
                            ctx, _(i18n_keys.TITLE__ENTER_PIN), allow_fingerprint=False,standy_wall_only = True
                            )
        # curpin = await request_pin_on_device(  # 在设备上请求PIN码
        #         ctx,
        #          _(i18n_keys.TITLE__ENTER_PIN),
        #         config.get_pin_rem(),  # 获取剩余尝试次数
        #         True,
        #         False,
        #         close_others=False,
        #         standy_wall_only=True
        #     )


        print(curpin)
        pinstatus,result = config.check_pin(curpin, None,1)
        if pinstatus == False:
           return  await error_pin_invalid(ctx)


        passphrase_pin = await request_passphrase_pin_confirm(ctx)        
        if curpin == passphrase_pin:
            return await error_pin_used(ctx)

        if len(passphrase_pin) >= 6:
            passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
            pinstatus,result = config.check_pin(passphrase_pin_str,None, 4) 
            print(f"passphrase_pin={passphrase_pin_str}, pinstatus={pinstatus}, result={result}")
            if result == 4:
                current_space = se_thd89.get_pin_passphrase_space()
                print(f"DEBUG: current_space = {current_space}")
                if current_space < 1: 
                     result =   await show_hit_the_limit_window(ctx)  
                     if result == 1:
                         while True:
                            passphrase_pin = await request_passphrase_pin(ctx, _(i18n_keys.TITLE__ENTER_PASSPHRASE))
                            passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
                            pinstatus,result = config.check_pin(passphrase_pin_str,None, 4) 

                            if passphrase_pin_str != curpin and  result == 3:
                                remove_status = await show_confirm_remove_pin_window(ctx)
                                print(f"DEBUG: remove_status = {remove_status}")

                                if remove_status == 1:
                                    passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
                                    remove_result, is_current = se_thd89.delete_pin_passphrase(passphrase_pin_str)
                                    print(f"remove_result={remove_result}, is_current={is_current}")
                                    if remove_result == True:
                                        await showr_remove_pin_success_window(ctx)
                                        if is_current:
                                                return lock_device_if_unlocked()
                                        return True
                                    else:
                                        print(f"remove_result={remove_result}, is_current={is_current}")
                                        return False 

                                elif remove_status == 0:
                                    # 用户点击了"放弃"按钮，返回上一个页面
                                    print("User cancelled removal")   
                                    return                             
                                    # continue   
                            else:  ### passphrase 输入错误
                                print(f"try_again  before before before")  # 添加打印语句
                                try_again = await error_passphrase_pin_invalid(ctx)
                                print(f"try_again = {try_again}")  # 添加打印语句
                                if try_again == 1:
                                    print("contuine passphrase")
                                    continue                                  
                                else: 

                                    return

                     else:
                         return



                result = await show_not_attached_window(ctx)
                if result == 0:
                    return False
                while True:
                    result = await show_attach_one_passphrase(ctx)
                    if result == 0:
                        return False
                
                    from trezor.ui.layouts import request_passphrase_on_device  
                    passphrase = await request_passphrase_on_device(ctx, 50, min_len=1) 
                    if passphrase is None:
                        continue
                    print("111 passphrase passphrase",passphrase) 
                    if passphrase != 0:
                        print("passphrase ", passphrase)
                        await show_save_your_passphrase_window(ctx)
                        # 确保所有参数都是字符串类型
                        curpin_str = str(curpin) if not isinstance(curpin, str) else curpin
                        passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
                        passphrase_content_str = str(passphrase) if not isinstance(passphrase, str) else passphrase

                        print(f"save_pin_passphrase: curpin={type(curpin_str)}, passphrase_pin={type(passphrase_pin_str)}, passphrase_content={type(passphrase_content_str)}")
                        print(f"curpin={curpin_str}, passphrase_pin={passphrase_pin_str}, passphrase_content={passphrase_content_str}")
                        save_result, save_status = se_thd89.save_pin_passphrase(
                                            curpin_str,
                                            passphrase_pin_str,
                                            passphrase_content_str)
                        print(f"save_result = {save_result}, save_status = {save_status}")
                        if save_result == True:
                            await show_passphrase_set_and_attached_to_pin_window(ctx)
                            return True
                        else:
                            print(f"save_result = {save_result}, save_status = {save_status}")
                            return False
            else:
                if passphrase_pin == curpin: 
                    await show_pin_already_used_window(ctx)
                else:
                #  while True:  
                   next_status = await  show_has_attached_window(ctx)
                   print(f"next_status = {next_status}")
                   if next_status == 1:
                       print("update update")
                       while True:
                            passphrase_result = await show_attach_one_passphrase(ctx)   
                            if passphrase_result == 0:
                               print("User cancelled passphrase attachment, showing previous screen")
                               return False
                            #    continue  # 继续循环，重新显示上一个页面
                            from trezor.ui.layouts import request_passphrase_on_device  
                            passphrase = await request_passphrase_on_device(ctx, 50, min_len=1)  
                            if passphrase is None:
                                continue
                            if passphrase != 0:
                                print("passphrase ", passphrase)
                                await show_save_your_passphrase_window(ctx)
                                curpin_str = str(curpin) if not isinstance(curpin, str) else curpin
                                passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
                                passphrase_content_str = str(passphrase) if not isinstance(passphrase, str) else passphrase
                                print("passphrasestr ", passphrase_content_str)
                                remove_result, is_current =se_thd89.delete_pin_passphrase(passphrase_pin_str)
                                save_result, save_status = se_thd89.save_pin_passphrase(
                                            curpin_str,
                                            passphrase_pin_str,
                                            passphrase_content_str)
                                if is_current:
                                    passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
                                    pinstatus,result = config.check_pin(passphrase_pin_str,None, 2) 

                                print(f"save_result = {save_result}, save_status = {save_status}")
                                if save_result == True:
                                    await show_passphrase_set_and_attached_to_pin_window(ctx)
                                    return True  
                    #    break         
                   elif next_status == 0: #移除流程
                       print("remove remove")
                       remove_status = await show_confirm_remove_pin_window(ctx)
                       print(f"remove_status = {remove_status}")
                       if remove_status == 1:
                           passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
                           remove_result, is_current = se_thd89.delete_pin_passphrase(passphrase_pin_str)
                           print(f"remove_result={remove_result}, is_current={is_current}")
                           if remove_result == True:
                               await showr_remove_pin_success_window(ctx)
                               if is_current:
                                      return lock_device_if_unlocked()
                               return True
                           else:
                               print(f"remove_result={remove_result}, is_current={is_current}")
                               return False 
                        #    break
                       elif remove_status == 0:
                           # 用户点击了"放弃"按钮，返回上一个页面
                           print("User cancelled removal")
                        #    continue     
                   else:                             # 返回
                          return False                                             
                    #    storage_success = se_thd89.save_pin_passphrase(
                    #                         "1111",
                    #                         passphrase_pin,
                    #                         "")                                                           
        # else:
        #     result = await show_not_attached_window(ctx)                    
            # if result == 1: 
            #     result = await show_attach_one_passphrase(ctx)
            #     if result == 1:
            #         from trezor.ui.layouts import request_passphrase_on_device  
            #         passphrase = await request_passphrase_on_device(ctx, 50)  
            #         if passphrase != 0:
            #             print("passphrase ", passphrase)
            #             result = await show_save_your_passphrase_window(ctx)
            #             if result != 0:
            #                 mainpin =  await ctx.wait(InputMainPin().request())
            #                 if mainpin != 0:
            #                     result = await show_passphrase_set_and_attached_to_pin_window(ctx)
            #                     from trezor.crypto import se_thd89
            #                     state = se_thd89.get_session_state()
            #                     # save_pin_passphrase
                    #                     if result != 0:
                    #                         return True                                
        return True
    except Exception as e:
        if __debug__:
            print(f"Error in show_attach_to_pin_window: {e}")
        return False

async def error_passphrase_pin_invalid(ctx: wire.Context):
    screen =  FullSizeWindow(
        _(i18n_keys.TITLE__WRONG_PIN),
        _(i18n_keys.SUBTITLE__SET_PIN_WRONG_PIN),
        confirm_text=_(i18n_keys.BUTTON__TRY_AGAIN),  # "Try Again"
        cancel_text=_(i18n_keys.BUTTON__CLOSE),       # "Close"
        icon_path="A:/res/danger.png",
        anim_dir=0,
    )
    return await ctx.wait(screen.request())


#PIN is not be attached    
async def show_not_attached_window(ctx: wire.Context):
    screen = FullSizeWindow(
        None,  # 不使用自动标题
        None,  # 不使用自动副标题
        confirm_text=_(i18n_keys.PASSPHRASE__PIN_ATTACHED_ONE),
        # cancel_text=_(i18n_keys.BUTTON__BACK),
        anim_dir=0,
    )
    
    # 添加关闭按钮
    close_btn = lv.btn(screen)
    close_btn.set_size(48, 48)
    close_btn.align(lv.ALIGN.TOP_RIGHT, -12, 56)
    close_btn.set_style_bg_color(lv_colors.BLACK, 0)
    close_btn.set_style_bg_opa(0, 0)
    close_btn.set_style_border_width(0, 0)
    close_btn.set_style_shadow_width(0, 0)
    close_btn.add_flag(lv.obj.FLAG.CLICKABLE) 
    close_btn.set_ext_click_area(100)

    close_img = lv.img(close_btn)
    close_img.set_src("A:/res/nav-icon.png")
    close_img.center()

    # 手动创建标题
    title_label = lv.label(screen.content_area)
    title_label.set_text(_(i18n_keys.PASSPHRASE__PIN_NOT_ATTACHED))
    title_label.set_style_text_font(font_GeistSemiBold64, 0)  # 使用GeistSemiBold64字体
    title_label.set_style_text_color(lv_colors.WHITE, 0)
    title_label.set_style_text_letter_space(-6, 0)
    title_label.set_style_text_line_space(-5, 0)
    title_label.set_long_mode(lv.label.LONG.WRAP)
    title_label.set_size(456, lv.SIZE.CONTENT)  # 宽度保持456，但通过对齐方式实现12px边距
    title_label.align(lv.ALIGN.TOP_MID, 0, 72)  # 水平居中，距离顶部80px（增加8px，从72px到80px）

    # 如果已经有副标题，先移除它
    if hasattr(screen, "subtitle"):
        screen.subtitle.delete()

    # 手动创建副标题
    subtitle_label = lv.label(screen.content_area)
    subtitle_label.set_text(_(i18n_keys.PASSPHRASE__PIN_NOT_ATTACHED_DESC))
    subtitle_label.set_style_text_font(font_GeistRegular30, 0)  # 使用GeistRegular30字体
    subtitle_label.set_style_text_color(lv_colors.LIGHT_GRAY, 0)
    subtitle_label.set_style_text_letter_space(-1, 0)
    subtitle_label.set_style_text_line_space(-1, 0)
    subtitle_label.set_long_mode(lv.label.LONG.WRAP)
    subtitle_label.set_size(456, lv.SIZE.CONTENT)  # 宽度保持456，但通过对齐方式实现12px边距
    subtitle_label.align_to(title_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 16)

    # 为关闭按钮添加事件处理程序
    processing = False  # 防止重复处理

    def on_close_clicked(e):
        nonlocal processing
        if e.code == lv.EVENT.CLICKED and not processing:
            processing = True  # 设置标志防止重复处理
            print("Close button clicked!")  # 调试输出
            screen.show_dismiss_anim()
            screen.channel.publish(0)  # 返回 0 表示取消并返回上一页

    close_btn.add_event_cb(on_close_clicked, lv.EVENT.CLICKED, None)
    
    screen.btn_layout_ver()
    result = await ctx.wait(screen.request())
    return result

# PIN has attached one Passphrase

async def show_has_attached_window(ctx: wire.Context):
    screen = FullSizeWindow(
        None,  # 不使用自动标题
        None,  # 不使用自动副标题
        confirm_text=_(i18n_keys.PASSPHRASE__PIN_UPDATE),
        cancel_text=_(i18n_keys.PASSPHRASE__PIN_REMOVE),
        anim_dir=0,
    )
    
    # 添加关闭按钮
    close_btn = lv.btn(screen)
    close_btn.set_size(48, 48)
    close_btn.align(lv.ALIGN.TOP_RIGHT, -12, 56)
    close_btn.set_style_bg_color(lv_colors.BLACK, 0)
    close_btn.set_style_bg_opa(0, 0)
    close_btn.set_style_border_width(0, 0)
    close_btn.set_style_shadow_width(0, 0)
    close_btn.add_flag(lv.obj.FLAG.CLICKABLE) 
    close_btn.set_ext_click_area(100)

    close_img = lv.img(close_btn)
    close_img.set_src("A:/res/nav-icon.png")
    close_img.center()

    # 手动创建标题
    title_label = lv.label(screen.content_area)
    title_label.set_text(_(i18n_keys.PASSPHRASE__PIN_ATTACHED))
    title_label.set_style_text_font(font_GeistSemiBold64, 0)  # 使用GeistSemiBold64字体
    title_label.set_style_text_color(lv_colors.WHITE, 0)
    title_label.set_style_text_letter_space(-6, 0)
    title_label.set_style_text_line_space(-5, 0)
    title_label.set_long_mode(lv.label.LONG.WRAP)
    title_label.set_size(456, lv.SIZE.CONTENT)  # 宽度保持456，但通过对齐方式实现12px边距
    title_label.align(lv.ALIGN.TOP_MID, 0, 80)  # 水平居中，距离顶部80px

    # 如果已经有副标题，先移除它
    if hasattr(screen, "subtitle"):
        screen.subtitle.delete()

    # 手动创建副标题
    subtitle_label = lv.label(screen.content_area)
    subtitle_label.set_text(_(i18n_keys.PASSPHRASE__PIN_ATTACHED_DESC))
    subtitle_label.set_style_text_font(font_GeistRegular30, 0)  # 使用GeistRegular30字体
    subtitle_label.set_style_text_color(lv_colors.LIGHT_GRAY, 0)
    subtitle_label.set_style_text_letter_space(-3, 0)
    subtitle_label.set_style_text_line_space(4, 0)
    subtitle_label.set_long_mode(lv.label.LONG.WRAP)
    subtitle_label.set_size(456, lv.SIZE.CONTENT)  # 宽度保持456，但通过对齐方式实现12px边距
    subtitle_label.align_to(title_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 16)

    # 为关闭按钮添加事件处理程序
    processing = False  # 防止重复处理

    def on_close_clicked(e):
        nonlocal processing
        if e.code == lv.EVENT.CLICKED and not processing:
            processing = True  # 设置标志防止重复处理
            print("Close button clicked!")  # 调试输出
            screen.show_dismiss_anim()
            screen.channel.publish(-1)  # 返回 -1 表示取消并返回上一页

    close_btn.add_event_cb(on_close_clicked, lv.EVENT.CLICKED, None)
    
    screen.btn_no.enable(lv_colors.ONEKEY_RED_1, text_color=lv_colors.BLACK)

    result = await ctx.wait(screen.request())
    return result


        # await show_fullsize_window(
        #                         ctx,
        #                         _(i18n_keys.TITLE__CONNECT_FAILED),
        #                         _(
        #                             i18n_keys.CONTENT__THE_TWO_ONEKEY_LITE_USED_FOR_CONNECTION_ARE_NOT_THE_SAME
        #                         ),
        #                         _(i18n_keys.BUTTON__I_GOT_IT),
        #                         icon_path="A:/res/danger.png",
        #                     )
#PIN already used
async def show_pin_already_used_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__PIN_USED),
        _(i18n_keys.PASSPHRASE__PIN_USED_DESC),
        confirm_text=_(i18n_keys.BUTTON__CLOSE),
        icon_path="A:/res/danger.png",
        anim_dir=0,
    )
    result = await ctx.wait(screen.request())
    return result


#Hit the limit
async def show_hit_the_limit_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__PIN_HIT_LIMIT),
        _(i18n_keys.PASSPHRASE__PIN_HIT_LIMIT_DESC),
        confirm_text=_(i18n_keys.PASSPHRASE__PIN_REMOVE),
        cancel_text=_(i18n_keys.BUTTON__CLOSE), 
        icon_path="A:/res/danger.png",
        anim_dir=0,
    )
    screen.btn_yes.enable(lv_colors.ONEKEY_RED_1, text_color=lv_colors.BLACK)
    result = await ctx.wait(screen.request())
    return result

#confirm remove pin
async def show_confirm_remove_pin_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__REMOVE),
        _(i18n_keys.PASSPHRASE__REMOVE_DESC),
        confirm_text=_(i18n_keys.BUTTON__REMOVE),
        cancel_text=_(i18n_keys.BUTTON__CANCEL),
        icon_path="A:/res/warning.png",
        anim_dir=0,
    )
    # 设置确认按钮为红底黑字
    screen.btn_yes.enable(lv_colors.ONEKEY_RED_1, text_color=lv_colors.BLACK)
    result = await ctx.wait(screen.request())
    return result

async def showr_remove_pin_success_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__REMOVE_SUCCESSFUL),
        "",
        confirm_text=_(i18n_keys.BUTTON__DONE),
        icon_path="A:/res/success.png",
        anim_dir=0,
    )
    result = await ctx.wait(screen.request())
    return result



# Save you passphrase
async def show_save_your_passphrase_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__SAVE),
        _(i18n_keys.PASSPHRASE__SAVE_DESC),
        confirm_text=_(i18n_keys.PASSPHRASE__UNDERSTAND),
        icon_path="A:/res/warning.png",
        anim_dir=0,
    )
    result = await ctx.wait(screen.request())
    return result

# passphrase_set_and_attached_to_pin
async def show_passphrase_set_and_attached_to_pin_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__SET),
        _(i18n_keys.PASSPHRASE__SET_DESC),
        confirm_text=_(i18n_keys.BUTTON__DONE),
        icon_path="A:/res/success.png",
        anim_dir=0,
    )
    result = await ctx.wait(screen.request())
    return result

async def show_attach_one_passphrase(ctx: wire.Context):
    """显示擦除设备提示窗口，使用复选框和滑块确认"""
    class AttachOnePassphraseTips(FullSizeWindow):
        def __init__(self):
            title = _(i18n_keys.PASSPHRASE__ATTACH_ONE_PASSPHRASE)
            # subtitle = _(i18n_keys.SUBTITLE__DEVICE_WIPE_DEVICE_FACTORY_RESET)
            # icon_path = "A:/res/danger.png"
            super().__init__(
                title,
                None,
                _(i18n_keys.BUTTON__SLIDE_TO_CONFIRM),
                _(i18n_keys.BUTTON__CANCEL),
                # icon_path=icon_path,
                hold_confirm=True,
                primary_color=lv_colors.WHITE,  # 设置滑块的主要颜色为白色
            )
            self.container = ContainerFlexCol(
                self.content_area,
                self.title,
                padding_row=8,
                clip_corner=False,
            )
            self.item1 = ListItemWithLeadingCheckbox(
                self.container,
                _(i18n_keys.PASSPHRASE__ATTACH_ONE_PASSPHRASE_DESC1),
                radius=40,
            )
            self.item2 = ListItemWithLeadingCheckbox(
                self.container,
                _(i18n_keys.PASSPHRASE__ATTACH_ONE_PASSPHRASE_DESC2),
                radius=40,
            )

            # 修改滑块旋钮颜色为白色
            if hasattr(self, "slider"):
                # 设置旋钮颜色为白色
                self.slider.set_style_bg_color(lv_colors.WHITE, lv.PART.KNOB | lv.STATE.DEFAULT)

                # 保存原始的enable方法
                original_enable = self.slider.enable

                # 重写enable方法，确保启用时旋钮保持白色
                def new_enable(enable=True):
                    original_enable(enable)
                    if enable:
                        self.slider.set_style_bg_color(lv_colors.WHITE, lv.PART.KNOB | lv.STATE.DEFAULT)

                # 替换enable方法
                self.slider.enable = new_enable

            self.slider_enable(False)
            self.container.add_event_cb(self.on_value_changed, lv.EVENT.VALUE_CHANGED, None)
            self.cb_cnt = 0

        def slider_enable(self, enable: bool = True):
            if enable:
                self.slider.add_flag(lv.obj.FLAG.CLICKABLE)
                self.slider.enable()
            else:
                self.slider.clear_flag(lv.obj.FLAG.CLICKABLE)
                self.slider.enable(False)

        def on_value_changed(self, event_obj):
            code = event_obj.code
            target = event_obj.get_target()
            if code == lv.EVENT.VALUE_CHANGED:
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
                    self.slider_enable()
                elif self.cb_cnt < 2:
                    self.slider_enable(False)

    screen = AttachOnePassphraseTips()
    result = await ctx.wait(screen.request())
    return result

async def show_pin_input_screen(ctx: wire.Context):
    """Display the PIN input screen for attaching passphrase to PIN"""
    screen = FullSizeWindow(
        None,  # 不使用自动标题
        _(i18n_keys.ITEM__ATTACH_TO_PIN_DESC),
        confirm_text=_(i18n_keys.BUTTON__CONTINUE),
        anim_dir=0,
    )

    # 添加关闭按钮
    close_btn = lv.btn(screen)
    close_btn.set_size(48, 48)
    close_btn.align(lv.ALIGN.TOP_RIGHT, -12, 56)
    close_btn.set_style_bg_color(lv_colors.BLACK, 0)
    close_btn.set_style_bg_opa(0, 0)
    close_btn.set_style_border_width(0, 0)
    close_btn.set_style_shadow_width(0, 0)
    close_btn.add_flag(lv.obj.FLAG.CLICKABLE) 
    close_btn.set_ext_click_area(100)

    close_img = lv.img(close_btn)
    close_img.set_src("A:/res/nav-icon.png")
    close_img.center()

    # 手动创建标题
    title_label = lv.label(screen.content_area)
    title_label.set_text(_(i18n_keys.PASSPHRASE__ATTACH_TO_PIN))
    title_label.set_style_text_font(font_GeistSemiBold64, 0)  # 使用GeistSemiBold64字体
    title_label.set_style_text_color(lv_colors.WHITE, 0)
    title_label.set_style_text_letter_space(-6, 0)
    title_label.set_style_text_line_space(-5, 0)
    title_label.set_long_mode(lv.label.LONG.WRAP)
    title_label.set_size(456, lv.SIZE.CONTENT)  # 宽度保持456，但通过对齐方式实现12px边距
    title_label.align(lv.ALIGN.TOP_MID, 0, 72)  # 水平居中，距离顶部72px

    # 如果已经有副标题，先移除它
    if hasattr(screen, "subtitle"):
        screen.subtitle.delete()

    # 手动创建副标题
    subtitle_label = lv.label(screen.content_area)
    subtitle_label.set_text(_(i18n_keys.ITEM__ATTACH_TO_PIN_DESC))
    subtitle_label.set_style_text_font(font_GeistRegular30, 0)  # 使用GeistRegular30字体
    subtitle_label.set_style_text_color(lv_colors.LIGHT_GRAY, 0)
    subtitle_label.set_style_text_letter_space(-1, 0)
    subtitle_label.set_style_text_line_space(-1, 0)
    subtitle_label.set_long_mode(lv.label.LONG.WRAP)
    subtitle_label.set_size(456, lv.SIZE.CONTENT)  # 宽度保持456，但通过对齐方式实现12px边距
    subtitle_label.align_to(title_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 16)

    # 创建 PIN 输入字段容器
    pin_container = lv.obj(screen.content_area)
    pin_container.set_size(lv.pct(100), lv.SIZE.CONTENT)
    pin_container.align_to(subtitle_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 24)  # 位于副标题下方
    pin_container.set_style_bg_opa(0, 0)
    pin_container.set_style_border_width(0, 0)
    pin_container.set_style_pad_all(0, 0)

    # 使用合并后的单一图片 - 位于副标题下方
    pin_img = lv.img(pin_container)
    pin_img.set_src("A:/res/attach_to_pin_display.png")  # 使用新的合并图片
    pin_img.align_to(subtitle_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 48)  # 在副标题下方24px

    # 添加设备示意图 - 位于pin_img下方
    device_img = lv.img(screen.content_area)
    device_img.set_src("A:/res/attach_to_pin_dot_group.png")
    device_img.align_to(pin_img, lv.ALIGN.OUT_BOTTOM_MID, 0, 24)  # 在pin_img下方24px

    # 为关闭按钮添加事件处理程序
    processing = False  # 防止重复处理

    def on_close_clicked(e):
        nonlocal processing
        if e.code == lv.EVENT.CLICKED and not processing:
            processing = True  # 设置标志防止重复处理
            print("Close button clicked!")  # 调试输出
            screen.show_dismiss_anim()
            screen.channel.publish(False)  # 返回 False 表示取消并返回上一页

    close_btn.add_event_cb(on_close_clicked, lv.EVENT.CLICKED, None)
    # 添加调试信息
    print("PIN input screen displayed, waiting for interaction...")
    result = await ctx.wait(screen.request())
    print(f"PIN input screen result: {result}")  # 调试输出
    return result