#include STM32_HAL_H
#include "sdram.h"

SDRAM_HandleTypeDef hsdram[1];
static FMC_SDRAM_CommandTypeDef Command;

#define REFRESH_COUNT ((uint32_t)0x0603) /* (100Mhz clock) */
#define FMC_SDRAM_TIMEOUT ((uint32_t)0xFFFF)

static void sdram_delay(uint32_t delay) {
  uint32_t tickstart;
  tickstart = HAL_GetTick();
  while ((HAL_GetTick() - tickstart) < delay) {
  }
}

static int sdram_init_sequence(void) {
  /* SDRAM initialization sequence */
  /* Step 1: Configure a clock configuration enable command */
  Command.CommandMode = FMC_SDRAM_DEVICE_CLK_ENABLE_CMD;
  Command.CommandTarget = FMC_SDRAM_CMD_TARGET_BANK2;
  Command.AutoRefreshNumber = 1;
  Command.ModeRegisterDefinition = 0;

  /* Send the command */
  if (HAL_SDRAM_SendCommand(&hsdram[0], &Command, FMC_SDRAM_TIMEOUT) !=
      HAL_OK) {
    return HAL_ERROR;
  }

  /* Step 2: Insert 100 us minimum delay */
  /* Inserted delay is equal to 1 ms due to systick time base unit (ms) */
  sdram_delay(1);

  /* Step 3: Configure a PALL (precharge all) command */
  Command.CommandMode = FMC_SDRAM_DEVICE_PALL_CMD;
  Command.CommandTarget = FMC_SDRAM_CMD_TARGET_BANK2;
  Command.AutoRefreshNumber = 1;
  Command.ModeRegisterDefinition = 0;

  /* Send the command */
  if (HAL_SDRAM_SendCommand(&hsdram[0], &Command, FMC_SDRAM_TIMEOUT) !=
      HAL_OK) {
    return HAL_ERROR;
  }

  /* Step 4: Configure a Refresh command */
  Command.CommandMode = FMC_SDRAM_DEVICE_AUTOREFRESH_MODE_CMD;
  Command.CommandTarget = FMC_SDRAM_CMD_TARGET_BANK2;
  Command.AutoRefreshNumber = 8;
  Command.ModeRegisterDefinition = 0;

  /* Send the command */
  if (HAL_SDRAM_SendCommand(&hsdram[0], &Command, FMC_SDRAM_TIMEOUT) !=
      HAL_OK) {
    return HAL_ERROR;
  }

  /* Step 5: Program the external memory mode register */
  uint32_t tmpmrd;

  /* Program the external memory mode register */
  tmpmrd = (uint32_t)FMC_SDRAM_DEVICE_BURST_LENGTH_1 |
           FMC_SDRAM_DEVICE_BURST_TYPE_SEQUENTIAL |
           FMC_SDRAM_DEVICE_CAS_LATENCY_2 |
           FMC_SDRAM_DEVICE_OPERATING_MODE_STANDARD |
           FMC_SDRAM_DEVICE_WRITEBURST_MODE_SINGLE;

  Command.CommandMode = FMC_SDRAM_DEVICE_LOAD_MODE_CMD;
  Command.CommandTarget = FMC_SDRAM_CMD_TARGET_BANK2;
  Command.AutoRefreshNumber = 1;
  Command.ModeRegisterDefinition = tmpmrd;

  /* Send the command */
  if (HAL_SDRAM_SendCommand(&hsdram[0], &Command, FMC_SDRAM_TIMEOUT) !=
      HAL_OK) {
    return HAL_ERROR;
  }
  /* Step 6: Set the refresh rate counter */
  if (HAL_SDRAM_ProgramRefreshRate(&hsdram[0], REFRESH_COUNT) != HAL_OK) {
    return HAL_ERROR;
  }
  return HAL_OK;
}

