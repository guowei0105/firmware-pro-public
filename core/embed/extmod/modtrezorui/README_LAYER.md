# LCD Layer 功能说明

## 概述
本模块为LCD显示添加了第二层layer支持，可以在屏幕中心绘制红色矩形。

## 新增功能

### 1. 第二层Layer配置
- `lcd_add_second_layer()`: 配置并启用第二层layer
- 第二层layer使用半透明设置，可以与第一层layer混合显示
- 内存地址：`FMC_SDRAM_LTDC_BUFFER_ADDRESS + (FMC_SDRAM_LTDC_BUFFER_LEN / 2)`

### 2. 红色矩形绘制
- `lcd_draw_red_rectangle_center()`: 在屏幕中心绘制100x80像素的红色矩形
- 使用直接内存写入，避免与DMA2D操作冲突
- 矩形位置：屏幕中心
- 颜色：RGB565格式的红色 (0xF800)

### 3. DMA2D操作后自动绘制（可选）
- `lcd_draw_red_rectangle_after_dma2d()`: 专门用于DMA2D操作后绘制红色矩形
- 通过宏 `ENABLE_RED_RECTANGLE_AFTER_DMA2D` 控制是否启用
- 默认启用，在每次DMA2D操作完成后自动绘制红色矩形
- 支持 `dma2d_copy_buffer()` 和 `dma2d_copy_ycbcr_to_rgb()` 函数

### 4. 测试函数
- `lcd_test_red_rectangle()`: 完整的测试函数，包含layer配置和矩形绘制

## 使用方法

### 自动模式
LCD初始化时会自动添加第二层layer并绘制红色矩形。

### 手动模式
```c
// 手动添加第二层layer
lcd_add_second_layer();

// 绘制红色矩形
lcd_draw_red_rectangle_center();

// 或者使用测试函数
lcd_test_red_rectangle();
```

### DMA2D操作模式（自动）
```c
// 启用DMA2D操作后的自动红色矩形绘制
#define ENABLE_RED_RECTANGLE_AFTER_DMA2D 1

// 调用DMA2D复制函数，会自动在复制完成后绘制红色矩形
dma2d_copy_buffer(src_buffer, dst_buffer, x, y, width, height);

// 调用YCbCr转换函数，会自动在转换完成后绘制红色矩形
dma2d_copy_ycbcr_to_rgb(src_buffer, dst_buffer, width, height, chroma_sampling);

// 每次调用都会自动绘制红色矩形，无需手动调用
```

## 技术细节

### 内存布局
- 第一层layer: `FMC_SDRAM_LTDC_BUFFER_ADDRESS` (0xD0000000)
- 第二层layer: `FMC_SDRAM_LTDC_BUFFER_ADDRESS + 1MB` (0xD0100000)
- 每个layer使用1MB内存空间

### Layer配置
- Layer 0: 不透明，作为背景层
- Layer 1: 半透明 (Alpha = 128)，作为前景层
- 混合模式：PAxCA (Pixel Alpha x Constant Alpha)

### 绘制方法
- 使用直接内存写入，避免与DMA2D操作冲突
- 支持RGB565和ARGB8888像素格式
- 逐像素操作，确保准确性

### 性能优化
- 避免DMA2D资源冲突
- 使用直接内存访问
- 支持RGB565和ARGB8888像素格式

## 故障排除

### 第一层显示问题
如果第一层layer显示出现问题，可能的原因和解决方案：

1. **DMA2D资源冲突**
   - 解决方案：禁用DMA2D操作后的自动红色矩形绘制
   - 设置 `#define ENABLE_RED_RECTANGLE_AFTER_DMA2D 0`

2. **内存地址冲突**
   - 检查第二层layer的内存地址是否正确
   - 确保不与第一层layer内存重叠

3. **Layer配置干扰**
   - 确保第一层layer配置正确
   - 检查透明度设置

### 推荐配置
```c
// 推荐设置：禁用DMA2D操作后的自动红色矩形绘制
#define ENABLE_RED_RECTANGLE_AFTER_DMA2D 0

// 手动控制红色矩形绘制
lcd_add_second_layer();
lcd_draw_red_rectangle_center();
```

## 注意事项
1. 确保SDRAM已正确初始化
2. 第二层layer的内存地址不会与其他区域冲突
3. 默认禁用DMA2D操作后的自动红色矩形绘制，避免影响第一层显示
4. 支持480x800分辨率 (TXW350135B0 LCD)
5. 使用直接内存写入，避免DMA2D资源冲突 