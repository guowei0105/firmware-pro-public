#!/usr/bin/env python3

from PIL import Image, ImageDraw

def create_optimized_msg_icon():
    """创建专门为48x48优化的消息图标"""
    
    # 创建48x48的图像，黑色背景
    img = Image.new('RGB', (48, 48), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 设计一个清晰的信息图标 (i)
    # 使用白色 (255, 255, 255)
    white = (255, 255, 255)
    
    # 绘制字母 "i" 的点部分 (上方的圆点)
    # 位置: 中心偏上
    center_x = 24
    dot_y = 12
    dot_radius = 3
    
    # 绘制圆点
    draw.ellipse([center_x - dot_radius, dot_y - dot_radius, 
                  center_x + dot_radius, dot_y + dot_radius], fill=white)
    
    # 绘制字母 "i" 的竖线部分
    line_width = 4
    line_start_y = 20
    line_end_y = 36
    
    # 绘制竖线
    draw.rectangle([center_x - line_width//2, line_start_y,
                    center_x + line_width//2, line_end_y], fill=white)
    
    return img

def create_clean_geometric_icon():
    """创建一个几何风格的清晰图标"""
    
    img = Image.new('RGB', (48, 48), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    white = (255, 255, 255)
    
    # 绘制一个信息符号 - 圆圈内的 "i"
    # 外圆
    circle_center = 24
    outer_radius = 20
    inner_radius = 16
    
    # 绘制外圆环
    draw.ellipse([circle_center - outer_radius, circle_center - outer_radius,
                  circle_center + outer_radius, circle_center + outer_radius], outline=white, width=2)
    
    # 绘制内部的 "i"
    # 点
    dot_radius = 2
    dot_y = 18
    draw.ellipse([circle_center - dot_radius, dot_y - dot_radius,
                  circle_center + dot_radius, dot_y + dot_radius], fill=white)
    
    # 竖线
    line_width = 3
    line_start_y = 24
    line_end_y = 32
    draw.rectangle([circle_center - line_width//2, line_start_y,
                    circle_center + line_width//2, line_end_y], fill=white)
    
    return img

def convert_to_rgb565_array(img, array_name):
    """将PIL图像转换为RGB565格式的C数组"""
    
    # 转换为RGB模式
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # 转换为RGB565格式
    rgb565_data = []
    white_pixel_count = 0
    
    for y in range(48):
        for x in range(48):
            r, g, b = img.getpixel((x, y))
            
            # 转换为RGB565格式
            r5 = (r >> 3) & 0x1F
            g6 = (g >> 2) & 0x3F  
            b5 = (b >> 3) & 0x1F
            
            rgb565 = (r5 << 11) | (g6 << 5) | b5
            
            # 统计白色像素
            if rgb565 == 0xFFFF:
                white_pixel_count += 1
            
            # 小端序存储
            rgb565_data.append(rgb565 & 0xFF)         # 低字节
            rgb565_data.append((rgb565 >> 8) & 0xFF)  # 高字节
    
    # 生成C数组
    c_array = f"// {array_name} - 48x48 optimized raw RGB565 data\n"
    c_array += f"// White pixels: {white_pixel_count}\n"
    c_array += f"static const uint8_t {array_name}[] = {{\n"
    
    for i in range(0, len(rgb565_data), 16):
        line = "    "
        for j in range(16):
            if i + j < len(rgb565_data):
                line += f"0x{rgb565_data[i + j]:02x}, "
        c_array += line + "\n"
    
    c_array += "};\n"
    
    print(f"Generated array '{array_name}' with {len(rgb565_data)} bytes")
    print(f"White pixels: {white_pixel_count}")
    
    return c_array

def main():
    print("创建优化的48x48消息图标...")
    
    # 方案1: 简单的 "i" 图标
    print("\n=== 方案1: 简洁的 'i' 图标 ===")
    simple_icon = create_optimized_msg_icon()
    simple_icon.save('/home/zhou/Desktop/format/firmware-pro/msg_simple_48x48.png')
    simple_array = convert_to_rgb565_array(simple_icon, "toi_msg_simple_icon")
    
    # 方案2: 几何风格的圆圈+i图标  
    print("\n=== 方案2: 几何风格圆圈图标 ===")
    geometric_icon = create_clean_geometric_icon()
    geometric_icon.save('/home/zhou/Desktop/format/firmware-pro/msg_geometric_48x48.png')
    geometric_array = convert_to_rgb565_array(geometric_icon, "toi_msg_geometric_icon")
    
    # 生成头文件
    header_content = f"""#ifndef ICON_MSG_OPTIMIZED_H
#define ICON_MSG_OPTIMIZED_H

{simple_array}

{geometric_array}

#endif // ICON_MSG_OPTIMIZED_H
"""
    
    with open('/home/zhou/Desktop/format/firmware-pro/core/embed/bootloader/icon_msg_optimized.h', 'w') as f:
        f.write(header_content)
    
    print(f"\n✅ 优化图标已生成:")
    print(f"   - /home/zhou/Desktop/format/firmware-pro/msg_simple_48x48.png")
    print(f"   - /home/zhou/Desktop/format/firmware-pro/msg_geometric_48x48.png") 
    print(f"   - /home/zhou/Desktop/format/firmware-pro/core/embed/bootloader/icon_msg_optimized.h")
    
    print(f"\n建议:")
    print(f"   方案1更简洁，方案2更有设计感")
    print(f"   可以在代码中切换测试哪个效果更好")

if __name__ == "__main__":
    main()