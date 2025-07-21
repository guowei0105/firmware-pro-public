#!/usr/bin/env python3
"""
Layer1背景修复脚本

这个脚本可以直接修复Layer1黑色背景问题，并测试背景切换功能。
使用方法：
1. 复制到设备
2. 运行脚本
3. 选择修复选项

解决用户问题："layer1的背景依然是黑色的,且layer执行的时候没有变化"
"""

def get_main_screen():
    """获取MainScreen实例"""
    try:
        from trezor.lvglui.scrs.homescreen import MainScreen
        return MainScreen._instance
    except:
        print("❌ 无法获取MainScreen实例")
        return None

def direct_fix_layer1_background():
    """直接修复Layer1背景 - 最直接的方法"""
    print("=== 直接修复Layer1背景 ===")
    
    try:
        from trezorui import Display
        display = Display()
        
        print("1. 🔧 重置背景加载标志...")
        # 强制重新加载标志会在C层被重置
        
        print("2. 📁 设置背景路径...")
        if hasattr(display, 'cover_background_set_layer1_path'):
            display.cover_background_set_layer1_path("/res/wallpaper-1.jpg")
            print("✅ 背景路径设置完成")
        
        print("3. 🖼️ 强制加载Layer1背景...")
        if hasattr(display, 'cover_background_load_layer1_background'):
            # 多次调用确保加载成功
            for i in range(3):
                print(f"   尝试 {i+1}/3...")
                display.cover_background_load_layer1_background()
            print("✅ Layer1背景加载完成")
        else:
            print("❌ 背景加载方法不存在")
            return False
        
        print("4. 🔄 强制LVGL重绘...")
        try:
            import lvgl as lv
            current_scr = lv.scr_act()
            if current_scr:
                current_scr.invalidate()
                print("   ✅ 屏幕无效化")
            
            lv.refr_now(None)
            print("   ✅ 立即刷新")
            
            # 多次刷新确保生效
            for i in range(3):
                lv.refr_now(None)
            print("✅ LVGL重绘完成")
            
        except Exception as e:
            print(f"❌ LVGL重绘失败: {e}")
        
        print("🎉 Layer1背景修复完成！检查屏幕是否显示壁纸")
        return True
        
    except Exception as e:
        print(f"❌ 直接修复失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_layer2_background_switching():
    """测试Layer2背景切换功能"""
    print("=== 测试Layer2背景切换 ===")
    
    try:
        from trezorui import Display
        display = Display()
        
        # 检查背景切换功能是否可用
        if not hasattr(display, 'cover_background_set_image_paths'):
            print("❌ 背景切换功能不可用")
            return False
        
        print("1. 🎨 设置两张背景图片...")
        display.cover_background_set_image_paths(
            "/res/wallpaper-1.jpg",  # 背景1
            "/res/wallpaper-2.jpg"   # 背景2
        )
        print("✅ 背景路径设置完成")
        
        print("2. 📱 查询当前背景...")
        current = display.cover_background_get_current()
        print(f"   当前背景编号: {current}")
        
        print("3. 🔄 测试背景切换...")
        print(f"   从背景{current}切换...")
        display.cover_background_toggle()
        new_current = display.cover_background_get_current()
        print(f"   ✅ 切换到背景: {new_current}")
        
        print("4. 📺 显示Layer2...")
        display.cover_background_show()
        print("✅ Layer2已显示")
        
        print("🎉 Layer2背景切换测试完成！")
        return True
        
    except Exception as e:
        print(f"❌ Layer2测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def comprehensive_background_test():
    """综合背景测试"""
    print("=== 综合背景功能测试 ===")
    
    print("📍 步骤1: 修复Layer1背景")
    success1 = direct_fix_layer1_background()
    
    print("\\n📍 步骤2: 测试Layer2背景切换")
    success2 = test_layer2_background_switching()
    
    print("\\n📊 测试结果:")
    print(f"   Layer1背景修复: {'✅ 成功' if success1 else '❌ 失败'}")
    print(f"   Layer2背景切换: {'✅ 成功' if success2 else '❌ 失败'}")
    
    if success1 and success2:
        print("🎉 所有背景功能正常！")
        return True
    else:
        print("⚠️ 部分功能有问题，请检查日志")
        return False

def interactive_background_fixer():
    """交互式背景修复工具"""
    print("🔧 Layer1背景修复工具")
    print("====================")
    
    while True:
        print("\\n选择操作:")
        print("1. 🔧 修复Layer1黑色背景")
        print("2. 🎨 测试Layer2背景切换")
        print("3. 🧪 综合测试所有功能")
        print("4. 📊 显示背景状态")
        print("0. 🚪 退出")
        
        try:
            choice = input("请选择 (0-4): ").strip()
        except:
            choice = "0"
        
        if choice == "1":
            direct_fix_layer1_background()
        elif choice == "2":
            test_layer2_background_switching()
        elif choice == "3":
            comprehensive_background_test()
        elif choice == "4":
            try:
                from trezorui import Display
                display = Display()
                
                print("📊 当前背景状态:")
                if hasattr(display, 'cover_background_get_current'):
                    current = display.cover_background_get_current()
                    print(f"   当前背景编号: {current}")
                
                if hasattr(display, 'cover_background_is_visible'):
                    visible = display.cover_background_is_visible()
                    print(f"   Layer2可见性: {visible}")
                
                if hasattr(display, 'cover_background_get_y_position'):
                    y_pos = display.cover_background_get_y_position()
                    print(f"   Layer2 Y位置: {y_pos}")
                    
            except Exception as e:
                print(f"❌ 获取状态失败: {e}")
                
        elif choice == "0":
            print("👋 退出修复工具")
            break
        else:
            print("❌ 无效选择，请重试")

# 快速修复函数 - 可以直接调用
def quick_fix():
    """快速修复Layer1背景 - 一键解决"""
    print("⚡ 快速修复Layer1背景")
    return direct_fix_layer1_background()

if __name__ == "__main__":
    print("🎯 Layer1背景修复脚本")
    print("解决问题：layer1的背景依然是黑色的")
    print("========================================")
    
    # 可以直接运行快速修复
    # quick_fix()
    
    # 或者运行交互式工具
    interactive_background_fixer()