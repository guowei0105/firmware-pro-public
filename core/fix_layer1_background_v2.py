#!/usr/bin/env python3
"""
Layer1背景修复脚本 v2
解决问题：
1. layer1背景为空/白色
2. 滑动几次后手势失效
3. 显示MainScreen _init()的内容

这个脚本直接修复运行时的问题
"""

import gc
import lvgl as lv
from trezor.lvglui.scrs.homescreen import MainScreen

def fix_appdrawer_background():
    """修复AppDrawer背景显示问题"""
    print("=== 修复AppDrawer背景 ===")
    
    try:
        # 获取MainScreen实例
        main_screen = MainScreen._instance
        if not main_screen:
            print("❌ MainScreen实例未找到")
            return False
            
        # 获取AppDrawer
        if not hasattr(main_screen, 'apps'):
            print("❌ AppDrawer未找到")
            return False
            
        app_drawer = main_screen.apps
        print(f"✅ 找到AppDrawer，visible={app_drawer.visible}")
        
        # 修复1：确保AppDrawer有正确的背景
        print("🔧 修复背景显示...")
        
        # 移除所有样式并重新应用
        app_drawer.remove_style_all()
        
        # 1. 基础黑色背景
        from trezor.lvglui.widgets.style import StyleWrapper
        from trezor.lvglui.lv_colors import lv_colors
        
        app_drawer.add_style(
            StyleWrapper().bg_opa(lv.OPA.COVER).bg_color(lv_colors.BLACK).border_width(0),
            0,
        )
        print("   ✅ 设置基础黑色背景")
        
        # 2. 设置背景图片
        try:
            app_drawer.add_style(
                StyleWrapper().bg_img_src("A:/res/wallpaper-1.jpg").border_width(0),
                0,
            )
            print("   ✅ 设置背景图片 wallpaper-1.jpg")
        except Exception as e:
            print(f"   ❌ 设置背景图片失败: {e}")
            
        # 3. 强制刷新
        app_drawer.invalidate()
        print("   ✅ 触发界面刷新")
        
        # 修复2：确保手势事件正常工作
        print("🔧 修复手势处理...")
        
        # 确保AppDrawer始终可点击和可手势
        app_drawer.add_flag(lv.obj.FLAG.CLICKABLE)
        app_drawer.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
        print("   ✅ 设置CLICKABLE标志")
        print("   ✅ 清除GESTURE_BUBBLE标志")
        
        # 确保MainScreen也能处理手势
        main_screen.add_flag(lv.obj.FLAG.CLICKABLE)
        main_screen.clear_flag(lv.obj.FLAG.SCROLLABLE)
        print("   ✅ MainScreen手势设置完成")
        
        # 修复3：重新绑定事件回调（如果需要）
        # AppDrawer的事件回调应该已经在init时设置
        
        # 如果AppDrawer当前可见，触发完整刷新
        if app_drawer.visible:
            print("🔄 AppDrawer当前可见，触发完整刷新...")
            # 获取当前屏幕并刷新
            current_scr = lv.scr_act()
            if current_scr:
                current_scr.invalidate()
            lv.refr_now(None)
            print("   ✅ 屏幕刷新完成")
            
        print("✅ AppDrawer修复完成！")
        return True
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_background_switching():
    """测试背景切换功能"""
    print("\n=== 测试背景切换 ===")
    
    try:
        main_screen = MainScreen._instance
        if not main_screen or not hasattr(main_screen, 'apps'):
            print("❌ 无法获取AppDrawer")
            return False
            
        app_drawer = main_screen.apps
        
        # 如果AppDrawer不可见，先显示它
        if not app_drawer.visible:
            print("📱 显示AppDrawer...")
            app_drawer.show()
            
        # 测试切换背景
        print("🎨 测试背景切换...")
        
        # 切换到wallpaper-2
        print("   切换到 wallpaper-2.jpg...")
        app_drawer.change_background_image("/res/wallpaper-2.jpg")
        
        # 等待一下
        import time
        time.sleep(1)
        
        # 切换回wallpaper-1
        print("   切换回 wallpaper-1.jpg...")
        app_drawer.change_background_image("/res/wallpaper-1.jpg")
        
        print("✅ 背景切换测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_gesture_state():
    """检查手势状态"""
    print("\n=== 检查手势状态 ===")
    
    try:
        main_screen = MainScreen._instance
        if not main_screen:
            print("❌ MainScreen未找到")
            return
            
        print(f"MainScreen:")
        print(f"  - CLICKABLE: {main_screen.has_flag(lv.obj.FLAG.CLICKABLE)}")
        print(f"  - SCROLLABLE: {main_screen.has_flag(lv.obj.FLAG.SCROLLABLE)}")
        print(f"  - GESTURE_BUBBLE: {main_screen.has_flag(lv.obj.FLAG.GESTURE_BUBBLE)}")
        
        if hasattr(main_screen, 'apps'):
            app_drawer = main_screen.apps
            print(f"\nAppDrawer:")
            print(f"  - visible: {app_drawer.visible}")
            print(f"  - HIDDEN: {app_drawer.has_flag(lv.obj.FLAG.HIDDEN)}")
            print(f"  - CLICKABLE: {app_drawer.has_flag(lv.obj.FLAG.CLICKABLE)}")
            print(f"  - SCROLLABLE: {app_drawer.has_flag(lv.obj.FLAG.SCROLLABLE)}")
            print(f"  - GESTURE_BUBBLE: {app_drawer.has_flag(lv.obj.FLAG.GESTURE_BUBBLE)}")
            
    except Exception as e:
        print(f"❌ 检查失败: {e}")

def force_refresh_display():
    """强制刷新显示"""
    print("\n=== 强制刷新显示 ===")
    
    try:
        # 多次刷新确保生效
        for i in range(3):
            lv.refr_now(None)
            print(f"   刷新 {i+1}/3")
            
        # 触发垃圾回收
        gc.collect()
        print("✅ 显示刷新完成")
        
    except Exception as e:
        print(f"❌ 刷新失败: {e}")

def comprehensive_fix():
    """综合修复所有问题"""
    print("🔧 开始综合修复...")
    print("=" * 40)
    
    # 1. 修复AppDrawer背景
    success1 = fix_appdrawer_background()
    
    # 2. 检查手势状态
    check_gesture_state()
    
    # 3. 强制刷新显示
    force_refresh_display()
    
    # 4. 可选：测试背景切换
    # test_background_switching()
    
    print("\n" + "=" * 40)
    if success1:
        print("✅ 修复完成！请检查:")
        print("  1. AppDrawer背景是否显示")
        print("  2. 手势是否正常工作")
        print("  3. 多次滑动是否仍然有效")
    else:
        print("⚠️ 部分修复可能失败，请查看错误信息")

# 运行修复
if __name__ == "__main__":
    print("Layer1背景修复脚本 v2")
    print("解决：背景空白和手势失效问题")
    print("")
    comprehensive_fix()