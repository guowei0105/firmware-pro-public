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

#include <memory.h>
#include <stdbool.h>
#include <stdlib.h>

#include STM32_HAL_H

#include "flash.h"
#include "image.h"
#include "sdram.h"
#include "secbool.h"

// Note: as Arm V7-M MPU requires region base addr aligns to region size
// some parts we have to set multiple regions to cover it
// MPU REGION LAYERS
// --- base
// 定义MPU区域编号常量，用于配置不同内存区域的保护策略
#define MPU_REGION_BASE MPU_REGION_NUMBER0       // 基础区域（整个4GB地址空间）
#define MPU_REGION_SRAMs MPU_REGION_NUMBER1      // 各种SRAM区域（DTCM-RAM, AXI-SRAM等）
#define MPU_REGION_SDRAM MPU_REGION_NUMBER2      // 外部SDRAM区域
#define MPU_REGION_FLASH MPU_REGION_NUMBER3      // 内部Flash存储区域
#define MPU_REGION_FLASH_OTP MPU_REGION_NUMBER4  // Flash一次性可编程区域

// 定义不同固件阶段的MPU区域编号
#define MPU_REGION_FLASH_BOARD MPU_REGION_NUMBER5  // 板载加载器(boardloader)区域
#define MPU_REGION_FLASH_BOOT MPU_REGION_NUMBER6   // 引导加载器(bootloader)区域
#define MPU_REGION_FLASH_FWBK1 MPU_REGION_NUMBER7  // 固件区域(Bank1)
#define MPU_REGION_FLASH_FWBK2 MPU_REGION_NUMBER8  // 固件区域(Bank2)
// 其他特殊用途区域
#define MPU_REGION_SRAM3_DMA MPU_REGION_NUMBER9    // 用于DMA的SRAM3区域
#define MPU_REGION_QSPI_FLASH MPU_REGION_NUMBER10  // QSPI Flash区域

// 定义Flash子区域掩码，用于精确控制Flash不同部分的访问权限
// 每个掩码表示8个子区域中哪些是启用的(0)哪些是禁用的(1)
// 取反操作(~)是因为MPU中0表示启用该子区域，1表示禁用
#define MPU_SUBREGION_MASK_BK1_BOARD (uint8_t)(~0b00000001U)  // Bank1中的boardloader区域
#define MPU_SUBREGION_MASK_BK1_BOOT (uint8_t)(~0b00000110U)   // Bank1中的bootloader区域
#define MPU_SUBREGION_MASK_BK1_FW (uint8_t)(~0b11111000U)     // Bank1中的固件区域
#define MPU_SUBREGION_MASK_BK2_FW (uint8_t)(~0b01111111U)     // Bank2中的固件区域
#define MPU_SUBREGION_MASK_BK2_OTP (uint8_t)(~0b10000000U)    // Bank2中的OTP区域
#define MPU_SUBREGION_MASK_NONE 0xffU                         // 禁用所有子区域

// 控制MPU的启用或禁用
void mpu_ctrl(secbool mpu_enable) {
  if (mpu_enable != secfalse)  // 如果mpu_enable不是secfalse(0)
    HAL_MPU_Enable(MPU_PRIVILEGED_DEFAULT);  // 启用MPU，允许特权模式下的默认内存访问
  else
    HAL_MPU_Disable();  // 禁用MPU
}

