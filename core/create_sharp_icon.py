#!/usr/bin/env python3
"""
创建一个真正清晰的信息图标
使用简单的几何形状，确保在48x48分辨率下清晰显示
"""
import struct

def create_sharp_info_icon():
    """创建一个清晰的信息图标"""
    width = 48
    height = 48
    
    # 创建RGB565格式的像素数据
    # 白色 = 0xFFFF, 黑色 = 0x0000, 蓝色 = 0x001F
    WHITE = 0xFFFF
    BLACK = 0x0000
    BLUE = 0x1F << 11  # 蓝色 (RGB565: 11111_000000_00000)
    
    pixels = []
    center_x, center_y = 24, 24
    outer_radius = 22
    inner_radius = 18
    
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance_sq = dx * dx + dy * dy
            distance = distance_sq ** 0.5
            
            if distance <= outer_radius and distance >= inner_radius:
                # 圆环边框 - 使用蓝色
                pixels.append(BLUE)
            elif distance < inner_radius:
                # 圆环内部
                # 绘制大写字母 "i"
                # 上面的点
                if 10 <= y <= 14 and 21 <= x <= 27:
                    pixels.append(WHITE)
                # 下面的竖线
                elif 18 <= y <= 35 and 22 <= x <= 26:
                    pixels.append(WHITE)
                # 竖线底部的横线
                elif 35 <= y <= 37 and 20 <= x <= 28:
                    pixels.append(WHITE)
                else:
                    pixels.append(BLACK)
            else:
                # 圆环外部 - 透明/黑色
                pixels.append(BLACK)
    
    return pixels, width, height

def create_toif_file(pixels, width, height, filename):
    """创建TOIF文件"""
    # 转换像素为字节
    pixel_bytes = bytearray()
    for pixel in pixels:
        pixel_bytes.extend(struct.pack('<H', pixel))
    
    # TOIF头部
    magic = b'TOIf'  # 全彩色格式
    width_bytes = struct.pack('<H', width)
    height_bytes = struct.pack('<H', height)
    data_len = struct.pack('<I', len(pixel_bytes))
    
    # 写入文件
    with open(filename, 'wb') as f:
        f.write(magic)
        f.write(width_bytes)
        f.write(height_bytes)
        f.write(data_len)
        f.write(pixel_bytes)
    
    return len(magic + width_bytes + height_bytes + data_len + pixel_bytes)

def toif_to_c_array(toif_filename, c_filename, array_name):
    """将TOIF转换为C数组"""
    with open(toif_filename, 'rb') as f:
        data = f.read()
    
    # 解析头部
    magic = data[0:4].decode('ascii')
    width = struct.unpack('<H', data[4:6])[0]
    height = struct.unpack('<H', data[6:8])[0]
    data_len = struct.unpack('<I', data[8:12])[0]
    
    print(f"TOIF: {magic}, {width}x{height}, {data_len} bytes data")
    
    # 生成C代码
    c_code = f"// Sharp info icon - {width}x{height}\n"
    c_code += f"static const uint8_t {array_name}[] = {{\n"
    
    # Magic
    c_code += "    // magic\n"
    c_code += f"    '{magic[0]}', '{magic[1]}', '{magic[2]}', '{magic[3]}',\n"
    
    # 尺寸
    c_code += "    // width (16-bit), height (16-bit)\n"
    c_code += f"    0x{data[4]:02x}, 0x{data[5]:02x}, 0x{data[6]:02x}, 0x{data[7]:02x},\n"
    
    # 数据长度
    c_code += "    // data length (32-bit)\n"
    c_code += f"    0x{data[8]:02x}, 0x{data[9]:02x}, 0x{data[10]:02x}, 0x{data[11]:02x},\n"
    
    # 像素数据
    c_code += "    // pixel data (RGB565)\n"
    pixel_data = data[12:]
    
    for i in range(0, len(pixel_data), 16):
        c_code += "    "
        line_data = pixel_data[i:i+16]
        hex_values = [f"0x{b:02x}" for b in line_data]
        c_code += ", ".join(hex_values)
        if i + 16 < len(pixel_data):
            c_code += ","
        c_code += "\n"
    
    c_code += "};\n"
    
    # 写入C文件
    with open(c_filename, 'w') as f:
        f.write(c_code)
    
    print(f"Generated C header: {c_filename}")

def main():
    print("Creating sharp info icon...")
    
    # 创建像素数据
    pixels, width, height = create_sharp_info_icon()
    
    # 生成TOIF文件
    toif_file = "../sharp_info_icon.toif"
    file_size = create_toif_file(pixels, width, height, toif_file)
    print(f"Created TOIF file: {toif_file} ({file_size} bytes)")
    
    # 生成C头文件
    c_file = "embed/bootloader/icon_sharp.h"
    toif_to_c_array(toif_file, c_file, "toi_sharp_icon_info")
    
    print("Sharp icon creation complete!")

if __name__ == "__main__":
    main()