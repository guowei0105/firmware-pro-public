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

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "py/compile.h"
#include "py/gc.h"
#include "py/mperrno.h"
#include "py/nlr.h"
#include "py/repl.h"
#include "py/runtime.h"
#include "py/stackctrl.h"
#include "shared/runtime/pyexec.h"

#include "ports/stm32/gccollect.h"
#include "ports/stm32/pendsv.h"

#include "debug_utils.h"
// #include "adc.h"
#include "bl_check.h"
#include "board_capabilities.h"
#include "common.h"
#include "compiler_traits.h"
#include "display.h"
#include "emmc_fs.h"
#include "flash.h"
#include "hardware_version.h"
#include "image.h"
#include "mpu.h"
#include "random_delays.h"
#include "systick.h"
#include "usart.h"
#ifdef SYSTEM_VIEW
#include "systemview.h"
#endif
#include "rng.h"
// #include "sdcard.h"
#include "adc.h"
#include "camera.h"
#include "device.h"
#include "fingerprint.h"
#include "mipi_lcd.h"
#include "motor.h"
#include "nfc.h"
#include "qspi_flash.h"
#include "se_thd89.h"
#include "spi_legacy.h"
#include "supervise.h"
#include "systick.h"
#include "thd89.h"
#include "timer.h"
#include "touch.h"
#ifdef USE_SECP256K1_ZKP
#include "zkp_context.h"
#endif
#include "cm_backtrace.h"
#include "version.h"

// from util.s
extern void shutdown_privileged(void);

static void copyflash2sdram(void) {
  extern int _flash2_load_addr, _flash2_start, _flash2_end;
  volatile uint32_t *dst = (volatile uint32_t *)&_flash2_start;
  volatile uint32_t *end = (volatile uint32_t *)&_flash2_end;
  volatile uint32_t *src = (volatile uint32_t *)&_flash2_load_addr;

  while (dst < end) {
    *dst = *src;
    if (*dst != *src) {
      error_shutdown("Internal error", "(CF2S)", NULL, NULL);
    }
    dst++;
    src++;
  }
}

int main(void) {
  SystemCoreClockUpdate();  // 更新系统核心时钟变量
  dwt_init();  // 初始化数据监视跟踪单元

  // 配置内存保护单元(MPU)以保护不同的固件区域
  mpu_config_boardloader(sectrue, secfalse);  // 配置板载加载程序区域
  mpu_config_bootloader(sectrue, secfalse);   // 配置引导加载程序区域
  mpu_config_firmware(sectrue, sectrue);      // 配置固件区域
  mpu_config_base();  // 基础配置最后设置，因为它包含拒绝访问层，且MPU可能已经运行
  mpu_ctrl(sectrue);  // 确保MPU已启用

  // 禁用所有外部通信或用户输入中断
  // 稍后将通过调用它们的初始化函数重新启用
  // 蓝牙UART
  HAL_NVIC_DisableIRQ(UART4_IRQn);
  HAL_NVIC_ClearPendingIRQ(UART4_IRQn);
  // 蓝牙SPI
  HAL_NVIC_DisableIRQ(SPI2_IRQn);
  HAL_NVIC_ClearPendingIRQ(SPI2_IRQn);
  HAL_NVIC_DisableIRQ(EXTI15_10_IRQn);
  HAL_NVIC_ClearPendingIRQ(EXTI15_10_IRQn);
  // USB
  HAL_NVIC_DisableIRQ(OTG_HS_IRQn);
  HAL_NVIC_ClearPendingIRQ(OTG_HS_IRQn);

  // 重新启用全局中断
  __enable_irq();
  __enable_fault_irq();

  // 初始化显示和内存
  lcd_ltdc_dsi_disable();  // 禁用LCD控制器
  sdram_reinit();          // 重新初始化SDRAM
  // lcd_para_init(DISPLAY_RESX, DISPLAY_RESY, LCD_PIXEL_FORMAT_RGB565);  // 已注释的LCD参数初始化
  lcd_ltdc_dsi_enable();   // 启用LCD控制器
  lcd_pwm_init();          // 初始化LCD背光PWM
  touch_init();            // 初始化触摸屏
  adc_init();              // 初始化模数转换器

  // 初始化文件系统和闪存
  ensure_emmcfs(emmc_fs_init(), "emmc_fs_init");  // 确保eMMC文件系统初始化成功
  ensure_emmcfs(emmc_fs_mount(true, false), "emmc_fs_mount");  // 确保eMMC文件系统挂载成功
  if (get_hw_ver() < HW_VER_3P0A) {  // 如果硬件版本低于3.0A
    qspi_flash_init();               // 初始化QSPI闪存
    qspi_flash_config();             // 配置QSPI闪存
    qspi_flash_memory_mapped();      // 设置QSPI闪存为内存映射模式
  }
  cm_backtrace_init("firmware", hw_ver_to_str(get_hw_ver()), ONEKEY_VERSION);

  // 初始化通信接口
  ble_usart_init();   // 初始化蓝牙UART
  spi_slave_init();   // 初始化SPI从设备

  // 初始化随机数生成和安全功能
  random_delays_init();  // 初始化随机延迟
  collect_hw_entropy();  // 收集硬件熵

  // 初始化外设
  motor_init();        // 初始化电机
  thd89_init();        // 初始化THD89模块
  camera_init();       // 初始化摄像头
  fingerprint_init();  // 初始化指纹传感器
  nfc_init();          // 初始化NFC

  // 系统初始化
  timer_init();        // 初始化定时器
  display_clear();     // 清除显示
  pendsv_init();       // 初始化PendSV中断

  // 设备测试
  device_test(false);         // 执行设备测试
  device_burnin_test(false);  // 执行设备老化测试

  // 设备参数和安全初始化
  device_para_init();  // 初始化设备参数
  ensure(se_sync_session_key(), "se start up failed");  // 确保安全元件会话密钥同步成功

  // 检查引导加载程序版本并决定是否需要复制固件
  uint32_t bootloader_version = get_bootloader_version();
  bootloader_version >>= 8;

  if (bootloader_version >= 0x020503) {
    // 引导加载程序版本大于等于2.5.3，不需要固件复制
  } else {
    copyflash2sdram();  // 将闪存内容复制到SDRAM
  }

#ifdef RDI
  rdi_start();  // 启动RDI（如果定义）
#endif

#ifdef SYSTEM_VIEW
  enable_systemview();  // 启用SystemView调试（如果定义）
#endif

#if !PRODUCTION
  // 启用总线故障和使用故障处理程序（非生产环境）
  SCB->SHCSR |= (SCB_SHCSR_USGFAULTENA_Msk | SCB_SHCSR_BUSFAULTENA_Msk);
#endif

#ifdef USE_SECP256K1_ZKP
  ensure(sectrue * (zkp_context_init() == 0), NULL);  // 初始化零知识证明上下文（如果定义）
#endif

  printf("CORE: Preparing stack\n");
  // 栈限制应小于实际栈大小，以便我们有机会从限制命中中恢复
  mp_stack_set_top(&_estack);  // 设置MicroPython栈顶
  mp_stack_set_limit((char *)&_estack - (char *)&_sstack - 1024);  // 设置栈限制

#if MICROPY_ENABLE_PYSTACK
  static mp_obj_t pystack[2048];  // 定义Python栈
  mp_pystack_init(pystack, &pystack[MP_ARRAY_SIZE(pystack)]);  // 初始化Python栈
#endif

  // 垃圾回收初始化
  printf("CORE: Starting GC\n");
  gc_init(&_heap_start, &_heap_end);  // 初始化垃圾回收器

  // 解释器初始化
  printf("CORE: Starting interpreter\n");
  mp_init();  // 初始化MicroPython
  mp_obj_list_init(mp_sys_argv, 0);  // 初始化sys.argv
  mp_obj_list_init(mp_sys_path, 0);  // 初始化sys.path
  mp_obj_list_append(
      mp_sys_path,
      MP_OBJ_NEW_QSTR(MP_QSTR_));  // 添加当前目录（或脚本的基本目录）到sys.path

  // 执行主脚本
  printf("CORE: Executing main script\n");
  pyexec_frozen_module("main.py");  // 执行冻结的main.py模块
  // 清理
  printf("CORE: Main script finished, cleaning up\n");
  mp_deinit();  // 反初始化MicroPython

  return 0;
}