int sdram_init(void) {
  GPIO_InitTypeDef gpio_init_structure;  // 定义GPIO初始化结构体

  /* Enable FMC clock */  // 启用FMC时钟
  __HAL_RCC_FMC_CLK_ENABLE();  // 使能FMC时钟
  __FMC_NORSRAM_DISABLE(FMC_NORSRAM_DEVICE, FMC_NORSRAM_BANK1);  // 禁用FMC NORSRAM设备的BANK1

  /* Enable GPIOs clock */  // 启用GPIO时钟
  __HAL_RCC_GPIOD_CLK_ENABLE();  // 使能GPIOD时钟
  __HAL_RCC_GPIOE_CLK_ENABLE();  // 使能GPIOE时钟
  __HAL_RCC_GPIOF_CLK_ENABLE();  // 使能GPIOF时钟
  __HAL_RCC_GPIOG_CLK_ENABLE();  // 使能GPIOG时钟
  __HAL_RCC_GPIOH_CLK_ENABLE();  // 使能GPIOH时钟
  __HAL_RCC_GPIOI_CLK_ENABLE();  // 使能GPIOI时钟

  /* Common GPIO configuration */  // 通用GPIO配置
  gpio_init_structure.Mode = GPIO_MODE_AF_PP;  // 设置为复用推挽输出模式
  gpio_init_structure.Pull = GPIO_PULLUP;  // 设置为上拉模式
  gpio_init_structure.Speed = GPIO_SPEED_FREQ_MEDIUM;  // 设置为中速模式
  gpio_init_structure.Alternate = GPIO_AF12_FMC;  // 设置为FMC复用功能

  /* GPIOD configuration */  // GPIOD配置
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_8 | GPIO_PIN_9 |  // 配置GPIOD的引脚
                            GPIO_PIN_10 | GPIO_PIN_14 | GPIO_PIN_15;  // 使用按位或组合多个引脚

  HAL_GPIO_Init(GPIOD, &gpio_init_structure);  // 初始化GPIOD

  /* GPIOE configuration */  // GPIOE配置
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_7 | GPIO_PIN_8 |  // 配置GPIOE的引脚
                            GPIO_PIN_9 | GPIO_PIN_10 | GPIO_PIN_11 |  // 使用按位或组合多个引脚
                            GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |  // 继续组合引脚
                            GPIO_PIN_15;  // 最后一个引脚

  HAL_GPIO_Init(GPIOE, &gpio_init_structure);  // 初始化GPIOE
  /* GPIOF configuration */  // GPIOF配置
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3 |  // 配置GPIOF的引脚
                            GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_11 |  // 使用按位或组合多个引脚
                            GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |  // 继续组合引脚
                            GPIO_PIN_15;  // 最后一个引脚

  HAL_GPIO_Init(GPIOF, &gpio_init_structure);  // 初始化GPIOF
  /* GPIOG configuration */  // GPIOG配置
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 |  // 配置GPIOG的引脚
                            GPIO_PIN_2 /*| GPIO_PIN_3 */ | GPIO_PIN_4 |  // GPIO_PIN_3被注释掉了
                            GPIO_PIN_5 | GPIO_PIN_15;  // 使用按位或组合多个引脚
  HAL_GPIO_Init(GPIOG, &gpio_init_structure);  // 初始化GPIOG

  /* GPIOH configuration */  // GPIOH配置
  gpio_init_structure.Pin = GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7 | GPIO_PIN_8 |  // 配置GPIOH的引脚
                            GPIO_PIN_9 | GPIO_PIN_10 | GPIO_PIN_11 |  // 使用按位或组合多个引脚
                            GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |  // 继续组合引脚
                            GPIO_PIN_15;  // 最后一个引脚

  HAL_GPIO_Init(GPIOH, &gpio_init_structure);  // 初始化GPIOH

  /* GPIOI configuration */  // GPIOI配置
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3 |  // 配置GPIOI的引脚
                            GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7 |  // 使用按位或组合多个引脚
                            GPIO_PIN_9 | GPIO_PIN_10;  // 最后两个引脚

  HAL_GPIO_Init(GPIOI, &gpio_init_structure);  // 初始化GPIOI

  gpio_init_structure.Speed = GPIO_SPEED_FREQ_VERY_HIGH;  // 设置为非常高速模式
  gpio_init_structure.Pull = GPIO_PULLDOWN;  // 设置为下拉模式
  gpio_init_structure.Pin = GPIO_PIN_8;  // 配置GPIOG的PIN8引脚

  HAL_GPIO_Init(GPIOG, &gpio_init_structure);  // 初始化GPIOG的PIN8

  FMC_SDRAM_TimingTypeDef sdram_timing;  // 定义SDRAM时序结构体

  /* SDRAM device configuration */  // SDRAM设备配置
  hsdram[0].Instance = FMC_SDRAM_DEVICE;  // 设置SDRAM设备实例

  /* SDRAM handle configuration */  // SDRAM句柄配置
  hsdram[0].Init.SDBank = FMC_SDRAM_BANK2;  // 设置SDRAM为BANK2
  hsdram[0].Init.ColumnBitsNumber = FMC_SDRAM_COLUMN_BITS_NUM_9;  // 设置列地址位数为9
  hsdram[0].Init.RowBitsNumber = FMC_SDRAM_ROW_BITS_NUM_12;  // 设置行地址位数为12
  hsdram[0].Init.MemoryDataWidth = FMC_SDRAM_MEM_BUS_WIDTH_32;  // 设置内存数据宽度为32位
  hsdram[0].Init.InternalBankNumber = FMC_SDRAM_INTERN_BANKS_NUM_4;  // 设置内部bank数量为4
  hsdram[0].Init.CASLatency = FMC_SDRAM_CAS_LATENCY_2;  // 设置CAS延迟为2
  hsdram[0].Init.WriteProtection = FMC_SDRAM_WRITE_PROTECTION_DISABLE;  // 禁用写保护
  hsdram[0].Init.SDClockPeriod = FMC_SDRAM_CLOCK_PERIOD_2;  // 设置SDRAM时钟周期为2
  hsdram[0].Init.ReadBurst = FMC_SDRAM_RBURST_ENABLE;  // 启用读突发
  hsdram[0].Init.ReadPipeDelay = FMC_SDRAM_RPIPE_DELAY_0;  // 设置读管道延迟为0

  /* Timing configuration for 100Mhz as SDRAM clock frequency (System clock is
   * up to 200Mhz) */  // 配置SDRAM时钟频率为100MHz的时序参数（系统时钟最高200MHz）
  sdram_timing.LoadToActiveDelay = 2;  // 设置加载到激活延迟为2
  sdram_timing.ExitSelfRefreshDelay = 7;  // 设置退出自刷新延迟为7
  sdram_timing.SelfRefreshTime = 4;  // 设置自刷新时间为4
  sdram_timing.RowCycleDelay = 7;  // 设置行周期延迟为7
  sdram_timing.WriteRecoveryTime = 2;  // 设置写恢复时间为2
  sdram_timing.RPDelay = 2;  // 设置行预充电延迟为2
  sdram_timing.RCDDelay = 2;  // 设置行列延迟为2

  /* SDRAM controller initialization */  // SDRAM控制器初始化
  if (HAL_SDRAM_Init(&hsdram[0], &sdram_timing) != HAL_OK) {  // 初始化SDRAM控制器
    return HAL_ERROR;  // 如果初始化失败，返回错误
  }

  if (!sdram_init_sequence()) return HAL_ERROR;  // 执行SDRAM初始化序列，如果失败返回错误

  return HAL_OK;  // 初始化成功，返回OK
}

