#include STM32_HAL_H
#include <stdio.h>
#include <stdbool.h>
#include <math.h>
#include <string.h>

#include "mipi_lcd.h"
#include "sdram.h"
#include "jpeg_dma.h"
#include "systick.h"

// 第二层layer的内存基地址（使用LTDC buffer的最后四分之一，避免与正常显示缓冲区冲突）
#define LAYER2_MEMORY_BASE (FMC_SDRAM_LTDC_BUFFER_ADDRESS + (FMC_SDRAM_LTDC_BUFFER_LEN * 3 / 4))

// 透明状态栏配置 - Layer2顶部44px保持透明，露出Layer1状态栏
#define TRANSPARENT_STATUSBAR_HEIGHT 44

// 透明颜色键值 - 用于Color Keying实现透明效果
#define TRANSPARENT_COLOR_KEY 0x0001  // 特殊颜色值，将被设置为透明

// Layer1背景图片路径存储
// static char g_layer1_background_path[256] = "A:/res/2222.png";  // 默认背景

// 全局变量跟踪第二层layer是否已初始化
static bool g_layer2_initialized = false;

// 全局动画状态标志
static volatile bool g_animation_in_progress = false;

// 全局状态栏透明度状态标志
static bool g_statusbar_transparent = true;  // 默认透明状态

// 静态缓冲区用于保存顶部44像素的原始数据
// 屏幕宽度480，但我们需要减少内存使用，所以使用动态分配或更小的缓冲区
// 改为使用指针，在需要时从SDRAM分配
static uint16_t* g_statusbar_backup_buffer = NULL;
static bool g_statusbar_backup_valid = false;  // 标记备份数据是否有效

// 不使用大的备份数组，而是使用动态恢复方案

static DbgPrintf_t dbg_printf = NULL;

// Fps = LCD_PCLK / ((LCD_WIDTH + LCD_HBP + LCD_HFP + LCD_HSW) * (LCD_HEIGHT +
// LCD_VBP + LCD_VFP + LCD_VSW)) mipi_mbps = ((LCD_WIDTH + LCD_HBP + LCD_HFP +
// LCD_HSW) * (LCD_HEIGHT + LCD_VBP + LCD_VFP + LCD_VSW) * fps * 24) /

#define LCD_TXW350135B0  // 默认选择TXW350135B0 LCD型号

#if 0 
// 这样写是为了让每个配置都用elif分支
#elif defined(LCD_TXW350135B0)
#include "TXW350135B0.c"  // 包含TXW350135B0的参数定义
#define LCD_init_sequence TXW350135B0_init_sequence  // 初始化序列宏定义
const DisplayParam_t lcd_params = {
    .hres = TXW350135B0_HRES,         // 水平分辨率
    .vres = TXW350135B0_VRES,         // 垂直分辨率
    .hsync = TXW350135B0_HSYNC,       // 水平同步宽度
    .hfp = TXW350135B0_HFP,           // 水平前沿
    .hbp = TXW350135B0_HBP,           // 水平后沿
    .vsync = TXW350135B0_VSYNC,       // 垂直同步宽度
    .vfp = TXW350135B0_VFP,           // 垂直前沿
    .vbp = TXW350135B0_VBP,           // 垂直后沿
    .pixel_format_ltdc = LTDC_PIXEL_FORMAT_RGB565, // LTDC像素格式
    .pixel_format_dsi = DSI_RGB565,               // DSI像素格式
    .bbp = 2,                                     // 每像素字节数
    .fb_base = DISPLAY_MEMORY_BASE,               // 帧缓冲基地址

    .ltdc_pll = {                                // LTDC PLL参数
        .PLL3N = 132U,
        .PLL3R = 20U,
        .PLL3FRACN = 0U,
    }};
#elif defined(LCD_TXW700140K0)
#include "TXW700140K0.c"  // 包含TXW700140K0的参数定义
#define LCD_init_sequence TXW700140K0_init_sequence  // 初始化序列宏定义
const DisplayParam_t lcd_params = {
    .hres = TXW700140K0_HRES,         // 水平分辨率
    .vres = TXW700140K0_VRES,         // 垂直分辨率
    .hsync = TXW700140K0_HSYNC,       // 水平同步宽度
    .hfp = TXW700140K0_HFP,           // 水平前沿
    .hbp = TXW700140K0_HBP,           // 水平后沿
    .vsync = TXW700140K0_VSYNC,       // 垂直同步宽度
    .vfp = TXW700140K0_VFP,           // 垂直前沿
    .vbp = TXW700140K0_VBP,           // 垂直后沿
    .pixel_format_ltdc = LTDC_PIXEL_FORMAT_RGB565, // LTDC像素格式
    .pixel_format_dsi = DSI_RGB565,               // DSI像素格式
    .bbp = 2,                                     // 每像素字节数
    .fb_base = DISPLAY_MEMORY_BASE,               // 帧缓冲基地址

    .ltdc_pll = {                                // LTDC PLL参数
        .PLL3N = 43U,
        .PLL3R = 5U,
        .PLL3FRACN = 2048U,
    }};
#else
#error "display selection not defined!"  // 未定义显示屏型号时报错
#endif

#define LED_PWM_TIM_PERIOD (50)  // LED背光PWM周期

// HSE/DIVM3*(DIVN3+(FRACN3/8192))/DIVR3/to_Khz 计算LTDC时钟频率
#define LTDC_FREQ                                          \
  (uint32_t)(HSE_VALUE / 5 *                               \
             (lcd_params.ltdc_pll.PLL3N +                  \
              (lcd_params.ltdc_pll.PLL3FRACN / 8192.0F)) / \
             lcd_params.ltdc_pll.PLL3R / 1000)

// HSE/IDF*2*NDIV/2/ODF/8/to_Khz = 62.5 Mhz or 625000 Khz 计算DSI时钟频率
#define DSI_FREQ (uint32_t)(HSE_VALUE / 1 * 2 * 40 / 2 / 2 / 8 / 1000)

// 计算目标帧率FPS
// LCD_PCLK / ((LCD_WIDTH + LCD_HBP + LCD_HFP + LCD_HSW) * (LCD_HEIGHT + LCD_VBP + LCD_VFP + LCD_VSW))
#define FPS_TARGET                                                     \
  (uint32_t)((float)LTDC_FREQ / ((lcd_params.hres + lcd_params.hbp +   \
                                  lcd_params.hfp + lcd_params.hsync) * \
                                 (lcd_params.vres + lcd_params.vbp +   \
                                  lcd_params.vfp + lcd_params.vsync)))

// 显示屏背光亮度（全局变量，-1表示未初始化）
static int DISPLAY_BACKLIGHT = -1;
// 显示屏方向（全局变量，-1表示未初始化）
static int DISPLAY_ORIENTATION = -1;

// DSI、DMA2D、LTDC外设句柄（全局变量）
static DSI_HandleTypeDef hlcd_dsi = {0};
static DMA2D_HandleTypeDef hlcd_dma2d = {0};
static LTDC_HandleTypeDef hlcd_ltdc = {0};

// DSI中断处理函数
void DSI_IRQHandler(void) {
  HAL_DSI_IRQHandler(&hlcd_dsi);
  dbg_printf("DSI_IRQHandler called!");  // 调试信息
}

// 当前LCD帧率
float lcd_fps = 0.0;
// static void frame_callback(DSI_HandleTypeDef* hdsi)
// {
//     static uint32_t lcd_fps_tick = 0;
//     static uint32_t lcd_fps_tock = 0;
//     lcd_fps_tick = lcd_fps_tock;
//     lcd_fps_tock = HAL_GetTick();
//     lcd_fps = 1000 / (lcd_fps_tock - lcd_fps_tick);
// }

// 初始化LCD背光PWM
void lcd_pwm_init(void) {
  GPIO_InitTypeDef gpio_init_structure = {0};
  /* LCD_BL_CTRL GPIO配置 */
  __HAL_RCC_GPIOK_CLK_ENABLE();   // 使能GPIOK时钟
  __HAL_RCC_TIM1_CLK_ENABLE();    // 使能TIM1时钟
  // LCD_PWM/PA7 (背光控制)
  gpio_init_structure.Mode = GPIO_MODE_AF_PP;         // 复用推挽输出
  gpio_init_structure.Pull = GPIO_NOPULL;             // 无上下拉
  gpio_init_structure.Speed = GPIO_SPEED_FREQ_LOW;    // 低速
  gpio_init_structure.Alternate = GPIO_AF1_TIM1;      // 复用为TIM1
  gpio_init_structure.Pin = LCD_BL_CTRL_PIN;          // 背光控制引脚
  HAL_GPIO_Init(LCD_BL_CTRL_GPIO_PORT, &gpio_init_structure);

  // 使能PWM定时器
  TIM_HandleTypeDef TIM1_Handle;
  TIM1_Handle.Instance = TIM1;
  TIM1_Handle.Init.Period = LED_PWM_TIM_PERIOD - 1;  // 设置周期
  // TIM1/APB2时钟等于fCPU，目标1MHz
  TIM1_Handle.Init.Prescaler =
      SystemCoreClock / 1000000 / 4 - 1;  // APB = fCPU/2(AHB)/2(APB)
  TIM1_Handle.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;  // 时钟分频
  TIM1_Handle.Init.CounterMode = TIM_COUNTERMODE_UP;        // 向上计数
  TIM1_Handle.Init.RepetitionCounter = 0;                   // 重复计数器
  HAL_TIM_PWM_Init(&TIM1_Handle);

  TIM_OC_InitTypeDef TIM_OC_InitStructure;
  TIM_OC_InitStructure.Pulse =
      (LED_PWM_TIM_PERIOD / 2 - 1);  // 默认50%占空比
  TIM_OC_InitStructure.OCMode = TIM_OCMODE_PWM2;            // PWM模式2
  TIM_OC_InitStructure.OCPolarity = TIM_OCPOLARITY_HIGH;    // 高电平有效
  TIM_OC_InitStructure.OCFastMode = TIM_OCFAST_DISABLE;     // 关闭快速模式
  TIM_OC_InitStructure.OCNPolarity = TIM_OCNPOLARITY_HIGH;  // 高电平有效
  TIM_OC_InitStructure.OCIdleState = TIM_OCIDLESTATE_SET;   // 空闲状态
  TIM_OC_InitStructure.OCNIdleState = TIM_OCNIDLESTATE_SET; // 空闲状态
  HAL_TIM_PWM_ConfigChannel(&TIM1_Handle, &TIM_OC_InitStructure, TIM_CHANNEL_1);

  HAL_TIM_PWM_Start(&TIM1_Handle, TIM_CHANNEL_1);           // 启动PWM
  HAL_TIMEx_PWMN_Start(&TIM1_Handle, TIM_CHANNEL_1);        // 启动互补PWM
}

// 初始化DMA2D外设
static HAL_StatusTypeDef dma2d_init(DMA2D_HandleTypeDef* hdma2d) {
  if (hdma2d->Instance != DMA2D) return HAL_ERROR;  // 检查实例

  // clock source
  {
    __HAL_RCC_DMA2D_CLK_ENABLE();
    __HAL_RCC_DMA2D_FORCE_RESET();
    __HAL_RCC_DMA2D_RELEASE_RESET();
  }

  return HAL_OK;
}

