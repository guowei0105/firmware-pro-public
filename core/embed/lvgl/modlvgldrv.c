#include <stdbool.h>
#include <stdint.h>
#include "../../vendor/lvgl_mp/driver/include/common.h"
#include "lv_conf.h"
#include "lvgl.h"
#include "py/mphal.h"
#include "py/runtime.h"

#include "mipi_lcd.h"
#include "sdram.h"
#include "touch.h"

// Forward declaration for second layer animation
extern void lcd_ensure_second_layer(void);

lv_color_t *fb[2] = {NULL, NULL};

static mp_obj_t mp_disp_drv_framebuffer(mp_obj_t n_obj) {
  int n = mp_obj_get_int(n_obj) - 1;

  if (n < 0 || n > 1) {
    return mp_const_none;
  }
#ifdef LVGL_DOUBLE_BUFFER
  if (fb[n] == NULL) {
    static lv_color_t *lv_disp_buf =
        (lv_color_t *)(FMC_SDRAM_LTDC_BUFFER_ADDRESS);
    fb[n] = MP_STATE_PORT(disp_drv_fb[n]) = lv_disp_buf + 480 * 800 * n;
  }
#else
  if (n == 1) {
    // single buffer mode, the second buffer is not used.
    return mp_const_none;
  }
  if (fb[n] == NULL) {
    static lv_color_t *lv_disp_buf =
        (lv_color_t *)(FMC_SDRAM_LTDC_BUFFER_ADDRESS);
    fb[n] = MP_STATE_PORT(disp_drv_fb[n]) = lv_disp_buf + 480 * 800;
  }
#endif
  return mp_obj_new_bytearray_by_ref(sizeof(lv_color_t) * 480 * 800,
                                     (void *)fb[n]);
}

static void mp_disp_drv_flush(lv_disp_drv_t *disp_drv, const lv_area_t *area,
                              lv_color_t *color_p) {
#ifdef LVGL_DOUBLE_BUFFER
  lcd_set_src_addr((uint32_t)color_p);
#else
  dma2d_copy_buffer((uint32_t *)color_p, (uint32_t *)lcd_get_src_addr(),
                    area->x1, area->y1, area->x2 - area->x1 + 1,
                    area->y2 - area->y1 + 1);
  
  // In single buffer mode, we need to manually call second layer animation
  // since lcd_set_src_addr is not called
  static uint32_t flush_counter = 0;
  flush_counter++;
  if (flush_counter % 2 == 0) {  // Every other flush to maintain smooth animation
    lcd_ensure_second_layer();
  }
#endif
  lv_disp_flush_ready(disp_drv);
}

static bool mp_ts_read(struct _lv_indev_drv_t *indev_drv,
                       lv_indev_data_t *data) {
  int pos = touch_read();

  /* Save the pressed coordinates and the state */
  if (pos & TOUCH_START || pos & TOUCH_MOVE) {
    data->state = LV_INDEV_STATE_PR;
  } else if (pos & TOUCH_END) {
    data->state = LV_INDEV_STATE_REL;
  } else {
    data->state = LV_INDEV_STATE_REL;
  }

  /* Set the last pressed coordinates */
  data->point.x = (pos >> 12) & 0xfff;
  data->point.y = pos & 0xfff;

  return false;
}

STATIC MP_DEFINE_CONST_FUN_OBJ_1(mp_disp_drv_framebuffer_obj,
                                 mp_disp_drv_framebuffer);
DEFINE_PTR_OBJ(mp_disp_drv_flush);
DEFINE_PTR_OBJ(mp_ts_read);

STATIC const mp_rom_map_elem_t lvgl_drv_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_lvgldrv)},
    {MP_ROM_QSTR(MP_QSTR_flush), MP_ROM_PTR(&PTR_OBJ(mp_disp_drv_flush))},
    {MP_ROM_QSTR(MP_QSTR_framebuffer),
     MP_ROM_PTR(&PTR_OBJ(mp_disp_drv_framebuffer))},
    {MP_ROM_QSTR(MP_QSTR_ts_read), MP_ROM_PTR(&PTR_OBJ(mp_ts_read))},
};

STATIC MP_DEFINE_CONST_DICT(mp_module_lvgl_drv_globals, lvgl_drv_globals_table);

const mp_obj_module_t mp_module_lvgldrv = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&mp_module_lvgl_drv_globals};

MP_REGISTER_MODULE(MP_QSTR_lvgldrv, mp_module_lvgldrv, 1);
