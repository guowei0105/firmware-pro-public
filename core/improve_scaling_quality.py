#!/usr/bin/env python3

from PIL import Image, ImageFilter, ImageEnhance
import math

def high_quality_resize_with_antialiasing(input_path, output_size=(48, 48)):
    """使用高质量抗锯齿算法缩放图像"""
    
    # 打开原始96x96图像
    img = Image.open(input_path)
    print(f"原始图像尺寸: {img.size}")
    
    # 转换为RGBA模式以保持透明度信息
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # 方法1: 超采样 + 高质量缩放
    # 先放大到更大尺寸，再缩小（超采样抗锯齿）
    supersample_size = (output_size[0] * 4, output_size[1] * 4)  # 192x192
    
    # 使用LANCZOS算法放大
    img_large = img.resize(supersample_size, Image.LANCZOS)
    
    # 应用轻微的高斯模糊减少锯齿
    img_large = img_large.filter(ImageFilter.GaussianBlur(radius=0.5))
    
    # 缩小到目标尺寸
    img_final = img_large.resize(output_size, Image.LANCZOS)
    
    return img_final

def create_smooth_circle_antialiasing(input_path, output_size=(48, 48)):
    """专门针对圆形图标的平滑抗锯齿处理"""
    
    img = Image.open(input_path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # 创建一个更大的画布进行处理
    work_size = (output_size[0] * 8, output_size[1] * 8)  # 384x384
    
    # 高质量放大
    img_work = img.resize(work_size, Image.LANCZOS)
    
    # 应用锐化以增强边缘
    enhancer = ImageEnhance.Sharpness(img_work)
    img_work = enhancer.enhance(1.2)
    
    # 应用轻微模糊进行抗锯齿
    img_work = img_work.filter(ImageFilter.GaussianBlur(radius=1.0))
    
    # 缩小到目标尺寸
    img_final = img_work.resize(output_size, Image.LANCZOS)
    
    return img_final

def bicubic_resize_with_edge_enhancement(input_path, output_size=(48, 48)):
    """使用双三次插值加边缘增强的缩放"""
    
    img = Image.open(input_path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # 使用BICUBIC算法缩放（比LANCZOS更平滑）
    img_resized = img.resize(output_size, Image.BICUBIC)
    
    # 轻微锐化以补偿模糊
    img_resized = img_resized.filter(ImageFilter.UnsharpMask(radius=1, percent=100, threshold=3))
    
    return img_resized

def convert_to_optimized_rgb565(img, array_name):
    """转换为优化的RGB565格式，处理边缘平滑"""
    
    # 转换为RGB模式
    if img.mode == 'RGBA':
        # 使用黑色背景合成RGBA
        background = Image.new('RGB', img.size, (0, 0, 0))
        img = Image.alpha_composite(background.convert('RGBA'), img).convert('RGB')
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    rgb565_data = []
    white_pixel_count = 0
    gray_pixel_count = 0
    
    for y in range(48):
        for x in range(48):
            r, g, b = img.getpixel((x, y))
            
            # 对于抗锯齿处理，保留灰度信息作为alpha混合
            # 如果像素是灰色（抗锯齿边缘），进行特殊处理
            gray_level = (r + g + b) // 3
            
            if gray_level > 200:  # 接近白色
                # 保持白色
                r, g, b = 255, 255, 255
                white_pixel_count += 1
            elif gray_level > 50:  # 灰色（抗锯齿边缘）
                # 根据灰度级别调整
                intensity = gray_level
                r, g, b = intensity, intensity, intensity
                gray_pixel_count += 1
            else:  # 接近黑色
                r, g, b = 0, 0, 0
            
            # 转换为RGB565格式
            r5 = (r >> 3) & 0x1F
            g6 = (g >> 2) & 0x3F  
            b5 = (b >> 3) & 0x1F
            
            rgb565 = (r5 << 11) | (g6 << 5) | b5
            
            # 小端序存储
            rgb565_data.append(rgb565 & 0xFF)
            rgb565_data.append((rgb565 >> 8) & 0xFF)
    
    # 生成C数组
    c_array = f"// {array_name} - 48x48 high-quality antialiased RGB565 data\n"
    c_array += f"// White pixels: {white_pixel_count}, Gray pixels: {gray_pixel_count}\n"
    c_array += f"static const uint8_t {array_name}[] = {{\n"
    
    for i in range(0, len(rgb565_data), 16):
        line = "    "
        for j in range(16):
            if i + j < len(rgb565_data):
                line += f"0x{rgb565_data[i + j]:02x}, "
        c_array += line + "\n"
    
    c_array += "};\n"
    
    print(f"Generated '{array_name}' with {white_pixel_count} white pixels, {gray_pixel_count} gray pixels")
    return c_array

def main():
    input_path = '/home/zhou/Desktop/format/firmware-pro/msg96x96.png'
    
    print("=== 高质量缩放96x96消息图标到48x48 ===")
    
    # 方法1: 超采样抗锯齿
    print("\n方法1: 超采样抗锯齿")
    img1 = high_quality_resize_with_antialiasing(input_path)
    img1.save('/home/zhou/Desktop/format/firmware-pro/msg_supersample_48x48.png')
    array1 = convert_to_optimized_rgb565(img1, "toi_msg_supersample")
    
    # 方法2: 圆形专用平滑处理
    print("\n方法2: 圆形专用平滑处理")
    img2 = create_smooth_circle_antialiasing(input_path)
    img2.save('/home/zhou/Desktop/format/firmware-pro/msg_smooth_circle_48x48.png')
    array2 = convert_to_optimized_rgb565(img2, "toi_msg_smooth_circle")
    
    # 方法3: 双三次插值加边缘增强
    print("\n方法3: 双三次插值加边缘增强")
    img3 = bicubic_resize_with_edge_enhancement(input_path)
    img3.save('/home/zhou/Desktop/format/firmware-pro/msg_bicubic_48x48.png')
    array3 = convert_to_optimized_rgb565(img3, "toi_msg_bicubic")
    
    # 生成头文件
    header_content = f"""#ifndef ICON_MSG_HIGHQUALITY_H
#define ICON_MSG_HIGHQUALITY_H

{array1}

{array2}

{array3}

#endif // ICON_MSG_HIGHQUALITY_H
"""
    
    with open('/home/zhou/Desktop/format/firmware-pro/core/embed/bootloader/icon_msg_highquality.h', 'w') as f:
        f.write(header_content)
    
    print(f"\n✅ 高质量缩放图标已生成:")
    print(f"   - msg_supersample_48x48.png      (超采样抗锯齿)")
    print(f"   - msg_smooth_circle_48x48.png    (圆形专用平滑)")
    print(f"   - msg_bicubic_48x48.png          (双三次插值)")
    print(f"   - icon_msg_highquality.h         (C数组文件)")
    
    print(f"\n这些方法保留了96x96的原始设计，同时大幅减少锯齿效果")
    print(f"建议先测试方法2（圆形专用），应该效果最好")

if __name__ == "__main__":
    main()