// LTDC初始化函数
static HAL_StatusTypeDef ltdc_init(LTDC_HandleTypeDef* hltdc) {
  if (hltdc->Instance != LTDC) return HAL_ERROR;

  // 配置LTDC时钟源
  {
    __HAL_RCC_LTDC_CLK_ENABLE();      // 使能LTDC时钟
    __HAL_RCC_LTDC_FORCE_RESET();     // 复位LTDC外设
    __HAL_RCC_LTDC_RELEASE_RESET();   // 释放LTDC外设复位

    RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};
    PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_LTDC;
    PeriphClkInitStruct.PLL3.PLL3M = 5U; // PLL3分频系数M
    PeriphClkInitStruct.PLL3.PLL3N = lcd_params.ltdc_pll.PLL3N; // PLL3倍频系数N
    PeriphClkInitStruct.PLL3.PLL3P = 2U; // PLL3分频系数P
    PeriphClkInitStruct.PLL3.PLL3Q = 2U; // PLL3分频系数Q
    PeriphClkInitStruct.PLL3.PLL3R = lcd_params.ltdc_pll.PLL3R; // PLL3分频系数R
    PeriphClkInitStruct.PLL3.PLL3RGE = RCC_PLLCFGR_PLL3RGE_2; // PLL3输入频率范围
    PeriphClkInitStruct.PLL3.PLL3VCOSEL = RCC_PLL3VCOWIDE; // PLL3宽VCO
    PeriphClkInitStruct.PLL3.PLL3FRACN = lcd_params.ltdc_pll.PLL3FRACN; // PLL3小数分频
    HAL_StatusTypeDef result = HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct);
    if (result != HAL_OK) {
      return result;
    }
  }

  // 配置极性参数
  hltdc->Init.HSPolarity = LTDC_HSPOLARITY_AH; // 行同步极性
  // hltdc->Init.HSPolarity = LTDC_HSPOLARITY_AL;

  hltdc->Init.VSPolarity = LTDC_VSPOLARITY_AH; // 场同步极性
  // hltdc->Init.VSPolarity = LTDC_VSPOLARITY_AL;

  // hltdc->Init.DEPolarity = LTDC_DEPOLARITY_AH;
  hltdc->Init.DEPolarity = LTDC_DEPOLARITY_AL; // 数据使能极性

  hltdc->Init.PCPolarity = LTDC_PCPOLARITY_IPC; // 像素时钟极性

  // 配置时序参数
  hltdc->Init.HorizontalSync = lcd_params.hsync - 1; // 行同步宽度
  hltdc->Init.AccumulatedHBP = lcd_params.hsync + lcd_params.hbp - 1; // 行同步+后沿
  hltdc->Init.AccumulatedActiveW =
      lcd_params.hsync + lcd_params.hres + lcd_params.hbp - 1; // 行同步+后沿+有效宽度
  hltdc->Init.TotalWidth =
      lcd_params.hsync + lcd_params.hres + lcd_params.hbp + lcd_params.hfp - 1; // 总宽度
  hltdc->Init.VerticalSync = lcd_params.vsync - 1; // 场同步宽度
  hltdc->Init.AccumulatedVBP = lcd_params.vsync + lcd_params.vbp - 1; // 场同步+后沿
  hltdc->Init.AccumulatedActiveH =
      lcd_params.vsync + lcd_params.vres + lcd_params.vbp - 1; // 场同步+后沿+有效高度
  hltdc->Init.TotalHeigh =
      lcd_params.vsync + lcd_params.vres + lcd_params.vbp + lcd_params.vfp - 1; // 总高度

  // 保持原来的黑色背景，避免影响正常显示
  hltdc->Init.Backcolor.Blue = 0x00;
  hltdc->Init.Backcolor.Green = 0x00;
  hltdc->Init.Backcolor.Red = 0x00;

  return HAL_LTDC_Init(hltdc);
}

// 配置LTDC图层参数
static HAL_StatusTypeDef ltdc_layer_config(LTDC_HandleTypeDef* hltdc,
                                           uint32_t layer_index,
                                           LTDC_LAYERCONFIG* config) {
  LTDC_LayerCfgTypeDef pLayerCfg;

  // 设置窗口起始和结束坐标
  pLayerCfg.WindowX0 = config->x0; // 窗口左上角X坐标
  pLayerCfg.WindowX1 = config->x1; // 窗口右下角X坐标
  pLayerCfg.WindowY0 = config->y0; // 窗口左上角Y坐标
  pLayerCfg.WindowY1 = config->y1; // 窗口右下角Y坐标
  // 设置像素格式
  pLayerCfg.PixelFormat = config->pixel_format; // 像素格式
  // 设置帧缓冲起始地址
  pLayerCfg.FBStartAdress = config->address; // 帧缓冲区起始地址
  // 设置图像宽高
  pLayerCfg.ImageWidth = (config->x1 - config->x0);   // 图像宽度
  pLayerCfg.ImageHeight = (config->y1 - config->y0);  // 图像高度
  // 设置背景色为黑色
  pLayerCfg.Backcolor.Blue = 0;   // 背景蓝色分量
  pLayerCfg.Backcolor.Green = 0;  // 背景绿色分量
  pLayerCfg.Backcolor.Red = 0;    // 背景红色分量
  
  if (layer_index == 0) {
    // 第一层：底层，完全不透明
    pLayerCfg.Alpha = 255; // 全局Alpha值，255为不透明
    pLayerCfg.Alpha0 = 0;  // 默认Alpha0
    pLayerCfg.BlendingFactor1 = LTDC_BLENDING_FACTOR1_PAxCA; // 混合因子1
    pLayerCfg.BlendingFactor2 = LTDC_BLENDING_FACTOR2_PAxCA; // 混合因子2
    // printf("Configuring first layer - opaque mode\n");
  } else {
    // 第二层：上层，根据状态栏透明度配置Color Keying混合
    pLayerCfg.Alpha = 255;  // 完全不透明
    pLayerCfg.Alpha0 = 0;
    pLayerCfg.BlendingFactor1 = LTDC_BLENDING_FACTOR1_PAxCA;
    pLayerCfg.BlendingFactor2 = LTDC_BLENDING_FACTOR2_PAxCA;
  }
  
  // 配置图层
  HAL_StatusTypeDef result = HAL_LTDC_ConfigLayer(hltdc, &pLayerCfg, layer_index);
  
  // 为Layer2根据当前状态配置Color Keying
  // 动画期间避免重新配置Color Keying，防止屏幕闪烁
  if (layer_index == 1 && result == HAL_OK && !g_animation_in_progress) {
    if (g_statusbar_transparent) {
      // 状态栏透明：启用Color Keying
      uint16_t color_key = TRANSPARENT_COLOR_KEY;
      uint32_t red = ((color_key >> 11) & 0x1F) << 3;     // R5 -> R8
      uint32_t green = ((color_key >> 5) & 0x3F) << 2;    // G6 -> G8
      uint32_t blue = (color_key & 0x1F) << 3;            // B5 -> B8
      
      uint32_t rgb888_key = (red << 16) | (green << 8) | blue;
      
      printf("Configuring Layer2 with Color Keying support\n");
      printf("Enabling Color Keying for Layer2: 0x%04x -> 0x%06lx (R:%lu G:%lu B:%lu)\n", 
             color_key, rgb888_key, red, green, blue);
      
      // 启用Color Keying
      if (HAL_LTDC_ConfigColorKeying(hltdc, rgb888_key, layer_index) == HAL_OK) {
        if (HAL_LTDC_EnableColorKeying(hltdc, layer_index) == HAL_OK) {
          printf("Color Keying enabled successfully for Layer2\n");
        } else {
          printf("Failed to enable Color Keying for Layer2\n");
        }
      } else {
        printf("Failed to configure Color Keying for Layer2\n");
      }
    } else {
      // 状态栏不透明：禁用Color Keying
      printf("Configuring Layer2 without Color Keying (opaque statusbar)\n");
      HAL_LTDC_DisableColorKeying(hltdc, layer_index);
    }
  } else if (layer_index == 1 && g_animation_in_progress) {
    // 动画期间不重新配置Color Keying，避免闪烁
    printf("Skipping Color Keying reconfiguration during animation to prevent flicker\n");
  }
  return result;
}

