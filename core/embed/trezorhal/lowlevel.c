/*
 * This file is part of the Trezor project, https://trezor.io/
 *
 * Copyright (c) SatoshiLabs
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include STM32_HAL_H

#include "lowlevel.h"
#include "common.h"
#include "flash.h"

#pragma GCC optimize( \
    "no-stack-protector")  // applies to all functions in this file

#if PRODUCTION
#define WANT_RDP_LEVEL (OB_RDP_LEVEL_2)
#define WANT_WRP_SECTORS (OB_WRP_SECTOR_0)
#else
#define WANT_RDP_LEVEL (OB_RDP_LEVEL_0)
#define WANT_WRP_SECTORS (0)
#endif

// BOR LEVEL 3: Reset level threshold is around 2.5 V
#define WANT_BOR_LEVEL (OB_BOR_LEVEL3)

/**
 * @brief  CPU L1-Cache enable.
 * @param  None
 * @retval None
 */
void cpu_cache_enable(void) {
  /* Enable I-Cache */
  SCB_EnableICache();

  /* Enable D-Cache */
  SCB_EnableDCache();
}

void cpu_cache_disable(void) {
  /* Disable I-Cache */
  SCB_DisableICache();

  /* Disable D-Cache */
  SCB_DisableDCache();
}

/**
 * @brief  System Clock Configuration
 *         The system Clock is configured as follow :
 *            System Clock source            = PLL (HSE)
 *            SYSCLK(Hz)                     = 400000000 (CM7 CPU Clock)
 *            HCLK(Hz)                       = 200000000 (CM4 CPU, AXI and AHBs
 * Clock) AHB Prescaler                  = 2 D1 APB3 Prescaler              = 2
 * (APB3 Clock  100MHz) D2 APB1 Prescaler              = 2 (APB1 Clock  100MHz)
 *            D2 APB2 Prescaler              = 2 (APB2 Clock  100MHz)
 *            D3 APB4 Prescaler              = 2 (APB4 Clock  100MHz)
 *            HSE Frequency(Hz)              = 25000000
 *            PLL_M                          = 5
 *            PLL_N                          = 160
 *            PLL_P                          = 2
 *            PLL_Q                          = 4
 *            PLL_R                          = 2
 *            VDD(V)                         = 3.3
 *            Flash Latency(WS)              = 4
 * @param  None
 * @retval None
 */
