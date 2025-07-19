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

#ifndef __BOOTUI_H__
#define __BOOTUI_H__

#include "image.h"
#include "secbool.h"
#include "stdbool.h"

char* format_progress_value(char* prefix);

const char* format_ver(const char* format, uint32_t version);
void ui_screen_boot(const vendor_header* const vhdr,
                    const image_header* const hdr);
void ui_screen_boot_wait(int wait_seconds);
void ui_screen_boot_click(void);

void ui_screen_welcome_first(void);
void ui_screen_welcome_second(void);
void ui_screen_welcome_third(void);

void ui_bootloader_factory(void);

void ui_screen_firmware_info(const vendor_header* const vhdr,
                             const image_header* const hdr);
void ui_screen_firmware_fingerprint(const image_header* const hdr);

void ui_screen_install_confirm_upgrade(const vendor_header* const vhdr,
                                       const image_header* const hdr);
void ui_screen_install_confirm_newvendor_or_downgrade_wipe(char* new_version);
void ui_screen_install_start(void);
void ui_screen_install_progress_erase(int pos, int len);
void ui_screen_install_progress_upload(int pos);

void ui_screen_confirm(char* title, char* note_l1, char* note_l2, char* note_l3,
                       char* note_l4);
void ui_screen_progress_bar_init(char* title, char* notes, int progress);
void ui_screen_progress_bar_prepare(char* title, char* notes);
void ui_screen_progress_bar_update(char* msg_status, char* notes, int progress);

void ui_screen_wipe_confirm(void);
void ui_screen_wipe(void);
void ui_screen_wipe_progress(int pos, int len);
void ui_screen_wipe_done(void);

void ui_screen_done(int restart_seconds, secbool full_redraw);
void ui_screen_success(char* title, char* notes);
void ui_screen_fail(void);

void ui_fadein(void);
void ui_fadeout(void);

// clang-format off
#define INPUT_CANCEL 0x01        // Cancel button
#define INPUT_CONFIRM 0x02       // Confirm button
#define INPUT_LONG_CONFIRM 0x04  // Long Confirm button
#define INPUT_INFO 0x08          // Info icon
#define INPUT_NEXT 0x10          // Next icon
#define INPUT_PREVIOUS 0x20      // Previous icon
#define INPUT_RESTART 0x40       // Restart icon
#define INPUT_BOOT_VERSION_TEXT 0x80     // Boot Version
#define INPUT_BUILD_ID_TEXT 0x0100         // Build ID
#define INPUT_MENU_DEVICE_INFO 0x0200      // Device Info menu item
#define INPUT_MENU_GENERATE_TRNG 0x0400    // Generate TRNG menu item
#define INPUT_MENU_REBOOT 0x0800           // Reboot Device menu item
#define INPUT_MENU_FACTORY_RESET 0x1000    // Factory Reset menu item

// clang-format on

void ui_statusbar_update(void);
int ui_user_input(int zones);
int ui_input_poll(int zones, bool poll);
void ui_bootloader_simple(void);
void ui_bootloader_first(const image_header* const hdr);
void ui_bootloader_view_details(const image_header* const hdr);
void ui_wipe_confirm(const image_header* const hdr);
void ui_show_version_info(int y, char* current_ver, char* new_ver);
void ui_screen_install_title_clear(void);
void ui_install_confirm(image_header* current_hdr,
                        const image_header* const new_hdr);
void ui_install_ble_confirm(void);
void ui_install_thd89_confirm(const char* old_ver, const char* boot_ver);
void ui_update_info_show(update_info_t update_info);
void ui_install_progress(image_header* current_hdr,
                         const image_header* const new_hdr);
void ui_bootloader_page_switch(const image_header* const hdr);
int get_ui_bootloader_page_current(void);
void ui_bootloader_factory_reset_confirm(void);
#endif
