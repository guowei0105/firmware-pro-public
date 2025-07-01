/*
 * This file is part of the Trezor project, https://trezor.io/  // 这是Trezor项目的一部分
 *
 * Copyright (c) SatoshiLabs  // 版权所有 SatoshiLabs
 *
 * This program is free software: you can redistribute it and/or modify  // 本程序是自由软件:你可以重新分发和/或修改
 * it under the terms of the GNU General Public License as published by  // 根据GNU通用公共许可证的条款
 * the Free Software Foundation, either version 3 of the License, or  // 由自由软件基金会发布的版本3或
 * (at your option) any later version.  // (由你选择)任何更新的版本
 *
 * This program is distributed in the hope that it will be useful,  // 本程序的发布是希望它能够有用
 * but WITHOUT ANY WARRANTY; without even the implied warranty of  // 但不做任何保证,甚至不保证
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the  // 适销性或特定用途的适用性。参见
 * GNU General Public License for more details.  // GNU通用公共许可证了解更多详情
 *
 * You should have received a copy of the GNU General Public License  // 你应该已经收到了GNU通用公共许可证
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.  // 如果没有,请访问<http://www.gnu.org/licenses/>
 */

#include <string.h>  // 包含字符串处理函数
#include <sys/types.h>  // 包含系统类型定义

#include "adc.h"  // 包含ADC相关定义
#include "common.h"  // 包含通用功能定义
#include "compiler_traits.h"  // 包含编译器特性定义
#include "device.h"  // 包含设备相关定义
#include "display.h"  // 包含显示相关定义
#include "flash.h"  // 包含闪存相关定义
#include "fw_keys.h"  // 包含固件密钥定义
#include "hardware_version.h"  // 包含硬件版本定义
#include "image.h"  // 包含镜像相关定义
#include "lowlevel.h"  // 包含底层功能定义
#include "mini_printf.h"  // 包含简化版printf定义
#include "mipi_lcd.h"  // 包含MIPI LCD定义
#include "mpu.h"  // 包含MPU相关定义
#include "qspi_flash.h"  // 包含QSPI闪存定义
#include "random_delays.h"  // 包含随机延迟定义
#include "sdram.h"  // 包含SDRAM相关定义
#include "se_thd89.h"  // 包含SE THD89定义
#include "secbool.h"  // 包含安全布尔定义
#include "systick.h"  // 包含系统滴答定义
#include "thd89.h"  // 包含THD89相关定义
#include "thd89_boot.h"  // 包含THD89启动定义
#include "touch.h"  // 包含触摸相关定义
#include "usb.h"  // 包含USB相关定义
#include "usbd_desc.h"  // 包含USB描述符定义
#include "version.h"  // 包含版本相关定义

#include "ble.h"  // 包含蓝牙相关定义
#include "bootui.h"  // 包含启动UI定义
#include "device.h"  // 包含设备相关定义
#include "i2c.h"  // 包含I2C相关定义
#include "jpeg_dma.h"  // 包含JPEG DMA定义
#include "messages.h"  // 包含消息相关定义
#include "motor.h"  // 包含电机相关定义
#include "spi.h"  // 包含SPI相关定义
#include "spi_legacy.h"  // 包含传统SPI定义
#include "usart.h"  // 包含USART相关定义

#define MSG_NAME_TO_ID(x) MessageType_MessageType_##x  // 定义消息名称到ID的转换宏

#if defined(STM32H747xx)  // 如果定义了STM32H747xx
#include "stm32h7xx_hal.h"  // 包含STM32H7 HAL库
#endif

#include "camera.h"  // 包含相机相关定义
#include "emmc_wrapper.h"  // 包含eMMC封装定义

static bool usb_tiny_enable = false;  // 定义USB tiny模式使能标志

#if !PRODUCTION  // 如果不是生产环境

