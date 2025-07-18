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
static char g_layer1_background_path[256] = "A:/res/2222.png";  // 默认背景

// 全局变量跟踪第二层layer是否已初始化
static bool g_layer2_initialized = false;

// 全局动画状态标志
static volatile bool g_animation_in_progress = false;

static int dummy_dbg_printf(const char* fmt, ...) { return 0; }

static DbgPrintf_t dbg_printf = dummy_dbg_printf;

inline void disp_set_dbg_printf(DbgPrintf_t func) { dbg_printf = func; }

// Fps = LCD_PCLK / ((LCD_WIDTH + LCD_HBP + LCD_HFP + LCD_HSW) * (LCD_HEIGHT +
// LCD_VBP + LCD_VFP + LCD_VSW)) mipi_mbps = ((LCD_WIDTH + LCD_HBP + LCD_HFP +
// LCD_HSW) * (LCD_HEIGHT + LCD_VBP + LCD_VFP + LCD_VSW) * fps * 24) /

#define LCD_TXW350135B0

#if 0 
// this is for let every configuration use elif
#elif defined(LCD_TXW350135B0)
#include "TXW350135B0.c"
#define LCD_init_sequence TXW350135B0_init_sequence
const DisplayParam_t lcd_params = {

    .hres = TXW350135B0_HRES,
    .vres = TXW350135B0_VRES,
    .hsync = TXW350135B0_HSYNC,
    .hfp = TXW350135B0_HFP,
    .hbp = TXW350135B0_HBP,
    .vsync = TXW350135B0_VSYNC,
    .vfp = TXW350135B0_VFP,
    .vbp = TXW350135B0_VBP,
    .pixel_format_ltdc = LTDC_PIXEL_FORMAT_RGB565,
    .pixel_format_dsi = DSI_RGB565,
    .bbp = 2,
    .fb_base = DISPLAY_MEMORY_BASE,

    .ltdc_pll = {
        .PLL3N = 132U,
        .PLL3R = 20U,
        .PLL3FRACN = 0U,
    }};
#elif defined(LCD_TXW700140K0)
#include "TXW700140K0.c"
#define LCD_init_sequence TXW700140K0_init_sequence
const DisplayParam_t lcd_params = {

    .hres = TXW700140K0_HRES,
    .vres = TXW700140K0_VRES,
    .hsync = TXW700140K0_HSYNC,
    .hfp = TXW700140K0_HFP,
    .hbp = TXW700140K0_HBP,
    .vsync = TXW700140K0_VSYNC,
    .vfp = TXW700140K0_VFP,
    .vbp = TXW700140K0_VBP,
    .pixel_format_ltdc = LTDC_PIXEL_FORMAT_RGB565,
    .pixel_format_dsi = DSI_RGB565,
    .bbp = 2,
    .fb_base = DISPLAY_MEMORY_BASE,

    .ltdc_pll = {
        .PLL3N = 43U,
        .PLL3R = 5U,
        .PLL3FRACN = 2048U,
    }};
#else
#error "display selection not defined!"
#endif

#define LED_PWM_TIM_PERIOD (50)

// HSE/DIVM3*(DIVN3+(FRACN3/8192))/DIVR3/to_Khz
#define LTDC_FREQ                                          \
  (uint32_t)(HSE_VALUE / 5 *                               \
             (lcd_params.ltdc_pll.PLL3N +                  \
              (lcd_params.ltdc_pll.PLL3FRACN / 8192.0F)) / \
             lcd_params.ltdc_pll.PLL3R / 1000)

// HSE/IDF*2*NDIV/2/ODF/8/to_Khz = 62.5 Mhz or 625000 Khz
#define DSI_FREQ (uint32_t)(HSE_VALUE / 1 * 2 * 40 / 2 / 2 / 8 / 1000)

// LCD_PCLK / ((LCD_WIDTH + LCD_HBP + LCD_HFP + LCD_HSW) * (LCD_HEIGHT + LCD_VBP
// + LCD_VFP + LCD_VSW))
#define FPS_TARGET                                                     \
  (uint32_t)((float)LTDC_FREQ / ((lcd_params.hres + lcd_params.hbp +   \
                                  lcd_params.hfp + lcd_params.hsync) * \
                                 (lcd_params.vres + lcd_params.vbp +   \
                                  lcd_params.vfp + lcd_params.vsync)))

static int DISPLAY_BACKLIGHT = -1;
static int DISPLAY_ORIENTATION = -1;

static DSI_HandleTypeDef hlcd_dsi = {0};
static DMA2D_HandleTypeDef hlcd_dma2d = {0};
static LTDC_HandleTypeDef hlcd_ltdc = {0};

void DSI_IRQHandler(void) {
  HAL_DSI_IRQHandler(&hlcd_dsi);
  dbg_printf("DSI_IRQHandler called!");
}

float lcd_fps = 0.0;
// static void frame_callback(DSI_HandleTypeDef* hdsi)
// {
//     static uint32_t lcd_fps_tick = 0;
//     static uint32_t lcd_fps_tock = 0;
//     lcd_fps_tick = lcd_fps_tock;
//     lcd_fps_tock = HAL_GetTick();
//     lcd_fps = 1000 / (lcd_fps_tock - lcd_fps_tick);
// }

void lcd_pwm_init(void) {
  GPIO_InitTypeDef gpio_init_structure = {0};
  /* LCD_BL_CTRL GPIO configuration */
  __HAL_RCC_GPIOK_CLK_ENABLE();
  __HAL_RCC_TIM1_CLK_ENABLE();
  // LCD_PWM/PA7 (backlight control)
  gpio_init_structure.Mode = GPIO_MODE_AF_PP;
  gpio_init_structure.Pull = GPIO_NOPULL;
  gpio_init_structure.Speed = GPIO_SPEED_FREQ_LOW;
  gpio_init_structure.Alternate = GPIO_AF1_TIM1;
  gpio_init_structure.Pin = LCD_BL_CTRL_PIN;
  HAL_GPIO_Init(LCD_BL_CTRL_GPIO_PORT, &gpio_init_structure);

  // enable PWM timer
  TIM_HandleTypeDef TIM1_Handle;
  TIM1_Handle.Instance = TIM1;
  TIM1_Handle.Init.Period = LED_PWM_TIM_PERIOD - 1;
  // TIM1/APB2 source frequency equals to fCPU in our configuration,
  // we want 1 MHz
  TIM1_Handle.Init.Prescaler =
      SystemCoreClock / 1000000 / 4 - 1;  // APB is fCPU/2(AHB)/2(APB)
  TIM1_Handle.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  TIM1_Handle.Init.CounterMode = TIM_COUNTERMODE_UP;
  TIM1_Handle.Init.RepetitionCounter = 0;
  HAL_TIM_PWM_Init(&TIM1_Handle);

  TIM_OC_InitTypeDef TIM_OC_InitStructure;
  TIM_OC_InitStructure.Pulse =
      (LED_PWM_TIM_PERIOD / 2 - 1);  // default 50% dutycycle
  TIM_OC_InitStructure.OCMode = TIM_OCMODE_PWM2;
  TIM_OC_InitStructure.OCPolarity = TIM_OCPOLARITY_HIGH;
  TIM_OC_InitStructure.OCFastMode = TIM_OCFAST_DISABLE;
  TIM_OC_InitStructure.OCNPolarity = TIM_OCNPOLARITY_HIGH;
  TIM_OC_InitStructure.OCIdleState = TIM_OCIDLESTATE_SET;
  TIM_OC_InitStructure.OCNIdleState = TIM_OCNIDLESTATE_SET;
  HAL_TIM_PWM_ConfigChannel(&TIM1_Handle, &TIM_OC_InitStructure, TIM_CHANNEL_1);

  HAL_TIM_PWM_Start(&TIM1_Handle, TIM_CHANNEL_1);
  HAL_TIMEx_PWMN_Start(&TIM1_Handle, TIM_CHANNEL_1);
}