// 初始化DSI主机
static HAL_StatusTypeDef dsi_host_init(DSI_HandleTypeDef* hdsi) {
  if (hdsi->Instance != DSI) return HAL_ERROR;

  // 配置DSI时钟源
  {
    /** 使能DSI主机和包裹时钟 */
    __HAL_RCC_DSI_CLK_ENABLE();      // 使能DSI时钟
    __HAL_RCC_DSI_FORCE_RESET();     // DSI复位
    __HAL_RCC_DSI_RELEASE_RESET();   // 释放DSI复位

    RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};
    PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_DSI; // 选择DSI外设时钟
    PeriphClkInitStruct.DsiClockSelection = RCC_DSICLKSOURCE_PHY; // 选择DSI时钟源为PHY
    // PeriphClkInitStruct.DsiClockSelection = RCC_DSICLKSOURCE_PLL2; // PLL2Q = 9 in sdram.c
    HAL_StatusTypeDef result = HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct); // 配置外设时钟
    if (result != HAL_OK) {
      return result;
    }
  }

  // 配置中断（如有需要，可启用）
  {
      // HAL_NVIC_SetPriority(DSI_IRQn, 0, 0);
      // HAL_NVIC_EnableIRQ(DSI_IRQn);
  }

  // 配置DSI时钟分频
  {
    hdsi->Init.AutomaticClockLaneControl = DSI_AUTO_CLK_LANE_CTRL_DISABLE; // 禁用自动时钟通道控制
    hdsi->Init.TXEscapeCkdiv = 4;  // lp txclkesc 15.625 Mhz，低功耗逃逸时钟分频
    hdsi->Init.NumberOfLanes = DSI_TWO_DATA_LANES; // 使用2条数据通道

    // 配置DSI PLL，lane byte速率62.5MHz（最大支持）
    DSI_PLLInitTypeDef PLLInit = {0};
    PLLInit.PLLNDIV = 40;                 // PLL倍频系数
    PLLInit.PLLIDF = DSI_PLL_IN_DIV1;     // PLL输入分频
    PLLInit.PLLODF = DSI_PLL_OUT_DIV2;    // PLL输出分频
    if (HAL_DSI_Init(hdsi, &PLLInit) != HAL_OK) {
      return HAL_ERROR;
    }
  }

  // 配置DSI超时参数
  {
    DSI_HOST_TimeoutTypeDef HostTimeouts = {0};
    HostTimeouts.TimeoutCkdiv = 1;                 // 超时分频
    HostTimeouts.HighSpeedTransmissionTimeout = 0; // 高速传输超时
    HostTimeouts.LowPowerReceptionTimeout = 0;     // 低功耗接收超时
    HostTimeouts.HighSpeedReadTimeout = 0;         // 高速读超时
    HostTimeouts.LowPowerReadTimeout = 0;          // 低功耗读超时
    HostTimeouts.HighSpeedWriteTimeout = 0;        // 高速写超时
    HostTimeouts.HighSpeedWritePrespMode = DSI_HS_PM_DISABLE; // 高速写预响应模式
    HostTimeouts.LowPowerWriteTimeout = 0;         // 低功耗写超时
    HostTimeouts.BTATimeout = 0;                   // BTA超时
    if (HAL_DSI_ConfigHostTimeouts(hdsi, &HostTimeouts) != HAL_OK) {
      return HAL_ERROR;
    }
  }

  // 配置DSI PHY时序参数
  {
    DSI_PHY_TimerTypeDef PhyTimings = {0};
    PhyTimings.ClockLaneHS2LPTime = 27;   // 时钟通道HS到LP转换时间
    PhyTimings.ClockLaneLP2HSTime = 32;   // 时钟通道LP到HS转换时间
    PhyTimings.DataLaneHS2LPTime = 15;    // 数据通道HS到LP转换时间
    PhyTimings.DataLaneLP2HSTime = 24;    // 数据通道LP到HS转换时间
    PhyTimings.DataLaneMaxReadTime = 0;   // 数据通道最大读时间
    PhyTimings.StopWaitTime = 0;          // 停止等待时间
    if (HAL_DSI_ConfigPhyTimer(hdsi, &PhyTimings) != HAL_OK) {
      return HAL_ERROR;
    }
  }

  // 配置DSI流控、低功耗接收过滤器和错误监控
  if (HAL_DSI_ConfigFlowControl(hdsi, DSI_FLOW_CONTROL_BTA) != HAL_OK) {
    return HAL_ERROR;
  }
  if (HAL_DSI_SetLowPowerRXFilter(hdsi, 10000) != HAL_OK) {
    return HAL_ERROR;
  }
  if (HAL_DSI_ConfigErrorMonitor(hdsi, HAL_DSI_ERROR_GEN) != HAL_OK) {
    return HAL_ERROR;
  }

  // 配置DSI视频模式参数
  {
    DSI_VidCfgTypeDef VidCfg = {0};
    VidCfg.VirtualChannelID = 0; // 虚拟通道ID
    VidCfg.ColorCoding = lcd_params.pixel_format_dsi; // 颜色编码
    VidCfg.LooselyPacked = DSI_LOOSELY_PACKED_DISABLE; // 非松散打包
    VidCfg.Mode = DSI_VID_MODE_BURST; // burst模式
    VidCfg.PacketSize = lcd_params.hres; // 每行像素数
    VidCfg.NumberOfChunks = 0;  // burst模式下无需分块
    VidCfg.NullPacketSize = 0;  // burst模式下无需空包
    VidCfg.HSPolarity = DSI_HSYNC_ACTIVE_HIGH; // 行同步极性
    VidCfg.VSPolarity = DSI_VSYNC_ACTIVE_HIGH; // 场同步极性
    VidCfg.DEPolarity = DSI_DATA_ENABLE_ACTIVE_HIGH; // 数据使能极性
    VidCfg.HorizontalSyncActive = (lcd_params.hsync * DSI_FREQ) / LTDC_FREQ; // 行同步宽度
    VidCfg.HorizontalBackPorch = (lcd_params.hbp * DSI_FREQ) / LTDC_FREQ;    // 行后沿
    VidCfg.HorizontalLine = ((lcd_params.hres + lcd_params.hsync +
                              lcd_params.hbp + lcd_params.hfp) *
                             DSI_FREQ) /
                            LTDC_FREQ; // 总行周期
    VidCfg.VerticalSyncActive = lcd_params.vsync; // 场同步宽度
    VidCfg.VerticalBackPorch = lcd_params.vbp;    // 场后沿
    VidCfg.VerticalFrontPorch = lcd_params.vfp;   // 场前沿
    VidCfg.VerticalActive = lcd_params.vres;      // 有效行数

    // 低功耗模式相关配置
    VidCfg.LPCommandEnable = DSI_LP_COMMAND_ENABLE;           // 使能低功耗命令
    VidCfg.LPLargestPacketSize = 128;                         // 低功耗最大包大小
    VidCfg.LPVACTLargestPacketSize = 0;                       // 低功耗VACT最大包大小
    VidCfg.LPHorizontalFrontPorchEnable = DSI_LP_HFP_ENABLE;  // 使能低功耗HFP
    VidCfg.LPHorizontalBackPorchEnable = DSI_LP_HBP_ENABLE;   // 使能低功耗HBP
    VidCfg.LPVerticalActiveEnable = DSI_LP_VACT_ENABLE;       // 使能低功耗VACT
    VidCfg.LPVerticalFrontPorchEnable = DSI_LP_VFP_ENABLE;    // 使能低功耗VFP
    VidCfg.LPVerticalBackPorchEnable = DSI_LP_VBP_ENABLE;     // 使能低功耗VBP
    VidCfg.LPVerticalSyncActiveEnable = DSI_LP_VSYNC_ENABLE;  // 使能低功耗VSYNC
    VidCfg.FrameBTAAcknowledgeEnable = DSI_FBTAA_DISABLE;     // 禁用BTA帧确认

    if (HAL_DSI_ConfigVideoMode(hdsi, &VidCfg) != HAL_OK) {
      return HAL_ERROR;
    }
  }

  return HAL_OK;
}

// 将RGB565格式颜色转换为ARGB8888格式的宏定义
#define CONVERTRGB5652ARGB8888(Color)                                   \
  ((((((((Color) >> (11U)) & 0x1FU) * 527U) + 23U) >> (6U)) << (16U)) | \
   (((((((Color) >> (5U)) & 0x3FU) * 259U) + 33U) >> (6U)) << (8U)) |   \
   (((((Color)&0x1FU) * 527U) + 23U) >> (6U)) | (0xFF000000U))


// 向指定坐标(x_pos, y_pos)写入像素值
void fb_write_pixel(uint32_t x_pos, uint32_t y_pos, uint32_t color) {
  if (lcd_params.pixel_format_ltdc == LTDC_PIXEL_FORMAT_ARGB8888) {
    *(uint32_t*)(lcd_params.fb_base +
                 (lcd_params.bbp * (lcd_params.hres * y_pos + x_pos))) = color;
  } else {
    /* LTDC像素格式为RGB565 */
    *(uint16_t*)(lcd_params.fb_base +
                 (lcd_params.bbp * (lcd_params.hres * y_pos + x_pos))) = color;
  }
}

// 使用DMA2D填充缓冲区
static void fb_fill_buffer(uint32_t* dest, uint32_t x_size, uint32_t y_size,
                           uint32_t offset, uint32_t color) {
  uint32_t output_color_mode, input_color = color;

  switch (lcd_params.pixel_format_ltdc) {
    case LTDC_PIXEL_FORMAT_RGB565:
      output_color_mode = DMA2D_OUTPUT_RGB565; /* RGB565输出模式 */
      input_color = CONVERTRGB5652ARGB8888(color); // 转换为ARGB8888
      break;
    case LTDC_PIXEL_FORMAT_RGB888:
    default:
      output_color_mode = DMA2D_OUTPUT_ARGB8888; /* ARGB8888输出模式 */
      break;
  }

  /* 配置DMA2D为寄存器到内存模式，颜色模式为output_color_mode */
  hlcd_dma2d.Init.Mode = DMA2D_R2M;
  hlcd_dma2d.Init.ColorMode = output_color_mode;
  hlcd_dma2d.Init.OutputOffset = offset;

  hlcd_dma2d.Instance = DMA2D;

  /* DMA2D初始化 */
  if (HAL_DMA2D_Init(&hlcd_dma2d) == HAL_OK) {
    if (HAL_DMA2D_ConfigLayer(&hlcd_dma2d, 1) == HAL_OK) {
      if (HAL_DMA2D_Start(&hlcd_dma2d, input_color, (uint32_t)dest, x_size,
                          y_size) == HAL_OK) {
        /* 轮询等待DMA传输完成 */
        (void)HAL_DMA2D_PollForTransfer(&hlcd_dma2d, 25);
      }
    }
  }
}

// 填充矩形区域
void fb_fill_rect(uint32_t x_pos, uint32_t y_pos, uint32_t width,
                  uint32_t height, uint32_t color) {
  /* 获取矩形起始地址 */
  uint32_t address = lcd_params.fb_base +
                     ((lcd_params.bbp) * (lcd_params.hres * y_pos + x_pos));

  /* 填充矩形 */
  fb_fill_buffer((uint32_t*)address, width, height, (lcd_params.hres - width),
                 color);
}


// 使用DMA2D拷贝缓冲区
void dma2d_copy_buffer(uint32_t* pSrc, uint32_t* pDst, uint16_t x, uint16_t y,
                       uint16_t xsize, uint16_t ysize) {
  uint32_t destination =
      (uint32_t)pDst + (y * lcd_params.hres + x) * (lcd_params.bbp);
  uint32_t source = (uint32_t)pSrc;

  /*##-1- 配置DMA2D模式、颜色模式和输出偏移量 #############*/
  hlcd_dma2d.Init.Mode = DMA2D_M2M;
  hlcd_dma2d.Init.ColorMode = DMA2D_OUTPUT_RGB565;
  hlcd_dma2d.Init.OutputOffset = lcd_params.hres - xsize;
  hlcd_dma2d.Init.AlphaInverted =
      DMA2D_REGULAR_ALPHA; /* 不反转输出Alpha */
  hlcd_dma2d.Init.RedBlueSwap =
      DMA2D_RB_REGULAR; /* 不交换输出红蓝 */

  /*##-2- DMA2D回调配置 ######################################*/
  hlcd_dma2d.XferCpltCallback = NULL;

  /*##-3- 前景层配置 ###########################################*/
  hlcd_dma2d.LayerCfg[1].AlphaMode = DMA2D_NO_MODIF_ALPHA;
  hlcd_dma2d.LayerCfg[1].InputAlpha = 0xFF;
  hlcd_dma2d.LayerCfg[1].InputColorMode = DMA2D_INPUT_RGB565;
  hlcd_dma2d.LayerCfg[1].InputOffset = 0;
  hlcd_dma2d.LayerCfg[1].RedBlueSwap =
      DMA2D_RB_REGULAR; /* 不交换前景红蓝 */
  hlcd_dma2d.LayerCfg[1].AlphaInverted =
      DMA2D_REGULAR_ALPHA; /* 不反转前景Alpha */

  hlcd_dma2d.Instance = DMA2D;

  /* DMA2D初始化 */
  if (HAL_DMA2D_Init(&hlcd_dma2d) == HAL_OK) {
    if (HAL_DMA2D_ConfigLayer(&hlcd_dma2d, 1) == HAL_OK) {
      // while ( lcd_ltdc_busy() ) {}
      if (HAL_DMA2D_Start(&hlcd_dma2d, source, destination, xsize, ysize) ==
          HAL_OK) {
        /* 轮询等待DMA传输完成 */
        HAL_DMA2D_PollForTransfer(&hlcd_dma2d, HAL_MAX_DELAY);
      }
    }
  }
}

