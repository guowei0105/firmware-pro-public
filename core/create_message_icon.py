#!/usr/bin/env python3

from PIL import Image, ImageDraw

def create_message_icon_with_dots():
    """创建圆环内有三个点的消息图标"""
    
    # 创建48x48的图像，黑色背景
    img = Image.new('RGB', (48, 48), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 设置白色
    white = (255, 255, 255)
    
    # 圆环参数
    center_x, center_y = 24, 24
    outer_radius = 20
    inner_radius = 16
    
    # 绘制圆环（外圆减去内圆）
    # 先画外圆
    draw.ellipse([center_x - outer_radius, center_y - outer_radius,
                  center_x + outer_radius, center_y + outer_radius], fill=white)
    
    # 再画内圆（黑色，形成圆环效果）
    draw.ellipse([center_x - inner_radius, center_y - inner_radius,
                  center_x + inner_radius, center_y + inner_radius], fill=(0, 0, 0))
    
    # 在圆环内绘制三个点
    dot_radius = 2
    
    # 三个点的位置 - 垂直排列
    dot_spacing = 5
    dot1_y = center_y - dot_spacing
    dot2_y = center_y
    dot3_y = center_y + dot_spacing
    
    # 绘制三个点
    for dot_y in [dot1_y, dot2_y, dot3_y]:
        draw.ellipse([center_x - dot_radius, dot_y - dot_radius,
                      center_x + dot_radius, dot_y + dot_radius], fill=white)
    
    return img

def create_alternative_message_icon():
    """创建另一种样式的消息图标 - 水平排列的三个点"""
    
    img = Image.new('RGB', (48, 48), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    white = (255, 255, 255)
    
    # 圆环参数
    center_x, center_y = 24, 24
    outer_radius = 20
    inner_radius = 16
    
    # 绘制圆环
    draw.ellipse([center_x - outer_radius, center_y - outer_radius,
                  center_x + outer_radius, center_y + outer_radius], fill=white)
    draw.ellipse([center_x - inner_radius, center_y - inner_radius,
                  center_x + inner_radius, center_y + inner_radius], fill=(0, 0, 0))
    
    # 三个点水平排列
    dot_radius = 2
    dot_spacing = 5
    
    dot1_x = center_x - dot_spacing
    dot2_x = center_x
    dot3_x = center_x + dot_spacing
    
    # 绘制三个点
    for dot_x in [dot1_x, dot2_x, dot3_x]:
        draw.ellipse([dot_x - dot_radius, center_y - dot_radius,
                      dot_x + dot_radius, center_y + dot_radius], fill=white)
    
    return img

def create_speech_bubble_icon():
    """创建对话气泡样式的消息图标"""
    
    img = Image.new('RGB', (48, 48), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    white = (255, 255, 255)
    
    # 绘制对话气泡外框
    bubble_x = 8
    bubble_y = 8
    bubble_width = 32
    bubble_height = 24
    
    # 气泡主体（圆角矩形）
    draw.rounded_rectangle([bubble_x, bubble_y, 
                           bubble_x + bubble_width, bubble_y + bubble_height],
                          radius=6, outline=white, width=2)
    
    # 气泡尾巴（小三角形）
    tail_points = [(bubble_x + 8, bubble_y + bubble_height),
                   (bubble_x + 4, bubble_y + bubble_height + 6),
                   (bubble_x + 12, bubble_y + bubble_height)]
    draw.polygon(tail_points, fill=white)
    
    # 气泡内的三个点
    dot_radius = 2
    dot_y = bubble_y + bubble_height // 2
    
    dot1_x = bubble_x + 8
    dot2_x = bubble_x + 16
    dot3_x = bubble_x + 24
    
    for dot_x in [dot1_x, dot2_x, dot3_x]:
        draw.ellipse([dot_x - dot_radius, dot_y - dot_radius,
                      dot_x + dot_radius, dot_y + dot_radius], fill=white)
    
    return img

def convert_to_rgb565_array(img, array_name):
    """将PIL图像转换为RGB565格式的C数组"""
    
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
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
            
            if rgb565 == 0xFFFF:
                white_pixel_count += 1
            
            # 小端序存储
            rgb565_data.append(rgb565 & 0xFF)
            rgb565_data.append((rgb565 >> 8) & 0xFF)
    
    # 生成C数组
    c_array = f"// {array_name} - 48x48 message icon with dots\n"
    c_array += f"// White pixels: {white_pixel_count}\n"
    c_array += f"static const uint8_t {array_name}[] = {{\n"
    
    for i in range(0, len(rgb565_data), 16):
        line = "    "
        for j in range(16):
            if i + j < len(rgb565_data):
                line += f"0x{rgb565_data[i + j]:02x}, "
        c_array += line + "\n"
    
    c_array += "};\n"
    
    print(f"Generated '{array_name}' with {white_pixel_count} white pixels")
    return c_array

def main():
    print("创建圆环三个点的消息图标...")
    
    # 方案1: 圆环 + 垂直三个点
    print("\n=== 方案1: 圆环 + 垂直三个点 ===")
    vertical_icon = create_message_icon_with_dots()
    vertical_icon.save('/home/zhou/Desktop/format/firmware-pro/msg_vertical_dots.png')
    vertical_array = convert_to_rgb565_array(vertical_icon, "toi_msg_vertical_dots")
    
    # 方案2: 圆环 + 水平三个点
    print("\n=== 方案2: 圆环 + 水平三个点 ===")
    horizontal_icon = create_alternative_message_icon()
    horizontal_icon.save('/home/zhou/Desktop/format/firmware-pro/msg_horizontal_dots.png')
    horizontal_array = convert_to_rgb565_array(horizontal_icon, "toi_msg_horizontal_dots")
    
    # 方案3: 对话气泡 + 三个点
    print("\n=== 方案3: 对话气泡 + 三个点 ===")
    bubble_icon = create_speech_bubble_icon()
    bubble_icon.save('/home/zhou/Desktop/format/firmware-pro/msg_bubble_dots.png')
    bubble_array = convert_to_rgb565_array(bubble_icon, "toi_msg_bubble_dots")
    
    # 生成头文件
    header_content = f"""#ifndef ICON_MSG_DOTS_H
#define ICON_MSG_DOTS_H

{vertical_array}

{horizontal_array}

{bubble_array}

#endif // ICON_MSG_DOTS_H
"""
    
    with open('/home/zhou/Desktop/format/firmware-pro/core/embed/bootloader/icon_msg_dots.h', 'w') as f:
        f.write(header_content)
    
    print(f"\n✅ 消息图标已生成:")
    print(f"   - msg_vertical_dots.png    (圆环+垂直三点)")
    print(f"   - msg_horizontal_dots.png  (圆环+水平三点)")
    print(f"   - msg_bubble_dots.png      (对话气泡+三点)")
    print(f"   - icon_msg_dots.h          (C数组文件)")
    
    print(f"\n推荐方案1或方案2，更符合你描述的'圆环三个点'")

if __name__ == "__main__":
    main()