static HAL_StatusTypeDef dma2d_init(DMA2D_HandleTypeDef* hdma2d) {
  if (hdma2d->Instance != DMA2D) return HAL_ERROR;

  // clock source
  {
    __HAL_RCC_DMA2D_CLK_ENABLE();
    __HAL_RCC_DMA2D_FORCE_RESET();
    __HAL_RCC_DMA2D_RELEASE_RESET();
  }

  return HAL_OK;
}

static HAL_StatusTypeDef ltdc_init(LTDC_HandleTypeDef* hltdc) {
  if (hltdc->Instance != LTDC) return HAL_ERROR;

  // clock source
  {
    __HAL_RCC_LTDC_CLK_ENABLE();
    __HAL_RCC_LTDC_FORCE_RESET();
    __HAL_RCC_LTDC_RELEASE_RESET();

    RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};
    PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_LTDC;
    PeriphClkInitStruct.PLL3.PLL3M = 5U;
    PeriphClkInitStruct.PLL3.PLL3N = lcd_params.ltdc_pll.PLL3N;
    PeriphClkInitStruct.PLL3.PLL3P = 2U;
    PeriphClkInitStruct.PLL3.PLL3Q = 2U;
    PeriphClkInitStruct.PLL3.PLL3R = lcd_params.ltdc_pll.PLL3R;
    PeriphClkInitStruct.PLL3.PLL3RGE = RCC_PLLCFGR_PLL3RGE_2;
    PeriphClkInitStruct.PLL3.PLL3VCOSEL = RCC_PLL3VCOWIDE;
    PeriphClkInitStruct.PLL3.PLL3FRACN = lcd_params.ltdc_pll.PLL3FRACN;
    HAL_StatusTypeDef result = HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct);
    if (result != HAL_OK) {
      return result;
    }
  }

  hltdc->Init.HSPolarity = LTDC_HSPOLARITY_AH;
  // hltdc->Init.HSPolarity = LTDC_HSPOLARITY_AL;

  hltdc->Init.VSPolarity = LTDC_VSPOLARITY_AH;
  // hltdc->Init.VSPolarity = LTDC_VSPOLARITY_AL;

  // hltdc->Init.DEPolarity = LTDC_DEPOLARITY_AH;
  hltdc->Init.DEPolarity = LTDC_DEPOLARITY_AL;

  hltdc->Init.PCPolarity = LTDC_PCPOLARITY_IPC;

  hltdc->Init.HorizontalSync = lcd_params.hsync - 1;
  hltdc->Init.AccumulatedHBP = lcd_params.hsync + lcd_params.hbp - 1;
  hltdc->Init.AccumulatedActiveW =
      lcd_params.hsync + lcd_params.hres + lcd_params.hbp - 1;
  hltdc->Init.TotalWidth =
      lcd_params.hsync + lcd_params.hres + lcd_params.hbp + lcd_params.hfp - 1;
  hltdc->Init.VerticalSync = lcd_params.vsync - 1;
  hltdc->Init.AccumulatedVBP = lcd_params.vsync + lcd_params.vbp - 1;
  hltdc->Init.AccumulatedActiveH =
      lcd_params.vsync + lcd_params.vres + lcd_params.vbp - 1;
  hltdc->Init.TotalHeigh =
      lcd_params.vsync + lcd_params.vres + lcd_params.vbp + lcd_params.vfp - 1;

  // 保持原来的黑色背景，避免影响正常显示
  hltdc->Init.Backcolor.Blue = 0x00;
  hltdc->Init.Backcolor.Green = 0x00;
  hltdc->Init.Backcolor.Red = 0x00;

  return HAL_LTDC_Init(hltdc);
}

static HAL_StatusTypeDef ltdc_layer_config(LTDC_HandleTypeDef* hltdc,
                                           uint32_t layer_index,
                                           LTDC_LAYERCONFIG* config) {
  LTDC_LayerCfgTypeDef pLayerCfg;

  pLayerCfg.WindowX0 = config->x0;
  pLayerCfg.WindowX1 = config->x1;
  pLayerCfg.WindowY0 = config->y0;
  pLayerCfg.WindowY1 = config->y1;
  pLayerCfg.PixelFormat = config->pixel_format;
  pLayerCfg.FBStartAdress = config->address;
  pLayerCfg.ImageWidth = (config->x1 - config->x0);
  pLayerCfg.ImageHeight = (config->y1 - config->y0);
  pLayerCfg.Backcolor.Blue = 0;
  pLayerCfg.Backcolor.Green = 0;
  pLayerCfg.Backcolor.Red = 0;
  
  if (layer_index == 0) {
    // 第一层：底层，完全不透明
    pLayerCfg.Alpha = 255;
    pLayerCfg.Alpha0 = 0;
    pLayerCfg.BlendingFactor1 = LTDC_BLENDING_FACTOR1_PAxCA;
    pLayerCfg.BlendingFactor2 = LTDC_BLENDING_FACTOR2_PAxCA;
    // printf("Configuring first layer - opaque mode\n");
  } else {
    // 第二层：上层，支持Color Keying透明混合，前44px透明显示Layer1状态栏
    pLayerCfg.Alpha = 255;  // 完全不透明
    pLayerCfg.Alpha0 = 0;
    pLayerCfg.BlendingFactor1 = LTDC_BLENDING_FACTOR1_PAxCA;
    pLayerCfg.BlendingFactor2 = LTDC_BLENDING_FACTOR2_PAxCA;
    
    printf("Configuring Layer2 with Color Keying support\n");
  }
  
  HAL_StatusTypeDef result = HAL_LTDC_ConfigLayer(hltdc, &pLayerCfg, layer_index);
  
  // 为Layer2配置Color Keying - 让TRANSPARENT_COLOR_KEY颜色透明
  if (layer_index == 1 && result == HAL_OK) {
    // 将RGB565颜色键分解为RGB888分量
    uint16_t color_key = TRANSPARENT_COLOR_KEY;
    uint32_t red = ((color_key >> 11) & 0x1F) << 3;     // R5 -> R8
    uint32_t green = ((color_key >> 5) & 0x3F) << 2;    // G6 -> G8
    uint32_t blue = (color_key & 0x1F) << 3;            // B5 -> B8
    
    uint32_t rgb888_key = (red << 16) | (green << 8) | blue;
    
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
  }
  
  return result;
}

