"""
测试LTDC Layer 1在屏幕中心显示
在设备的MicroPython REPL中运行：
exec(open('test_layer1_center.py').read())
"""

import lvgldrv
import lvgl as lv
import time

def test_layer1_center_display():
    """测试Layer 1在屏幕中心显示彩色方块"""
    print("=== 测试Layer 1中心显示 ===")
    
    # 步骤1：初始化Layer 1
    print("1. 初始化Layer 1...")
    lvgldrv.layer1_init()
    
    # 步骤2：填充Layer 1缓冲区为红色
    print("2. 填充Layer 1缓冲区为红色...")
    lvgldrv.layer1_fill_color(0xF800)  # 红色 RGB565
    
    # 步骤3：启用Layer 1
    print("3. 启用Layer 1...")
    lvgldrv.layer1_enable(1)
    
    print("应该看到屏幕中心有一个200x200的红色方块")
    time.sleep_ms(3000)
    
    # 步骤4：改变颜色
    print("4. 改变为绿色...")
    lvgldrv.layer1_fill_color(0x07E0)  # 绿色 RGB565
    time.sleep_ms(2000)
    
    print("5. 改变为蓝色...")
    lvgldrv.layer1_fill_color(0x001F)  # 蓝色 RGB565
    time.sleep_ms(2000)
    
    # 步骤5：测试位置移动
    print("6. 测试位置移动...")
    # 移动到左上角
    lvgldrv.layer1_set_position(50, 50)
    time.sleep_ms(1000)
    
    # 移动到右上角
    lvgldrv.layer1_set_position(230, 50)  # 480-200-50 = 230
    time.sleep_ms(1000)
    
    # 移动到右下角
    lvgldrv.layer1_set_position(230, 550)  # 800-200-50 = 550
    time.sleep_ms(1000)
    
    # 移动到左下角
    lvgldrv.layer1_set_position(50, 550)
    time.sleep_ms(1000)
    
    # 回到中心
    lvgldrv.layer1_set_position(140, 300)
    time.sleep_ms(1000)
    
    # 步骤6：测试尺寸变化
    print("7. 测试尺寸变化...")
    lvgldrv.layer1_set_size(100, 100)  # 缩小到100x100
    time.sleep_ms(1000)
    
    lvgldrv.layer1_set_size(300, 200)  # 放大到300x200
    time.sleep_ms(1000)
    
    lvgldrv.layer1_set_size(200, 200)  # 恢复到200x200
    time.sleep_ms(1000)
    
    # 步骤7：禁用Layer 1
    print("8. 禁用Layer 1...")
    lvgldrv.layer1_enable(0)
    
    print("测试完成！")

def create_test_pattern():
    """创建渐变测试图案"""
    print("创建渐变测试图案...")
    
    # 创建从红到蓝的渐变
    for i in range(200):
        # 计算渐变颜色 (从红色0xF800到蓝色0x001F)
        red_component = (31 * (200 - i)) // 200  # 红色分量递减
        blue_component = (31 * i) // 200         # 蓝色分量递增
        color = (red_component << 11) | blue_component
        
        # 填充一行
        # 这里需要更精细的控制，暂时简化为整体颜色变化
        pass

if __name__ == "__main__":
    print("开始Layer 1中心显示测试")
    print("=" * 40)
    
    test_layer1_center_display()
    
    print("\n测试说明：")
    print("1. 如果看到红/绿/蓝色方块在屏幕中心显示，说明Layer 1工作正常")
    print("2. 如果方块能正确移动到四个角落，说明位置控制正常")
    print("3. 如果方块大小能正确变化，说明尺寸控制正常")
    print("4. 如果最后方块消失，说明enable/disable正常")
    print("5. 如果出现黑框或其他异常，需要进一步调试")