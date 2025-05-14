from trezor import wire, loop
from trezor.lvglui.scrs.common import FullSizeWindow
from trezor.lvglui.scrs.components.container import ContainerFlexCol
from trezor.lvglui.scrs.components.listitem import ListItemWithLeadingCheckbox
from trezor.lvglui.i18n import gettext as _, keys as i18n_keys
from trezor.lvglui.scrs.common import lv
from trezor.lvglui.lv_colors import lv_colors
from trezor import config

async def show_attach_to_pin_window(ctx: wire.Context):
    from trezor.lvglui.scrs.pinscreen import request_passphrase_pin_confirm,InputMainPin
    try:
        from trezor.crypto import se_thd89
        from apps.common.request_pin import (
                        error_pin_invalid,
                        request_pin_and_sd_salt,
                        request_pin_confirm,
                    )
        # save_result, save_status = se_thd89.save_pin_passphrase(
        #                                     "1111",
        #                                     "222222",
        #                                     "222222")
        # print(f"save_pin_passphrase returned: ({save_result}, {save_status})")
        # if save_success == True: 
        #     print("save_success")
        # else:
        #     print("save_error")
        # current_space = se_thd89.get_pin_passphrase_space()
        # print("current_space",current_space)
        # return 
        await show_pin_input_screen(ctx)
        passphrase_pin = await request_passphrase_pin_confirm(ctx)
        if len(passphrase_pin) >= 6:
            # 查询是否已经存在， 后面该代码附近还要添加一个查询容量
            passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
            pinstatus = config.check_pin(passphrase_pin_str,None, 1) # # 
            print(f"passphrase_pin={passphrase_pin_str}, pinstatus={pinstatus}")
            # 这里面后面要加一个查询状态接口 
            if pinstatus == False:  #表示这次输入的pin不存在
                current_space = se_thd89.get_pin_passphrase_space()
                if current_space < 1: 
                     return  await show_hit_the_limit_window(ctx)  # 超过最大容量
                result = await show_not_attached_window(ctx)
                if result == 0:
                    return False
                result = await show_attach_one_passphrase(ctx)
                if result == 0:
                    return False
                from trezor.ui.layouts import request_passphrase_on_device  
                passphrase = await request_passphrase_on_device(ctx, 50)  
                if passphrase != 0:
                    print("passphrase ", passphrase)
                    passphrase_content = await show_save_your_passphrase_window(ctx)
                    # mainpin_status = config.check_pin(mainpin,None, True)

                    # from apps.common.request_pin import can_lock_device, verify_user_pin
                    # from trezor.ui.layouts import request_pin_on_device
                    # pin = await request_pin_on_device(  # 在设备上请求PIN码
                    #         ctx,
                    #         _(i18n_keys.PASSPHRASE_ENTER_MAIN_PIN),
                    #         config.get_pin_rem(),  # 获取剩余尝试次数
                    #         True,
                    #         False,
                    #         close_others=False,
                    # )
                    # if not config.check_pin(curpin, salt):
                    #       await error_pin_invalid(ctx)
                    curpin, salt = await request_pin_and_sd_salt(
                            ctx, _(i18n_keys.PASSPHRASE_ENTER_MAIN_PIN), allow_fingerprint=False
                            )
                    print(curpin)
                    if  config.check_pin(curpin, None,True) == False:
                        await error_pin_invalid(ctx)

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
                        # await show_passphrase_set_and_attached_to_pin_window()
                        return False
            else:
                pinstatus = config.check_pin(passphrase_pin,None, 0) # 判断重复的是否是主PIN
                if pinstatus == True:  # 输入的pin是主pin
                    await show_pin_already_used_window(ctx)
                else:
                   next_status = await  show_has_attached_window(ctx)
                   print(f"next_status = {next_status}")
                   if next_status == 1:  #更新 passphrase ,与添加一样
                       print("update update")
                       await show_attach_one_passphrase(ctx)   
                       from trezor.ui.layouts import request_passphrase_on_device  
                       passphrase = await request_passphrase_on_device(ctx, 50)  
                       if passphrase != 0:
                            print("passphrase ", passphrase)
                            passphrase_content = await show_save_your_passphrase_window(ctx)

                            curpin, salt = await request_pin_and_sd_salt(
                            ctx, _(i18n_keys.PASSPHRASE_ENTER_MAIN_PIN), allow_fingerprint=False
                            )
                            print(curpin)
                            if  config.check_pin(curpin, None,0) == False:
                                await error_pin_invalid(ctx)
                              # 确保所有参数都是字符串类型
                            curpin_str = str(curpin) if not isinstance(curpin, str) else curpin
                            passphrase_pin_str = str(passphrase_pin) if not isinstance(passphrase_pin, str) else passphrase_pin
                            passphrase_content_str = str(passphrase) if not isinstance(passphrase, str) else passphrase
                         
                            save_result, save_status = se_thd89.save_pin_passphrase(
                                            curpin_str,
                                            passphrase_pin_str,
                                            passphrase_content_str)
                            print(f"save_result = {save_result}, save_status = {save_status}")
                            if save_result == True:
                                await show_passphrase_set_and_attached_to_pin_window(ctx)
                                return True           
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
                               return True
                           else:
                               print(f"remove_result={remove_result}, is_current={is_current}")
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