static HAL_StatusTypeDef dsi_host_init(DSI_HandleTypeDef* hdsi) {
  if (hdsi->Instance != DSI) return HAL_ERROR;

  // clock source
  {
    /** Enable DSI Host and wrapper clocks */
    __HAL_RCC_DSI_CLK_ENABLE();
    __HAL_RCC_DSI_FORCE_RESET();
    __HAL_RCC_DSI_RELEASE_RESET();

    RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};
    PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_DSI;
    PeriphClkInitStruct.DsiClockSelection = RCC_DSICLKSOURCE_PHY;
    // PeriphClkInitStruct.DsiClockSelection = RCC_DSICLKSOURCE_PLL2; // PLL2Q =
    // 9 in sdram.c
    HAL_StatusTypeDef result = HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct);
    if (result != HAL_OK) {
      return result;
    }
  }

  // interrupt
  {
      // HAL_NVIC_SetPriority(DSI_IRQn, 0, 0);
      // HAL_NVIC_EnableIRQ(DSI_IRQn);
  }

  // clock div
  {
    hdsi->Init.AutomaticClockLaneControl = DSI_AUTO_CLK_LANE_CTRL_DISABLE;
    hdsi->Init.TXEscapeCkdiv = 4;  // lp txclkesc 15.625 Mhz
    hdsi->Init.NumberOfLanes = DSI_TWO_DATA_LANES;

    // dsi speed (lane byte) 62.5 Mhz, which is the maximum can support
    DSI_PLLInitTypeDef PLLInit = {0};
    PLLInit.PLLNDIV = 40;
    PLLInit.PLLIDF = DSI_PLL_IN_DIV1;
    PLLInit.PLLODF = DSI_PLL_OUT_DIV2;
    if (HAL_DSI_Init(hdsi, &PLLInit) != HAL_OK) {
      return HAL_ERROR;
    }
  }

  // timeout
  {
    DSI_HOST_TimeoutTypeDef HostTimeouts = {0};
    HostTimeouts.TimeoutCkdiv = 1;
    HostTimeouts.HighSpeedTransmissionTimeout = 0;
    HostTimeouts.LowPowerReceptionTimeout = 0;
    HostTimeouts.HighSpeedReadTimeout = 0;
    HostTimeouts.LowPowerReadTimeout = 0;
    HostTimeouts.HighSpeedWriteTimeout = 0;
    HostTimeouts.HighSpeedWritePrespMode = DSI_HS_PM_DISABLE;
    HostTimeouts.LowPowerWriteTimeout = 0;
    HostTimeouts.BTATimeout = 0;
    if (HAL_DSI_ConfigHostTimeouts(hdsi, &HostTimeouts) != HAL_OK) {
      return HAL_ERROR;
    }
  }

  // phy timing
  {
    DSI_PHY_TimerTypeDef PhyTimings = {0};
    PhyTimings.ClockLaneHS2LPTime = 27;
    PhyTimings.ClockLaneLP2HSTime = 32;
    PhyTimings.DataLaneHS2LPTime = 15;
    PhyTimings.DataLaneLP2HSTime = 24;
    PhyTimings.DataLaneMaxReadTime = 0;
    PhyTimings.StopWaitTime = 0;
    if (HAL_DSI_ConfigPhyTimer(hdsi, &PhyTimings) != HAL_OK) {
      return HAL_ERROR;
    }
  }

  if (HAL_DSI_ConfigFlowControl(hdsi, DSI_FLOW_CONTROL_BTA) != HAL_OK) {
    return HAL_ERROR;
  }
  if (HAL_DSI_SetLowPowerRXFilter(hdsi, 10000) != HAL_OK) {
    return HAL_ERROR;
  }
  if (HAL_DSI_ConfigErrorMonitor(hdsi, HAL_DSI_ERROR_GEN) != HAL_OK) {
    return HAL_ERROR;
  }

  // video mode
  {
    DSI_VidCfgTypeDef VidCfg = {0};
    VidCfg.VirtualChannelID = 0;
    VidCfg.ColorCoding = lcd_params.pixel_format_dsi;
    VidCfg.LooselyPacked = DSI_LOOSELY_PACKED_DISABLE;
    VidCfg.Mode = DSI_VID_MODE_BURST;
    VidCfg.PacketSize = lcd_params.hres;
    VidCfg.NumberOfChunks = 0;  // no need in video burst mode
    VidCfg.NullPacketSize = 0;  // no need in video burst mode
    VidCfg.HSPolarity = DSI_HSYNC_ACTIVE_HIGH;
    VidCfg.VSPolarity = DSI_VSYNC_ACTIVE_HIGH;
    VidCfg.DEPolarity = DSI_DATA_ENABLE_ACTIVE_HIGH;
    VidCfg.HorizontalSyncActive = (lcd_params.hsync * DSI_FREQ) / LTDC_FREQ;
    VidCfg.HorizontalBackPorch = (lcd_params.hbp * DSI_FREQ) / LTDC_FREQ;
    VidCfg.HorizontalLine = ((lcd_params.hres + lcd_params.hsync +
                              lcd_params.hbp + lcd_params.hfp) *
                             DSI_FREQ) /
                            LTDC_FREQ;
    VidCfg.VerticalSyncActive = lcd_params.vsync;
    VidCfg.VerticalBackPorch = lcd_params.vbp;
    VidCfg.VerticalFrontPorch = lcd_params.vfp;
    VidCfg.VerticalActive = lcd_params.vres;

    VidCfg.LPCommandEnable = DSI_LP_COMMAND_ENABLE;
    VidCfg.LPLargestPacketSize = 128;
    VidCfg.LPVACTLargestPacketSize = 0;
    VidCfg.LPHorizontalFrontPorchEnable = DSI_LP_HFP_ENABLE;
    VidCfg.LPHorizontalBackPorchEnable = DSI_LP_HBP_ENABLE;
    VidCfg.LPVerticalActiveEnable = DSI_LP_VACT_ENABLE;
    VidCfg.LPVerticalFrontPorchEnable = DSI_LP_VFP_ENABLE;
    VidCfg.LPVerticalBackPorchEnable = DSI_LP_VBP_ENABLE;
    VidCfg.LPVerticalSyncActiveEnable = DSI_LP_VSYNC_ENABLE;
    VidCfg.FrameBTAAcknowledgeEnable = DSI_FBTAA_DISABLE;

    if (HAL_DSI_ConfigVideoMode(hdsi, &VidCfg) != HAL_OK) {
      return HAL_ERROR;
    }
  }

  return HAL_OK;
}

#define CONVERTRGB5652ARGB8888(Color)                                   \
  ((((((((Color) >> (11U)) & 0x1FU) * 527U) + 23U) >> (6U)) << (16U)) | \
   (((((((Color) >> (5U)) & 0x3FU) * 259U) + 33U) >> (6U)) << (8U)) |   \
   (((((Color)&0x1FU) * 527U) + 23U) >> (6U)) | (0xFF000000U))

void fb_read_pixel(uint32_t x_pos, uint32_t y_pos, uint32_t* color) {
  if (lcd_params.pixel_format_ltdc == LTDC_PIXEL_FORMAT_ARGB8888) {
    /* Read data value from SDRAM memory */
    *color = *(uint32_t*)(lcd_params.fb_base +
                          (lcd_params.bbp * (lcd_params.hres * y_pos + x_pos)));
  } else {
    /*LTDC_PIXEL_FORMAT_RGB565 */
    *color = *(uint16_t*)(lcd_params.fb_base +
                          (lcd_params.bbp * (lcd_params.hres * y_pos + x_pos)));
  }
}