// 使用DMA2D将YCbCr格式转换为RGB并拷贝
void dma2d_copy_ycbcr_to_rgb(uint32_t* pSrc, uint32_t* pDst, uint16_t xsize,
                             uint16_t ysize, uint32_t ChromaSampling) {
  uint32_t cssMode = DMA2D_CSS_420, inputLineOffset = 0;

  // 根据色度子采样类型设置DMA2D参数
  if (ChromaSampling == JPEG_420_SUBSAMPLING) {
    cssMode = DMA2D_CSS_420;

    inputLineOffset = xsize % 16;
    if (inputLineOffset != 0) {
      inputLineOffset = 16 - inputLineOffset;
    }
  } else if (ChromaSampling == JPEG_444_SUBSAMPLING) {
    cssMode = DMA2D_NO_CSS;

    inputLineOffset = xsize % 8;
    if (inputLineOffset != 0) {
      inputLineOffset = 8 - inputLineOffset;
    }
  } else if (ChromaSampling == JPEG_422_SUBSAMPLING) {
    cssMode = DMA2D_CSS_422;

    inputLineOffset = xsize % 16;
    if (inputLineOffset != 0) {
      inputLineOffset = 16 - inputLineOffset;
    }
  }

  /*##-1- 配置DMA2D模式、颜色模式和输出偏移量 #############*/
  hlcd_dma2d.Init.Mode = DMA2D_M2M_PFC;
  hlcd_dma2d.Init.ColorMode = DMA2D_OUTPUT_RGB565;
  hlcd_dma2d.Init.OutputOffset = 0;
  hlcd_dma2d.Init.AlphaInverted =
      DMA2D_REGULAR_ALPHA; /* 不反转输出Alpha */
  hlcd_dma2d.Init.RedBlueSwap =
      DMA2D_RB_REGULAR; /* 不交换输出红蓝 */

  /*##-2- DMA2D回调配置 ######################################*/
  hlcd_dma2d.XferCpltCallback = NULL;

  /*##-3- 前景层配置 ###########################################*/
  hlcd_dma2d.LayerCfg[1].AlphaMode = DMA2D_REPLACE_ALPHA;
  hlcd_dma2d.LayerCfg[1].InputAlpha = 0xFF;
  hlcd_dma2d.LayerCfg[1].InputColorMode = DMA2D_INPUT_YCBCR;
  hlcd_dma2d.LayerCfg[1].ChromaSubSampling = cssMode;
  hlcd_dma2d.LayerCfg[1].InputOffset = inputLineOffset;
  hlcd_dma2d.LayerCfg[1].RedBlueSwap =
      DMA2D_RB_REGULAR; /* 不交换前景红蓝 */
  hlcd_dma2d.LayerCfg[1].AlphaInverted =
      DMA2D_REGULAR_ALPHA; /* 不反转前景Alpha */

  hlcd_dma2d.Instance = DMA2D;

  /*##-4- DMA2D初始化     ###########################################*/
  HAL_DMA2D_Init(&hlcd_dma2d);
  HAL_DMA2D_ConfigLayer(&hlcd_dma2d, 1);

  HAL_DMA2D_Start(&hlcd_dma2d, (uint32_t)pSrc, (uint32_t)pDst, xsize, ysize);
  HAL_DMA2D_PollForTransfer(
      &hlcd_dma2d, 25); /* 等待前一次DMA2D传输完成 */
}

// 发送DSI DCS写命令
int DSI_DCS_write(uint16_t cmd, uint8_t* data, uint16_t data_len) {
  // 如果数据长度小于等于1，使用短包写命令
  if (data_len <= 1) {
    return HAL_DSI_ShortWrite(&hlcd_dsi, 0, DSI_DCS_SHORT_PKT_WRITE_P1, cmd,
                              (uint32_t)data[0]);
  } else {
    // 否则使用长包写命令
    return HAL_DSI_LongWrite(&hlcd_dsi, 0, DSI_DCS_LONG_PKT_WRITE, data_len,
                             cmd, data);
  }
}

// 设置显示屏背光亮度（0~255），并返回当前背光值
int display_backlight(int val) {
  // 只有当亮度值发生变化且在有效范围内时才更新
  if (DISPLAY_BACKLIGHT != val && val >= 0 && val <= 255) {
    DISPLAY_BACKLIGHT = val;
    // 设置PWM占空比调节背光
    TIM1->CCR1 = (LED_PWM_TIM_PERIOD - 1) * val / 255;
  }
  return DISPLAY_BACKLIGHT;
}

// 设置背光亮度，并在亮灭时自动复位/恢复LCD
int display_backlight_with_lcd_reset(int val) {
  // 关闭背光且当前不是0时，先关背光再挂起刷新
  if (val == 0 && DISPLAY_BACKLIGHT != 0) {
    display_backlight(0);
    lcd_refresh_suspend();
  } else if (val > 0 && DISPLAY_BACKLIGHT == 0) {
    // 打开背光且当前为0时，先恢复刷新再开背光
    lcd_refresh_resume();
    HAL_Delay(5); // 等待LCD恢复
  }
  return display_backlight(val);
}

// 设置显示方向（0/90/180/270度），返回当前方向
int display_orientation(int degrees) {
  if (degrees != DISPLAY_ORIENTATION) {
    if (degrees == 0 || degrees == 90 || degrees == 180 || degrees == 270) {
      DISPLAY_ORIENTATION = degrees;
      // 这里只记录方向，不做实际操作
    }
  }
  return DISPLAY_ORIENTATION;
}

// LCD初始化函数
void lcd_init(void) {
  // printf("LCD initialization started - single layer mode\n");
  
  // gpio初始化
  {
    GPIO_InitTypeDef gpio_init_structure = {0};

    // RESET引脚初始化
    __HAL_RCC_GPIOG_CLK_ENABLE();
    gpio_init_structure.Pin = LCD_RESET_PIN;
    gpio_init_structure.Mode = GPIO_MODE_OUTPUT_PP;
    gpio_init_structure.Pull = GPIO_PULLUP;
    gpio_init_structure.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LCD_RESET_GPIO_PORT, &gpio_init_structure);

    // TE引脚初始化
    __HAL_RCC_GPIOJ_CLK_ENABLE();
    gpio_init_structure.Pin = LCD_TE_PIN;
    gpio_init_structure.Mode = GPIO_MODE_INPUT;
    gpio_init_structure.Pull = GPIO_NOPULL;
    gpio_init_structure.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(LCD_TE_GPIO_PORT, &gpio_init_structure);
    // HAL_GPIO_WritePin(LCD_TE_GPIO_PORT, LCD_TE_PIN, GPIO_PIN_SET); // TODO: 是否需要？
  }

  // dma2d初始化
  {
    hlcd_dma2d.Instance = DMA2D;
    dma2d_init(&hlcd_dma2d);
  }

  // ltdc初始化
  {
    hlcd_ltdc.Instance = LTDC;
    if (ltdc_init(&hlcd_ltdc) != HAL_OK) dbg_printf("ltdc_init failed !\r\n");

    LTDC_LAYERCONFIG config;
    config.x0 = 0;
    config.x1 = lcd_params.hres;
    config.y0 = 0;
    config.y1 = lcd_params.vres;
    config.pixel_format = lcd_params.pixel_format_ltdc;
    config.address = DISPLAY_MEMORY_BASE;
    if (ltdc_layer_config(&hlcd_ltdc, 0, &config) != HAL_OK)
      dbg_printf("ltdc_layer_config failed !\r\n");
  }

  // dsi host初始化
  {
    hlcd_dsi.Instance = DSI;
    if (dsi_host_init(&hlcd_dsi) != HAL_OK)
      dbg_printf("dsi_host_init failed !\r\n");
  }

  // lcd初始化流程
  {
    // 复位LCD
    HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_SET);
    HAL_Delay(20);
    HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_RESET);
    HAL_Delay(50);
    HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_SET);
    HAL_Delay(120);
    HAL_DSI_Start(&hlcd_dsi);  // 确保ltdc已初始化后再启动DSI

    // 发送LCD初始化序列
    int result = LCD_init_sequence(DSI_DCS_write, HAL_Delay);
    if (result != 0) {
      dbg_printf("LCD_init_sequence failed with 0x%02x!\r\n", result);
      while (1)
        ;
    }
  }

  dbg_printf("LTDC_FREQ=%d\r\n", LTDC_FREQ);
  dbg_printf("DSI_FREQ=%d\r\n", DSI_FREQ);
  dbg_printf("FPS_TARGET=%d\r\n", FPS_TARGET);
  
  // printf("First layer initialization completed, starting second layer initialization\n");
  
  // 初始化第二层layer
  lcd_add_second_layer();
  
  // printf("LCD initialization completely finished\n");
}

// 刷新显示（未实现）
void display_refresh(void) {}

// 设置显示窗口（未实现）
void display_set_window(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1) {}

void display_reset_state() {}

void display_clear_save(void) {}

const char* display_save(const char* prefix) { return NULL; }

// 灰度值转换为RGB565格式（反色）
static uint16_t grayscale_to_rgb565(uint8_t gray) {
  uint16_t r = (gray * 31 + 127) / 255;
  uint16_t g = (gray * 63 + 127) / 255;
  uint16_t b = (gray * 31 + 127) / 255;

  return 0xffff - ((r << 11) | (g << 5) | b);
}

// 按灰度数据绘制像素块
void display_fp(uint16_t x, uint16_t y, uint16_t w, uint16_t h,
                const uint8_t* data) {
  for (uint32_t i = 0; i < w * h; i++) {
    fb_write_pixel(x + i % w, y + i / w, grayscale_to_rgb565(data[i]));
  }
}

// 判断LTDC是否忙（低电平为忙）
int lcd_ltdc_busy(void) {
  hlcd_ltdc.Instance = LTDC;
  // low is busy
  return hlcd_ltdc.Instance->CDSR & 0x01 ? 0 : 1;
}

// 禁用LTDC和DSI（等待传输完成）
void lcd_ltdc_dsi_disable(void) {
  hlcd_ltdc.Instance = LTDC;
  hlcd_dsi.Instance = DSI;
  while (lcd_ltdc_busy()) {
  }
  HAL_DSI_Stop(&hlcd_dsi);
  __HAL_LTDC_DISABLE(&hlcd_ltdc);
}

// 使能LTDC和DSI
void lcd_ltdc_dsi_enable(void) {
  hlcd_ltdc.Instance = LTDC;
  hlcd_dsi.Instance = DSI;
  __HAL_LTDC_ENABLE(&hlcd_ltdc);
  HAL_DSI_Start(&hlcd_dsi);
}

// 挂起LCD刷新（先禁用LTDC/DSI，再复位LCD，等待完全消隐）
void lcd_refresh_suspend(void) {
  // 等待传输完成
  lcd_ltdc_dsi_disable();

  // 复位LCD
  HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_RESET);
  // 等待完全消隐，Sleep Out模式下需120ms
  HAL_Delay(125);
}

void lcd_refresh_resume(void) { // 恢复LCD刷新
  // lcd reset // 复位LCD
  HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_RESET); // 拉低复位引脚
  HAL_Delay(5); // 延时5毫秒
  HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_SET); // 拉高复位引脚
  HAL_Delay(50); // 延时50毫秒
  lcd_ltdc_dsi_enable(); // 使能LTDC和DSI
  // lcd wakeup / re-init // 唤醒LCD并重新初始化
  int result = LCD_init_sequence(DSI_DCS_write, HAL_Delay); // 执行LCD初始化序列
  if (result != 0) { // 如果初始化失败
    dbg_printf("LCD_init_sequence failed with 0x%02x!\r\n", result); // 打印错误信息
    while (1) // 死循环，阻止继续执行
      ;
  }
}

static volatile uint32_t g_current_display_addr = FMC_SDRAM_LTDC_BUFFER_ADDRESS; // 当前显示帧缓冲区地址