// 配置基本MPU设置，为不同内存区域设置访问权限
void mpu_config_base() {
  MPU_Region_InitTypeDef mpu_init_struct = {0};  // 初始化MPU区域配置结构体

  // 配置基础区域(整个4GB地址空间)
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;  // 启用该区域
    mpu_init_struct.Number = MPU_REGION_BASE;    // 设置区域编号
    mpu_init_struct.BaseAddress = 0x00000000;    // 基地址为0
    mpu_init_struct.Size = MPU_REGION_SIZE_4GB;  // 区域大小为4GB
    mpu_init_struct.SubRegionDisable =
        0x87;  // 子区域禁用掩码，参考ST社区链接中的解释
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;  // 类型扩展字段设置
    mpu_init_struct.AccessPermission = MPU_REGION_NO_ACCESS;  // 默认不允许访问
    mpu_init_struct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;  // 禁止执行代码
    mpu_init_struct.IsShareable = MPU_ACCESS_SHAREABLE;  // 可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_NOT_CACHEABLE;  // 不可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);  // 应用配置
  }

  // 配置各种SRAM区域(DTCM-RAM, AXI-SRAM, SRAM1-5, BAK-SRAM)
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;  // 启用该区域
    mpu_init_struct.Number = MPU_REGION_SRAMs;   // 设置区域编号
    mpu_init_struct.BaseAddress = 0x20000000;    // SRAM基地址
    mpu_init_struct.Size = MPU_REGION_SIZE_512MB;  // 区域大小为512MB
    mpu_init_struct.SubRegionDisable = 0x00;     // 不禁用任何子区域
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL1;  // 类型扩展字段设置
    mpu_init_struct.AccessPermission = MPU_REGION_FULL_ACCESS;  // 完全访问权限
    mpu_init_struct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;  // 禁止执行代码
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;  // 不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_CACHEABLE;  // 可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_BUFFERABLE;  // 可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);  // 应用配置
  }

  // 配置SDRAM区域
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;  // 启用该区域
    mpu_init_struct.Number = MPU_REGION_SDRAM;   // 设置区域编号
    mpu_init_struct.BaseAddress = 0xD0000000;    // SDRAM基地址
    mpu_init_struct.Size = MPU_REGION_SIZE_32MB;  // 区域大小为32MB
    mpu_init_struct.SubRegionDisable = 0x00;     // 不禁用任何子区域
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;  // 类型扩展字段设置
    mpu_init_struct.AccessPermission = MPU_REGION_FULL_ACCESS;  // 完全访问权限
    mpu_init_struct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;  // 禁止执行代码
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;  // 不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_CACHEABLE;  // 可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);  // 应用配置
  }

  // 配置Flash区域，写透缓存，保持默认配置
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;  // 启用该区域
    mpu_init_struct.Number = MPU_REGION_FLASH;   // 设置区域编号
    mpu_init_struct.BaseAddress = FLASH_BASE;    // Flash基地址
    mpu_init_struct.Size = MPU_REGION_SIZE_2MB;  // 区域大小为2MB
    mpu_init_struct.SubRegionDisable = 0x00;     // 不禁用任何子区域
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;  // 类型扩展字段设置
    mpu_init_struct.AccessPermission = MPU_REGION_NO_ACCESS;  // 默认不允许访问
    mpu_init_struct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;  // 禁止执行代码
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;  // 不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_CACHEABLE;  // 可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);  // 应用配置
  }

  // 配置Flash OTP(一次性可编程)区域
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;  // 启用该区域
    mpu_init_struct.Number = MPU_REGION_FLASH;   // 设置区域编号
    mpu_init_struct.BaseAddress = FLASH_BANK2_BASE;  // Flash Bank2基地址
    mpu_init_struct.Size = MPU_REGION_SIZE_1MB;  // 区域大小为1MB
    mpu_init_struct.SubRegionDisable = MPU_SUBREGION_MASK_BK2_OTP;  // 设置OTP子区域掩码
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;  // 类型扩展字段设置
    mpu_init_struct.AccessPermission = MPU_REGION_PRIV_RW_URO;  // 特权模式读写，用户模式只读
    // mpu_init_struct.AccessPermission = MPU_REGION_FULL_ACCESS;  // 注释掉的完全访问权限选项
    mpu_init_struct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;  // 禁止执行代码
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;  // 不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_CACHEABLE;  // 可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);  // 应用配置
  }
}

