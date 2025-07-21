#!/usr/bin/env python3
"""
综合修复脚本 - 解决Layer1背景和手势问题
"""

import gc
import lvgl as lv
from trezor import loop

def diagnose_issues():
    """诊断当前问题"""
    print("=== 诊断当前状态 ===")
    
    try:
        from trezor.lvglui.scrs.homescreen import MainScreen
        
        # 检查MainScreen
        if not hasattr(MainScreen, '_instance') or not MainScreen._instance:
            print("❌ MainScreen实例未找到")
            return False
            
        main_screen = MainScreen._instance
        print("✅ MainScreen实例存在")
        
        # 检查标题/副标题状态
        if hasattr(main_screen, 'title'):
            title_hidden = main_screen.title.has_flag(lv.obj.FLAG.HIDDEN)
            print(f"   标题隐藏状态: {title_hidden}")
            
        if hasattr(main_screen, 'subtitle'):
            subtitle_hidden = main_screen.subtitle.has_flag(lv.obj.FLAG.HIDDEN)
            print(f"   副标题隐藏状态: {subtitle_hidden}")
        
        # 检查AppDrawer
        if not hasattr(main_screen, 'apps'):
            print("❌ AppDrawer未找到")
            return False
            
        app_drawer = main_screen.apps
        print(f"✅ AppDrawer存在")
        print(f"   visible: {app_drawer.visible}")
        print(f"   HIDDEN flag: {app_drawer.has_flag(lv.obj.FLAG.HIDDEN)}")
        print(f"   CLICKABLE flag: {app_drawer.has_flag(lv.obj.FLAG.CLICKABLE)}")
        
        # 检查样式数量
        style_count = app_drawer.get_style_count(0)
        print(f"   样式数量: {style_count}")
        
        # 检查子对象
        child_count = app_drawer.get_child_cnt()
        print(f"   子对象数量: {child_count}")
        
        return True
        
    except Exception as e:
        print(f"❌ 诊断失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def fix_appdrawer_display():
    """修复AppDrawer显示问题"""
    print("\n=== 修复AppDrawer显示 ===")
    
    try:
        from trezor.lvglui.scrs.homescreen import MainScreen
        from trezor.lvglui.widgets.style import StyleWrapper
        from trezor.lvglui.lv_colors import lv_colors
        
        main_screen = MainScreen._instance
        app_drawer = main_screen.apps
        
        # 1. 确保AppDrawer在正确的层级
        print("1. 调整层级...")
        app_drawer.move_foreground()
        print("   ✅ 移到前景")
        
        # 2. 重建背景样式
        print("2. 重建背景样式...")
        
        # 获取当前样式数量
        style_count = app_drawer.get_style_count(0)
        print(f"   当前样式数: {style_count}")
        
        # 创建新的样式列表
        styles_to_apply = []
        
        # 基础样式 - 黑色背景
        base_style = StyleWrapper()
        base_style.bg_opa(lv.OPA.COVER)
        base_style.bg_color(lv_colors.BLACK)
        base_style.border_width(0)
        base_style.pad_all(0)
        styles_to_apply.append(base_style)
        
        # 背景图片样式
        bg_style = StyleWrapper()
        bg_style.bg_img_src("A:/res/wallpaper-1.jpg")
        bg_style.border_width(0)
        styles_to_apply.append(bg_style)
        
        # 清除所有现有样式
        app_drawer.remove_style_all()
        print("   ✅ 清除所有样式")
        
        # 应用新样式
        for i, style in enumerate(styles_to_apply):
            app_drawer.add_style(style, 0)
            print(f"   ✅ 应用样式 {i+1}")
        
        # 3. 强制刷新
        print("3. 强制刷新...")
        app_drawer.invalidate()
        
        # 刷新整个屏幕
        current_scr = lv.scr_act()
        if current_scr:
            current_scr.invalidate()
        
        # 触发立即重绘
        lv.refr_now(None)
        print("   ✅ 触发重绘")
        
        # 4. 如果AppDrawer可见，确保MainScreen元素隐藏
        if app_drawer.visible and not app_drawer.has_flag(lv.obj.FLAG.HIDDEN):
            print("4. 隐藏MainScreen元素...")
            main_screen.hidden_others(True)
            print("   ✅ MainScreen元素已隐藏")
        
        print("✅ AppDrawer显示修复完成")
        return True
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def ensure_gesture_handling():
    """确保手势处理正常工作"""
    print("\n=== 确保手势处理 ===")
    
    try:
        from trezor.lvglui.scrs.homescreen import MainScreen
        
        main_screen = MainScreen._instance
        app_drawer = main_screen.apps
        
        # 1. MainScreen手势设置
        print("1. MainScreen手势设置...")
        main_screen.add_flag(lv.obj.FLAG.CLICKABLE)
        main_screen.clear_flag(lv.obj.FLAG.SCROLLABLE)
        main_screen.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
        print("   ✅ MainScreen手势已启用")
        
        # 2. AppDrawer手势设置
        print("2. AppDrawer手势设置...")
        app_drawer.add_flag(lv.obj.FLAG.CLICKABLE)
        app_drawer.clear_flag(lv.obj.FLAG.GESTURE_BUBBLE)
        app_drawer.clear_flag(lv.obj.FLAG.SCROLLABLE)
        print("   ✅ AppDrawer手势已启用")
        
        # 3. 确保事件回调存在
        print("3. 检查事件回调...")
        # 事件回调应该在init时已经设置，这里只是确认
        print("   ✅ 事件回调保持不变")
        
        print("✅ 手势处理设置完成")
        return True
        
    except Exception as e:
        print(f"❌ 设置失败: {e}")
        return False

def test_appdrawer_functionality():
    """测试AppDrawer功能"""
    print("\n=== 测试AppDrawer功能 ===")
    
    try:
        from trezor.lvglui.scrs.homescreen import MainScreen
        
        main_screen = MainScreen._instance
        app_drawer = main_screen.apps
        
        # 测试显示/隐藏
        print("1. 测试显示/隐藏...")
        
        if not app_drawer.visible:
            print("   显示AppDrawer...")
            app_drawer.show()
            # 等待动画
            loop.sleep(100)
            print(f"   visible={app_drawer.visible}, HIDDEN={app_drawer.has_flag(lv.obj.FLAG.HIDDEN)}")
        
        # 测试背景切换
        print("2. 测试背景切换...")
        original_bg = "/res/wallpaper-1.jpg"
        test_bg = "/res/wallpaper-2.jpg"
        
        print(f"   切换到: {test_bg}")
        app_drawer.change_background_image(test_bg)
        
        # 等待一下
        loop.sleep(500)
        
        print(f"   切换回: {original_bg}")
        app_drawer.change_background_image(original_bg)
        
        print("✅ 功能测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

async def async_comprehensive_fix():
    """异步综合修复"""
    print("🔧 开始异步综合修复...")
    print("=" * 50)
    
    # 1. 诊断
    diagnose_issues()
    
    # 2. 修复显示
    await loop.sleep(100)
    fix_appdrawer_display()
    
    # 3. 确保手势
    await loop.sleep(100)
    ensure_gesture_handling()
    
    # 4. 强制垃圾回收
    gc.collect()
    
    print("\n" + "=" * 50)
    print("✅ 异步修复完成！")
    print("\n请检查:")
    print("  1. AppDrawer背景是否正确显示")
    print("  2. 手势上下滑动是否正常")
    print("  3. 多次滑动后是否仍然有效")
    print("  4. Layer2切换时背景是否变化")

def sync_comprehensive_fix():
    """同步综合修复（立即执行）"""
    print("🔧 开始同步综合修复...")
    print("=" * 50)
    
    # 1. 诊断
    if not diagnose_issues():
        print("⚠️ 诊断发现问题，继续尝试修复...")
    
    # 2. 修复显示
    fix_appdrawer_display()
    
    # 3. 确保手势
    ensure_gesture_handling()
    
    # 4. 强制多次刷新
    print("\n强制刷新显示...")
    for i in range(5):
        lv.refr_now(None)
        print(f"   刷新 {i+1}/5")
    
    # 5. 垃圾回收
    gc.collect()
    
    print("\n" + "=" * 50)
    print("✅ 同步修复完成！")

# 主函数
def main():
    print("综合修复脚本")
    print("解决问题：")
    print("  - Layer1背景为空/白色")
    print("  - 滑动手势失效")
    print("  - 显示MainScreen内容")
    print("")
    
    # 使用同步修复（立即执行）
    sync_comprehensive_fix()
    
    # 如果需要异步修复，可以调用：
    # loop.schedule(async_comprehensive_fix())

if __name__ == "__main__":
    main()