void system_clock_config(void) {
  RCC_ClkInitTypeDef RCC_ClkInitStruct;                   // 定义RCC时钟初始化结构体
  RCC_OscInitTypeDef RCC_OscInitStruct;                   // 定义RCC振荡器初始化结构体
  RCC_PeriphCLKInitTypeDef PeriphClkInitStruct;           // 定义RCC外设时钟初始化结构体
  HAL_StatusTypeDef ret = HAL_OK;                         // 定义HAL状态变量并初始化为OK

  /*!< Supply configuration update enable */               // 电源配置更新使能
  // HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);              // LDO供电模式（已注释）
  HAL_PWREx_ConfigSupply(PWR_DIRECT_SMPS_SUPPLY);         // 配置为SMPS直接供电模式

  /* The voltage scaling allows optimizing the power consumption when the device
     is clocked below the maximum system frequency, to update the voltage
     scaling value regarding system frequency refer to product datasheet.  */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1); // 配置电压调节器为Scale1模式（最高性能）

  while (!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {          // 等待电压调节器稳定
  }

  /* Enable HSE Oscillator and activate PLL with HSE as source */
  RCC_OscInitStruct.OscillatorType =                      // 配置振荡器类型
      RCC_OSCILLATORTYPE_HSI48 | RCC_OSCILLATORTYPE_HSE;  // 使用HSI48和HSE振荡器
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;                // 启用HSE振荡器
  RCC_OscInitStruct.HSI48State = RCC_HSI48_ON;            // 启用HSI48振荡器
  RCC_OscInitStruct.HSIState = RCC_HSI_OFF;               // 关闭HSI振荡器
  RCC_OscInitStruct.CSIState = RCC_CSI_OFF;               // 关闭CSI振荡器
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;            // 启用PLL
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;    // PLL时钟源为HSE

  RCC_OscInitStruct.PLL.PLLM = 5;                         // PLL分频系数M=5
  RCC_OscInitStruct.PLL.PLLN = 160;                       // PLL倍频系数N=160
  RCC_OscInitStruct.PLL.PLLFRACN = 0;                     // PLL小数部分为0
  RCC_OscInitStruct.PLL.PLLP = 2;                         // PLL分频系数P=2
  RCC_OscInitStruct.PLL.PLLQ = 4;                         // PLL分频系数Q=4
  RCC_OscInitStruct.PLL.PLLR = 2;                         // PLL分频系数R=2

  RCC_OscInitStruct.PLL.PLLVCOSEL = RCC_PLL1VCOWIDE;      // 配置PLL VCO为宽频模式
  RCC_OscInitStruct.PLL.PLLRGE = RCC_PLL1VCIRANGE_2;      // 配置PLL输入频率范围
  ret = HAL_RCC_OscConfig(&RCC_OscInitStruct);            // 配置RCC振荡器
  if (ret != HAL_OK) {                                     // 如果配置失败
    ensure(secfalse, "HAL_RCC_OscConfig failed");         // 报错并停止执行
  }

  /* Select PLL as system clock source and configure  bus clocks dividers */
  RCC_ClkInitStruct.ClockType =                           // 配置时钟类型
      (RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_D1PCLK1 |
       RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2 | RCC_CLOCKTYPE_D3PCLK1); // 配置所有总线时钟

  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK; // 系统时钟源为PLL
  RCC_ClkInitStruct.SYSCLKDivider = RCC_SYSCLK_DIV1;      // 系统时钟不分频
  RCC_ClkInitStruct.AHBCLKDivider = RCC_HCLK_DIV2;        // AHB时钟2分频
  RCC_ClkInitStruct.APB3CLKDivider = RCC_APB3_DIV2;       // APB3时钟2分频
  RCC_ClkInitStruct.APB1CLKDivider = RCC_APB1_DIV2;       // APB1时钟2分频
  RCC_ClkInitStruct.APB2CLKDivider = RCC_APB2_DIV2;       // APB2时钟2分频
  RCC_ClkInitStruct.APB4CLKDivider = RCC_APB4_DIV2;       // APB4时钟2分频
  ret = HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4); // 配置RCC时钟和Flash延迟
  if (ret != HAL_OK) {                                     // 如果配置失败
    ensure(secfalse, "HAL_RCC_ClockConfig failed");       // 报错并停止执行
  }

  PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_USB; // 选择USB外设时钟
  PeriphClkInitStruct.UsbClockSelection = RCC_USBCLKSOURCE_HSI48; // USB时钟源为HSI48
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct) != HAL_OK) { // 配置外设时钟
    ensure(secfalse, "HAL_RCCEx_PeriphCLKConfig failed"); // 如果配置失败，报错并停止执行
  }

  /*
   Note : The activation of the I/O Compensation Cell is recommended with
   communication  interfaces (GPIO, SPI, FMC, QSPI ...)  when  operating at high
   frequencies(please refer to product datasheet) The I/O Compensation Cell
   activation  procedure requires :
         - The activation of the CSI clock
         - The activation of the SYSCFG clock
         - Enabling the I/O Compensation Cell : setting bit[0] of register
   SYSCFG_CCCSR
  */

  /*activate CSI clock mondatory for I/O Compensation Cell*/
  __HAL_RCC_CSI_ENABLE();                                 // 启用CSI时钟（I/O补偿单元必需）

  /* Enable SYSCFG clock mondatory for I/O Compensation Cell */
  __HAL_RCC_SYSCFG_CLK_ENABLE();                          // 启用SYSCFG时钟（I/O补偿单元必需）

  /* Enables the I/O Compensation Cell */
  HAL_EnableCompensationCell();                           // 启用I/O补偿单元

  SCB->CPACR |=                                           // 配置协处理器访问控制寄存器
      ((3UL << 10 * 2) | (3UL << 11 * 2));                // 设置CP10和CP11为完全访问（启用FPU）

  SystemCoreClockUpdate();                                // 更新系统核心时钟变量
}

