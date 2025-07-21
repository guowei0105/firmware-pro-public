#!/usr/bin/env python3
"""
简化的背景切换实现方案
根据用户需求：
1. layer2向上滑动时，layer1背景换成wallpaper-2.jpg
2. layer2向下滑动到底部时，layer1背景换成wallpaper-1.jpg
"""

# 实现方案分析：

"""
当前问题：
1. AppDrawer（layer1）不可见时仍接收手势事件
2. MainScreen和AppDrawer的手势处理混乱
3. 背景切换逻辑没有正确触发

正确的流程应该是：
1. MainScreen接收UP手势 -> 显示AppDrawer
2. AppDrawer可见时接收UP手势 -> 隐藏layer2并切换背景到wallpaper-2
3. AppDrawer可见时接收DOWN手势 -> 显示layer2并切换背景到wallpaper-1，然后隐藏AppDrawer

需要修改的地方：
1. MainScreen的on_gesture方法 - 处理显示AppDrawer
2. AppDrawer的on_gesture方法 - 只在可见时处理手势
3. AppDrawer的change_background_image方法 - 确保背景正确切换
"""

# homescreen.py 需要的修改：

# 1. MainScreen.on_gesture - 简化版本
def mainscreen_on_gesture(self, event_obj):
    """Handle gestures - only for showing AppDrawer"""
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

# 2. AppDrawer.on_gesture - 修复版本
def appdrawer_on_gesture(self, event_obj):
    code = event_obj.code
    
    # 只有在AppDrawer可见时才处理手势
    if not self.visible:
        return
        
    if code == lv.EVENT.GESTURE:
        indev = lv.indev_get_act()
        _dir = indev.get_gesture_dir()
        
        if _dir == lv.DIR.TOP:
            # UP gesture - Hide layer2 and change background
            print("AppDrawer: UP gesture - hiding layer2")
            try:
                from trezorui import Display
                display = Display()
                
                # 切换背景到wallpaper-2.jpg
                self.change_background_image("/res/wallpaper-2.jpg")
                
                # 隐藏layer2
                if hasattr(display, 'cover_background_is_visible'):
                    if not display.cover_background_is_visible():
                        # layer2已经隐藏，向上滑出
                        if hasattr(display, 'cover_background_animate_to_y'):
                            display.cover_background_set_visible(True)
                            display.cover_background_animate_to_y(-800, 350)
                    else:
                        # layer2可见，隐藏它
                        if hasattr(display, 'cover_background_animate_to_y'):
                            display.cover_background_animate_to_y(-800, 350)
                            # 延迟隐藏
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
                
                # 显示layer2
                if hasattr(display, 'cover_background_is_visible') and not display.cover_background_is_visible():
                    # 加载壁纸
                    if hasattr(display, 'cover_background_load_jpeg'):
                        display.cover_background_load_jpeg("/res/wallpaper-1.jpg")
                    
                    # 动画显示
                    if hasattr(display, 'cover_background_animate_to_y'):
                        display.cover_background_move_to_y(-800)
                        display.cover_background_set_visible(True)
                        display.cover_background_animate_to_y(0, 350)
                    
                    # 切换背景到wallpaper-1.jpg
                    self.change_background_image("/res/wallpaper-1.jpg")
                    
                    # 延迟隐藏AppDrawer
                    async def delayed_dismiss():
                        import trezor.loop as loop
                        await loop.sleep(400)
                        self.dismiss()
                    import trezor.loop as loop
                    loop.schedule(delayed_dismiss())
                    
            except Exception as e:
                print(f"AppDrawer: Error in DOWN gesture: {e}")

# 3. AppDrawer.change_background_image - 简化版本
def change_background_image(self, image_path):
    """Change the background image of the AppDrawer"""
    print(f"AppDrawer: Changing background to: {image_path}")
    
    try:
        # 确保路径有A:前缀
        if not image_path.startswith("A:"):
            image_path = f"A:{image_path}"
        
        # 移除所有样式
        self.remove_style_all()
        
        # 重新应用基础样式（黑色背景）
        from trezor.lvglui.widgets.style import StyleWrapper
        from trezor.lvglui.lv_colors import lv_colors
        
        self.add_style(
            StyleWrapper().bg_opa(lv.OPA.COVER).bg_color(lv_colors.BLACK).border_width(0),
            0,
        )
        
        # 应用新的背景图片
        self.add_style(
            StyleWrapper().bg_img_src(image_path).border_width(0),
            0,
        )
        
        # 强制刷新
        self.invalidate()
        
        print(f"AppDrawer: Background changed successfully")
    except Exception as e:
        print(f"AppDrawer: Error changing background: {e}")