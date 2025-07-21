#!/usr/bin/env python3
"""
完整的修复方案 - 解决手势处理混乱和背景切换问题
"""

def complete_fix():
    """应用完整的修复"""
    print("=== 应用完整修复方案 ===")
    
    try:
        from trezor.lvglui.scrs.homescreen import MainScreen
        
        # 1. 获取MainScreen实例
        if not hasattr(MainScreen, '_instance') or not MainScreen._instance:
            print("❌ MainScreen未初始化")
            return False
            
        main_screen = MainScreen._instance
        app_drawer = main_screen.apps if hasattr(main_screen, 'apps') else None
        
        if not app_drawer:
            print("❌ AppDrawer未找到")
            return False
            
        print("✅ 找到MainScreen和AppDrawer")
        
        # 2. 修复AppDrawer的change_background_image方法
        print("\n🔧 修复背景切换方法...")
        
        def fixed_change_background_image(self, image_path):
            """修复版的背景切换方法"""
            print(f"AppDrawer: Changing background to: {image_path}")
            
            try:
                # Ensure path has A: prefix
                if not image_path.startswith("A:"):
                    image_path = f"A:{image_path}"
                
                # Remove all styles
                self.remove_style_all()
                
                # Re-apply base style (black background)
                from trezor.lvglui.widgets.style import StyleWrapper
                from trezor.lvglui.lv_colors import lv_colors
                
                self.add_style(
                    StyleWrapper().bg_opa(lv.OPA.COVER).bg_color(lv_colors.BLACK).border_width(0),
                    0,
                )
                
                # Apply new background image
                self.add_style(
                    StyleWrapper().bg_img_src(image_path).border_width(0),
                    0,
                )
                
                # Force refresh
                self.invalidate()
                
                print(f"AppDrawer: Background changed successfully")
            except Exception as e:
                print(f"AppDrawer: Error changing background: {e}")
        
        # 绑定修复后的方法
        app_drawer.change_background_image = fixed_change_background_image.__get__(app_drawer, app_drawer.__class__)
        print("   ✅ change_background_image方法已修复")
        
        # 3. 修复AppDrawer的on_gesture方法
        print("\n🔧 修复AppDrawer手势处理...")
        
        def fixed_on_gesture(self, event_obj):
            """修复版的手势处理"""
            code = event_obj.code
            
            # 只有在AppDrawer可见时才处理手势
            if not self.visible:
                return
                
            if code == lv.EVENT.GESTURE:
                indev = lv.indev_get_act()
                _dir = indev.get_gesture_dir()
                print(f"AppDrawer: Gesture direction: {_dir} (TOP=4, BOTTOM=8)")
                
                if _dir == lv.DIR.TOP:
                    # UP gesture - Hide layer2 and change background
                    print("AppDrawer: UP gesture - hiding layer2")
                    try:
                        from trezorui import Display
                        display = Display()
                        
                        # Change background to wallpaper-2.jpg
                        self.change_background_image("/res/wallpaper-2.jpg")
                        
                        # Hide layer2 with animation
                        if hasattr(display, 'cover_background_is_visible'):
                            if not display.cover_background_is_visible():
                                # layer2 already hidden, slide it up
                                if hasattr(display, 'cover_background_animate_to_y'):
                                    display.cover_background_set_visible(True)
                                    display.cover_background_animate_to_y(-800, 350)
                            else:
                                # layer2 visible, hide it
                                if hasattr(display, 'cover_background_animate_to_y'):
                                    display.cover_background_animate_to_y(-800, 350)
                                    # Delayed hide
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
                    # DOWN gesture - Show layer2 and change background
                    print("AppDrawer: DOWN gesture - showing layer2")
                    try:
                        from trezorui import Display
                        display = Display()
                        
                        # Show layer2
                        if hasattr(display, 'cover_background_is_visible') and not display.cover_background_is_visible():
                            # Load wallpaper
                            if hasattr(display, 'cover_background_load_jpeg'):
                                display.cover_background_load_jpeg("/res/wallpaper-1.jpg")
                            
                            # Animate in
                            if hasattr(display, 'cover_background_animate_to_y'):
                                display.cover_background_move_to_y(-800)
                                display.cover_background_set_visible(True)
                                display.cover_background_animate_to_y(0, 350)
                            
                            # Change background to wallpaper-1.jpg
                            self.change_background_image("/res/wallpaper-1.jpg")
                            
                            # Delayed dismiss AppDrawer
                            async def delayed_dismiss():
                                import trezor.loop as loop
                                await loop.sleep(400)
                                self.dismiss()
                            import trezor.loop as loop
                            loop.schedule(delayed_dismiss())
                            
                    except Exception as e:
                        print(f"AppDrawer: Error in DOWN gesture: {e}")
                        
                elif _dir in [lv.DIR.LEFT, lv.DIR.RIGHT]:
                    # Handle page switching
                    if hasattr(self, 'indicators') and self.indicators:
                        self.indicators[self.current_page].set_active(False)
                        if _dir == lv.DIR.LEFT:
                            page_idx = (self.current_page + 1) % self.PAGE_SIZE
                        else:
                            page_idx = (self.current_page - 1 + self.PAGE_SIZE) % self.PAGE_SIZE
                        self.indicators[page_idx].set_active(True)
                        self.show_page(page_idx)
        
        # 绑定修复后的方法
        app_drawer.on_gesture = fixed_on_gesture.__get__(app_drawer, app_drawer.__class__)
        print("   ✅ on_gesture方法已修复")
        
        # 4. 修复show方法
        print("\n🔧 修复show方法...")
        
        def fixed_show(self):
            """修复版的show方法"""
            if self.visible:
                return
            print("AppDrawer: show() called")
            self.visible = True  # Set visible FIRST
            self.parent.add_state(lv.STATE.USER_1)
            self.show_anim.start()
            self.slide = False
            # Ensure AppDrawer is clickable and can receive gestures
            self.clear_flag(lv.obj.FLAG.HIDDEN)
            self.add_flag(lv.obj.FLAG.CLICKABLE)
            print("AppDrawer: Now visible and ready for gestures")
        
        # 绑定修复后的方法
        app_drawer.show = fixed_show.__get__(app_drawer, app_drawer.__class__)
        print("   ✅ show方法已修复")
        
        # 5. 修复MainScreen的on_gesture方法
        print("\n🔧 修复MainScreen手势处理...")
        
        def fixed_mainscreen_on_gesture(self, event_obj):
            """修复版的MainScreen手势处理"""
            code = event_obj.code
            if code == lv.EVENT.GESTURE:
                try:
                    indev = lv.indev_get_act()
                    if indev:
                        _dir = indev.get_gesture_dir()
                        
                        if _dir == lv.DIR.TOP:
                            # UP gesture - Show AppDrawer
                            if hasattr(self, 'apps') and not self.apps.visible:
                                print("MainScreen: UP gesture - showing AppDrawer")
                                self.apps.show()
                                
                except Exception as e:
                    print(f"MainScreen: Error in gesture: {e}")
        
        # 绑定修复后的方法
        main_screen.on_gesture = fixed_mainscreen_on_gesture.__get__(main_screen, main_screen.__class__)
        print("   ✅ MainScreen on_gesture方法已修复")
        
        # 6. 确保手势状态正确
        print("\n🔧 设置手势状态...")
        import lvgl as lv
        
        # MainScreen设置
        main_screen.add_flag(lv.obj.FLAG.CLICKABLE)
        main_screen.clear_flag(lv.obj.FLAG.SCROLLABLE)
        main_screen.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
        print("   ✅ MainScreen手势设置完成")
        
        # AppDrawer设置
        app_drawer.add_flag(lv.obj.FLAG.CLICKABLE)
        app_drawer.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
        app_drawer.clear_flag(lv.obj.FLAG.SCROLLABLE)
        print("   ✅ AppDrawer手势设置完成")
        
        # 7. 刷新显示
        print("\n🔄 刷新显示...")
        lv.refr_now(None)
        
        print("\n✅ 所有修复已应用！")
        print("\n现在的功能：")
        print("  1. MainScreen UP手势 -> 显示AppDrawer")
        print("  2. AppDrawer UP手势 -> 隐藏layer2，背景切换到wallpaper-2.jpg")
        print("  3. AppDrawer DOWN手势 -> 显示layer2，背景切换到wallpaper-1.jpg，然后隐藏AppDrawer")
        print("  4. 只有AppDrawer可见时才处理其手势")
        
        return True
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
        return False

# 运行修复
if __name__ == "__main__":
    print("完整修复方案 - 解决手势和背景切换问题")
    print("=" * 50)
    complete_fix()