// DO NOT USE THIS UNLESS YOU KNOW WHAT YOU ARE DOING  // 除非你知道你在做什么,否则不要使用这个
// Warning: this is for developers to setup a dummy config only!  // 警告:这仅供开发人员设置虚拟配置使用!
// configuration to SE is permanent, there is no way to reset it!  // SE的配置是永久性的,无法重置!
static void write_dev_dummy_serial() {  // 写入开发用虚拟序列号函数
  if (!device_serial_set()) {  // 如果序列号未设置
    // device_set_serial("TCTestSerialNumberXXXXXXXXXXXXX");  // 设置测试序列号
    device_set_serial("PRA50I0000 ES");  // 设置ES序列号
  }
}
static void write_dev_dummy_cert() {  // 写入开发用虚拟证书函数
  uint8_t dummy_cert[] = {  // 定义虚拟证书数据
      0x30, 0x82, 0x01, 0x58, 0x30, 0x82, 0x01, 0x0A, 0xA0, 0x03, 0x02, 0x01,
      0x02, 0x02, 0x08, 0x44, 0x9F, 0x65, 0xB6, 0x90, 0xE4, 0x90, 0x09, 0x30,
      0x05, 0x06, 0x03, 0x2B, 0x65, 0x70, 0x30, 0x36, 0x31, 0x0F, 0x30, 0x0D,
      0x06, 0x03, 0x55, 0x04, 0x0A, 0x13, 0x06, 0x4F, 0x6E, 0x65, 0x4B, 0x65,
      0x79, 0x31, 0x0B, 0x30, 0x09, 0x06, 0x03, 0x55, 0x04, 0x0B, 0x13, 0x02,
      0x4E, 0x41, 0x31, 0x16, 0x30, 0x14, 0x06, 0x03, 0x55, 0x04, 0x03, 0x0C,
      0x0D, 0x4F, 0x4E, 0x45, 0x4B, 0x45, 0x59, 0x5F, 0x44, 0x45, 0x56, 0x5F,
      0x43, 0x41, 0x30, 0x22, 0x18, 0x0F, 0x39, 0x39, 0x39, 0x39, 0x31, 0x32,
      0x33, 0x31, 0x32, 0x33, 0x35, 0x39, 0x35, 0x39, 0x5A, 0x18, 0x0F, 0x39,
      0x39, 0x39, 0x39, 0x31, 0x32, 0x33, 0x31, 0x32, 0x33, 0x35, 0x39, 0x35,
      0x39, 0x5A, 0x30, 0x2A, 0x31, 0x28, 0x30, 0x26, 0x06, 0x03, 0x55, 0x04,
      0x03, 0x13, 0x1F, 0x54, 0x43, 0x54, 0x65, 0x73, 0x74, 0x53, 0x65, 0x72,
      0x69, 0x61, 0x6C, 0x4E, 0x75, 0x6D, 0x62, 0x65, 0x72, 0x58, 0x58, 0x58,
      0x58, 0x58, 0x58, 0x58, 0x58, 0x58, 0x58, 0x58, 0x58, 0x58, 0x30, 0x59,
      0x30, 0x13, 0x06, 0x07, 0x2A, 0x86, 0x48, 0xCE, 0x3D, 0x02, 0x01, 0x06,
      0x08, 0x2A, 0x86, 0x48, 0xCE, 0x3D, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00,
      0x04, 0x20, 0x32, 0xF5, 0xC1, 0x3B, 0x55, 0x5C, 0x8B, 0xF7, 0xE0, 0xB4,
      0x8A, 0x83, 0x5C, 0x67, 0xD3, 0xC2, 0x04, 0xB7, 0x90, 0x2F, 0x49, 0x78,
      0xF8, 0x5D, 0x2B, 0xFE, 0xA1, 0xAF, 0x0B, 0xCA, 0x6F, 0x94, 0xD3, 0x20,
      0xD9, 0x04, 0x5B, 0xD7, 0x0B, 0xB2, 0x8D, 0xA7, 0xF1, 0x8D, 0x39, 0xA9,
      0xC5, 0x44, 0x53, 0x67, 0x5C, 0xA9, 0x6D, 0x5F, 0x45, 0x74, 0x77, 0x32,
      0x38, 0x8D, 0x91, 0x5F, 0xE2, 0xA3, 0x0F, 0x30, 0x0D, 0x30, 0x0B, 0x06,
      0x03, 0x55, 0x1D, 0x0F, 0x04, 0x04, 0x03, 0x02, 0x07, 0x80, 0x30, 0x05,
      0x06, 0x03, 0x2B, 0x65, 0x70, 0x03, 0x41, 0x00, 0x9F, 0x5D, 0x95, 0xFB,
      0x4A, 0xAD, 0xE6, 0xC6, 0x3B, 0x8E, 0x15, 0xB0, 0xBD, 0x0D, 0xF0, 0x70,
      0x81, 0x4E, 0x05, 0x9A, 0xAD, 0xC4, 0xE4, 0x6E, 0x44, 0xDE, 0xF1, 0xDB,
      0x51, 0xCB, 0x85, 0xB7, 0x5F, 0xAF, 0x55, 0xEB, 0x28, 0x9A, 0x66, 0x95,
      0xAA, 0x08, 0x66, 0x8E, 0x84, 0xC1, 0x22, 0x5D, 0x34, 0x75, 0xF3, 0x01,
      0x2F, 0x6D, 0x33, 0x21, 0x35, 0x1E, 0x54, 0xEC, 0x71, 0xEC, 0x3D, 0x04};
  UNUSED(dummy_cert);  // 防止未使用警告

  if (!se_has_cerrificate()) {  // 如果没有证书
    if (!se_write_certificate(dummy_cert, sizeof(dummy_cert)))  // 写入虚拟证书
      ensure(secfalse, "set cert failed");  // 确保写入成功
  }
}

#endif

// this is mainly for ignore/supress faults during flash read (for check  // 这主要用于在闪存读取期间忽略/抑制故障(用于检查
// purpose). if bus fault enabled, it will catched by BusFault_Handler, then we  // 目的)。如果启用总线故障,它将被BusFault_Handler捕获,然后我们
// could ignore it. if bus fault disabled, it will elevate to hard fault, this  // 可以忽略它。如果禁用总线故障,它将升级为硬故障,这
// is not what we want  // 不是我们想要的
static secbool handle_flash_ecc_error = secfalse;  // 定义处理闪存ECC错误标志
static void set_handle_flash_ecc_error(secbool val) {  // 设置处理闪存ECC错误标志函数
  handle_flash_ecc_error = val;  // 设置标志值
}

