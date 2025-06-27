#!/usr/bin/env python3
"""
将msg.png转换为C数组格式供bootloader使用
"""
import struct
from PIL import Image

def convert_png_to_raw_array(png_path, output_h_path, array_name):
    """将PNG转换为原始RGB565格式的C数组（供display_image使用）"""
    # 打开PNG图像
    img = Image.open(png_path)
    
    # 将96x96缩放到48x48像素，使用高质量的LANCZOS算法
    print(f"原始图像尺寸: {img.size}")
    if img.size != (48, 48):
        img = img.resize((48, 48), Image.LANCZOS)
        print("已缩放到 48x48 像素")
    
    # 转换为RGBA模式确保有alpha通道
    img = img.convert('RGBA')
    
    width, height = img.size
    print(f"图像尺寸: {width}x{height}")
    
    # 转换像素为RGB565格式
    pixel_bytes = bytearray()
    white_pixels = 0
    black_pixels = 0
    
    for y in range(height):
        for x in range(width):
            r, g, b, a = img.getpixel((x, y))
            
            # 如果alpha < 128，视为透明（使用黑色）
            if a < 128:
                pixel = 0x0000  # 黑色/透明
                black_pixels += 1
            else:
                # 转换为RGB565格式
                r5 = (r >> 3) & 0x1F
                g6 = (g >> 2) & 0x3F  
                b5 = (b >> 3) & 0x1F
                pixel = (r5 << 11) | (g6 << 5) | b5
                
                # 如果是白色或接近白色，改为白色
                if r > 200 and g > 200 and b > 200:
                    pixel = 0xFFFF  # 纯白色
                    white_pixels += 1
                elif pixel == 0x0000:
                    black_pixels += 1
            
            # 存储为小端序
            pixel_bytes.extend(struct.pack('<H', pixel))
    
    print(f"白色像素数量: {white_pixels}")
    print(f"黑色像素数量: {black_pixels}")
    print(f"总像素数量: {len(pixel_bytes)//2}")
    
    # 生成C头文件 - 只包含原始像素数据
    c_code = f"// {array_name} - {width}x{height} raw RGB565 data from msg.png\n"
    c_code += f"static const uint8_t {array_name}[] = {{\n"
    
    # 只输出像素数据
    for i in range(0, len(pixel_bytes), 16):
        c_code += "    "
        line_data = pixel_bytes[i:i+16]
        hex_values = [f"0x{b:02x}" for b in line_data]
        c_code += ", ".join(hex_values)
        if i + 16 < len(pixel_bytes):
            c_code += ","
        c_code += "\n"
    
    c_code += "};\n"
    
    # 写入C头文件
    with open(output_h_path, 'w') as f:
        f.write(c_code)
    
    print(f"Generated C header: {output_h_path}")
    print(f"Array name: {array_name}")
    print(f"Raw pixel data size: {len(pixel_bytes)} bytes ({len(pixel_bytes)//2} pixels)")

def main():
    png_file = "/home/zhou/Desktop/format/firmware-pro/msg96x96.png"
    h_file = "embed/bootloader/icon_msg.h"
    array_name = "toi_msg_icon_info"
    
    print("Converting msg96x96.png to 48x48 raw RGB565 array...")
    convert_png_to_raw_array(png_file, h_file, array_name)
    print("Conversion complete!")

if __name__ == "__main__":
    main()