void periph_init(void) {
  // STM32F4xx HAL library initialization:                // STM32F4xx HAL库初始化：
  //  - configure the Flash prefetch, instruction and data caches  // - 配置Flash预取，指令和数据缓存
  //  - configure the Systick to generate an interrupt each 1 msec  // - 配置Systick产生1毫秒中断
  //  - set NVIC Group Priority to 4                      // - 设置NVIC组优先级为4
  //  - global MSP (MCU Support Package) initialization   // - 全局MSP（MCU支持包）初始化
  HAL_Init();                                             // 调用HAL初始化函数

  // enable the PVD (programmable voltage detector).      // 启用PVD（可编程电压检测器）
  // select the "2.7V" threshold (level 5).               // 选择"2.7V"阈值（级别5）
  // this detector will be active regardless of the       // 无论闪存选项字节BOR设置如何
  // flash option byte BOR setting.                       // 该检测器都将处于活动状态

  PWR_PVDTypeDef pvd_config;                              // 定义PVD配置结构体
  pvd_config.PVDLevel = PWR_PVDLEVEL_5;                   // 设置PVD电平为级别5（2.7V）
  pvd_config.Mode = PWR_PVD_MODE_IT_RISING_FALLING;       // 设置PVD模式为上升沿和下降沿中断
  HAL_PWR_ConfigPVD(&pvd_config);                         // 配置PVD
  HAL_PWR_EnablePVD();                                    // 启用PVD
  NVIC_EnableIRQ(PVD_AVD_IRQn);                           // 在NVIC中启用PVD中断
}

void reset_flags_reset(void) {
  RCC->RSR |= RCC_RSR_RMVF;  // clear the reset flags  // 清除复位标志位
}