void lcd_set_src_addr(uint32_t addr) { // 设置LTDC源地址
  static uint32_t animation_counter = 0; // 动画计数器
  static uint32_t last_addr = 0; // 上一次设置的地址
  
  // 如果地址没有变化则跳过更新，减少不必要的重载
  if (addr == last_addr) { // 地址未变化
    return; // 直接返回
  }
  
  // 动画期间保持Layer0正常更新，但使用更温和的重载方式
  // 不跳过更新，确保Layer0内容正常显示
  
  last_addr = addr; // 更新上一次的地址
  
  hlcd_ltdc.Instance = LTDC; // 设置LTDC实例
  LTDC_LAYERCONFIG config; // 定义层配置结构体
  config.x0 = 0; // 层起始X坐标为0
  config.x1 = lcd_params.hres; // 层结束X坐标为屏幕宽度
  config.y0 = 0; // 层起始Y坐标为0
  config.y1 = lcd_params.vres; // 层结束Y坐标为屏幕高度
  config.pixel_format = lcd_params.pixel_format_ltdc; // 设置像素格式
  config.address = addr; // 设置帧缓冲区地址
  if (ltdc_layer_config(&hlcd_ltdc, 0, &config) != HAL_OK) { // 配置Layer0
    dbg_printf("ltdc_layer_config failed !\r\n"); // 配置失败打印错误
  }
  
  // Ensure first layer is always enabled // 确保Layer0始终启用
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 0); // 启用Layer0
  // 注意：不要在这里设置Layer0透明度，会干扰正常显示
  // Remove frequent debug output to reduce log spam // 移除频繁的调试输出，减少日志干扰
  
  // 使用VSync重载减少闪动
  __HAL_LTDC_RELOAD_CONFIG(&hlcd_ltdc); // 触发LTDC重载（VSync同步）
  
  // 动画期间暂停second layer维护，避免干扰Layer0显示
  if (!g_animation_in_progress) { // 如果没有动画进行中
    animation_counter++; // 动画计数器自增
    if (animation_counter % 2 == 0) {  // Every other call to maintain 30fps animation // 每两次调用维护一次第二层，保持30fps动画
      lcd_ensure_second_layer(); // 确保第二层存在
    }
  }
  
  g_current_display_addr = addr; // 更新当前显示地址
  
  // 当Layer2显示时，更新Layer1背景以匹配Layer2，确保状态栏区域背景一致
  // 只有在非动画期间且Layer2可见时才更新，避免性能影响
  if (!g_animation_in_progress && lcd_cover_background_is_visible() && animation_counter % 4 == 0) { // 满足条件时
    lcd_cover_background_update_layer1_from_layer2(); // 用Layer2内容更新Layer1状态栏区域
  }
}

uint32_t lcd_get_src_addr(void) { return g_current_display_addr; } // 获取当前显示帧缓冲区地址

// Second layer configuration function - CoverBackground 硬件层
void lcd_add_second_layer(void) { // 添加第二层（CoverBackground）
  // Check if already initialized // 检查是否已初始化
  if (g_layer2_initialized) { // 已初始化则直接返回
    return;
  }
  
  // 配置第二层layer (layer 1) - 专门用于CoverBackground
  // Layer2覆盖整个屏幕，但顶部44px保持透明，让Layer1状态栏透过
  printf("Configuring Layer2 covering full screen with transparent statusbar (height=%d)\n", TRANSPARENT_STATUSBAR_HEIGHT); // 打印配置信息
  LTDC_LAYERCONFIG config; // 定义层配置结构体
  config.x0 = 0; // 层起始X坐标为0
  config.x1 = lcd_params.hres; // 层结束X坐标为屏幕宽度
  config.y0 = 0;  // 从0开始显示，覆盖整个屏幕
  config.y1 = lcd_params.vres; // 层结束Y坐标为屏幕高度
  config.pixel_format = lcd_params.pixel_format_ltdc; // 设置像素格式
  // Layer2内存从第一行开始，前44行保持透明，壁纸内容从第一行开始与Layer1重合
  config.address = LAYER2_MEMORY_BASE; // 设置Layer2帧缓冲区地址
  
  if (ltdc_layer_config(&hlcd_ltdc, 1, &config) != HAL_OK) { // 配置Layer1
    return; // 配置失败直接返回
  }
  
  // 初始化CoverBackground内容
  lcd_cover_background_init(); // 初始化CoverBackground内容
  
  // 初始状态：只配置Layer1，不干扰Layer0
  hlcd_ltdc.Instance = LTDC; // 设置LTDC实例
  
  // 确保Layer0已经启用（但不修改其透明度，避免干扰正常显示）
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 0); // 启用Layer0
  
  // 只配置Layer1
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // Layer 1 完全不透明
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1); // 启用Layer1
  
  // 将layer初始化到屏幕上方位置（考虑透明状态栏）
  // 标记为已初始化后再移动
  g_layer2_initialized = true; // 标记Layer2已初始化
  
  // 初始化动画系统
  lcd_animation_init(); // 初始化动画系统
  
  // 现在可以安全地移动layer
  lcd_cover_background_move_to_y(-800); // 将Layer2移动到屏幕上方（隐藏）
  
  // 使用VSync重载避免干扰正常显示
  __HAL_LTDC_RELOAD_CONFIG(&hlcd_ltdc); // 触发LTDC重载（VSync同步）
}



// CoverBackground layer state - 硬件层实现
static struct {
  bool visible; // 是否可见
  uint8_t opacity;     // 0-255 // 透明度
  int32_t y_offset;    // Y轴偏移，-60为隐藏位置，0为显示位置
  bool is_animating; // 是否正在动画
} cover_bg_state = {false, 0, -800, false};  // 初始状态：隐藏，透明，位置在屏幕上方（考虑透明状态栏）

// 初始化 CoverBackground 内容
void lcd_cover_background_init(void) { // 初始化CoverBackground内容
  if (!g_layer2_initialized) { // 如果Layer2未初始化
    return; // 直接返回
  }
  
  // 在初始化时就分配备份缓冲区
  if (g_statusbar_backup_buffer == NULL) {
    uint32_t backup_size = lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT * sizeof(uint16_t);
    // 使用SDRAM中的一个安全位置（在Layer2内存后面）
    g_statusbar_backup_buffer = (uint16_t*)(LAYER2_MEMORY_BASE + lcd_params.hres * lcd_params.vres * 2 + 0x1000);
    printf("CoverBackground: Allocated backup buffer at 0x%p, size: %lu bytes\n", g_statusbar_backup_buffer, backup_size);
  }
  
  uint16_t *layer2_buffer = (uint16_t*)LAYER2_MEMORY_BASE; // 获取Layer2缓冲区指针
  uint32_t buffer_size = lcd_params.hres * lcd_params.vres; // 计算像素数量
  
  // 先清空整个layer2缓冲区，避免随机数据
  printf("CoverBackground: Clearing layer2 buffer...\n"); // 打印清空信息
  for (uint32_t i = 0; i < buffer_size; i++) { // 遍历每个像素
    layer2_buffer[i] = 0x0000;  // 清除为黑色
  }
  
  // 复制Layer1当前显示内容到Layer2，确保背景一致
  printf("CoverBackground: Copying Layer1 background to Layer2 for consistency\n"); // 打印复制信息
  
  // 使用DMA2D安全地复制当前Layer1显示内容
  if (g_current_display_addr != 0) { // 如果当前显示地址有效
    printf("CoverBackground: Using DMA2D to copy Layer1 background (addr=0x%08lx)\n", g_current_display_addr); // 打印地址信息
    
    // 使用DMA2D复制整个Layer1内容到Layer2，确保背景一致
    dma2d_copy_buffer((uint32_t*)g_current_display_addr, 
                      (uint32_t*)LAYER2_MEMORY_BASE,
                      0, 0, lcd_params.hres, lcd_params.vres); // DMA2D拷贝
    
    printf("CoverBackground: Layer1 background copied to Layer2 successfully\n"); // 打印成功信息
  } else {
    // 如果没有Layer1内容，使用默认Layer1帧缓冲区
    printf("CoverBackground: Using default Layer1 framebuffer for background consistency\n"); // 打印默认信息
    dma2d_copy_buffer((uint32_t*)FMC_SDRAM_LTDC_BUFFER_ADDRESS, 
                      (uint32_t*)LAYER2_MEMORY_BASE,
                      0, 0, lcd_params.hres, lcd_params.vres); // DMA2D拷贝
  }
  
  // 验证初始化后状态栏区域的数据，不再添加测试图案
  printf("CoverBackground: Verifying statusbar area after initialization\n");
  uint32_t statusbar_non_black = 0;
  for (uint32_t i = 0; i < lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT; i++) {
    if (layer2_buffer[i] != 0x0000) {
      statusbar_non_black++;
    }
  }
  printf("CoverBackground: Statusbar area has %lu non-black pixels after init\n", statusbar_non_black);
}


// 更新Layer1背景以匹配Layer2 - 确保状态栏区域背景一致
void lcd_cover_background_update_layer1_from_layer2(void) { // 用Layer2内容更新Layer1状态栏区域
  if (!g_layer2_initialized) { // 如果Layer2未初始化
    return; // 直接返回
  }
  
  printf("CoverBackground: Updating Layer1 background to match Layer2\n"); // 打印更新信息
  
  // 使用当前Layer1显示地址
  uint32_t layer1_addr = g_current_display_addr ? g_current_display_addr : FMC_SDRAM_LTDC_BUFFER_ADDRESS; // 获取Layer1地址
  
  // 方案1：直接复制Layer2的状态栏区域到Layer1
  // 这样可以确保状态栏区域背景完全一致
  dma2d_copy_buffer((uint32_t*)LAYER2_MEMORY_BASE, 
                    (uint32_t*)layer1_addr,
                    0, 0, lcd_params.hres, TRANSPARENT_STATUSBAR_HEIGHT); // DMA2D拷贝状态栏区域
  
  printf("CoverBackground: Layer1 statusbar background updated to match Layer2 (addr=0x%08lx)\n", layer1_addr); // 打印成功信息
  
  // 方案2：如果需要更完整的背景一致性，可以加载相同的背景图片到Layer1
  // 这里可以调用JPEG解码器将g_layer1_background_path指定的图片加载到Layer1
  // 但这会覆盖Layer1的UI元素，所以暂时只使用方案1
}


// 显示 CoverBackground - 硬件透明度控制
void lcd_cover_background_show(void) { // 显示CoverBackground
  if (!g_layer2_initialized) { // 如果Layer2未初始化
    return; // 直接返回
  }
  
  cover_bg_state.visible = true; // 设置为可见
  cover_bg_state.opacity = 255;  // 完全不透明
  cover_bg_state.y_offset = 0;  // 显示时的正常位置
  
  // Layer1始终保持不透明
  hlcd_ltdc.Instance = LTDC; // 设置LTDC实例
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // 始终不透明
  
  // 不自动启用Color Keying，statusbar透明度将通过专门的函数控制
  printf("CoverBackground: Layer2 shown, statusbar transparency will be controlled separately\n");
  
  // 移动layer到正确位置（显示时的正常位置）
  lcd_cover_background_move_to_y(0); // 移动Layer2到显示位置
  
  // 显示Layer2时，立即更新Layer1背景以匹配Layer2，确保状态栏区域背景一致
  lcd_cover_background_update_layer1_from_layer2(); // 用Layer2内容更新Layer1状态栏区域
  
  __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc); // 立即重载LTDC配置
}

// 隐藏 CoverBackground - 硬件透明度控制
void lcd_cover_background_hide(void) {
  if (!g_layer2_initialized) {
    return;
  }
  
  cover_bg_state.visible = false;
  cover_bg_state.opacity = 0;
  cover_bg_state.y_offset = -800;
  
  // Layer1保持不透明，只通过位置隐藏
  hlcd_ltdc.Instance = LTDC;
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // 保持不透明
  
  // 禁用Layer2的Color Keying功能
  printf("CoverBackground: Disabling Color Keying for Layer2\n");
  HAL_LTDC_DisableColorKeying(&hlcd_ltdc, 1);
  
  // 移动layer到隐藏位置
  lcd_cover_background_move_to_y(-800);
  
  __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
}