#PIN is not be attached    
async def show_not_attached_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__PIN_NOT_ATTACHED),
        _(i18n_keys.PASSPHRASE__PIN_NOT_ATTACHED_DESC),
        confirm_text=_(i18n_keys.PASSPHRASE__PIN_ATTACHED_ONE),
        # cancel_text=_(i18n_keys.BUTTON__BACK),
        anim_dir=0,
    )
    screen.add_nav_back()
    processing = False
    def nav_back_clicked(e):
        nonlocal processing
        if e.code == lv.EVENT.CLICKED and not processing:
            processing = True  
            screen.show_dismiss_anim()
            screen.channel.publish(0)
    if hasattr(screen, "nav_back"):
        screen.nav_back.add_flag(lv.obj.FLAG.CLICKABLE)
        screen.nav_back.add_event_cb(nav_back_clicked, lv.EVENT.CLICKED, None)
    screen.btn_layout_ver()
    result = await ctx.wait(screen.request())
    return result

# PIN has attached one Passphrase

async def show_has_attached_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__PIN_ATTACHED),
        _(i18n_keys.PASSPHRASE__PIN_ATTACHED_DESC),
        confirm_text=_(i18n_keys.PASSPHRASE__PIN_UPDATE),
        cancel_text=_(i18n_keys.PASSPHRASE__PIN_REMOVE),
        anim_dir=0,
    )
    screen.add_nav_back()
    screen.btn_no.enable(lv_colors.ONEKEY_RED_1)
    processing = False
    
    def nav_back_clicked(e):
        nonlocal processing
        if e.code == lv.EVENT.CLICKED and not processing:
            processing = True  # 设置标志防止重复处理
            screen.show_dismiss_anim()
            screen.channel.publish(0)
    
    if hasattr(screen, "nav_back"):
        screen.nav_back.add_flag(lv.obj.FLAG.CLICKABLE)
        screen.nav_back.add_event_cb(nav_back_clicked, lv.EVENT.CLICKED, None)
    
    # screen.btn_layout_ver()
    
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
        confirm_text=_(i18n_keys.BUTTON__CLOSE),
        icon_path="A:/res/danger.png",
        anim_dir=0,
    )
    result = await ctx.wait(screen.request())
    return result

