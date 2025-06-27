#!/usr/bin/env python3
"""
创建更清晰的图标
"""
import struct
import os

def create_optimized_toif():
    # 读取原始msg.png的信息，创建一个48x48的清晰图标
    width = 48
    height = 48
    
    # 创建一个简单的信息图标（圆形边框内有一个 "i"）
    # 使用RGB565格式的数据
    
    # 白色 = 0xFFFF, 黑色 = 0x0000
    WHITE = 0xFFFF
    BLACK = 0x0000
    
    # 创建48x48的图标数据
    icon_data = []
    
    center_x, center_y = 24, 24
    radius = 20
    
    for y in range(height):
        for x in range(width):
            # 计算到中心的距离
            dx = x - center_x
            dy = y - center_y
            distance = (dx * dx + dy * dy) ** 0.5
            
            # 绘制圆形边框和内部的 "i"
            if distance <= radius and distance >= radius - 2:
                # 圆形边框
                color = WHITE
            elif distance < radius - 2:
                # 圆形内部
                # 绘制 "i" 的点
                if 8 <= y <= 12 and 22 <= x <= 26:
                    color = WHITE
                # 绘制 "i" 的竖线
                elif 16 <= y <= 36 and 22 <= x <= 26:
                    color = WHITE
                else:
                    color = BLACK
            else:
                # 圆形外部
                color = BLACK
            
            icon_data.append(color)
    
    # 转换为字节数据
    rgb565_data = bytearray()
    for color in icon_data:
        rgb565_data.extend(struct.pack('<H', color))
    
    # 创建TOIF文件
    magic = b'TOIf'
    width_bytes = struct.pack('<H', width)
    height_bytes = struct.pack('<H', height)
    data_len = struct.pack('<I', len(rgb565_data))
    
    toif_path = '../msg_optimized.toif'
    with open(toif_path, 'wb') as f:
        f.write(magic)
        f.write(width_bytes)
        f.write(height_bytes)
        f.write(data_len)
        f.write(rgb565_data)
    
    print(f"Created optimized TOIF: {toif_path}")
    print(f"Size: {len(magic + width_bytes + height_bytes + data_len + rgb565_data)} bytes")
    return toif_path

def convert_toif_to_c(toif_path):
    """将TOIF转换为C数组"""
    with open(toif_path, 'rb') as f:
        file_content = f.read()
    
    # 解析TOIF头部
    magic = file_content[0:4].decode('ascii')
    width = file_content[4] | (file_content[5] << 8)
    height = file_content[6] | (file_content[7] << 8)
    data_len = file_content[8] | (file_content[9] << 8) | (file_content[10] << 16) | (file_content[11] << 24)
    
    print(f"TOIF info: {magic}, {width}x{height}, {data_len} bytes")
    
    # 生成C数组
    c_code = "// Optimized icon - generated automatically\n"
    c_code += "static const uint8_t toi_optimized_icon_info[] = {\n"
    
    # 添加magic
    c_code += "    // magic\n"
    c_code += f"    '{magic[0]}', '{magic[1]}', '{magic[2]}', '{magic[3]}',\n"
    
    # 添加尺寸
    c_code += "    // width (16-bit), height (16-bit)\n"
    c_code += f"    0x{file_content[4]:02x}, 0x{file_content[5]:02x}, 0x{file_content[6]:02x}, 0x{file_content[7]:02x},\n"
    
    # 添加数据长度
    c_code += "    // data length (32-bit)\n"
    c_code += f"    0x{file_content[8]:02x}, 0x{file_content[9]:02x}, 0x{file_content[10]:02x}, 0x{file_content[11]:02x},\n"
    
    # 添加数据
    c_code += "    // pixel data\n"
    data = file_content[12:]
    
    # 每行16个字节
    for i in range(0, len(data), 16):
        c_code += "    "
        line_data = data[i:i+16]
        hex_values = [f"0x{b:02x}" for b in line_data]
        c_code += ", ".join(hex_values)
        if i + 16 < len(data):
            c_code += ","
        c_code += "\n"
    
    c_code += "};\n"
    
    # 写入头文件
    header_path = 'embed/bootloader/icon_optimized.h'
    with open(header_path, 'w') as f:
        f.write(c_code)
    
    print(f"Generated C header: {header_path}")
    return header_path

if __name__ == "__main__":
    print("Creating optimized icon...")
    toif_path = create_optimized_toif()
    header_path = convert_toif_to_c(toif_path)
    print("Done!")