void flash_option_bytes_init(void) {
  // 此函数用于初始化和配置Flash选项字节，主要负责：
  // 1. 检查并设置读保护级别(RDP)
  // 2. 配置BCM4功能（如果已启用则禁用）
  // 3. 设置写保护扇区(WRP)、掉电复位级别(BOR)和各种用户选项
  // 4. 确保安全设置符合设备要求
  
  FLASH_OBProgramInitTypeDef ob_config;                   // 定义Flash选项字节程序初始化结构体

  HAL_FLASHEx_OBGetConfig(&ob_config);                    // 获取当前Flash选项字节配置

  if (ob_config.RDPLevel != OB_RDP_LEVEL_2) {             // 如果读保护级别不是级别2
    if ((ob_config.USERConfig & OB_BCM4_ENABLE) != OB_BCM4_DISABLE) {  // 如果BCM4功能已启用
      ob_config.OptionType |= OPTIONBYTE_USER;            // 设置选项类型为用户选项字节
      ob_config.USERType |= OB_USER_BCM4;                 // 设置用户类型包含BCM4
      ob_config.USERConfig &= ~OB_BCM4_ENABLE;            // 清除BCM4启用位，禁用BCM4

      HAL_FLASH_Unlock();                                 // 解锁Flash
      HAL_FLASH_OB_Unlock();                              // 解锁选项字节

      if (HAL_FLASHEx_OBProgram(&ob_config) != HAL_OK) {  // 编程选项字节
        ensure(secfalse, "HAL_FLASHEx_OBProgram failed"); // 如果编程失败，确保安全失败
      }

      if (HAL_FLASH_OB_Launch() != HAL_OK) {              // 启动选项字节加载
        ensure(secfalse, "HAL_FLASH_OB_Launch failed");   // 如果加载失败，确保安全失败
      }

      HAL_FLASH_OB_Lock();                                // 锁定选项字节
      HAL_FLASH_Lock();                                   // 锁定Flash
    }
  }

  if (ob_config.RDPLevel != WANT_RDP_LEVEL) {             // 如果读保护级别不是期望的级别
    ob_config.OptionType |=                               // 设置选项类型包含以下选项
        OPTIONBYTE_WRP | OPTIONBYTE_RDP | OPTIONBYTE_USER | OPTIONBYTE_BOR;  // 写保护、读保护、用户选项和BOR选项
    ob_config.RDPLevel = WANT_RDP_LEVEL;                  // 设置为期望的读保护级别
    ob_config.BORLevel = WANT_BOR_LEVEL;                  // 设置为期望的BOR级别
    ob_config.WRPSector = WANT_WRP_SECTORS;               // 设置为期望的写保护扇区
    ob_config.USERType =                                  // 设置用户类型包含以下选项
        OB_USER_IWDG1_SW | OB_USER_IWDG2_SW | OB_USER_NRST_STOP_D1 |  // 独立看门狗1软件、独立看门狗2软件、D1域STOP模式下NRST行为
        OB_USER_NRST_STOP_D2 | OB_USER_NRST_STDBY_D1 | OB_USER_NRST_STDBY_D2 |  // D2域STOP模式下NRST行为、D1域STANDBY模式下NRST行为、D2域STANDBY模式下NRST行为
        OB_USER_IWDG_STOP | OB_USER_IWDG_STDBY | OB_USER_IOHSLV |  // STOP模式下IWDG行为、STANDBY模式下IWDG行为、IO高速低电压垫片
        OB_USER_SWAP_BANK | OB_USER_SECURITY | OB_USER_BCM4;  // 交换BANK、安全功能、BCM4功能
    ob_config.USERConfig =                                // 设置用户配置为以下值
        OB_IWDG1_SW | OB_IWDG2_SW | OB_STOP_NO_RST_D1 | OB_STOP_NO_RST_D2 |  // 软件控制IWDG1、软件控制IWDG2、D1域STOP模式不复位、D2域STOP模式不复位
        OB_STDBY_NO_RST_D1 | OB_STDBY_NO_RST_D2 | OB_IWDG_STOP_FREEZE |  // D1域STANDBY模式不复位、D2域STANDBY模式不复位、STOP模式冻结IWDG
        OB_IWDG_STDBY_FREEZE | OB_IOHSLV_ENABLE | OB_SWAP_BANK_DISABLE |  // STANDBY模式冻结IWDG、启用IO高速低电压垫片、禁用BANK交换
        OB_SECURITY_DISABLE | OB_BCM4_DISABLE;            // 禁用安全功能、禁用BCM4功能

    HAL_FLASH_Unlock();                                   // 解锁Flash
    HAL_FLASH_OB_Unlock();                                // 解锁选项字节

    if (HAL_FLASHEx_OBProgram(&ob_config) != HAL_OK) {    // 编程选项字节
      ensure(secfalse, "HAL_FLASHEx_OBProgram failed");   // 如果编程失败，确保安全失败
    }

    if (HAL_FLASH_OB_Launch() != HAL_OK) {                // 启动选项字节加载
      ensure(secfalse, "HAL_FLASH_OB_Launch failed");     // 如果加载失败，确保安全失败
    }

    HAL_FLASH_OB_Lock();                                  // 锁定选项字节
    HAL_FLASH_Lock();                                     // 锁定Flash

    HAL_FLASHEx_OBGetConfig(&ob_config);                  // 重新获取Flash选项字节配置
  }
}

void bus_fault_enable(void) { SCB->SHCSR |= SCB_SHCSR_BUSFAULTENA_Msk; }
void bus_fault_disable(void) { SCB->SHCSR &= ~SCB_SHCSR_BUSFAULTENA_Msk; }