// 设置 CoverBackground 透明度 - 硬件控制
void lcd_cover_background_set_opacity(uint8_t opacity) {
  if (!g_layer2_initialized) {
    return;
  }
  
  // 不再支持透明度变化，始终保持不透明
  cover_bg_state.opacity = 255;  // 强制为不透明
  
  // Layer1始终保持不透明
  hlcd_ltdc.Instance = LTDC;
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // 始终不透明
  __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
}

// 设置 CoverBackground 可见性状态 - 不改变硬件，只更新状态
void lcd_cover_background_set_visible(bool visible) {
  if (!g_layer2_initialized) {
    return;
  }
  
  cover_bg_state.visible = visible;
}

// 设置CoverBackground图片数据
void lcd_cover_background_set_image(const void* image_data, uint32_t image_size) {
  if (!g_layer2_initialized) {
    printf("ERROR: layer2 not initialized for image setting\n");
    return;
  }
  
  printf("Setting CoverBackground image, size: %lu bytes\n", image_size);
  
  uint16_t *layer2_buffer = (uint16_t*)LAYER2_MEMORY_BASE;
  uint32_t max_pixels = lcd_params.hres * lcd_params.vres;
  uint32_t max_bytes = max_pixels * 2; // RGB565 = 2 bytes per pixel
  
  // Ensure we don't exceed buffer size
  uint32_t copy_size = (image_size > max_bytes) ? max_bytes : image_size;
  
  // Copy image data directly to layer2 buffer
  memcpy(layer2_buffer, image_data, copy_size);
  
  printf("CoverBackground image set successfully\n");
}

// 加载JPEG图片到CoverBackground硬件层
void lcd_cover_background_load_jpeg(const char* jpeg_path) {
  if (!g_layer2_initialized) {
    printf("ERROR: layer2 not initialized for JPEG loading\n");
    return;
  }
  
  printf("Loading JPEG wallpaper: %s\n", jpeg_path);
  
  // 使用专用的JPEG输出缓冲区
  uint32_t jpeg_output_address = FMC_SDRAM_JPEG_OUTPUT_DATA_BUFFER_ADDRESS;
  
  // 初始化JPEG解码器（如果需要）
  jpeg_init();
  
  // 解码JPEG文件到临时缓冲区
  int decode_result = jped_decode((char*)jpeg_path, jpeg_output_address);
  
  if (decode_result != 0) {
    printf("ERROR: Failed to decode JPEG file %s, error code: %d\n", jpeg_path, decode_result);
    return;
  }
  
  // 获取解码后的图片信息
  uint32_t width, height, subsampling;
  jpeg_decode_info(&width, &height, &subsampling);
  
  printf("JPEG decoded successfully: %lux%lu, subsampling: %lu\n", width, height, subsampling);
  
  // 计算需要复制的像素数量（限制在显示分辨率内）
  uint32_t copy_width = (width > lcd_params.hres) ? lcd_params.hres : width;
  uint32_t copy_height = (height > lcd_params.vres) ? lcd_params.vres : height;
  
  // 首先清除layer2的所有内容为黑色，避免蓝色背景残留
  uint16_t *layer2_buffer = (uint16_t*)LAYER2_MEMORY_BASE;
  uint32_t total_pixels = lcd_params.hres * lcd_params.vres;
  
  printf("Clearing layer2 buffer (%lu pixels) before JPEG copy...\n", total_pixels);
  for (uint32_t i = 0; i < total_pixels; i++) {
    layer2_buffer[i] = 0x0000; // Clear to black
  }
  
  // 使用DMA2D复制解码后的JPEG数据到Layer2，从第1行开始与Layer1重合
  printf("Using DMA2D to copy JPEG data: %lux%lu -> layer2 starting from Y=0 (to align with Layer1)...\n", copy_width, copy_height);
  
  // 检查解码后的数据格式，确保是RGB565
  if (subsampling == JPEG_420_SUBSAMPLING || subsampling == JPEG_422_SUBSAMPLING || subsampling == JPEG_444_SUBSAMPLING) {
    // JPEG数据可能需要YCbCr到RGB转换
    printf("Converting YCbCr to RGB565 using DMA2D...\n");
    dma2d_copy_ycbcr_to_rgb((uint32_t*)jpeg_output_address, 
                            (uint32_t*)LAYER2_MEMORY_BASE,
                            copy_width, copy_height, subsampling);
  } else {
    // 如果是RGB565格式，直接复制
    printf("Direct RGB565 copy using DMA2D...\n");
    dma2d_copy_buffer((uint32_t*)jpeg_output_address, 
                      (uint32_t*)LAYER2_MEMORY_BASE,
                      0, 0, copy_width, copy_height);
  }
  
  // 不再自动设置前44行为透明颜色键，保持背景图片的完整内容
  // 透明状态栏将通过 lcd_cover_background_set_statusbar_opacity() 函数按需控制
  printf("JPEG background loaded completely, statusbar transparency will be controlled separately\n");
  
  // 验证JPEG加载后状态栏区域的数据
  printf("CoverBackground: Verifying statusbar area after JPEG load\n");
  uint32_t statusbar_non_black = 0;
  for (uint32_t i = 0; i < lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT; i++) {
    if (layer2_buffer[i] != 0x0000) {
      statusbar_non_black++;
    }
  }
  printf("CoverBackground: Statusbar area has %lu non-black pixels after JPEG load\n", statusbar_non_black);
  
  printf("DMA2D JPEG copy completed\n");
  
  // 加载JPEG后，如果Layer2可见，更新Layer1背景以匹配Layer2
  if (lcd_cover_background_is_visible()) {
    printf("CoverBackground: Updating Layer1 background after JPEG load\n");
    lcd_cover_background_update_layer1_from_layer2();
  }
  
  printf("JPEG wallpaper loaded to CoverBackground layer: %s (%lux%lu -> %lux%lu)\n", 
         jpeg_path, width, height, copy_width, copy_height);
}

// 正确的硬件移动 CoverBackground - 动态窗口避免黑屏遮挡
void lcd_cover_background_move_to_y(int16_t y_position) {
  if (!g_layer2_initialized) {
    return;
  }
  
  // 更新状态
  cover_bg_state.y_offset = y_position;
  
  // 处理边界情况 - Layer2完全移出屏幕上方时，直接禁用Layer2
  if (y_position <= -((int16_t)lcd_params.vres)) {
    // Layer2完全移出屏幕，禁用显示
    printf("CoverBackground: Layer2 completely off-screen at Y=%d, disabling\n", y_position);
    __HAL_LTDC_LAYER_DISABLE(&hlcd_ltdc, 1);
    __HAL_LTDC_RELOAD_CONFIG(&hlcd_ltdc);
    return;
  }
  
  // 确保Layer1启用
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1);
  
  // 关键优化：动态窗口而不是动态地址
  // 这样避免读取超出范围的内存导致黑屏
  
  uint32_t window_x0 = 0;
  uint32_t window_y0, window_y1;
  uint32_t window_x1 = lcd_params.hres;
  uint32_t layer_address = LAYER2_MEMORY_BASE;
  
  if (y_position < 0) {
    // 向上移动：窗口从屏幕顶部开始，高度减小
    // 下面露出的部分显示Layer1
    window_y0 = 0;
    window_y1 = lcd_params.vres + y_position; // y_position是负数
    
    // 起始地址需要跳过被移出屏幕的行数
    uint32_t bytes_per_line = lcd_params.hres * lcd_params.bbp;
    uint32_t skip_lines = (uint32_t)(-y_position);
    layer_address = LAYER2_MEMORY_BASE + (skip_lines * bytes_per_line);
  } else {
    // 向下移动：窗口向下偏移
    window_y0 = y_position;
    window_y1 = lcd_params.vres + y_position;
    
    // 地址保持不变
    layer_address = LAYER2_MEMORY_BASE;
  }
  
  // 确保窗口不超出屏幕范围
  if (window_y1 > lcd_params.vres) {
    window_y1 = lcd_params.vres;
  }
  
  // 动画期间使用简化的配置，只更新必要的参数，避免完整的layer重配置
  if (g_animation_in_progress) {
    // 动画期间确保Layer1状态稳定，防止alpha值变化导致的闪烁
    static uint32_t layer1_stabilize_counter = 0;
    layer1_stabilize_counter++;
    
    // 每4帧稳定一次Layer1的alpha值和混合参数，防止突然变暗
    if (layer1_stabilize_counter % 4 == 0) {
      HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // 确保Layer1完全不透明
      
      // 确保Layer1启用状态稳定
      __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1);
    }
    
    // 动画期间只创建配置但减少处理开销
    LTDC_LAYERCONFIG config;
    config.x0 = window_x0;
    config.x1 = window_x1;
    config.y0 = window_y0;
    config.y1 = window_y1;
    config.pixel_format = lcd_params.pixel_format_ltdc;
    config.address = layer_address;
    
    // 使用我们的轻量级配置函数（已经优化了Color Keying跳过）
    ltdc_layer_config(&hlcd_ltdc, 1, &config);
    
    // 动画期间减少状态栏数据恢复的频率，避免频繁内存拷贝导致的闪烁
    // 只在必要时恢复，不是每帧都恢复
    static uint32_t statusbar_restore_counter = 0;
    statusbar_restore_counter++;
    
    if (!g_statusbar_transparent && g_statusbar_backup_valid && g_statusbar_backup_buffer != NULL) {
      // 动画期间每8帧恢复一次状态栏数据，大大减少频率
      if (statusbar_restore_counter % 8 == 0) {
        printf("CoverBackground: Restoring statusbar data using DMA2D (every 8 frames)\n");
        
        // 使用DMA2D快速恢复状态栏数据，避免CPU循环
        dma2d_copy_buffer((uint32_t*)g_statusbar_backup_buffer, 
                          (uint32_t*)LAYER2_MEMORY_BASE,
                          0, 0, lcd_params.hres, TRANSPARENT_STATUSBAR_HEIGHT);
      }
    }
  } else {
    // 非动画期间使用完整的layer配置，确保所有参数正确
    LTDC_LAYERCONFIG config;
    config.x0 = window_x0;
    config.x1 = window_x1;
    config.y0 = window_y0;
    config.y1 = window_y1;
    config.pixel_format = lcd_params.pixel_format_ltdc;
    config.address = layer_address;
    
    // 重新配置Layer1（但不重新设置混合参数，只更新位置和地址）
    // 动画期间避免重新配置Color Keying，保持状态栏数据
    ltdc_layer_config(&hlcd_ltdc, 1, &config);
  }
  
  // 优化：同步LTDC重载与动画帧，减少视觉不一致导致的闪烁
  static uint32_t reload_counter = 0;
  reload_counter++;
  
  if (!g_animation_in_progress) {
    // 非动画期间：立即重载确保响应性
    __HAL_LTDC_RELOAD_CONFIG(&hlcd_ltdc);
  } else {
    // 动画期间：使用VSync同步重载，减少撕裂和闪烁
    // 每6帧重载一次，与状态栏恢复错开时机
    if (reload_counter % 6 == 0) {
      __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);  // 立即重载避免等待
    }
  }
}

// 检查动画是否正在进行
bool lcd_cover_background_is_animating(void) {
  return g_animation_in_progress;
}

// 全局动画状态结构
typedef struct {
  bool active;
  int16_t start_y;
  int16_t target_y;
  uint32_t start_time;
  uint32_t duration_ms;
  uint32_t last_update_time;
  uint32_t frame_count;
} animation_state_t;

static animation_state_t g_animation_state = {0};

