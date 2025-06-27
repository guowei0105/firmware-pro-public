# Layer 1 硬件层测试指南

## 测试目标
验证LTDC Layer 1硬件层能否在屏幕中心正常显示，并且不会产生黑框问题。

## 当前实现
已在 `mipi_lcd.c` 的 `lcd_init()` 函数中硬编码了Layer 1的初始化和显示：

```c
// 自动初始化和启用Layer 1进行测试
ltdc_layer1_init();
ltdc_layer1_fill_color(0xF800);  // 填充红色
ltdc_layer1_enable(1);           // 启用Layer 1
```

## 预期结果
设备启动后，应该在屏幕中心位置（坐标140, 300）看到一个200x200像素的红色方块。

## Layer 1 规格
- **位置**: 屏幕中心 (140, 300)
- **尺寸**: 200x200 像素
- **颜色**: 红色 (RGB565: 0xF800)
- **内存**: 80KB (200 * 200 * 2字节)
- **缓冲区地址**: FMC_SDRAM_LAYER1_BUFFER_ADDRESS

## 测试步骤
1. 烧录固件到设备
2. 启动设备
3. 观察屏幕中心是否出现红色方块
4. 确认没有黑框或其他异常显示

## 成功标准
- ✅ 屏幕中心显示红色方块
- ✅ 没有黑框问题
- ✅ 不影响其他UI元素显示
- ✅ 启动过程正常

## 如果出现问题
如果没有看到红色方块，可能的原因：
1. Layer 1配置错误
2. LTDC寄存器设置问题
3. 内存地址错误
4. 像素格式不匹配

如果出现黑框，说明：
1. Layer 1配置可能有问题
2. 需要调整初始化顺序
3. 可能需要其他LTDC设置

## 下一步
如果测试成功，可以：
1. 测试位置移动功能
2. 测试颜色变化功能
3. 集成到实际的动画系统中
4. 添加Python接口进行动态控制

## 代码位置
- **C实现**: `core/embed/extmod/modtrezorui/mipi_lcd.c`
- **头文件**: `core/embed/extmod/modtrezorui/mipi_lcd.h`
- **内存配置**: `core/embed/trezorhal/sdram.h`
- **Python绑定**: `core/embed/lvgl/modlvgldrv.c`