// fault handlers  // 故障处理程序
void HardFault_Handler(void) {  // 硬故障处理函数
  error_shutdown("Internal error", "(HF)", NULL, NULL);  // 显示内部错误并关机
}

void MemManage_Handler_MM(void) {  // 内存管理故障处理函数(MM)
  error_shutdown("Internal error", "(MM)", NULL, NULL);  // 显示内部错误并关机
}

void MemManage_Handler_SO(void) {  // 内存管理故障处理函数(SO)
  error_shutdown("Internal error", "(SO)", NULL, NULL);  // 显示内部错误并关机
}

void BusFault_Handler(void) {  // 总线故障处理函数
  // if want handle flash ecc error  // 如果要处理闪存ECC错误
  if (handle_flash_ecc_error == sectrue) {  // 如果启用了处理闪存ECC错误
    // dbgprintf_Wait("Internal flash ECC error detected at 0x%X", SCB->BFAR);  // 调试输出检测到的ECC错误地址

    // check if it's triggered by flash DECC  // 检查是否由闪存DECC触发
    if (flash_check_ecc_fault()) {  // 如果是闪存ECC故障
      // reset flash controller error flags  // 重置闪存控制器错误标志
      flash_clear_ecc_fault(SCB->BFAR);  // 清除ECC故障

      // reset bus fault error flags  // 重置总线故障错误标志
      SCB->CFSR &= ~(SCB_CFSR_BFARVALID_Msk | SCB_CFSR_PRECISERR_Msk);  // 清除CFSR标志
      __DSB();  // 数据同步屏障
      SCB->SHCSR &= ~(SCB_SHCSR_BUSFAULTACT_Msk);  // 清除SHCSR标志
      __DSB();  // 数据同步屏障

      // try to fix ecc error and reboot  // 尝试修复ECC错误并重启
      if (flash_fix_ecc_fault_FIRMWARE(SCB->BFAR)) {  // 如果修复成功
        error_shutdown("Internal flash ECC error", "Cleanup successful",  // 显示清理成功
                       "Firmware reinstall may required",  // 可能需要重新安装固件
                       "If the issue persists, contact support.");  // 如果问题持续存在,请联系支持
      } else {  // 如果修复失败
        error_shutdown("Internal flash ECC error", "Cleanup failed",  // 显示清理失败
                       "Reboot to try again",  // 重启以重试
                       "If the issue persists, contact support.");  // 如果问题持续存在,请联系支持
      }
    }
  }

  // normal route  // 正常路径
  error_shutdown("Internal error", "(BF)", NULL, NULL);  // 显示内部错误并关机
}

void UsageFault_Handler(void) {  // 使用故障处理函数
  error_shutdown("Internal error", "(UF)", NULL, NULL);  // 显示内部错误并关机
}

static secbool get_device_serial(char* serial, size_t len) {  // 获取设备序列号函数
  // init  // 初始化
  uint8_t otp_serial[FLASH_OTP_BLOCK_SIZE] = {0};  // 定义OTP序列号缓冲区
  memzero(otp_serial, sizeof(otp_serial));  // 清零OTP序列号缓冲区
  memzero(serial, len);  // 清零输出序列号缓冲区

  // get OTP serial  // 获取OTP序列号
  if (sectrue != flash_otp_is_locked(FLASH_OTP_DEVICE_SERIAL)) return secfalse;  // 检查OTP是否锁定

  if (sectrue != flash_otp_read(FLASH_OTP_DEVICE_SERIAL, 0, otp_serial,  // 读取OTP序列号
                                sizeof(otp_serial))) {
    return secfalse;  // 读取失败返回false
  }

  // make sure last element is '\0'  // 确保最后一个元素是'\0'
  otp_serial[FLASH_OTP_BLOCK_SIZE - 1] = '\0';  // 设置结束符

  // check if all is ascii  // 检查是否全是ASCII字符
  for (uint32_t i = 0; i < sizeof(otp_serial); i++) {  // 遍历OTP序列号
    if (otp_serial[i] == '\0') {  // 如果遇到结束符
      break;  // 跳出循环
    }
    if (otp_serial[i] < ' ' || otp_serial[i] > '~') {  // 如果不是可打印ASCII字符
      return secfalse;  // 返回false
    }
  }

  // copy to output buffer  // 复制到输出缓冲区
  memcpy(serial, otp_serial, MIN(len, sizeof(otp_serial)));  // 复制序列号

  // cutoff by strlen  // 按字符串长度截断
  serial[strlen(serial)] = '\0';  // 设置结束符

  return sectrue;  // 返回true
}