// Systick回调函数 - 在系统滴答中更新动画
static void animation_systick_callback(uint32_t tick) {
  // 限制动画更新频率匹配60fps (约16ms)
  // 添加基本的保护检查
  if (g_layer2_initialized && g_animation_state.active) {
    static uint32_t last_update_tick = 0;
    
    // 每16ms更新一次，匹配60fps显示
    if (tick - last_update_tick >= 16) {
      lcd_cover_background_update_animation();
      last_update_tick = tick;
    }
  }
}

// 初始化动画系统
void lcd_animation_init(void) {
  // 注册systick回调用于动画更新
  systick_enable_dispatch(SYSTICK_DISPATCH_ANIMATION_UPDATE, animation_systick_callback);
  printf("Animation system initialized with systick callback\n");
}

// 启动动画
void lcd_cover_background_start_animation(int16_t target_y, uint16_t duration_ms) {
  if (!g_layer2_initialized) {
    // 静默返回，动画期间不输出错误日志
    return;
  }
  
  int16_t start_y = cover_bg_state.y_offset;
  
  if (start_y == target_y) {
    // 静默跳过，不输出日志
    return;
  }
  
  // 完全禁用动画启动时的日志输出
  
  // 初始化动画状态
  g_animation_state.active = true;
  g_animation_state.start_y = start_y;
  g_animation_state.target_y = target_y;
  g_animation_state.start_time = HAL_GetTick();
  g_animation_state.duration_ms = duration_ms;
  g_animation_state.last_update_time = g_animation_state.start_time;
  g_animation_state.frame_count = 0;
  
  // 设置全局动画标志
  g_animation_in_progress = true;
  
  // 动画开始前预启用Layer1，确保动画流畅
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1);
  
  // 动画开始前确保Layer1状态完全稳定，防止闪烁
  hlcd_ltdc.Instance = LTDC;
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // Layer1完全不透明
  cover_bg_state.opacity = 255;
  
  // 强制刷新一次确保Layer1设置生效
  __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
  
  // 动画开始前根据当前状态设置Color Keying，避免动画期间状态不一致
  if (g_statusbar_transparent) {
    // 如果状态栏应该透明，确保Color Keying已启用
    uint16_t color_key = TRANSPARENT_COLOR_KEY;
    uint32_t red = ((color_key >> 11) & 0x1F) << 3;
    uint32_t green = ((color_key >> 5) & 0x3F) << 2;
    uint32_t blue = (color_key & 0x1F) << 3;
    uint32_t rgb888_key = (red << 16) | (green << 8) | blue;
    
    HAL_LTDC_ConfigColorKeying(&hlcd_ltdc, rgb888_key, 1);
    HAL_LTDC_EnableColorKeying(&hlcd_ltdc, 1);
  } else {
    // 如果状态栏应该不透明，确保Color Keying已禁用
    HAL_LTDC_DisableColorKeying(&hlcd_ltdc, 1);
  }
}

// 更新动画状态 - 需要定期调用
bool lcd_cover_background_update_animation(void) {
  if (!g_animation_state.active) {
    return false;
  }
  
  // 动画期间完全禁用调试日志输出
  
  uint32_t current_time = HAL_GetTick();
  uint32_t elapsed_time = current_time - g_animation_state.start_time;
  
  // 检查动画是否完成
  if (elapsed_time >= g_animation_state.duration_ms) {
    // 动画完成，移动到精确位置
    lcd_cover_background_move_to_y(g_animation_state.target_y);
    
    // 动画完成后强制重载，确保最终位置准确显示
    __HAL_LTDC_RELOAD_CONFIG(&hlcd_ltdc);
    
    // 清除动画状态
    g_animation_state.active = false;
    g_animation_in_progress = false;
    
    // 动画完成后重新稳定Layer1状态，确保没有闪烁残留
    HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // Layer1完全不透明
    __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1); // 确保Layer1启用
    
    // 强制重载所有配置，确保最终状态稳定
    __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
    
    // 动画完成后才输出统计信息
    uint32_t avg_fps = (g_animation_state.frame_count * 1000) / elapsed_time;
    printf("Animation completed: Y=%d, frames=%lu, time=%lums, fps=%lu\n", 
           g_animation_state.target_y, g_animation_state.frame_count, elapsed_time, avg_fps);
    
    return false;
  }
  
  // 计算动画进度
  float progress = (float)elapsed_time / g_animation_state.duration_ms;
  
  // 使用cubic ease-in-out缓动函数
  float eased_progress;
  if (progress < 0.5f) {
    eased_progress = 4.0f * progress * progress * progress;
  } else {
    float temp = -2.0f * progress + 2.0f;
    eased_progress = 1.0f - (temp * temp * temp) / 2.0f;
  }
  
  // 计算当前位置
  int16_t distance = g_animation_state.target_y - g_animation_state.start_y;
  int16_t current_y = g_animation_state.start_y + (int16_t)(distance * eased_progress);
  
  // 更新位置
  lcd_cover_background_move_to_y(current_y);
  
  // 更新帧计数和统计
  g_animation_state.frame_count++;
  
  // 动画期间完全禁用帧统计日志输出
  
  return true;
}


// 检查是否有动画正在进行
bool lcd_cover_background_has_active_animation(void) {
  return g_animation_state.active;
}

// 停止当前动画
void lcd_cover_background_stop_animation(void) {
  if (g_animation_state.active) {
    // 动画期间不输出日志，静默停止
    g_animation_state.active = false;
    g_animation_in_progress = false;
  }
}

// 直接的动画函数 - 简化版，不依赖systick
/*
 * lcd_cover_background_animate_to_y(int16_t target_y, uint16_t duration_ms)
 *
 * 这段代码实现了一个直接的、阻塞式的动画效果，用于将CoverBackground（第二层，Layer1）的Y轴偏移量平滑地从当前位置移动到目标位置（target_y），动画持续时间为duration_ms毫秒。
 *
 * 主要流程如下：
 * 1. 首先检查第二层（Layer1）是否已初始化，如果未初始化则直接返回。
 * 2. 获取当前Y偏移量（start_y），如果已经在目标位置则直接返回。
 * 3. 设置动画标志g_animation_in_progress为true，表示动画进行中。
 * 4. 确保Layer1已启用并设置为完全不透明（Alpha=255），并同步cover_bg_state.opacity。
 * 5. 记录动画起始时间（start_time）和帧计数器（frame_count）。
 * 6. 计算总移动距离distance。
 * 7. 进入一个循环，每帧执行以下操作：
 *    - 计算当前已用时间elapsed_time。
 *    - 如果动画时间已到，直接将背景移动到目标位置并跳出循环。
 *    - 否则，计算动画进度progress（0~1），并用cubic ease-in-out缓动函数（前半段加速，后半段减速）平滑动画。
 *    - 根据缓动进度计算当前Y坐标current_y，并调用lcd_cover_background_move_to_y(current_y)更新位置。
 *    - 帧计数自增。
 *    - 通过HAL_Delay(16)实现大约60fps的帧率。
 * 8. 动画结束后，清除动画标志，强制LTDC重载以确保最终显示位置准确。
 * 9. 最后输出动画统计信息，包括目标Y、帧数、总耗时和平均帧率。
 *
 * 注意：整个动画过程为阻塞式，期间不会输出调试日志，适合在UI线程或主循环中直接调用。
 */
void lcd_cover_background_animate_to_y(int16_t target_y, uint16_t duration_ms) {
  if (!g_layer2_initialized) {
    // 静默返回，不输出错误日志
    return;
  }
  
  int16_t start_y = cover_bg_state.y_offset;
  
  if (start_y == target_y) {
    // 静默跳过，不输出日志
    return;
  }
  
  // 完全禁用动画开始时的日志输出
  
  // 设置动画标志
  g_animation_in_progress = true;
  
  // 确保Layer1正确配置
  hlcd_ltdc.Instance = LTDC;
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1);
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);
  cover_bg_state.opacity = 255;
  
  uint32_t start_time = HAL_GetTick();
  uint32_t frame_count = 0;
  int16_t distance = target_y - start_y;
  
  // 动画期间完全禁用参数日志输出
  
  while (true) {
    uint32_t current_time = HAL_GetTick();
    uint32_t elapsed_time = current_time - start_time;
    
    // 检查动画是否完成
    if (elapsed_time >= duration_ms) {
      // 动画完成，移动到精确位置
      lcd_cover_background_move_to_y(target_y);
      break;
    }
    
    // 计算动画进度
    float progress = (float)elapsed_time / duration_ms;
    
    // 使用cubic ease-in-out缓动函数
    float eased_progress;
    if (progress < 0.5f) {
      eased_progress = 4.0f * progress * progress * progress;
    } else {
      float temp = -2.0f * progress + 2.0f;
      eased_progress = 1.0f - (temp * temp * temp) / 2.0f;
    }
    
    // 计算当前位置
    int16_t current_y = start_y + (int16_t)(distance * eased_progress);
    
    // 更新位置
    lcd_cover_background_move_to_y(current_y);
    
    frame_count++;
    
    // 动画期间完全禁用帧调试日志
    
    // 16ms延时，约60fps
    HAL_Delay(16);
  }
  
  // 清除动画标志
  g_animation_in_progress = false;
  
  // 动画完成后重新稳定Layer1状态，确保没有闪烁残留
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // Layer1完全不透明
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1); // 确保Layer1启用
  
  // 动画完成后强制重载，确保最终位置准确显示且状态稳定
  __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
  
  // 动画完成后才输出统计信息
  uint32_t total_time = HAL_GetTick() - start_time;
  uint32_t avg_fps = (frame_count * 1000) / total_time;
  printf("Direct animation completed: Y=%d, frames=%lu, time=%lums, fps=%lu\n", 
         target_y, frame_count, total_time, avg_fps);
}


// 获取当前透明度
uint8_t lcd_cover_background_get_opacity(void) {
  return cover_bg_state.opacity;
}

// 检查是否可见
bool lcd_cover_background_is_visible(void) {
  return cover_bg_state.visible && cover_bg_state.opacity > 0;
}