void fb_write_pixel(uint32_t x_pos, uint32_t y_pos, uint32_t color) {
  if (lcd_params.pixel_format_ltdc == LTDC_PIXEL_FORMAT_ARGB8888) {
    *(uint32_t*)(lcd_params.fb_base +
                 (lcd_params.bbp * (lcd_params.hres * y_pos + x_pos))) = color;
  } else {
    /*LTDC_PIXEL_FORMAT_RGB565 */
    *(uint16_t*)(lcd_params.fb_base +
                 (lcd_params.bbp * (lcd_params.hres * y_pos + x_pos))) = color;
  }
}

static void fb_fill_buffer(uint32_t* dest, uint32_t x_size, uint32_t y_size,
                           uint32_t offset, uint32_t color) {
  uint32_t output_color_mode, input_color = color;

  switch (lcd_params.pixel_format_ltdc) {
    case LTDC_PIXEL_FORMAT_RGB565:
      output_color_mode = DMA2D_OUTPUT_RGB565; /* RGB565 */
      input_color = CONVERTRGB5652ARGB8888(color);
      break;
    case LTDC_PIXEL_FORMAT_RGB888:
    default:
      output_color_mode = DMA2D_OUTPUT_ARGB8888; /* ARGB8888 */
      break;
  }

  /* Register to memory mode with ARGB8888 as color Mode */
  hlcd_dma2d.Init.Mode = DMA2D_R2M;
  hlcd_dma2d.Init.ColorMode = output_color_mode;
  hlcd_dma2d.Init.OutputOffset = offset;

  hlcd_dma2d.Instance = DMA2D;

  /* DMA2D Initialization */
  if (HAL_DMA2D_Init(&hlcd_dma2d) == HAL_OK) {
    if (HAL_DMA2D_ConfigLayer(&hlcd_dma2d, 1) == HAL_OK) {
      if (HAL_DMA2D_Start(&hlcd_dma2d, input_color, (uint32_t)dest, x_size,
                          y_size) == HAL_OK) {
        /* Polling For DMA transfer */
        (void)HAL_DMA2D_PollForTransfer(&hlcd_dma2d, 25);
      }
    }
  }
}

void fb_fill_rect(uint32_t x_pos, uint32_t y_pos, uint32_t width,
                  uint32_t height, uint32_t color) {
  /* Get the rectangle start address */
  uint32_t address = lcd_params.fb_base +
                     ((lcd_params.bbp) * (lcd_params.hres * y_pos + x_pos));

  /* Fill the rectangle */
  fb_fill_buffer((uint32_t*)address, width, height, (lcd_params.hres - width),
                 color);
}

void fb_draw_hline(uint32_t x_pos, uint32_t y_pos, uint32_t len,
                   uint32_t color) {
  uint32_t address = lcd_params.fb_base +
                     ((lcd_params.bbp) * (lcd_params.hres * y_pos + x_pos));
  fb_fill_buffer((uint32_t*)address, len, 1, 0, color);
}

void fb_draw_vline(uint32_t x_pos, uint32_t y_pos, uint32_t len,
                   uint32_t color) {
  uint32_t address = lcd_params.fb_base +
                     ((lcd_params.bbp) * (lcd_params.hres * y_pos + x_pos));
  fb_fill_buffer((uint32_t*)address, 1, len, lcd_params.hres - 1, color);
}

void dma2d_copy_buffer(uint32_t* pSrc, uint32_t* pDst, uint16_t x, uint16_t y,
                       uint16_t xsize, uint16_t ysize) {
  uint32_t destination =
      (uint32_t)pDst + (y * lcd_params.hres + x) * (lcd_params.bbp);
  uint32_t source = (uint32_t)pSrc;

  /*##-1- Configure the DMA2D Mode, Color Mode and output offset #############*/
  hlcd_dma2d.Init.Mode = DMA2D_M2M;
  hlcd_dma2d.Init.ColorMode = DMA2D_OUTPUT_RGB565;
  hlcd_dma2d.Init.OutputOffset = lcd_params.hres - xsize;
  hlcd_dma2d.Init.AlphaInverted =
      DMA2D_REGULAR_ALPHA; /* No Output Alpha Inversion*/
  hlcd_dma2d.Init.RedBlueSwap =
      DMA2D_RB_REGULAR; /* No Output Red & Blue swap */

  /*##-2- DMA2D Callbacks Configuration ######################################*/
  hlcd_dma2d.XferCpltCallback = NULL;

  /*##-3- Foreground Configuration ###########################################*/
  hlcd_dma2d.LayerCfg[1].AlphaMode = DMA2D_NO_MODIF_ALPHA;
  hlcd_dma2d.LayerCfg[1].InputAlpha = 0xFF;
  hlcd_dma2d.LayerCfg[1].InputColorMode = DMA2D_INPUT_RGB565;
  hlcd_dma2d.LayerCfg[1].InputOffset = 0;
  hlcd_dma2d.LayerCfg[1].RedBlueSwap =
      DMA2D_RB_REGULAR; /* No ForeGround Red/Blue swap */
  hlcd_dma2d.LayerCfg[1].AlphaInverted =
      DMA2D_REGULAR_ALPHA; /* No ForeGround Alpha inversion */

  hlcd_dma2d.Instance = DMA2D;

  /* DMA2D Initialization */
  if (HAL_DMA2D_Init(&hlcd_dma2d) == HAL_OK) {
    if (HAL_DMA2D_ConfigLayer(&hlcd_dma2d, 1) == HAL_OK) {
      // while ( lcd_ltdc_busy() ) {}
      if (HAL_DMA2D_Start(&hlcd_dma2d, source, destination, xsize, ysize) ==
          HAL_OK) {
        /* Polling For DMA transfer */
        HAL_DMA2D_PollForTransfer(&hlcd_dma2d, HAL_MAX_DELAY);
      }
    }
  }
}

void dma2d_copy_ycbcr_to_rgb(uint32_t* pSrc, uint32_t* pDst, uint16_t xsize,
                             uint16_t ysize, uint32_t ChromaSampling) {
  uint32_t cssMode = DMA2D_CSS_420, inputLineOffset = 0;

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

  /*##-1- Configure the DMA2D Mode, Color Mode and output offset #############*/
  hlcd_dma2d.Init.Mode = DMA2D_M2M_PFC;
  hlcd_dma2d.Init.ColorMode = DMA2D_OUTPUT_RGB565;
  hlcd_dma2d.Init.OutputOffset = 0;
  hlcd_dma2d.Init.AlphaInverted =
      DMA2D_REGULAR_ALPHA; /* No Output Alpha Inversion*/
  hlcd_dma2d.Init.RedBlueSwap =
      DMA2D_RB_REGULAR; /* No Output Red & Blue swap */

  /*##-2- DMA2D Callbacks Configuration ######################################*/
  hlcd_dma2d.XferCpltCallback = NULL;

  /*##-3- Foreground Configuration ###########################################*/
  hlcd_dma2d.LayerCfg[1].AlphaMode = DMA2D_REPLACE_ALPHA;
  hlcd_dma2d.LayerCfg[1].InputAlpha = 0xFF;
  hlcd_dma2d.LayerCfg[1].InputColorMode = DMA2D_INPUT_YCBCR;
  hlcd_dma2d.LayerCfg[1].ChromaSubSampling = cssMode;
  hlcd_dma2d.LayerCfg[1].InputOffset = inputLineOffset;
  hlcd_dma2d.LayerCfg[1].RedBlueSwap =
      DMA2D_RB_REGULAR; /* No ForeGround Red/Blue swap */
  hlcd_dma2d.LayerCfg[1].AlphaInverted =
      DMA2D_REGULAR_ALPHA; /* No ForeGround Alpha inversion */

  hlcd_dma2d.Instance = DMA2D;

  /*##-4- DMA2D Initialization     ###########################################*/
  HAL_DMA2D_Init(&hlcd_dma2d);
  HAL_DMA2D_ConfigLayer(&hlcd_dma2d, 1);

  HAL_DMA2D_Start(&hlcd_dma2d, (uint32_t)pSrc, (uint32_t)pDst, xsize, ysize);
  HAL_DMA2D_PollForTransfer(
      &hlcd_dma2d, 25); /* wait for the previous DMA2D transfer to ends */
}

