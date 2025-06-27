#!/usr/bin/env python3
import binascii
import argparse
import os

parser = argparse.ArgumentParser(description='Convert TOIF file to C-style array initializer.')
parser.add_argument("-i", "--input", help="the TOIF file to be converted")
parser.add_argument("-o", "--output", help="write output to a file")
parser.add_argument("-n", "--name", default="toi_ok_icon_info", help="array name")
parser.add_argument("-l", "--linebreak", type=int, default=16, help="add linebreak after every N element")
args = parser.parse_args()

if __name__ == "__main__":
    c_code = ""

    with open(args.input, 'rb') as f:
        file_content = f.read()
    
    # Parse TOIF header
    magic = file_content[0:4].decode('ascii')
    width = file_content[4] | (file_content[5] << 8)
    height = file_content[6] | (file_content[7] << 8)
    data_len = file_content[8] | (file_content[9] << 8) | (file_content[10] << 16) | (file_content[11] << 24)
    
    print(f"TOIF file: {args.input}")
    print(f"Magic: {magic}")
    print(f"Dimensions: {width}x{height}")
    print(f"Compressed size: {data_len} bytes")
    print(f"Total size: {len(file_content)} bytes")
    
    # Generate the full array
    c_code += f"static const uint8_t {args.name}[] = {{\n"
    
    # Add magic comment and values
    c_code += "    // magic\n"
    c_code += f"    '{magic[0]}', '{magic[1]}', '{magic[2]}', '{magic[3]}',\n"
    
    # Add dimensions comment and values
    c_code += "    // width (16-bit), height (16-bit)\n"
    c_code += f"    0x{file_content[4]:02x}, 0x{file_content[5]:02x}, 0x{file_content[6]:02x}, 0x{file_content[7]:02x},\n"
    
    # Add data length comment and values
    c_code += "    // compressed data length (32-bit)\n"
    c_code += f"    0x{file_content[8]:02x}, 0x{file_content[9]:02x}, 0x{file_content[10]:02x}, 0x{file_content[11]:02x},\n"
    
    # Add compressed data
    c_code += "    // compressed data\n"
    compressed_data = file_content[12:]
    
    # Convert to hex format
    hexstr = ["0x{:02x}".format(b) for b in compressed_data]
    
    # Add line breaks
    for i in range(0, len(hexstr), args.linebreak):
        c_code += "    "
        line_items = hexstr[i:i+args.linebreak]
        c_code += ", ".join(line_items)
        if i + args.linebreak < len(hexstr):
            c_code += ","
        c_code += "\n"
    
    c_code += "};\n"

    if args.output:
        with open(args.output, 'w') as f:
            f.write(c_code)
        print(f"\nC array written to: {args.output}")
    else:
        print("\n" + c_code)