static void usb_init_all(secbool usb21_landing) {  // USB初始化函数
  static bool usb_init_done = false;  // 定义USB初始化完成标志
  if (usb_init_done) {  // 如果已经初始化
    return;  // 直接返回
  }
  usb_init_done = true;  // 设置初始化完成标志

  usb_dev_info_t dev_info = {  // 定义USB设备信息
      .device_class = 0x00,  // 设备类
      .device_subclass = 0x00,  // 设备子类
      .device_protocol = 0x00,  // 设备协议
      .vendor_id = 0x1209,  // 厂商ID
      .product_id = 0x4F4A,  // 产品ID
      .release_num = 0x0200,  // 发布号
      .manufacturer = "OneKey Limited",  // 制造商
      .product = "OneKey Pro",  // 产品名
      .serial_number = "000000000000000000000000",  // 序列号
      .interface = "Bootloader Interface",  // 接口名
      .usb21_enabled = sectrue,  // USB 2.1使能
      .usb21_landing = usb21_landing,  // USB 2.1登陆页面
  };

  static char serial[USB_SIZ_STRING_SERIAL];  // 定义序列号缓冲区

  if (sectrue == get_device_serial(serial, sizeof(serial))) {  // 如果获取序列号成功
    dev_info.serial_number = serial;  // 设置序列号
  }

  static uint8_t rx_buffer[USB_PACKET_SIZE];  // 定义接收缓冲区

  static const usb_webusb_info_t webusb_info = {  // 定义WebUSB信息
      .iface_num = USB_IFACE_NUM,  // 接口号
      .ep_in = USB_EP_DIR_IN | 0x01,  // 输入端点
      .ep_out = USB_EP_DIR_OUT | 0x01,  // 输出端点
      .subclass = 0,  // 子类
      .protocol = 0,  // 协议
      .max_packet_len = sizeof(rx_buffer),  // 最大包长度
      .rx_buffer = rx_buffer,  // 接收缓冲区
      .polling_interval = 1,  // 轮询间隔
  };

  usb_init(&dev_info);  // 初始化USB设备

  ensure(usb_webusb_add(&webusb_info), NULL);  // 添加WebUSB接口

  // usb start after vbus connected  // USB在VBUS连接后启动
  // usb_start();  // 启动USB
}

static void usb_switch(void) {  // USB切换函数
  static bool usb_opened = false;  // 定义USB打开标志
  static uint32_t counter0 = 0, counter1 = 0;  // 定义计数器

  if (usb_3320_host_connected()) {  // 如果USB主机已连接
    counter0++;  // 计数器0增加
    counter1 = 0;  // 计数器1清零
    if (counter0 > 5) {  // 如果计数器0大于5
      counter0 = 0;  // 计数器0清零
      if (!usb_opened) {  // 如果USB未打开
        usb_start();  // 启动USB
        usb_opened = true;  // 设置USB打开标志
      }
    }
  } else {  // 如果USB主机未连接
    counter0 = 0;  // 计数器0清零
    counter1++;  // 计数器1增加
    if (counter1 > 5) {  // 如果计数器1大于5
      counter1 = 0;  // 计数器1清零
      if (usb_opened) {  // 如果USB已打开
        usb_stop();  // 停止USB
        usb_opened = false;  // 清除USB打开标志
      }
    }
  }
}

static void charge_switch(void) {  // 充电切换函数
  static bool charge_configured = false;  // 定义充电配置标志
  static bool charge_enabled = false;  // 定义充电使能标志

  if (!ble_charging_state()) {  // 如果未在充电状态
    ble_cmd_req(BLE_PWR, BLE_PWR_CHARGING);  // 请求充电
    return;  // 返回
  }

  if (ble_get_charge_type() == CHARGE_TYPE_USB) {  // 如果是USB充电
    if (!charge_enabled || !charge_configured) {  // 如果充电未使能或未配置
      charge_configured = true;  // 设置配置标志
      charge_enabled = true;  // 设置使能标志
      ble_cmd_req(BLE_PWR, BLE_PWR_CHARGE_ENABLE);  // 使能充电
    }
  } else {  // 如果不是USB充电
    if (charge_enabled || !charge_configured) {  // 如果充电已使能或未配置
      charge_configured = true;  // 设置配置标志
      charge_enabled = false;  // 清除使能标志
      ble_cmd_req(BLE_PWR, BLE_PWR_CHARGE_DISABLE);  // 禁用充电
    }
  }
}

void bootloader_usb_loop_tiny(void) {  // 小型USB循环函数
  if (!usb_tiny_enable) {  // 如果未使能tiny模式
    return;  // 直接返回
  }

  uint8_t buf[USB_PACKET_SIZE];  // 定义缓冲区
  bool cmd_received = false;  // 定义命令接收标志
  if (USB_PACKET_SIZE == spi_slave_poll(buf)) {  // 如果从SPI接收到数据
    host_channel = CHANNEL_SLAVE;  // 设置主机通道为从机
    cmd_received = true;  // 设置命令接收标志
  } else if (USB_PACKET_SIZE ==  // 如果从USB接收到数据
             usb_webusb_read(USB_IFACE_NUM, buf, USB_PACKET_SIZE)) {
    host_channel = CHANNEL_USB;  // 设置主机通道为USB
    cmd_received = true;  // 设置命令接收标志
  }
  if (cmd_received) {  // 如果接收到命令
    if (buf[0] != '?' || buf[1] != '#' || buf[2] != '#') {  // 如果不是有效命令
      return;  // 返回
    }
    if (buf[3] == 0 && buf[4] == 0) {  // 如果是获取特性命令
      send_msg_features_simple(USB_IFACE_NUM);  // 发送简单特性信息
    } else {  // 如果是其他命令
      send_failure(USB_IFACE_NUM, FailureType_Failure_ProcessError,  // 发送失败信息
                   format_progress_value("Update mode"));  // 格式化进度值
    }
  }
}