// 控制顶部44px状态栏区域的透明度
void lcd_cover_background_set_statusbar_opacity(bool transparent) {
  if (!g_layer2_initialized) {
    return;
  }
  
  // 更新全局状态
  g_statusbar_transparent = transparent;
  
  hlcd_ltdc.Instance = LTDC;
  uint16_t* layer2_buffer = (uint16_t*)LAYER2_MEMORY_BASE;
  
  if (transparent) {
    // 检查Layer2顶部44像素是否有非黑色内容
    bool has_valid_content = false;
    uint32_t non_black_pixels = 0;
    
    printf("CoverBackground: Checking Layer2 statusbar content before backup...\n");
    for (uint32_t i = 0; i < lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT; i++) {
      if (layer2_buffer[i] != 0x0000) {
        non_black_pixels++;
        has_valid_content = true;
      }
    }
    
    printf("CoverBackground: Found %lu non-black pixels in statusbar area\n", non_black_pixels);
    
    // 只有在有有效内容时才备份
    if (has_valid_content) {
      // 在设置透明之前，先保存顶部44像素的原始数据
      printf("CoverBackground: Saving statusbar area data before setting transparent\n");
      
      // 确保备份缓冲区已分配
      if (g_statusbar_backup_buffer == NULL) {
        uint32_t backup_size = lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT * sizeof(uint16_t);
        g_statusbar_backup_buffer = (uint16_t*)(LAYER2_MEMORY_BASE + lcd_params.hres * lcd_params.vres * 2 + 0x1000);
        printf("CoverBackground: Allocated backup buffer at 0x%p, size: %lu bytes\n", g_statusbar_backup_buffer, backup_size);
      }
      
      // 保存数据到备份缓冲区并验证
      for (uint32_t y = 0; y < TRANSPARENT_STATUSBAR_HEIGHT; y++) {
        for (uint32_t x = 0; x < lcd_params.hres; x++) {
          uint32_t pixel_idx = y * lcd_params.hres + x;
          g_statusbar_backup_buffer[pixel_idx] = layer2_buffer[pixel_idx];
        }
      }
      g_statusbar_backup_valid = true;
      
      // 验证备份数据
      uint32_t backup_non_black = 0;
      for (uint32_t i = 0; i < lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT; i++) {
        if (g_statusbar_backup_buffer[i] != 0x0000) {
          backup_non_black++;
        }
      }
      printf("CoverBackground: Backup contains %lu non-black pixels\n", backup_non_black);
    } else {
      printf("CoverBackground: Layer2 statusbar area is all black, skipping backup\n");
      g_statusbar_backup_valid = false;
    }
    
    // 将顶部44px设置为透明颜色键，显示Layer1状态栏
    printf("CoverBackground: Setting statusbar area to transparent (Color Keying)\n");
    for (uint32_t y = 0; y < TRANSPARENT_STATUSBAR_HEIGHT; y++) {
      for (uint32_t x = 0; x < lcd_params.hres; x++) {
        layer2_buffer[y * lcd_params.hres + x] = TRANSPARENT_COLOR_KEY;  // 透明颜色键
      }
    }
    
    // 启用Color Keying功能
    uint16_t color_key = TRANSPARENT_COLOR_KEY;
    uint32_t red = ((color_key >> 11) & 0x1F) << 3;     // R5 -> R8
    uint32_t green = ((color_key >> 5) & 0x3F) << 2;    // G6 -> G8
    uint32_t blue = (color_key & 0x1F) << 3;            // B5 -> B8
    uint32_t rgb888_key = (red << 16) | (green << 8) | blue;
    
    HAL_LTDC_ConfigColorKeying(&hlcd_ltdc, rgb888_key, 1);
    HAL_LTDC_EnableColorKeying(&hlcd_ltdc, 1);
  } else {
    // 恢复不透明状态：禁用Color Keying并恢复原始数据
    printf("CoverBackground: Restoring opaque statusbar\n");
    
    // 禁用Color Keying功能，让Layer2完全不透明显示
    printf("CoverBackground: Disabling Color Keying for opaque statusbar\n");
    HAL_LTDC_DisableColorKeying(&hlcd_ltdc, 1);
    
    // 如果之前没有备份，或者备份的是黑色数据，尝试重新加载JPEG图片的状态栏部分
    if (!g_statusbar_backup_valid || g_statusbar_backup_buffer == NULL) {
      printf("CoverBackground: No valid backup, attempting to reload JPEG statusbar area\n");
      
      // 重新加载JPEG的顶部44像素
      // 这里需要调用JPEG解码器，但只解码顶部44像素的部分
      // 暂时使用默认的灰色作为临时方案
      for (uint32_t y = 0; y < TRANSPARENT_STATUSBAR_HEIGHT; y++) {
        for (uint32_t x = 0; x < lcd_params.hres; x++) {
          uint32_t pixel_idx = y * lcd_params.hres + x;
          // 使用中灰色代替黑色，作为临时方案
          layer2_buffer[pixel_idx] = 0x7BEF;  // 中灰色 RGB565
        }
      }
      printf("CoverBackground: Set statusbar to gray as fallback\n");
    } else {
      // 恢复保存的原始数据
      printf("CoverBackground: Restoring original statusbar area data from backup\n");
      
      // 验证备份数据再次
      uint32_t backup_non_black = 0;
      for (uint32_t i = 0; i < lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT; i++) {
        if (g_statusbar_backup_buffer[i] != 0x0000) {
          backup_non_black++;
        }
      }
      printf("CoverBackground: About to restore %lu non-black pixels from backup\n", backup_non_black);
      
      for (uint32_t y = 0; y < TRANSPARENT_STATUSBAR_HEIGHT; y++) {
        for (uint32_t x = 0; x < lcd_params.hres; x++) {
          uint32_t pixel_idx = y * lcd_params.hres + x;
          layer2_buffer[pixel_idx] = g_statusbar_backup_buffer[pixel_idx];
        }
      }
      
      // 验证恢复后的数据
      uint32_t restored_non_black = 0;
      for (uint32_t i = 0; i < lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT; i++) {
        if (layer2_buffer[i] != 0x0000) {
          restored_non_black++;
        }
      }
      printf("CoverBackground: Restored data now has %lu non-black pixels\n", restored_non_black);
    }
  }
  
  // 立即重载LTDC配置以应用更改
  __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
}

// 强制重新加载JPEG图片的状态栏区域
void lcd_cover_background_reload_statusbar_from_jpeg(const char* jpeg_path) {
  if (!g_layer2_initialized || !jpeg_path) {
    return;
  }
  
  printf("CoverBackground: Force reloading statusbar area from JPEG: %s\n", jpeg_path);
  
  // 尝试多个可能的路径
  const char* paths_to_try[] = {
    jpeg_path,
    "/res/wallpaper-1.jpg",
    "A:/res/wallpaper-1.jpg",
    "/wallpaper-1.jpg",
    "wallpaper-1.jpg",
    NULL
  };
  
  uint32_t jpeg_output_address = FMC_SDRAM_JPEG_OUTPUT_DATA_BUFFER_ADDRESS;
  int decode_result = -1;
  const char* successful_path = NULL;
  
  // 尝试不同的路径
  for (int i = 0; paths_to_try[i] != NULL; i++) {
    printf("CoverBackground: Trying JPEG path: %s\n", paths_to_try[i]);
    decode_result = jped_decode((char*)paths_to_try[i], jpeg_output_address);
    if (decode_result == 0) {
      successful_path = paths_to_try[i];
      printf("CoverBackground: Successfully loaded JPEG from: %s\n", successful_path);
      break;
    } else {
      printf("CoverBackground: Failed to load from %s, error: %d\n", paths_to_try[i], decode_result);
    }
  }
  
  if (decode_result != 0) {
    printf("ERROR: All JPEG paths failed, using solid color fallback\n");
    // 使用固定的壁纸颜色作为后备方案
    uint16_t* layer2_buffer = (uint16_t*)LAYER2_MEMORY_BASE;
    for (uint32_t y = 0; y < TRANSPARENT_STATUSBAR_HEIGHT; y++) {
      for (uint32_t x = 0; x < lcd_params.hres; x++) {
        uint32_t pixel_idx = y * lcd_params.hres + x;
        // 使用深蓝色作为壁纸背景色
        layer2_buffer[pixel_idx] = 0x1A3B;  // 深蓝色 RGB565
      }
    }
    
    // 更新备份缓冲区
    if (g_statusbar_backup_buffer != NULL) {
      printf("Updating backup buffer with fallback color\n");
      for (uint32_t y = 0; y < TRANSPARENT_STATUSBAR_HEIGHT; y++) {
        for (uint32_t x = 0; x < lcd_params.hres; x++) {
          uint32_t pixel_idx = y * lcd_params.hres + x;
          g_statusbar_backup_buffer[pixel_idx] = 0x1A3B;  // 深蓝色
        }
      }
      g_statusbar_backup_valid = true;
    }
    
    printf("CoverBackground: Applied fallback color to statusbar area\n");
    return;
  }
  
  // 获取解码后的图片信息
  uint32_t width, height, subsampling;
  jpeg_decode_info(&width, &height, &subsampling);
  
  printf("JPEG decoded for statusbar: %lux%lu, subsampling: %lu\n", width, height, subsampling);
  
  // 只复制状态栏区域的数据
  uint32_t copy_width = (width > lcd_params.hres) ? lcd_params.hres : width;
  uint32_t copy_height = (TRANSPARENT_STATUSBAR_HEIGHT > height) ? height : TRANSPARENT_STATUSBAR_HEIGHT;
  
  uint16_t* layer2_buffer = (uint16_t*)LAYER2_MEMORY_BASE;
  
  printf("Copying JPEG statusbar area: %lu x %lu pixels\n", copy_width, copy_height);
  
  // 检查解码后的数据格式，使用DMA2D进行正确的格式转换
  if (subsampling == JPEG_420_SUBSAMPLING || subsampling == JPEG_422_SUBSAMPLING || subsampling == JPEG_444_SUBSAMPLING) {
    // JPEG数据需要YCbCr到RGB转换，使用DMA2D
    printf("Converting YCbCr to RGB565 for statusbar area using DMA2D...\n");
    
    // 为状态栏区域创建临时缓冲区
    uint32_t temp_buffer_addr = jpeg_output_address + (width * height * 2);  // 在JPEG缓冲区后面
    
    // 使用DMA2D转换状态栏区域
    dma2d_copy_ycbcr_to_rgb((uint32_t*)jpeg_output_address, 
                            (uint32_t*)temp_buffer_addr,
                            copy_width, copy_height, subsampling);
    
    // 复制转换后的数据到Layer2状态栏区域
    uint16_t* temp_buffer = (uint16_t*)temp_buffer_addr;
    for (uint32_t y = 0; y < copy_height; y++) {
      for (uint32_t x = 0; x < copy_width; x++) {
        uint32_t dst_idx = y * lcd_params.hres + x;
        uint32_t src_idx = y * copy_width + x;
        layer2_buffer[dst_idx] = temp_buffer[src_idx];
      }
    }
  } else {
    // 如果是RGB565格式，直接复制
    printf("Direct RGB565 copy for statusbar area...\n");
    uint16_t* jpeg_buffer = (uint16_t*)jpeg_output_address;
    
    for (uint32_t y = 0; y < copy_height; y++) {
      for (uint32_t x = 0; x < copy_width; x++) {
        uint32_t dst_idx = y * lcd_params.hres + x;
        uint32_t src_idx = y * width + x;
        layer2_buffer[dst_idx] = jpeg_buffer[src_idx];
      }
    }
  }
  
  // 更新备份缓冲区
  if (g_statusbar_backup_buffer != NULL) {
    printf("Updating backup buffer with reloaded JPEG data\n");
    for (uint32_t y = 0; y < TRANSPARENT_STATUSBAR_HEIGHT; y++) {
      for (uint32_t x = 0; x < lcd_params.hres; x++) {
        uint32_t pixel_idx = y * lcd_params.hres + x;
        g_statusbar_backup_buffer[pixel_idx] = layer2_buffer[pixel_idx];
      }
    }
    g_statusbar_backup_valid = true;
  }
  
  // 验证加载的数据
  uint32_t non_black_pixels = 0;
  for (uint32_t i = 0; i < lcd_params.hres * TRANSPARENT_STATUSBAR_HEIGHT; i++) {
    if (layer2_buffer[i] != 0x0000) {
      non_black_pixels++;
    }
  }
  printf("CoverBackground: Reloaded statusbar has %lu non-black pixels\n", non_black_pixels);
}

// Function to ensure second layer remains active
void lcd_ensure_second_layer(void) {
  static bool layer_enabled = false;
  
  if (!g_layer2_initialized) {
    return;
  }
  
  // Enable second layer only once (unless it was disabled)
  if (!layer_enabled) {
    __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1);
    layer_enabled = true;
  }
  
  // CoverBackground layer is now managed separately via dedicated functions
  // No automatic updates needed here - controlled by show/hide/set_opacity functions
}