int DSI_DCS_read(uint16_t cmd, uint8_t* data, uint16_t data_len) {
  return HAL_DSI_Read(&hlcd_dsi, 0, data, data_len, DSI_DCS_SHORT_PKT_READ, cmd,
                      (uint8_t[]){0, 0});
}

int DSI_DCS_write(uint16_t cmd, uint8_t* data, uint16_t data_len) {
  if (data_len <= 1) {
    return HAL_DSI_ShortWrite(&hlcd_dsi, 0, DSI_DCS_SHORT_PKT_WRITE_P1, cmd,
                              (uint32_t)data[0]);
  } else {
    return HAL_DSI_LongWrite(&hlcd_dsi, 0, DSI_DCS_LONG_PKT_WRITE, data_len,
                             cmd, data);
  }
}

int display_backlight(int val) {
  if (DISPLAY_BACKLIGHT != val && val >= 0 && val <= 255) {
    DISPLAY_BACKLIGHT = val;
    TIM1->CCR1 = (LED_PWM_TIM_PERIOD - 1) * val / 255;
  }
  return DISPLAY_BACKLIGHT;
}

int display_backlight_with_lcd_reset(int val) {
  if (val == 0 && DISPLAY_BACKLIGHT != 0) {
    display_backlight(0);
    lcd_refresh_suspend();
  } else if (val > 0 && DISPLAY_BACKLIGHT == 0) {
    lcd_refresh_resume();
    HAL_Delay(5);
  }
  return display_backlight(val);
}

int display_orientation(int degrees) {
  if (degrees != DISPLAY_ORIENTATION) {
    if (degrees == 0 || degrees == 90 || degrees == 180 || degrees == 270) {
      DISPLAY_ORIENTATION = degrees;
      // noop
    }
  }
  return DISPLAY_ORIENTATION;
}

void lcd_init(void) {
  // printf("LCD initialization started - single layer mode\n");
  
  // gpio
  {
    GPIO_InitTypeDef gpio_init_structure = {0};

    // RESET PIN
    __HAL_RCC_GPIOG_CLK_ENABLE();
    gpio_init_structure.Pin = LCD_RESET_PIN;
    gpio_init_structure.Mode = GPIO_MODE_OUTPUT_PP;
    gpio_init_structure.Pull = GPIO_PULLUP;
    gpio_init_structure.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LCD_RESET_GPIO_PORT, &gpio_init_structure);

    // TE PIN
    __HAL_RCC_GPIOJ_CLK_ENABLE();
    gpio_init_structure.Pin = LCD_TE_PIN;
    gpio_init_structure.Mode = GPIO_MODE_INPUT;
    gpio_init_structure.Pull = GPIO_NOPULL;
    gpio_init_structure.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(LCD_TE_GPIO_PORT, &gpio_init_structure);
    // HAL_GPIO_WritePin(LCD_TE_GPIO_PORT, LCD_TE_PIN, GPIO_PIN_SET); // TODO:
    // Needed?
  }

  // dma2d
  {
    hlcd_dma2d.Instance = DMA2D;
    dma2d_init(&hlcd_dma2d);
  }

  // ltdc
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

  // dsi host
  {
    hlcd_dsi.Instance = DSI;
    if (dsi_host_init(&hlcd_dsi) != HAL_OK)
      dbg_printf("dsi_host_init failed !\r\n");
  }

  // lcd init
  {
    HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_SET);
    HAL_Delay(20);
    HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_RESET);
    HAL_Delay(50);
    HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_SET);
    HAL_Delay(120);

    HAL_DSI_Start(&hlcd_dsi);  // make sure ltdc inited before this call

    // Send Init Seq.
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

void display_set_window(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1) {}

int display_get_orientation(void) { return DISPLAY_ORIENTATION; }
void display_reset_state() {}
void display_clear_save(void) {}
const char* display_save(const char* prefix) { return NULL; }
void display_refresh(void) {}

static uint16_t grayscale_to_rgb565(uint8_t gray) {
  uint16_t r = (gray * 31 + 127) / 255;
  uint16_t g = (gray * 63 + 127) / 255;
  uint16_t b = (gray * 31 + 127) / 255;

  return 0xffff - ((r << 11) | (g << 5) | b);
}

void display_fp(uint16_t x, uint16_t y, uint16_t w, uint16_t h,
                const uint8_t* data) {
  for (uint32_t i = 0; i < w * h; i++) {
    fb_write_pixel(x + i % w, y + i / w, grayscale_to_rgb565(data[i]));
  }
}

int lcd_ltdc_busy(void) {
  hlcd_ltdc.Instance = LTDC;
  // low is busy
  return hlcd_ltdc.Instance->CDSR & 0x01 ? 0 : 1;
}

void lcd_ltdc_dsi_disable(void) {
  hlcd_ltdc.Instance = LTDC;
  hlcd_dsi.Instance = DSI;
  while (lcd_ltdc_busy()) {
  }
  HAL_DSI_Stop(&hlcd_dsi);
  __HAL_LTDC_DISABLE(&hlcd_ltdc);
}

void lcd_ltdc_dsi_enable(void) {
  hlcd_ltdc.Instance = LTDC;
  hlcd_dsi.Instance = DSI;
  __HAL_LTDC_ENABLE(&hlcd_ltdc);
  HAL_DSI_Start(&hlcd_dsi);
}

void lcd_refresh_suspend(void) {
  // wait transfer
  lcd_ltdc_dsi_disable();

  // lcd reset
  HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_RESET);
  // wait for full blanking done
  // needs 120ms "When Reset applied during Sleep Out Mode."
  HAL_Delay(125);
}

void lcd_refresh_resume(void) {
  // lcd reset
  HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_RESET);
  HAL_Delay(5);
  HAL_GPIO_WritePin(LCD_RESET_GPIO_PORT, LCD_RESET_PIN, GPIO_PIN_SET);
  HAL_Delay(50);
  lcd_ltdc_dsi_enable();
  // lcd wakeup / re-init
  int result = LCD_init_sequence(DSI_DCS_write, HAL_Delay);
  if (result != 0) {
    dbg_printf("LCD_init_sequence failed with 0x%02x!\r\n", result);
    while (1)
      ;
  }
}

static volatile uint32_t g_current_display_addr = FMC_SDRAM_LTDC_BUFFER_ADDRESS;

