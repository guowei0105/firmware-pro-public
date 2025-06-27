/*
 * LCD显示调用示例
 * 
 * 这个文件展示了如何正确调用LCD显示功能
 */

#include "mipi_lcd.h"

// 示例1: 最简单的调用方式
void simple_display_example(void) {
    // 只需要调用LCD初始化，会自动添加第二层layer并绘制红色矩形
    lcd_init();
    
    // 现在屏幕上应该显示：
    // - 第一层layer: 正常的显示内容
    // - 第二层layer: 屏幕中心的红色矩形
}

// 示例2: 手动控制显示
void manual_display_example(void) {
    // 初始化LCD
    lcd_init();
    
    // 验证layer配置
    lcd_verify_layer_config();
    
    // 手动添加第二层layer
    lcd_add_second_layer();
    
    // 绘制红色矩形
    lcd_draw_red_rectangle_center();
    
    // 检查调试输出，应该看到：
    // "Second layer added successfully at address 0xD0100000"
    // "Red rectangle drawn at center: (190, 360) size: 100x80"
}

// 示例3: 在特定时机显示红色矩形
void conditional_display_example(void) {
    // 初始化LCD
    lcd_init();
    
    // 确保第二层layer存在
    lcd_add_second_layer();
    
    // 在特定条件下显示红色矩形
    int show_red_rectangle = 1;  // 你的条件判断
    
    if (show_red_rectangle) {
        lcd_draw_red_rectangle_center();
    }
}

// 示例4: 与DMA2D操作结合使用
void dma2d_display_example(void) {
    // 初始化LCD
    lcd_init();
    
    // 准备DMA2D数据
    uint32_t src_buffer[100 * 100];
    uint32_t dst_buffer[480 * 800];
    
    // 填充源数据
    for (int i = 0; i < 100 * 100; i++) {
        src_buffer[i] = 0xF800;  // 红色
    }
    
    // 执行DMA2D复制操作
    dma2d_copy_buffer(src_buffer, dst_buffer, 100, 100, 100, 100);
    
    // 在DMA2D操作完成后，手动绘制红色矩形
    lcd_draw_red_rectangle_center();
}

// 示例5: 使用测试函数
void test_function_example(void) {
    // 初始化LCD
    lcd_init();
    
    // 使用测试函数（包含完整的layer配置和矩形绘制）
    lcd_test_red_rectangle();
}

// 示例6: 动态控制红色矩形显示
void dynamic_display_example(void) {
    // 初始化LCD
    lcd_init();
    
    // 确保第二层layer存在
    lcd_add_second_layer();
    
    // 在需要的时候显示红色矩形
    lcd_draw_red_rectangle_center();
    
    // 等待一段时间
    HAL_Delay(2000);
    
    // 清除红色矩形（通过重新绘制透明背景）
    // 这里可以调用清除函数或重新绘制透明背景
    // 或者禁用第二层layer
}

// 示例7: 错误处理和调试
void debug_display_example(void) {
    // 设置调试输出函数（如果有的话）
    // disp_set_dbg_printf(your_debug_function);
    
    // 初始化LCD
    lcd_init();
    
    // 手动添加第二层layer并检查结果
    lcd_add_second_layer();
    
    // 绘制红色矩形并检查结果
    lcd_draw_red_rectangle_center();
    
    // 检查调试输出，确保没有错误信息
    // 应该看到成功信息，而不是错误信息
}

// 示例8: 完整的应用场景
void complete_application_example(void) {
    // 1. 初始化系统
    lcd_pwm_init();  // 初始化背光控制
    
    // 2. 初始化LCD
    lcd_init();
    
    // 3. 设置背光亮度
    display_backlight(128);  // 50%亮度
    
    // 4. 添加第二层layer
    lcd_add_second_layer();
    
    // 5. 绘制红色矩形
    lcd_draw_red_rectangle_center();
    
    // 6. 现在屏幕上应该显示：
    // - 第一层layer: 正常的显示内容
    // - 第二层layer: 屏幕中心的红色矩形
    // - 背光: 50%亮度
    
    // 7. 可以继续其他操作...
    // 例如：处理用户输入、更新显示内容等
}

// 示例9: 调试和验证layer配置
void debug_layer_config_example(void) {
    // 初始化LCD
    lcd_init();
    
    // 验证layer配置
    lcd_verify_layer_config();
    
    // 手动添加第二层layer
    lcd_add_second_layer();
    
    // 再次验证配置
    lcd_verify_layer_config();
    
    // 绘制红色矩形
    lcd_draw_red_rectangle_center();
    
    // 检查调试输出，确保：
    // 1. 内存地址正确分离
    // 2. 没有内存重叠
    // 3. Layer配置正确
    // 4. 红色矩形绘制成功
}

// 示例10: 测试dma2d_copy_buffer中的红色矩形功能
void test_dma2d_copy_buffer_red_rectangle(void) {
    // 初始化LCD
    lcd_init();
    
    // 准备测试数据
    uint32_t src_buffer[100 * 100];  // 100x100的源数据
    uint32_t dst_buffer[480 * 800];  // 目标缓冲区
    
    // 填充源数据为蓝色
    for (int i = 0; i < 100 * 100; i++) {
        src_buffer[i] = 0x001F;  // 蓝色 RGB565
    }
    
    // 调用dma2d_copy_buffer，会自动在复制完成后绘制红色矩形
    dma2d_copy_buffer(src_buffer, dst_buffer, 100, 100, 100, 100);
    
    // 现在屏幕上应该显示：
    // - 第一层layer: 在(100,100)位置有100x100的蓝色矩形
    // - 第二层layer: 屏幕中心有红色矩形
    
    dbg_printf("dma2d_copy_buffer test completed!\r\n");
}

// 示例11: 多次调用dma2d_copy_buffer测试
void test_multiple_dma2d_calls(void) {
    // 初始化LCD
    lcd_init();
    
    // 准备多个测试数据
    uint32_t src_buffer1[50 * 50];
    uint32_t src_buffer2[80 * 60];
    uint32_t dst_buffer[480 * 800];
    
    // 填充第一个源数据为绿色
    for (int i = 0; i < 50 * 50; i++) {
        src_buffer1[i] = 0x07E0;  // 绿色 RGB565
    }
    
    // 填充第二个源数据为黄色
    for (int i = 0; i < 80 * 60; i++) {
        src_buffer2[i] = 0xFFE0;  // 黄色 RGB565
    }
    
    // 第一次调用 - 会在复制完成后绘制红色矩形
    dma2d_copy_buffer(src_buffer1, dst_buffer, 50, 50, 50, 50);
    
    // 等待一段时间
    HAL_Delay(1000);
    
    // 第二次调用 - 会再次绘制红色矩形
    dma2d_copy_buffer(src_buffer2, dst_buffer, 200, 200, 80, 60);
    
    dbg_printf("Multiple dma2d_copy_buffer calls completed!\r\n");
} 