int sdram_reinit(void) {
  GPIO_InitTypeDef gpio_init_structure;

  __HAL_RCC_FMC_FORCE_RESET();
  __HAL_RCC_FMC_RELEASE_RESET();

  RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};

  PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_FMC;
  PeriphClkInitStruct.FmcClockSelection = RCC_FMCCLKSOURCE_PLL;
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct) != HAL_OK) {
    return HAL_ERROR;
  }

  __HAL_RCC_FMC_CLK_ENABLE();
  __FMC_NORSRAM_DISABLE(FMC_NORSRAM_DEVICE, FMC_NORSRAM_BANK1);

  /* Enable GPIOs clock */
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOG_CLK_ENABLE();
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOI_CLK_ENABLE();

  HAL_GPIO_DeInit(GPIOD, GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_8 | GPIO_PIN_9 |
                             GPIO_PIN_10 | GPIO_PIN_14 | GPIO_PIN_15);

  HAL_GPIO_DeInit(GPIOE, GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_7 | GPIO_PIN_8 |
                             GPIO_PIN_9 | GPIO_PIN_10 | GPIO_PIN_11 |
                             GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |
                             GPIO_PIN_15);

  HAL_GPIO_DeInit(GPIOF, GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3 |
                             GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_11 |
                             GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |
                             GPIO_PIN_15);
  HAL_GPIO_DeInit(GPIOG, GPIO_PIN_0 | GPIO_PIN_1 |
                             GPIO_PIN_2 /*| GPIO_PIN_3 */ | GPIO_PIN_4 |
                             GPIO_PIN_5 | GPIO_PIN_8 | GPIO_PIN_15);

  HAL_GPIO_DeInit(GPIOH, GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7 | GPIO_PIN_8 |
                             GPIO_PIN_9 | GPIO_PIN_10 | GPIO_PIN_11 |
                             GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |
                             GPIO_PIN_15);

  HAL_GPIO_DeInit(GPIOI, GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3 |
                             GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7 |
                             GPIO_PIN_9 | GPIO_PIN_10);

  /* Common GPIO configuration */
  gpio_init_structure.Mode = GPIO_MODE_AF_PP;
  gpio_init_structure.Pull = GPIO_PULLUP;
  gpio_init_structure.Speed = GPIO_SPEED_FREQ_MEDIUM;
  gpio_init_structure.Alternate = GPIO_AF12_FMC;

  /* GPIOD configuration */
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_8 | GPIO_PIN_9 |
                            GPIO_PIN_10 | GPIO_PIN_14 | GPIO_PIN_15;

  HAL_GPIO_Init(GPIOD, &gpio_init_structure);

  /* GPIOE configuration */
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_7 | GPIO_PIN_8 |
                            GPIO_PIN_9 | GPIO_PIN_10 | GPIO_PIN_11 |
                            GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |
                            GPIO_PIN_15;

  HAL_GPIO_Init(GPIOE, &gpio_init_structure);
  /* GPIOF configuration */
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3 |
                            GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_11 |
                            GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |
                            GPIO_PIN_15;

  HAL_GPIO_Init(GPIOF, &gpio_init_structure);
  /* GPIOG configuration */
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 |
                            GPIO_PIN_2 /*| GPIO_PIN_3 */ | GPIO_PIN_4 |
                            GPIO_PIN_5 | GPIO_PIN_15;
  HAL_GPIO_Init(GPIOG, &gpio_init_structure);

  /* GPIOH configuration */
  gpio_init_structure.Pin = GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7 | GPIO_PIN_8 |
                            GPIO_PIN_9 | GPIO_PIN_10 | GPIO_PIN_11 |
                            GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 |
                            GPIO_PIN_15;

  HAL_GPIO_Init(GPIOH, &gpio_init_structure);

  /* GPIOI configuration */
  gpio_init_structure.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3 |
                            GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7 |
                            GPIO_PIN_9 | GPIO_PIN_10;

  HAL_GPIO_Init(GPIOI, &gpio_init_structure);

  gpio_init_structure.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  gpio_init_structure.Pull = GPIO_PULLDOWN;
  gpio_init_structure.Pin = GPIO_PIN_8;

  HAL_GPIO_Init(GPIOG, &gpio_init_structure);

  FMC_SDRAM_TimingTypeDef sdram_timing;

  /* SDRAM device configuration */
  hsdram[0].Instance = FMC_SDRAM_DEVICE;

  /* SDRAM handle configuration */
  hsdram[0].Init.SDBank = FMC_SDRAM_BANK2;
  hsdram[0].Init.ColumnBitsNumber = FMC_SDRAM_COLUMN_BITS_NUM_9;
  hsdram[0].Init.RowBitsNumber = FMC_SDRAM_ROW_BITS_NUM_12;
  hsdram[0].Init.MemoryDataWidth = FMC_SDRAM_MEM_BUS_WIDTH_32;
  hsdram[0].Init.InternalBankNumber = FMC_SDRAM_INTERN_BANKS_NUM_4;
  hsdram[0].Init.CASLatency = FMC_SDRAM_CAS_LATENCY_2;
  hsdram[0].Init.WriteProtection = FMC_SDRAM_WRITE_PROTECTION_DISABLE;
  hsdram[0].Init.SDClockPeriod = FMC_SDRAM_CLOCK_PERIOD_2;
  hsdram[0].Init.ReadBurst = FMC_SDRAM_RBURST_ENABLE;
  hsdram[0].Init.ReadPipeDelay = FMC_SDRAM_RPIPE_DELAY_2;

  /* Timing configuration for 100Mhz as SDRAM clock frequency (System clock is
   * up to 200Mhz) */
  sdram_timing.LoadToActiveDelay = 2;
  sdram_timing.ExitSelfRefreshDelay = 7;
  sdram_timing.SelfRefreshTime = 4;
  sdram_timing.RowCycleDelay = 7;
  sdram_timing.WriteRecoveryTime = 2;
  sdram_timing.RPDelay = 2;
  sdram_timing.RCDDelay = 2;

  /* SDRAM controller initialization */
  if (HAL_SDRAM_Init(&hsdram[0], &sdram_timing) != HAL_OK) {
    return HAL_ERROR;
  }

  sdram_init_sequence();

  return HAL_OK;
}

void sdram_handler_init(void) {
  if (!hsdram[0].Instance) {
    hsdram[0].Instance = FMC_SDRAM_DEVICE;
    hsdram[0].Init.SDBank = FMC_SDRAM_BANK2;
    hsdram[0].State = HAL_SDRAM_STATE_READY;
  }
}

void sdram_set_self_refresh(void) {
  sdram_handler_init();

  Command.CommandMode = FMC_SDRAM_CMD_SELFREFRESH_MODE;
  Command.CommandTarget = FMC_SDRAM_CMD_TARGET_BANK2;
  Command.AutoRefreshNumber = 1;
  Command.ModeRegisterDefinition = 0;

  HAL_SDRAM_SendCommand(&hsdram[0], &Command, FMC_SDRAM_TIMEOUT);
}

void sdram_set_normal_mode(void) {
  sdram_handler_init();

  Command.CommandMode = FMC_SDRAM_CMD_NORMAL_MODE;
  Command.CommandTarget = FMC_SDRAM_CMD_TARGET_BANK2;
  Command.AutoRefreshNumber = 1;
  Command.ModeRegisterDefinition = 0;
  HAL_SDRAM_SendCommand(&hsdram[0], &Command, FMC_SDRAM_TIMEOUT);
}