void lcd_set_src_addr(uint32_t addr) {
  static uint32_t animation_counter = 0;
  static uint32_t last_addr = 0;
  
  // 如果地址没有变化则跳过更新，减少不必要的重载
  if (addr == last_addr) {
    return;
  }
  
  // 动画期间保持Layer0正常更新，但使用更温和的重载方式
  // 不跳过更新，确保Layer0内容正常显示
  
  last_addr = addr;
  
  hlcd_ltdc.Instance = LTDC;
  LTDC_LAYERCONFIG config;
  config.x0 = 0;
  config.x1 = lcd_params.hres;
  config.y0 = 0;
  config.y1 = lcd_params.vres;
  config.pixel_format = lcd_params.pixel_format_ltdc;
  config.address = addr;
  if (ltdc_layer_config(&hlcd_ltdc, 0, &config) != HAL_OK) {
    dbg_printf("ltdc_layer_config failed !\r\n");
  }
  
  // Ensure first layer is always enabled
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 0);
  // 注意：不要在这里设置Layer0透明度，会干扰正常显示
  // Remove frequent debug output to reduce log spam
  
  // 使用VSync重载减少闪动
  __HAL_LTDC_RELOAD_CONFIG(&hlcd_ltdc);
  
  // 动画期间暂停second layer维护，避免干扰Layer0显示
  if (!g_animation_in_progress) {
    animation_counter++;
    if (animation_counter % 2 == 0) {  // Every other call to maintain 30fps animation
      lcd_ensure_second_layer();
    }
  }
  
  g_current_display_addr = addr;
  
  // 当Layer2显示时，更新Layer1背景以匹配Layer2，确保状态栏区域背景一致
  // 只有在非动画期间且Layer2可见时才更新，避免性能影响
  if (!g_animation_in_progress && lcd_cover_background_is_visible() && animation_counter % 4 == 0) {
    lcd_cover_background_update_layer1_from_layer2();
  }
}

uint32_t lcd_get_src_addr(void) { return g_current_display_addr; }

// Second layer configuration function - CoverBackground 硬件层
void lcd_add_second_layer(void) {
  // Check if already initialized
  if (g_layer2_initialized) {
    return;
  }
  
  // 配置第二层layer (layer 1) - 专门用于CoverBackground
  // Layer2覆盖整个屏幕，但顶部44px保持透明，让Layer1状态栏透过
  printf("Configuring Layer2 covering full screen with transparent statusbar (height=%d)\n", TRANSPARENT_STATUSBAR_HEIGHT);
  LTDC_LAYERCONFIG config;
  config.x0 = 0;
  config.x1 = lcd_params.hres;
  config.y0 = 0;  // 从0开始显示，覆盖整个屏幕
  config.y1 = lcd_params.vres;
  config.pixel_format = lcd_params.pixel_format_ltdc;
  // Layer2内存从第一行开始，前44行保持透明，壁纸内容从第一行开始与Layer1重合
  config.address = LAYER2_MEMORY_BASE;
  
  if (ltdc_layer_config(&hlcd_ltdc, 1, &config) != HAL_OK) {
    return;
  }
  
  // 初始化CoverBackground内容
  lcd_cover_background_init();
  
  // 初始状态：只配置Layer1，不干扰Layer0
  hlcd_ltdc.Instance = LTDC;
  
  // 确保Layer0已经启用（但不修改其透明度，避免干扰正常显示）
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 0);
  
  // 只配置Layer1
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // Layer 1 完全不透明
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1);
  
  // 将layer初始化到屏幕上方位置（考虑透明状态栏）
  // 标记为已初始化后再移动
  g_layer2_initialized = true;
  
  // 初始化动画系统
  lcd_animation_init();
  
  // 现在可以安全地移动layer
  lcd_cover_background_move_to_y(-800);
  
  // 使用VSync重载避免干扰正常显示
  __HAL_LTDC_RELOAD_CONFIG(&hlcd_ltdc);
}

// Clear second layer memory
void lcd_clear_layer2_memory(void) {
  // printf("Clearing second layer memory...\n");
  
  uint32_t buffer_size = lcd_params.hres * lcd_params.vres * 2; // RGB565 is 2 bytes
  uint16_t *layer2_buffer = (uint16_t*)LAYER2_MEMORY_BASE;
  
  // Clear to 0x0000 (black - will be made transparent via Layer Alpha)
  for (uint32_t i = 0; i < buffer_size / 2; i++) {
    layer2_buffer[i] = 0x0000;
  }
  
  // printf("Second layer memory clearing completed, buffer size: %lu bytes\n", buffer_size);
}

// CoverBackground layer state - 硬件层实现
static struct {
  bool visible;
  uint8_t opacity;     // 0-255
  int32_t y_offset;    // Y轴偏移，-60为隐藏位置，0为显示位置
  bool is_animating;
} cover_bg_state = {false, 0, -800, false};  // 初始状态：隐藏，透明，位置在屏幕上方（考虑透明状态栏）

// 初始化 CoverBackground 内容
void lcd_cover_background_init(void) {
  if (!g_layer2_initialized) {
    return;
  }
  
  uint16_t *layer2_buffer = (uint16_t*)LAYER2_MEMORY_BASE;
  uint32_t buffer_size = lcd_params.hres * lcd_params.vres;
  
  // 先清空整个layer2缓冲区，避免随机数据
  printf("CoverBackground: Clearing layer2 buffer...\n");
  for (uint32_t i = 0; i < buffer_size; i++) {
    layer2_buffer[i] = 0x0000;  // 清除为黑色
  }
  
  // 复制Layer1当前显示内容到Layer2，确保背景一致
  printf("CoverBackground: Copying Layer1 background to Layer2 for consistency\n");
  
  // 使用DMA2D安全地复制当前Layer1显示内容
  if (g_current_display_addr != 0) {
    printf("CoverBackground: Using DMA2D to copy Layer1 background (addr=0x%08lx)\n", g_current_display_addr);
    
    // 使用DMA2D复制整个Layer1内容到Layer2，确保背景一致
    dma2d_copy_buffer((uint32_t*)g_current_display_addr, 
                      (uint32_t*)LAYER2_MEMORY_BASE,
                      0, 0, lcd_params.hres, lcd_params.vres);
    
    printf("CoverBackground: Layer1 background copied to Layer2 successfully\n");
  } else {
    // 如果没有Layer1内容，使用默认Layer1帧缓冲区
    printf("CoverBackground: Using default Layer1 framebuffer for background consistency\n");
    dma2d_copy_buffer((uint32_t*)FMC_SDRAM_LTDC_BUFFER_ADDRESS, 
                      (uint32_t*)LAYER2_MEMORY_BASE,
                      0, 0, lcd_params.hres, lcd_params.vres);
  }
}

// 设置Layer1背景图片路径
void lcd_cover_background_set_layer1_path(const char* path) {
  if (path && strlen(path) < sizeof(g_layer1_background_path)) {
    strncpy(g_layer1_background_path, path, sizeof(g_layer1_background_path) - 1);
    g_layer1_background_path[sizeof(g_layer1_background_path) - 1] = '\0';
    printf("CoverBackground: Layer1 background path set to: %s\n", g_layer1_background_path);
  }
}

