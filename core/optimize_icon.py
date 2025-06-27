#!/usr/bin/env python3
"""
优化图标转换脚本
将PNG转换为高质量的TOIF格式，然后生成C数组
"""
import subprocess
import os
import sys

def run_command(cmd):
    """运行命令并返回结果"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error running command: {cmd}")
            print(f"Error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"Exception running command: {cmd}")
        print(f"Exception: {e}")
        return False

def main():
    # 确保我们在正确的目录
    base_dir = "/home/zhou/Desktop/format/firmware-pro"
    
    # 源PNG文件
    source_png = f"{base_dir}/msg.png"
    
    # 目标文件
    optimized_toif = f"{base_dir}/msg_optimized.toif"
    output_header = f"{base_dir}/core/embed/bootloader/icon_optimized.h"
    
    if not os.path.exists(source_png):
        print(f"Source PNG not found: {source_png}")
        return False
    
    print(f"Converting {source_png} to optimized TOIF...")
    
    # 第一步：转换PNG到TOIF（使用较高质量设置）
    # 假设有trezor-core的toif工具，如果没有，我们创建一个简单的版本
    toif_cmd = f"python3 -c \"
import sys
sys.path.append('{base_dir}')
from PIL import Image
import struct

# 读取图像
img = Image.open('{source_png}')
print(f'Image size: {{img.size}}, mode: {{img.mode}}')

# 转换为RGBA，然后处理alpha通道
if img.mode != 'RGBA':
    img = img.convert('RGBA')

# 获取像素数据
pixels = img.getdata()
width, height = img.size

# 创建简单的TOIF格式
# Magic: TOIf (full color)
magic = b'TOIf'
width_bytes = struct.pack('<H', width)
height_bytes = struct.pack('<H', height)

# 简单的压缩：将RGBA转换为RGB565格式
rgb565_data = bytearray()
for r, g, b, a in pixels:
    if a < 128:  # 透明像素设为黑色
        r, g, b = 0, 0, 0
    else:  # 不透明像素保持原色
        pass
    
    # 转换为RGB565
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F  
    b5 = (b >> 3) & 0x1F
    rgb565 = (r5 << 11) | (g6 << 5) | b5
    rgb565_data.extend(struct.pack('<H', rgb565))

# 数据长度
data_len = struct.pack('<I', len(rgb565_data))

# 写入TOIF文件
with open('{optimized_toif}', 'wb') as f:
    f.write(magic)
    f.write(width_bytes)
    f.write(height_bytes)
    f.write(data_len)
    f.write(rgb565_data)

print(f'Generated TOIF: {{len(magic + width_bytes + height_bytes + data_len + rgb565_data)}} bytes')
\""
    
    if not run_command(toif_cmd):
        print("Failed to create TOIF file")
        return False
    
    print(f"Generated TOIF file: {optimized_toif}")
    
    # 第二步：转换TOIF到C数组
    convert_cmd = f"python3 {base_dir}/convert_toif_to_c.py -i {optimized_toif} -o {output_header} -n toi_optimized_icon_info"
    
    if not run_command(convert_cmd):
        print("Failed to convert TOIF to C array")
        return False
    
    print(f"Generated C header: {output_header}")
    print("Icon optimization complete!")
    return True

if __name__ == "__main__":
    main()