void mpu_config_boardloader(secbool access, secbool exec) {
  MPU_Region_InitTypeDef mpu_init_struct = {0};

  // FLASH
  // 此函数用于配置MPU（内存保护单元）以保护板载加载程序（boardloader）区域
  // 它设置Flash Bank1中的特定区域的访问权限和执行权限
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;                // 启用该MPU区域
    mpu_init_struct.Number = MPU_REGION_FLASH_BOARD;           // 设置区域编号为板载加载程序区域
    mpu_init_struct.BaseAddress = FLASH_BANK1_BASE;            // 设置基地址为Flash Bank1的起始地址
    mpu_init_struct.Size = MPU_REGION_SIZE_1MB;                // 设置区域大小为1MB
    mpu_init_struct.SubRegionDisable = MPU_SUBREGION_MASK_BK1_BOARD; // 设置子区域禁用掩码
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;             // 设置类型扩展字段为级别0
    mpu_init_struct.AccessPermission =                         // 根据access参数设置访问权限
        ((access == sectrue) ? MPU_REGION_FULL_ACCESS : MPU_REGION_NO_ACCESS);
    mpu_init_struct.DisableExec =                              // 根据exec参数设置执行权限
        ((exec == sectrue) ? MPU_INSTRUCTION_ACCESS_ENABLE
                           : MPU_INSTRUCTION_ACCESS_DISABLE);
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;    // 设置为不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_CACHEABLE;        // 设置为可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 设置为不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);                    // 应用MPU区域配置
  }
}

void mpu_config_bootloader(secbool access, secbool exec) {
  MPU_Region_InitTypeDef mpu_init_struct = {0};

  // FLASH
  // 此函数用于配置MPU（内存保护单元）以保护引导加载程序（bootloader）区域
  // 它设置Flash Bank1中的特定区域的访问权限和执行权限
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;                // 启用该MPU区域
    mpu_init_struct.Number = MPU_REGION_FLASH_BOOT;            // 设置区域编号为引导加载程序区域
    mpu_init_struct.BaseAddress = FLASH_BANK1_BASE;            // 设置基地址为Flash Bank1的起始地址
    mpu_init_struct.Size = MPU_REGION_SIZE_1MB;                // 设置区域大小为1MB
    mpu_init_struct.SubRegionDisable = MPU_SUBREGION_MASK_BK1_BOOT; // 设置子区域禁用掩码，指定bootloader所在的子区域
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;             // 设置类型扩展字段为级别0
    mpu_init_struct.AccessPermission =                         // 根据access参数设置访问权限
        ((access == sectrue) ? MPU_REGION_FULL_ACCESS : MPU_REGION_NO_ACCESS);
    mpu_init_struct.DisableExec =                              // 根据exec参数设置执行权限
        ((exec == sectrue) ? MPU_INSTRUCTION_ACCESS_ENABLE
                           : MPU_INSTRUCTION_ACCESS_DISABLE);
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;    // 设置为不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_CACHEABLE;        // 设置为可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 设置为不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);                    // 应用MPU区域配置
  }

  // SRAM3 SPI/UART DMA
  // 配置SRAM3区域用于SPI和UART的DMA传输
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;                // 启用该MPU区域
    mpu_init_struct.Number = MPU_REGION_SRAM3_DMA;             // 设置区域编号为SRAM3 DMA区域
    mpu_init_struct.BaseAddress = 0x30040000;                  // 设置基地址为SRAM3的起始地址
    mpu_init_struct.Size = MPU_REGION_SIZE_32KB;               // 设置区域大小为32KB
    mpu_init_struct.SubRegionDisable = 0x00;                   // 不禁用任何子区域
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL1;             // 设置类型扩展字段为级别1
    mpu_init_struct.AccessPermission = MPU_REGION_FULL_ACCESS;  // 设置为完全访问权限
    mpu_init_struct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE; // 禁止在此区域执行代码
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;    // 设置为不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_NOT_CACHEABLE;    // 设置为不可缓存（DMA区域通常不缓存）
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 设置为不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);                    // 应用MPU区域配置
  }

  // SPI FLASH
  // 配置外部SPI Flash存储器区域
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;                // 启用该MPU区域
    mpu_init_struct.Number = MPU_REGION_QSPI_FLASH;            // 设置区域编号为QSPI Flash区域
    mpu_init_struct.BaseAddress = 0x90000000;                  // 设置基地址为外部Flash的映射地址
    mpu_init_struct.Size = MPU_REGION_SIZE_8MB;                // 设置区域大小为8MB
    mpu_init_struct.SubRegionDisable = 0x00;                   // 不禁用任何子区域
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;             // 设置类型扩展字段为级别0
    mpu_init_struct.AccessPermission = MPU_REGION_PRIV_RW;     // 设置为特权模式读写权限
    mpu_init_struct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE; // 禁止在此区域执行代码
    mpu_init_struct.IsShareable = MPU_ACCESS_SHAREABLE;        // 设置为可共享（多个总线主设备可访问）
    mpu_init_struct.IsCacheable = MPU_ACCESS_NOT_CACHEABLE;    // 设置为不可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 设置为不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);                    // 应用MPU区域配置
  }
}