// 更新Layer1背景以匹配Layer2 - 确保状态栏区域背景一致
void lcd_cover_background_update_layer1_from_layer2(void) {
  if (!g_layer2_initialized) {
    return;
  }
  
  printf("CoverBackground: Updating Layer1 background to match Layer2\n");
  
  // 使用当前Layer1显示地址
  uint32_t layer1_addr = g_current_display_addr ? g_current_display_addr : FMC_SDRAM_LTDC_BUFFER_ADDRESS;
  
  // 方案1：直接复制Layer2的状态栏区域到Layer1
  // 这样可以确保状态栏区域背景完全一致
  dma2d_copy_buffer((uint32_t*)LAYER2_MEMORY_BASE, 
                    (uint32_t*)layer1_addr,
                    0, 0, lcd_params.hres, TRANSPARENT_STATUSBAR_HEIGHT);
  
  printf("CoverBackground: Layer1 statusbar background updated to match Layer2 (addr=0x%08lx)\n", layer1_addr);
  
  // 方案2：如果需要更完整的背景一致性，可以加载相同的背景图片到Layer1
  // 这里可以调用JPEG解码器将g_layer1_background_path指定的图片加载到Layer1
  // 但这会覆盖Layer1的UI元素，所以暂时只使用方案1
}

// 将相同的背景图片加载到Layer1 - 确保完整的背景一致性
void lcd_cover_background_sync_layer1_background(void) {
  if (!g_layer2_initialized) {
    return;
  }
  
  printf("CoverBackground: Synchronizing Layer1 background with Layer2\n");
  
  // 使用当前Layer1显示地址
  uint32_t layer1_addr = g_current_display_addr ? g_current_display_addr : FMC_SDRAM_LTDC_BUFFER_ADDRESS;
  
  // 使用JPEG解码器加载相同的背景图片到Layer1
  if (strlen(g_layer1_background_path) > 0) {
    printf("CoverBackground: Loading background image to Layer1: %s\n", g_layer1_background_path);
    
    // 使用专用的JPEG输出缓冲区
    uint32_t jpeg_output_address = FMC_SDRAM_JPEG_OUTPUT_DATA_BUFFER_ADDRESS;
    
    // 初始化JPEG解码器
    jpeg_init();
    
    // 解码JPEG文件到临时缓冲区
    int decode_result = jped_decode(g_layer1_background_path, jpeg_output_address);
    
    if (decode_result == 0) {
      // 获取解码后的图片信息
      uint32_t width, height, subsampling;
      jpeg_decode_info(&width, &height, &subsampling);
      
      printf("CoverBackground: JPEG decoded for Layer1: %lux%lu, subsampling: %lu\n", width, height, subsampling);
      
      // 计算需要复制的像素数量
      uint32_t copy_width = (width > lcd_params.hres) ? lcd_params.hres : width;
      uint32_t copy_height = (height > lcd_params.vres) ? lcd_params.vres : height;
      
      // 使用DMA2D复制解码后的图片到Layer1
      if (subsampling == JPEG_420_SUBSAMPLING || subsampling == JPEG_422_SUBSAMPLING || subsampling == JPEG_444_SUBSAMPLING) {
        dma2d_copy_ycbcr_to_rgb((uint32_t*)jpeg_output_address, 
                                (uint32_t*)layer1_addr,
                                copy_width, copy_height, subsampling);
      } else {
        dma2d_copy_buffer((uint32_t*)jpeg_output_address, 
                          (uint32_t*)layer1_addr,
                          0, 0, copy_width, copy_height);
      }
      
      printf("CoverBackground: Layer1 background synchronized successfully\n");
    } else {
      printf("CoverBackground: Failed to decode background image for Layer1: %s, error: %d\n", g_layer1_background_path, decode_result);
    }
  }
}

// 显示 CoverBackground - 硬件透明度控制
void lcd_cover_background_show(void) {
  if (!g_layer2_initialized) {
    return;
  }
  
  cover_bg_state.visible = true;
  cover_bg_state.opacity = 255;  // 完全不透明
  cover_bg_state.y_offset = 0;  // 显示时的正常位置
  
  // Layer1始终保持不透明
  hlcd_ltdc.Instance = LTDC;
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // 始终不透明
  
  // 确保Layer2的Color Keying功能启用，实现前44px透明
  printf("CoverBackground: Ensuring Color Keying is enabled for transparent statusbar\n");
  uint16_t color_key = TRANSPARENT_COLOR_KEY;
  uint32_t red = ((color_key >> 11) & 0x1F) << 3;     // R5 -> R8
  uint32_t green = ((color_key >> 5) & 0x3F) << 2;    // G6 -> G8
  uint32_t blue = (color_key & 0x1F) << 3;            // B5 -> B8
  uint32_t rgb888_key = (red << 16) | (green << 8) | blue;
  
  HAL_LTDC_ConfigColorKeying(&hlcd_ltdc, rgb888_key, 1);
  HAL_LTDC_EnableColorKeying(&hlcd_ltdc, 1);
  
  // 移动layer到正确位置（显示时的正常位置）
  lcd_cover_background_move_to_y(0);
  
  // 显示Layer2时，立即更新Layer1背景以匹配Layer2，确保状态栏区域背景一致
  lcd_cover_background_update_layer1_from_layer2();
  
  __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
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
  
  // 设置前44行为透明颜色键，确保状态栏区域可以看到Layer1
  printf("Setting transparent statusbar area (first %d lines) with color key 0x%04x...\n", 
         TRANSPARENT_STATUSBAR_HEIGHT, TRANSPARENT_COLOR_KEY);
  for (uint32_t y = 0; y < TRANSPARENT_STATUSBAR_HEIGHT; y++) {
    for (uint32_t x = 0; x < lcd_params.hres; x++) {
      layer2_buffer[y * lcd_params.hres + x] = TRANSPARENT_COLOR_KEY;  // 设置为透明颜色键
    }
  }
  
  printf("DMA2D JPEG copy completed\n");
  
  // 加载JPEG后，如果Layer2可见，更新Layer1背景以匹配Layer2
  if (lcd_cover_background_is_visible()) {
    printf("CoverBackground: Updating Layer1 background after JPEG load\n");
    lcd_cover_background_update_layer1_from_layer2();
  }
  
  printf("JPEG wallpaper loaded to CoverBackground layer: %s (%lux%lu -> %lux%lu)\n", 
         jpeg_path, width, height, copy_width, copy_height);
}

