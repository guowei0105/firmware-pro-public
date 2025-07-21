#!/usr/bin/env python3
"""
运行时修复脚本 - 立即解决问题
直接在设备上运行此脚本即可修复手势和背景切换问题
"""

print("🔧 开始修复手势和背景切换问题...")

try:
    from trezor.lvglui.scrs.homescreen import MainScreen
    import lvgl as lv
    
    # 获取实例
    main_screen = MainScreen._instance
    app_drawer = main_screen.apps
    
    print("✅ 找到MainScreen和AppDrawer")
    
    # 1. 修复change_background_image方法
    def new_change_background_image(image_path):
        print(f"AppDrawer: Changing background to: {image_path}")
        try:
            if not image_path.startswith("A:"):
                image_path = f"A:{image_path}"
            
            app_drawer.remove_style_all()
            
            from trezor.lvglui.widgets.style import StyleWrapper
            from trezor.lvglui.lv_colors import lv_colors
            
            app_drawer.add_style(
                StyleWrapper().bg_opa(lv.OPA.COVER).bg_color(lv_colors.BLACK).border_width(0),
                0,
            )
            
            app_drawer.add_style(
                StyleWrapper().bg_img_src(image_path).border_width(0),
                0,
            )
            
            app_drawer.invalidate()
            print(f"AppDrawer: Background changed successfully")
        except Exception as e:
            print(f"AppDrawer: Error changing background: {e}")
    
    # 2. 修复on_gesture方法 - 只在可见时处理
    def new_on_gesture(event_obj):
        code = event_obj.code
        
        # 关键修复：只有在可见时才处理手势
        if not app_drawer.visible:
            return
            
        if code == lv.EVENT.GESTURE:
            indev = lv.indev_get_act()
            _dir = indev.get_gesture_dir()
            print(f"AppDrawer: Gesture direction: {_dir} (visible={app_drawer.visible})")
            
            if _dir == lv.DIR.TOP:
                print("AppDrawer: UP gesture - hiding layer2")
                try:
                    from trezorui import Display
                    display = Display()
                    
                    # 切换背景
                    new_change_background_image("/res/wallpaper-2.jpg")
                    
                    # 隐藏layer2
                    if hasattr(display, 'cover_background_animate_to_y'):
                        display.cover_background_animate_to_y(-800, 350)
                        async def delayed_hide():
                            import trezor.loop as loop
                            await loop.sleep(400)
                            display.cover_background_hide()
                            display.cover_background_set_visible(False)
                        import trezor.loop as loop
                        loop.schedule(delayed_hide())
                        
                except Exception as e:
                    print(f"AppDrawer: Error in UP gesture: {e}")
                    
            elif _dir == lv.DIR.BOTTOM:
                print("AppDrawer: DOWN gesture - showing layer2")
                try:
                    from trezorui import Display
                    display = Display()
                    
                    if hasattr(display, 'cover_background_is_visible') and not display.cover_background_is_visible():
                        if hasattr(display, 'cover_background_load_jpeg'):
                            display.cover_background_load_jpeg("/res/wallpaper-1.jpg")
                        
                        if hasattr(display, 'cover_background_animate_to_y'):
                            display.cover_background_move_to_y(-800)
                            display.cover_background_set_visible(True)
                            display.cover_background_animate_to_y(0, 350)
                        
                        # 切换背景
                        new_change_background_image("/res/wallpaper-1.jpg")
                        
                        # 延迟隐藏AppDrawer
                        async def delayed_dismiss():
                            import trezor.loop as loop
                            await loop.sleep(400)
                            app_drawer.dismiss()
                        import trezor.loop as loop
                        loop.schedule(delayed_dismiss())
                        
                except Exception as e:
                    print(f"AppDrawer: Error in DOWN gesture: {e}")
            
            elif _dir in [lv.DIR.LEFT, lv.DIR.RIGHT]:
                # 页面切换
                if hasattr(app_drawer, 'indicators') and app_drawer.indicators:
                    app_drawer.indicators[app_drawer.current_page].set_active(False)
                    if _dir == lv.DIR.LEFT:
                        page_idx = (app_drawer.current_page + 1) % app_drawer.PAGE_SIZE
                    else:
                        page_idx = (app_drawer.current_page - 1 + app_drawer.PAGE_SIZE) % app_drawer.PAGE_SIZE
                    app_drawer.indicators[page_idx].set_active(True)
                    app_drawer.show_page(page_idx)
    
    # 3. 修复show方法
    original_show = app_drawer.show
    def new_show():
        if app_drawer.visible:
            return
        print("AppDrawer: show() called")
        app_drawer.visible = True  # 先设置visible
        app_drawer.clear_flag(lv.obj.FLAG.HIDDEN)
        app_drawer.add_flag(lv.obj.FLAG.CLICKABLE)
        original_show()  # 调用原始方法
        print("AppDrawer: Now visible and ready")
    
    # 4. 应用修复
    app_drawer.change_background_image = new_change_background_image
    app_drawer.on_gesture = new_on_gesture
    app_drawer.show = new_show
    
    # 5. 设置正确的初始背景
    new_change_background_image("/res/wallpaper-1.jpg")
    
    # 6. 刷新显示
    lv.refr_now(None)
    
    print("✅ 修复完成！")
    print("\n使用方法：")
    print("1. 在主屏幕向上滑动 -> 显示AppDrawer")
    print("2. 在AppDrawer向上滑动 -> 隐藏layer2，背景变为wallpaper-2.jpg")
    print("3. 在AppDrawer向下滑动 -> 显示layer2，背景变为wallpaper-1.jpg")
    
except Exception as e:
    print(f"❌ 修复失败: {e}")
    import traceback
    traceback.print_exc()