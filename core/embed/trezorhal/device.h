#ifndef _DEVICE_H_
#define _DEVICE_H_

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#define PRODUCT_STRING "OneKey Pro"
#define SE_NAME "THD89"

typedef struct __attribute__((packed)) {
  char product[2];
  char hardware[2];
  char color;
  char factory[2];
  char utc[10];
  char serial[7];
} DeviceSerialNo;

typedef struct __attribute__((packed)) {
  char serial[32];
  char cpu_info[16];
  char pre_firmware[16];
  uint32_t st_id[3];
  bool random_key_init;
  uint8_t random_key[32];
} DeviceInfomation;

typedef struct {
  uint32_t flag;
  uint32_t time;
  uint32_t touch;
} test_result;

void device_set_factory_mode(bool mode);
bool device_is_factory_mode(void);
void device_para_init(void);
bool device_serial_set(void);
bool device_set_serial(char *dev_serial);
bool device_cpu_firmware_set(void);
bool device_set_cpu_firmware(char *cpu_info, char *firmware_ver);
bool device_get_cpu_firmware(char **cpu_info, char **firmware_ver);
bool device_get_serial(char **serial);
char *device_get_se_config_version(void);
void device_get_enc_key(uint8_t key[32]);

void device_verify_ble(void);

void device_test(bool force);
void device_burnin_test(bool force);
void device_burnin_test_clear_flag(void);
void device_generate_trng_data(void);
;
#if !PRODUCTION
bool device_backup_otp(bool overwrite);
bool device_restore_otp();
bool device_overwrite_serial(char *dev_serial);
#endif

#endif