// 硬件移动 CoverBackground - 直接控制LTDC层位置
void lcd_cover_background_move_to_y(int16_t y_position) {
  if (!g_layer2_initialized) {
    printf("ERROR: Layer2 not initialized for movement\n");
    return;
  }
  
  // 更新状态
  cover_bg_state.y_offset = y_position;
  
  // 计算实际的窗口位置
  // Layer2覆盖整个屏幕，前44px透明，移动时整体向上移动
  uint32_t window_x0 = 0;
  uint32_t window_y0 = y_position;
  uint32_t window_x1 = lcd_params.hres;
  uint32_t window_y1 = lcd_params.vres + y_position;
  
  // 处理边界情况
  if (window_y1 <= 0) {
    // Layer2完全移出屏幕上方，禁用Layer2确保Layer1正常显示
    printf("Layer2 moved out of screen, disable Layer2 (Y=%d)\n", y_position);
    __HAL_LTDC_LAYER_DISABLE(&hlcd_ltdc, 1);
    __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
    return;
  }
  
  // 确保窗口不超出屏幕范围
  if ((int32_t)window_y0 < 0) window_y0 = 0;
  if (window_y1 > lcd_params.vres) window_y1 = lcd_params.vres;
  
  // 每隔一定帧数输出调试信息，避免日志过多
  static uint32_t move_counter = 0;
  move_counter++;
  if (move_counter % 50 == 0 || !g_animation_in_progress) {
    printf("Move Layer2 to Y=%d (window: %lu,%lu-%lu,%lu)\n", 
           y_position, window_x0, window_y0, window_x1, window_y1);
  }
  
  // 确保Layer1启用（可能之前被禁用）
  __HAL_LTDC_LAYER_ENABLE(&hlcd_ltdc, 1);
  
  // 重新配置第二层layer的窗口位置
  LTDC_LAYERCONFIG config;
  config.x0 = window_x0;
  config.x1 = window_x1;
  config.y0 = window_y0;
  config.y1 = window_y1;
  config.pixel_format = lcd_params.pixel_format_ltdc;
  config.address = LAYER2_MEMORY_BASE;
  
  // 计算内存地址偏移
  uint32_t bytes_per_line = lcd_params.hres * lcd_params.bbp;
  
  if (y_position < 0 && window_y0 == 0) {
    // 向上移动时，窗口从屏幕顶部开始，需要跳过被裁剪的行
    uint32_t skip_lines = -y_position;
    config.address = LAYER2_MEMORY_BASE + (skip_lines * bytes_per_line);
    if (move_counter % 50 == 0) {
      printf("Move up, skip %lu lines, memory address offset=0x%08lx\n", skip_lines, config.address);
    }
  } else {
    // 正常情况，Layer2从第一行开始，前44行保持透明
    config.address = LAYER2_MEMORY_BASE;
  }
  
  if (ltdc_layer_config(&hlcd_ltdc, 1, &config) == HAL_OK) {
    // 动画期间使用立即重载提升响应性，非动画期间使用VSync重载保持稳定
    if (g_animation_in_progress) {
      __HAL_LTDC_RELOAD_IMMEDIATE_CONFIG(&hlcd_ltdc);
    } else {
      __HAL_LTDC_RELOAD_CONFIG(&hlcd_ltdc);
    }
    
    if (move_counter % 50 == 0 || !g_animation_in_progress) {
      printf("Hardware layer movement configured, reload type=%s\n", 
             g_animation_in_progress ? "immediate" : "vsync");
    }
  } else {
    printf("ERROR: Layer2 configuration failed (Y=%d)\n", y_position);
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
  // 每毫秒调用一次，更新动画状态
  // 添加基本的保护检查
  if (g_layer2_initialized && g_animation_state.active) {
    // 添加调试信息来确认回调被调用
    static uint32_t callback_counter = 0;
    callback_counter++;
    
    // 每100次调用输出一次调试信息
    if (callback_counter % 100 == 0) {
      printf("Animation systick callback: tick=%lu, counter=%lu, active=%d\n", 
             tick, callback_counter, g_animation_state.active);
    }
    
    lcd_cover_background_update_animation();
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
    printf("ERROR: Layer2 not initialized for animation\n");
    return;
  }
  
  int16_t start_y = cover_bg_state.y_offset;
  
  if (start_y == target_y) {
    printf("Animation skipped: already at target position Y=%d\n", target_y);
    return;
  }
  
  printf("Animation init: g_layer2_initialized=%d, start_y=%d, target_y=%d\n", 
         g_layer2_initialized, start_y, target_y);
  
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
  
  // 动画开始前确保Layer1状态正确
  hlcd_ltdc.Instance = LTDC;
  HAL_LTDC_SetAlpha(&hlcd_ltdc, 255, 1);  // Layer1不透明
  cover_bg_state.opacity = 255;
  
  printf("Start non-blocking animation: from Y=%ld to Y=%d, duration=%dms, state.active=%d\n", 
         (long)start_y, target_y, duration_ms, g_animation_state.active);
}

// 更新动画状态 - 需要定期调用
bool lcd_cover_background_update_animation(void) {
  if (!g_animation_state.active) {
    return false;
  }
  
  // 第一次调用时输出调试信息
  if (g_animation_state.frame_count == 0) {
    printf("Animation update: first call, start_time=%lu, current_time=%lu\n", 
           g_animation_state.start_time, HAL_GetTick());
  }
  
  uint32_t current_time = HAL_GetTick();
  uint32_t elapsed_time = current_time - g_animation_state.start_time;
  
  // 检查动画是否完成
  if (elapsed_time >= g_animation_state.duration_ms) {
    // 动画完成，移动到精确位置
    lcd_cover_background_move_to_y(g_animation_state.target_y);
    
    // 清除动画状态
    g_animation_state.active = false;
    g_animation_in_progress = false;
    
    uint32_t avg_fps = (g_animation_state.frame_count * 1000) / elapsed_time;
    printf("Non-blocking animation completed: moved to Y=%d, total frames=%lu, actual time=%lums, avg FPS=%lu\n", 
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
  
  // 每隔20帧输出一次调试信息（减少日志输出量）
  if (g_animation_state.frame_count % 20 == 0) {
    uint32_t frame_time = current_time - g_animation_state.last_update_time;
    uint32_t fps = frame_time > 0 ? 20000 / frame_time : 0;
    printf("Animation frame %lu: Y=%d, progress=%.1f%%, 20frame_time=%lums, FPS=%lu\n", 
           g_animation_state.frame_count, current_y, (double)(progress * 100.0f), frame_time, fps);
    g_animation_state.last_update_time = current_time;
  }
  
  return true;
}

// 检查是否有动画正在进行
bool lcd_cover_background_has_active_animation(void) {
  return g_animation_state.active;
}

// 停止当前动画
void lcd_cover_background_stop_animation(void) {
  if (g_animation_state.active) {
    printf("Stop animation at Y=%ld position\n", (long)cover_bg_state.y_offset);
    g_animation_state.active = false;
    g_animation_in_progress = false;
  }
}

// 直接的动画函数 - 简化版，不依赖systick
void lcd_cover_background_animate_to_y(int16_t target_y, uint16_t duration_ms) {
  if (!g_layer2_initialized) {
    printf("ERROR: Layer2 not initialized for animation\n");
    return;
  }
  
  int16_t start_y = cover_bg_state.y_offset;
  
  if (start_y == target_y) {
    printf("Animation skipped: already at target position Y=%d\n", target_y);
    return;
  }
  
  printf("Start direct animation: from Y=%d to Y=%d, duration=%dms\n", start_y, target_y, duration_ms);
  
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
  
  printf("Animation parameters: start_y=%d, target_y=%d, distance=%d\n", start_y, target_y, distance);
  
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
    
    // 每20帧输出一次调试信息
    if (frame_count % 20 == 0) {
      printf("Animation frame %lu: Y=%d, progress=%.1f%%\n", 
             frame_count, current_y, (double)(progress * 100.0f));
    }
    
    // 16ms延时，约60fps
    HAL_Delay(16);
  }
  
  // 清除动画标志
  g_animation_in_progress = false;
  
  uint32_t total_time = HAL_GetTick() - start_time;
  uint32_t avg_fps = (frame_count * 1000) / total_time;
  printf("Direct animation completed: moved to Y=%d, frames=%lu, time=%lums, avg_fps=%lu\n", 
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