void enable_usb_tiny_task(bool init_usb) {  // 使能USB tiny任务函数
  if (init_usb) {  // 如果需要初始化USB
    usb_init_all(secfalse);  // 初始化所有USB
    usb_start();  // 启动USB
  }
  usb_tiny_enable = true;  // 使能USB tiny模式
}

void disable_usb_tiny_task(void) {  // 禁用USB tiny任务函数
  usb_tiny_enable = false;  // 禁用USB tiny模式
}

static secbool bootloader_usb_loop(const vendor_header* const vhdr,  // 引导程序USB循环函数
                                   const image_header* const hdr) {
  // if both are NULL, we don't have a firmware installed  // 如果两者都为NULL,说明未安装固件
  // let's show a webusb landing page in this case  // 这种情况下显示WebUSB登陆页面
  usb_init_all((vhdr == NULL && hdr == NULL) ? sectrue : secfalse);  // 初始化所有USB

  uint8_t buf[USB_PACKET_SIZE];  // 定义缓冲区
  int r;  // 定义返回值

  for (;;) {  // 无限循环
    while (true) {  // 内部循环
      ble_uart_poll();  // 轮询蓝牙UART

      usb_switch();  // USB切换

      charge_switch();  // 充电切换

      // check bluetooth  // 检查蓝牙
      if (USB_PACKET_SIZE == spi_slave_poll(buf)) {  // 如果从SPI接收到数据
        host_channel = CHANNEL_SLAVE;  // 设置主机通道为从机
        break;  // 跳出内部循环
      }
      // check usb  // 检查USB
      // check bluetooth
      if (USB_PACKET_SIZE == spi_slave_poll(buf)) {
        host_channel = CHANNEL_SLAVE;
        break;
      }
      // check usb
      else if (USB_PACKET_SIZE == usb_webusb_read_blocking(
                                      USB_IFACE_NUM, buf, USB_PACKET_SIZE, 5)) {
        host_channel = CHANNEL_USB;
        break;
      }
      // no packet, check if power button pressed
      // else if ( ble_power_button_state() == 1 ) // short press
      else if (ble_power_button_state() == 2)  // long press
      {
        // give a way to go back to bootloader home page
        if (get_ui_bootloader_page_current() != 0) {
          ble_power_button_state_clear();
          ui_progress_bar_visible_clear();
          ui_fadeout();
          ui_bootloader_first(NULL);
          ui_fadein();
        }
        memzero(buf, USB_PACKET_SIZE);
        continue;
      }
      // no packet, no pwer button pressed
      else {
        ui_bootloader_page_switch(hdr);
        static uint32_t tickstart = 0;
        if ((HAL_GetTick() - tickstart) >= 1000) {
          ui_statusbar_update();
          tickstart = HAL_GetTick();
        }
        continue;
      }
    }

    uint16_t msg_id;
    uint32_t msg_size;
    if (sectrue != msg_parse_header(buf, &msg_id, &msg_size)) {
      // invalid header -> discard
      continue;
    }

    switch (msg_id) {
      case MSG_NAME_TO_ID(Initialize):  // Initialize
        process_msg_Initialize(USB_IFACE_NUM, msg_size, buf, vhdr, hdr);
        break;
      case MSG_NAME_TO_ID(Ping):  // Ping
        process_msg_Ping(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(WipeDevice):  // WipeDevice
        ui_fadeout();
        ui_wipe_confirm(hdr);
        ui_fadein();
        int response = ui_input_poll(INPUT_CONFIRM | INPUT_CANCEL, true);
        if (INPUT_CANCEL == response) {
          ui_fadeout();
          ui_bootloader_first(hdr);
          ui_fadein();
          send_user_abort(USB_IFACE_NUM, "Wipe cancelled");
          break;
        }
        ui_fadeout();
        ui_screen_wipe();
        ui_fadein();
        r = process_msg_WipeDevice(USB_IFACE_NUM, msg_size, buf);
        if (r < 0) {  // error
          ui_fadeout();
          ui_screen_fail();
          ui_fadein();
          usb_stop();
          usb_deinit();
          while (!touch_click()) {
          }
          restart();
          return secfalse;  // shutdown
        } else {            // success
          ui_fadeout();
          ui_screen_wipe_done();
          ui_fadein();
          usb_stop();
          usb_deinit();
          while (!ui_input_poll(INPUT_NEXT, true)) {
          }
          restart();
          return secfalse;  // shutdown
        }
        break;
      case MSG_NAME_TO_ID(GetFeatures):  // GetFeatures
        process_msg_GetFeatures(USB_IFACE_NUM, msg_size, buf, vhdr, hdr);
        break;
      case MSG_NAME_TO_ID(Reboot):  // Reboot
        process_msg_Reboot(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(FirmwareUpdateEmmc):  // FirmwareUpdateEmmc
        r = process_msg_FirmwareUpdateEmmc(USB_IFACE_NUM, msg_size, buf);
        if (r < 0 && r != -4) {  // error
          ui_fadeout();
          ui_screen_fail();
          ui_fadein();
          while (!touch_click()) {
            hal_delay(10);
          }
          bluetooth_reset();
          // make sure we have latest bluetooth status (and wait for bluetooth
          // become ready)
          ble_refresh_dev_info();
          reboot_to_boot();
          return secfalse;  // shutdown
        }
        break;
      case MSG_NAME_TO_ID(EmmcFixPermission):  // EmmcFixPermission
        process_msg_EmmcFixPermission(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcPathInfo):  // EmmcPathInfo
        process_msg_EmmcPathInfo(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcFileRead):  // EmmcFileRead
        process_msg_EmmcFileRead(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcFileWrite):  // EmmcFileWrite
        process_msg_EmmcFileWrite(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcFileDelete):  // EmmcFileDelete
        process_msg_EmmcFileDelete(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcDirList):  // EmmcDirList
        process_msg_EmmcDirList(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcDirMake):  // EmmcDirMake
        process_msg_EmmcDirMake(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcDirRemove):  // EmmcDirRemove
        process_msg_EmmcDirRemove(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(OnekeyGetFeatures):  // OnekeyGetFeatures
        process_msg_OnekeyGetFeatures(USB_IFACE_NUM, msg_size, buf, vhdr, hdr);
        break;
      default:
        process_msg_unknown(USB_IFACE_NUM, msg_size, buf);
        break;
    }
  }
}

secbool bootloader_usb_loop_factory(const vendor_header* const vhdr,
                                    const image_header* const hdr) {
  // if both are NULL, we don't have a firmware installed
  // let's show a webusb landing page in this case
  usb_init_all((vhdr == NULL && hdr == NULL) ? sectrue : secfalse);

  usb_start();

  uint8_t buf[USB_PACKET_SIZE];
  int r;

  for (;;) {
    r = usb_webusb_read_blocking(USB_IFACE_NUM, buf, USB_PACKET_SIZE,
                                 USB_TIMEOUT);
    if (r != USB_PACKET_SIZE) {
      continue;
    }
    host_channel = CHANNEL_USB;

    uint16_t msg_id;
    uint32_t msg_size;
    if (sectrue != msg_parse_header(buf, &msg_id, &msg_size)) {
      // invalid header -> discard
      continue;
    }

    switch (msg_id) {
      case MSG_NAME_TO_ID(Initialize):  // Initialize
        process_msg_Initialize(USB_IFACE_NUM, msg_size, buf, vhdr, hdr);
        break;
      case MSG_NAME_TO_ID(Ping):  // Ping
        process_msg_Ping(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(GetFeatures):  // GetFeatures
        process_msg_GetFeatures(USB_IFACE_NUM, msg_size, buf, vhdr, hdr);
        break;
      case MSG_NAME_TO_ID(DeviceInfoSettings):  // DeviceInfoSettings
        process_msg_DeviceInfoSettings(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(GetDeviceInfo):  // GetDeviceInfo
        process_msg_GetDeviceInfo(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(WriteSEPrivateKey):  // WriteSEPrivateKey
        process_msg_WriteSEPrivateKey(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(ReadSEPublicKey):  // ReadSEPublicKey
        process_msg_ReadSEPublicKey(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(WriteSEPublicCert):  // WriteSEPublicCert
        process_msg_WriteSEPublicCert(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(ReadSEPublicCert):  // ReadSEPublicCert
        process_msg_ReadSEPublicCert(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(SESignMessage):  // SESignMessage
        process_msg_SESignMessage(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(Reboot):  // Reboot
        process_msg_Reboot(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(FirmwareUpdateEmmc):  // FirmwareUpdateEmmc
        process_msg_FirmwareUpdateEmmc(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcFixPermission):  // EmmcFixPermission
        process_msg_EmmcFixPermission(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcPathInfo):  // EmmcPathInfo
        process_msg_EmmcPathInfo(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcFileRead):  // EmmcFileRead
        process_msg_EmmcFileRead(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcFileWrite):  // EmmcFileWrite
        process_msg_EmmcFileWrite(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcFileDelete):  // EmmcFileDelete
        process_msg_EmmcFileDelete(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcDirList):  // EmmcDirList
        process_msg_EmmcDirList(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcDirMake):  // EmmcDirMake
        process_msg_EmmcDirMake(USB_IFACE_NUM, msg_size, buf);
        break;
      case MSG_NAME_TO_ID(EmmcDirRemove):  // EmmcDirRemove
        process_msg_EmmcDirRemove(USB_IFACE_NUM, msg_size, buf);
        break;
      default:
        process_msg_unknown(USB_IFACE_NUM, msg_size, buf);
        break;
    }
  }
  return sectrue;
}

#if PRODUCTION

// protection against bootloader downgrade
static void check_bootloader_version(void) {
  uint8_t bits[FLASH_OTP_BLOCK_SIZE];
  for (int i = 0; i < FLASH_OTP_BLOCK_SIZE * 8; i++) {
    if (i < VERSION_MONOTONIC) {
      bits[i / 8] &= ~(1 << (7 - (i % 8)));
    } else {
      bits[i / 8] |= (1 << (7 - (i % 8)));
    }
  }
  ensure(flash_otp_write(FLASH_OTP_BLOCK_BOOTLOADER_VERSION, 0, bits,
                         FLASH_OTP_BLOCK_SIZE),
         NULL);

  uint8_t bits2[FLASH_OTP_BLOCK_SIZE];
  ensure(flash_otp_read(FLASH_OTP_BLOCK_BOOTLOADER_VERSION, 0, bits2,
                        FLASH_OTP_BLOCK_SIZE),
         NULL);

  ensure(sectrue * (0 == memcmp(bits, bits2, FLASH_OTP_BLOCK_SIZE)),
         "Bootloader downgraded");
}

#endif

static bool enter_boot_forced(void) {
  return *BOOT_TARGET_FLAG_ADDR == BOOT_TARGET_BOOTLOADER;
}

static BOOT_TARGET decide_boot_target(vendor_header* const vhdr,
                                      image_header* const hdr,
                                      secbool* vhdr_valid, secbool* hdr_valid,
                                      secbool* code_valid) {
  // get boot target flag
  BOOT_TARGET boot_target = *BOOT_TARGET_FLAG_ADDR;  // cache flag
  *BOOT_TARGET_FLAG_ADDR = BOOT_TARGET_NORMAL;       // consume(reset) flag

  // verify at the beginning to ensure results are populated
  char err_msg[64];
  set_handle_flash_ecc_error(sectrue);
  secbool all_good = verify_firmware(vhdr, hdr, vhdr_valid, hdr_valid,
                                     code_valid, err_msg, sizeof(err_msg));
  set_handle_flash_ecc_error(secfalse);

  // if boot target already set to this level, no more checks
  if (boot_target == BOOT_TARGET_BOOTLOADER) return boot_target;

  // check se status
  if (se_get_state() != 0) {
    boot_target = BOOT_TARGET_BOOTLOADER;
    return boot_target;
  }

  // check bluetooth state
  if (bluetooth_detect_dfu()) {
    boot_target = BOOT_TARGET_BOOTLOADER;
    return boot_target;
  }

  // check firmware
  if (all_good != sectrue) {
    boot_target = BOOT_TARGET_BOOTLOADER;
    return boot_target;
  }

  // all check passed, manual set, since default ram value will be random
  boot_target = BOOT_TARGET_NORMAL;

  return boot_target;
}

int main(void) {
  SystemCoreClockUpdate();  // 更新系统时钟频率
  dwt_init();  // 初始化DWT(数据观察跟踪)单元

  mpu_config_boardloader(sectrue, secfalse);  // 配置板级引导程序的MPU(内存保护单元)
  mpu_config_bootloader(sectrue, sectrue);    // 配置引导程序的MPU
  mpu_config_firmware(sectrue, secfalse);     // 配置固件的MPU
  mpu_config_base();  // 配置基本MPU设置(最后配置,因为包含拒绝访问层且MPU可能已在运行)
  mpu_ctrl(sectrue);  // 确保MPU已启用

  // 禁用所有外部通信或用户输入中断
  // 稍后通过调用它们的init函数重新启用
  // 蓝牙串口
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

  __enable_irq();         // 启用普通中断
  __enable_fault_irq();   // 启用故障中断

  lcd_ltdc_dsi_disable();  // 禁用LCD控制器和DSI
  sdram_reinit();         // 重新初始化SDRAM
  // lcd_para_init(DISPLAY_RESX, DISPLAY_RESY, LCD_PIXEL_FORMAT_RGB565);  // LCD参数初始化(已注释)
  lcd_ltdc_dsi_enable();   // 启用LCD控制器和DSI
  lcd_pwm_init();         // 初始化LCD背光PWM
  touch_init();           // 初始化触摸屏

  adc_init();            // 初始化ADC

  // 保持屏幕显示但覆盖引导条
  // display_clear();    // 清除显示(已注释)
  display_bar_radius(160, 352, 160, 4, COLOR_BLACK, COLOR_BLACK, 2);  // 显示黑色圆角条

  // 故障处理程序
  bus_fault_enable();    // 在这里启用因为需要用户界面

  // 存储设备初始化
  ensure_emmcfs(emmc_fs_init(), "emmc_fs_init");           // 确保eMMC文件系统初始化
  ensure_emmcfs(emmc_fs_mount(true, false), "emmc_fs_mount");  // 确保eMMC文件系统挂载
  if (get_hw_ver() < HW_VER_3P0A) {                       // 如果硬件版本低于3.0A
    qspi_flash_init();                                    // 初始化QSPI闪存
    qspi_flash_config();                                  // 配置QSPI闪存
    qspi_flash_memory_mapped();                          // 设置QSPI闪存为内存映射模式
  }

  // 蓝牙/电源管理初始化
  ble_usart_init();     // 初始化蓝牙UART
  spi_slave_init();     // 初始化SPI从机
  ble_reset();         // 重置蓝牙模块

  // 其他/反馈初始化
  random_delays_init(); // 初始化随机延迟

  // 由于使用相同的I2C总线,在任何通信之前都需要上电
  camera_io_init();    // 初始化相机IO
  thd89_io_init();     // 初始化THD89 IO

  // 安全元件
  thd89_reset();       // 重置THD89
  thd89_init();        // 初始化THD89

  uint8_t se_mode = se_get_state();  // 获取安全元件状态
  // 所有安全元件处于应用模式
  if (se_mode == 0) {
    device_para_init();  // 初始化设备参数
  }

  if ((!device_serial_set() || !se_has_cerrificate()) && se_mode == 0) {  // 如果序列号未设置或无证书且SE处于应用模式
    display_clear();                    // 清除显示
    device_set_factory_mode(true);      // 设置工厂模式
    ui_bootloader_factory();            // 显示工厂模式UI
    if (bootloader_usb_loop_factory(NULL, NULL) != sectrue) {  // 进入工厂模式USB循环
      return 1;
    }
  }

#if !PRODUCTION  // 非生产环境

  // if (!device_serial_set()) {
  //   write_dev_dummy_serial();
  // }
  UNUSED(write_dev_dummy_serial);  // 防止未使用警告

  // if (!se_has_cerrificate()) {
  //   write_dev_dummy_cert();
  // }
  UNUSED(write_dev_dummy_cert);    // 防止未使用警告

  // if(!device_overwrite_serial("PRA50I0000 QA"))
  // {
  //   dbgprintf_Wait("serial overwrite failed!");
  // }

  // device_test(true);

  device_backup_otp(false);        // 备份OTP数据
  // device_restore_otp();         // 恢复OTP数据(已注释)

#endif

#if PRODUCTION  // 生产环境

  // 检查引导程序降级
  check_bootloader_version();

#endif

  if (!enter_boot_forced()) {                    // 如果不是强制进入引导模式
    check_firmware_from_file(USB_IFACE_NULL);    // 检查固件文件
  }

  vendor_header vhdr;              // 厂商头
  image_header hdr;                // 镜像头
  secbool vhdr_valid = secfalse;   // 厂商头有效标志
  secbool hdr_valid = secfalse;    // 镜像头有效标志
  secbool code_valid = secfalse;   // 代码有效标志

  BOOT_TARGET boot_target =        // 决定启动目标
      decide_boot_target(&vhdr, &hdr, &vhdr_valid, &hdr_valid, &code_valid);
  // boot_target = BOOT_TARGET_BOOTLOADER;  // 强制设置启动目标(已注释)

  if (boot_target == BOOT_TARGET_BOOTLOADER) {   // 如果启动目标是引导程序
    display_clear();                            // 清除显示

    if (sectrue == vhdr_valid && sectrue == hdr_valid) {  // 如果厂商头和镜像头都有效
      ui_bootloader_first(&hdr);                         // 显示首次引导UI(带头信息)
      if (bootloader_usb_loop(&vhdr, &hdr) != sectrue) {  // 进入USB循环
        return 1;
      }
    } else {
      ui_bootloader_first(NULL);                        // 显示首次引导UI(无头信息)
      if (bootloader_usb_loop(NULL, NULL) != sectrue) {  // 进入USB循环
        return 1;
      }
    }
  } else if (boot_target == BOOT_TARGET_NORMAL) {  // 如果启动目标是正常模式
    // 验证蓝牙密钥
    device_verify_ble();

    // 如果所有VTRUST标志都未设置 = 完全信任 => 跳过该过程
    if ((vhdr.vtrust & VTRUST_ALL) != VTRUST_ALL) {
      // ui_fadeout();  // 无淡出效果 - 我们从黑屏开始
      ui_screen_boot(&vhdr, &hdr);   // 显示启动屏幕
      ui_fadein();                   // 淡入效果

      int delay = (vhdr.vtrust & VTRUST_WAIT) ^ VTRUST_WAIT;  // 计算等待时间
      if (delay > 1) {                                       // 如果等待时间大于1秒
        while (delay > 0) {
          ui_screen_boot_wait(delay);                       // 显示等待倒计时
          hal_delay(1000);                                 // 延迟1秒
          delay--;
        }
      } else if (delay == 1) {                             // 如果等待时间为1秒
        hal_delay(1000);                                  // 延迟1秒
      }

      if ((vhdr.vtrust & VTRUST_CLICK) == 0) {            // 如果需要点击确认
        ui_screen_boot_click();                           // 显示点击提示
        int counter = 0;
        while (touch_read() == 0) {                       // 等待触摸
          hal_delay(10);
          counter++;
          if (counter > 200) {                           // 超时检查(2秒)
            break;
          }
        }
      }
    }

    display_clear();                // 清除显示
    bus_fault_disable();            // 禁用总线故障处理

    // 启用固件区域
    mpu_config_firmware(sectrue, sectrue);  // 配置固件MPU权限

    jump_to(FIRMWARE_START + vhdr.hdrlen + hdr.hdrlen);  // 跳转到固件起始位置
  }

  error_shutdown("Internal error", "Boot target invalid", "Tap to restart.",  // 显示错误信息并关机
                 "If the issue persists, contact support.");
  return -1;
}