// MicroPython default exception handler

void __attribute__((noreturn)) nlr_jump_fail(void *val) {
  error_shutdown("Internal error", "(UE)", NULL, NULL);
}

// interrupt handlers

void NMI_Handler(void) {
  // Clock Security System triggered NMI
  // if ((RCC->CIR & RCC_CIR_CSSF) != 0)
  { error_shutdown("Internal error", "(CS)", NULL, NULL); }
}

// Show fault
void ShowHardFault(void) {
  error_shutdown("Internal error", "(HF)", NULL, NULL);
}

void ShowMemManage_MM(void) {
  error_shutdown("Internal error", "(MM)", NULL, NULL);
}

void ShowMemManage_SO(void) {
  error_shutdown("Internal error", "(SO)", NULL, NULL);
}

void ShowBusFault(void) {
  error_shutdown("Internal error", "(BF)", NULL, NULL);
}

void ShowUsageFault(void) {
  error_shutdown("Internal error", "(UF)", NULL, NULL);
}

__attribute__((noreturn)) void reboot_to_bootloader() {
  jump_to_with_flag(BOOTLOADER_START + IMAGE_HEADER_SIZE,
                    BOOT_TARGET_BOOTLOADER);
  for (;;)
    ;
}

void SVC_C_Handler(uint32_t *stack) {
  uint8_t svc_number = ((uint8_t *)stack[6])[-2];
  switch (svc_number) {
    case SVC_ENABLE_IRQ:
      HAL_NVIC_EnableIRQ(stack[0]);
      break;
    case SVC_DISABLE_IRQ:
      HAL_NVIC_DisableIRQ(stack[0]);
      break;
    case SVC_SET_PRIORITY:
      NVIC_SetPriority(stack[0], stack[1]);
      break;
#ifdef SYSTEM_VIEW
    case SVC_GET_DWT_CYCCNT:
      cyccnt_cycles = *DWT_CYCCNT_ADDR;
      break;
#endif
    case SVC_SHUTDOWN:
      shutdown_privileged();
      for (;;)
        ;
      break;
    case SVC_RESET_SYSTEM:
      HAL_NVIC_SystemReset();
      while (1)
        ;
      break;
    default:
      stack[0] = 0xffffffff;
      break;
  }
}

__attribute__((naked)) void SVC_Handler(void) {
  __asm volatile(
      " tst lr, #4    \n"    // Test Bit 3 to see which stack pointer we should
                             // use.
      " ite eq        \n"    // Tell the assembler that the nest 2 instructions
                             // are if-then-else
      " mrseq r0, msp \n"    // Make R0 point to main stack pointer
      " mrsne r0, psp \n"    // Make R0 point to process stack pointer
      " b SVC_C_Handler \n"  // Off to C land
  );
}

// MicroPython builtin stubs

mp_import_stat_t mp_import_stat(const char *path) {
  return MP_IMPORT_STAT_NO_EXIST;
}

mp_obj_t mp_builtin_open(uint n_args, const mp_obj_t *args, mp_map_t *kwargs) {
  return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_KW(mp_builtin_open_obj, 1, mp_builtin_open);