#confirm remove pin
async def show_confirm_remove_pin_window(ctx: wire.Context):
    screen = FullSizeWindow(
        _(i18n_keys.PASSPHRASE__REMOVE),
        _(i18n_keys.PASSPHRASE__REMOVE_DESC),
        confirm_text=_(i18n_keys.PASSPHRASE__UNDERSTAND),
        icon_path="A:/res/warning.png",
        anim_dir=0,
    )
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
    close_btn.align(lv.ALIGN.TOP_RIGHT, -16, 61)
    close_btn.set_style_bg_color(lv_colors.BLACK, 0)
    close_btn.set_style_bg_opa(0, 0)
    close_btn.set_style_border_width(0, 0)
    close_btn.set_style_shadow_width(0, 0)
    
    close_img = lv.img(close_btn)
    close_img.set_src("A:/res/nav-icon.png")
    close_img.center()
    
    # 手动创建标题，不使用 Title 类
    title_label = lv.label(screen.content_area)
    title_label.set_text(_(i18n_keys.PASSPHRASE__ATTACH_TO_PIN))
    title_label.set_style_text_font(lv.font_montserrat_28, 0)  # 使用大字体
    title_label.set_style_text_color(lv_colors.WHITE, 0)
    title_label.align(lv.ALIGN.TOP_MID, 0, 116)  # 位于关闭按钮下方
    
    # 如果已经有副标题，先移除它
    if hasattr(screen, "subtitle"):
        screen.subtitle.delete()
    
    # 手动创建副标题，不使用 SubTitle 类
    subtitle_label = lv.label(screen.content_area)
    subtitle_label.set_text(_(i18n_keys.ITEM__ATTACH_TO_PIN_DESC))
    subtitle_label.set_style_text_font(lv.font_montserrat_20, 0)  # 使用中等字体
    subtitle_label.set_style_text_color(lv_colors.WHITE_3, 0)  # 使用灰色
    subtitle_label.set_long_mode(lv.label.LONG.WRAP)
    subtitle_label.set_width(440)  # 设置宽度以允许文本换行
    subtitle_label.align_to(title_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 16)
    
    # 创建 PIN 输入字段容器 - 位于副标题下方
    pin_container = lv.obj(screen.content_area)
    pin_container.set_size(lv.pct(100), lv.SIZE.CONTENT)
    pin_container.align_to(subtitle_label, lv.ALIGN.OUT_BOTTOM_MID, 0, 40)  # 位于副标题下方
    pin_container.set_style_bg_opa(0, 0)
    pin_container.set_style_border_width(0, 0)
    pin_container.set_style_pad_all(0, 0)
    
    # 定义 PIN 字段图像及其在 2x2 网格中的位置
    pin_fields = [
        {"row": 0, "col": 0, "img": "A:/res/pin_4digits.png"},
        {"row": 0, "col": 1, "img": "A:/res/pin_7digits.png"},
        {"row": 1, "col": 0, "img": "A:/res/pin_6digits.png"},
        {"row": 1, "col": 1, "img": "A:/res/pin_5digits.png"}
    ]
    
    # 计算尺寸
    row_height = 60
    col_width = 240  # 屏幕宽度的一半 (480/2)
    
    for field in pin_fields:
        # 为每个 PIN 字段创建容器
        field_container = lv.obj(pin_container)
        field_container.set_size(col_width, row_height)
        field_container.set_pos(field["col"] * col_width, field["row"] * row_height)
        field_container.set_style_bg_opa(0, 0)
        field_container.set_style_border_width(0, 0)
        field_container.set_style_pad_all(0, 0)
        
        # 添加锁图标
        lock_icon = lv.img(field_container)
        lock_icon.set_src("A:/res/pin_lock.png")
        lock_icon.align(lv.ALIGN.LEFT_MID, 12, 0)
        
        # 添加 PIN 字段图像
        pin_img = lv.img(field_container)
        pin_img.set_src(field["img"])
        pin_img.align_to(lock_icon, lv.ALIGN.OUT_RIGHT_MID, 8, 0)
    
    # 添加设备示意图
    device_img = lv.img(screen.content_area)
    device_img.set_src("A:/res/attach_to_pin_device.png")
    device_img.align(lv.ALIGN.CENTER, 0, 120)  # 调整位置以适应新布局
    
    # 为关闭按钮添加事件处理程序
    def on_close_clicked(e):
        if e.code == lv.EVENT.CLICKED:
            screen.show_dismiss_anim()
            screen.channel.publish(0)  # 返回 0 表示取消
    
    close_btn.add_event_cb(on_close_clicked, lv.EVENT.CLICKED, None)
    
    result = await ctx.wait(screen.request())
    return result