secbool mpu_config_firmware(secbool access, secbool exec) {
  MPU_Region_InitTypeDef mpu_init_struct = {0};

  // FLASH
  // 配置Flash Bank1区域的MPU设置，用于固件存储
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;                // 启用该MPU区域
    mpu_init_struct.Number = MPU_REGION_FLASH_FWBK1;           // 设置区域编号为Flash固件Bank1区域
    mpu_init_struct.BaseAddress = FLASH_BANK1_BASE;            // 设置基地址为Flash Bank1的起始地址
    mpu_init_struct.Size = MPU_REGION_SIZE_1MB;                // 设置区域大小为1MB
    mpu_init_struct.SubRegionDisable = MPU_SUBREGION_MASK_BK1_FW; // 设置子区域禁用掩码，指定固件所在的子区域
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;             // 设置类型扩展字段为级别0
    mpu_init_struct.AccessPermission =                         // 根据access参数设置访问权限
        ((access == sectrue) ? MPU_REGION_FULL_ACCESS : MPU_REGION_NO_ACCESS);
    mpu_init_struct.DisableExec =                              // 根据exec参数设置执行权限
        ((exec == sectrue) ? MPU_INSTRUCTION_ACCESS_ENABLE
                           : MPU_INSTRUCTION_ACCESS_DISABLE);
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;    // 设置为不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_CACHEABLE;        // 设置为可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 设置为不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);                    // 应用MPU区域配置
  }

  // FLASH
  // 配置Flash Bank2区域的MPU设置，用于固件存储
  {
    mpu_init_struct.Enable = MPU_REGION_ENABLE;                // 启用该MPU区域
    mpu_init_struct.Number = MPU_REGION_FLASH_FWBK2;           // 设置区域编号为Flash固件Bank2区域
    mpu_init_struct.BaseAddress = FLASH_BANK2_BASE;            // 设置基地址为Flash Bank2的起始地址
    mpu_init_struct.Size = MPU_REGION_SIZE_1MB;                // 设置区域大小为1MB
    mpu_init_struct.SubRegionDisable = MPU_SUBREGION_MASK_BK2_FW; // 设置子区域禁用掩码，指定固件所在的子区域
    mpu_init_struct.TypeExtField = MPU_TEX_LEVEL0;             // 设置类型扩展字段为级别0
    mpu_init_struct.AccessPermission =                         // 根据access参数设置访问权限
        ((access == sectrue) ? MPU_REGION_FULL_ACCESS : MPU_REGION_NO_ACCESS);
    mpu_init_struct.DisableExec =                              // 根据exec参数设置执行权限
        ((exec == sectrue) ? MPU_INSTRUCTION_ACCESS_ENABLE
                           : MPU_INSTRUCTION_ACCESS_DISABLE);
    mpu_init_struct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;    // 设置为不可共享
    mpu_init_struct.IsCacheable = MPU_ACCESS_CACHEABLE;        // 设置为可缓存
    mpu_init_struct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE;  // 设置为不可缓冲
    HAL_MPU_ConfigRegion(&mpu_init_struct);                    // 应用MPU区域配置
  }
  __asm__ volatile("dsb");                                     // 数据同步屏障指令，确保内存访问完成
  __asm__ volatile("isb");                                     // 指令同步屏障指令，确保管道刷新

  return sectrue;                                              // 返回安全布尔值true，表示配置成功
}
