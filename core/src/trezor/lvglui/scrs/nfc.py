from trezorio import nfc

from trezor import io, loop
from trezor.crypto import bip39

from ..i18n import gettext as _, keys as i18n_keys
from . import lv
from .common import FullSizeWindow

LITE_CARD_ERROR_REPONSE = -1
LITE_CARD_SUCCESS_REPONSE = 0
LITE_CARD_ERROR = 1
LITE_CARD_FIND = 2
LITE_CARD_CONNECT_FAILURE = 3
LITE_CARD_NOT_SAME = 4
LITE_CARD_HAS_BEEN_RESET = 5
LITE_CARD_PIN_ERROR = 6
LITE_CARD_NO_BACKUP = 8
LITE_CARD_UNSUPPORTED_WORD_COUNT = 9
LITE_CARD_DISCONNECT = 99
LITE_CARD_OPERATE_SUCCESS = 2
LITE_CARD_SUCCESS_STATUS = b"\x90\x00"
LITE_CARD_DISCONECT_STATUS = b"\x99\x99"

CMD_GET_SERIAL_NUMBER = b"\x80\xcb\x80\x00\x05\xdf\xff\x02\x81\x01"
CMD_OLD_APPLET = b"\x00\xa4\x04\x00\x08\xD1\x56\x00\x01\x32\x83\x40\x01"
CMD_NEW_APPLET = (
    b"\x00\xa4\x04\x00\x0E\x6F\x6E\x65\x6B\x65\x79\x2E\x62\x61\x63\x6B\x75\x70\x01"
)
CMD_GET_PIN_RETRY_COUNT = b"\x80\xcb\x80\x00\x05\xdf\xff\x02\x81\x02"
CMD_RESET_CARD = b"\x80\xcb\x80\x00\x05\xdf\xfe\x02\x82\x05"
CMD_GET_PIN_STATUS = b"\x80\xcb\x80\x00\x05\xdf\xff\x02\x81\x05"
CMD_SELECT_PRIMARY_SAFETY = b"\x00\xa4\x04\x00"
CMD_EXPORT_DATA = b"\x80\x4c\x00\x00"
CMD_BACKUP_DATA = b"\x80\x3c\x00\x00"
CMD_SETUP_NEW_PIN = b"\x80\xcb\x80\x00\x0e\xdf\xfe\x0b\x82\x04\x08\x00\x06"
CMD_GET_BACKUP_STATUS = b"\x80\x6A\x00\x00"
CMD_VERIFY_PIN = b"\x84\x20\x00\x00\x07\x06"
CMD_SET_CARD_LOCK = b"\x84\x21\x00\x00\x08\x06"


async def handle_sw1sw2_connect_error(self):
    self.channel.publish(LITE_CARD_CONNECT_FAILURE)
    await loop.sleep(180)
    self.clean()
    self.destroy()


def perform_ticks(motor_ctl, num_ticks):
    for _ticks in range(num_ticks):
        motor_ctl.tick()


async def handle_cleanup(self, data):
    self.channel.publish(data)
    await loop.sleep(180)
    self.clean()
    self.destroy()


async def run_card_search(self):
    while self.searching:
        await loop.sleep(1000)
        if nfc.poll_card():
            MOTOR_CTL = io.MOTOR()
            perform_ticks(MOTOR_CTL, 80)
            self.searching = False
            self.channel.publish(LITE_CARD_FIND)
            self.clean()
            self.destroy()
            return
        else:
            pass


async def get_card_num(self):
    card_num = None
    card_num, sw1sw2 = nfc.send_recv(CMD_GET_SERIAL_NUMBER)
    if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return card_num, LITE_CARD_ERROR_REPONSE
    elif sw1sw2 == LITE_CARD_SUCCESS_STATUS:
        pass
    else:
        _, sw1sw2 = nfc.send_recv(CMD_NEW_APPLET)
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return card_num, LITE_CARD_ERROR_REPONSE
        card_num, sw1sw2 = nfc.send_recv(CMD_GET_SERIAL_NUMBER)
        print("card_num:",card_num)
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return card_num, LITE_CARD_ERROR_REPONSE

    if isinstance(card_num, bytes):
        card_num_str = card_num.decode("utf-8")
    else:
        card_num_str = str(card_num)

    return card_num_str, LITE_CARD_SUCCESS_REPONSE


def get_card_type(card_num_str):
    card_type = "NEW"
    if len(card_num_str) >= 5:
        if card_num_str[4] == "T" and card_num_str[5] == "2":
            card_type = "OLD"
        elif card_num_str[4] == "B" and card_num_str[5] == "A":
            card_type = "NEW"
    return card_type


async def check_card_data(self):

    card_num, status = await get_card_num(self)
    if status == LITE_CARD_ERROR_REPONSE:
        return
    pinresp, pinsw1sw2 = nfc.send_recv(CMD_GET_PIN_STATUS)
    if pinsw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return
    if pinsw1sw2 == LITE_CARD_SUCCESS_STATUS and pinresp == b"\x02":
        if card_num is not None:
            data = "2" + str(card_num)
            await handle_cleanup(self, data)
            return
    elif pinsw1sw2 == LITE_CARD_SUCCESS_STATUS:
        if card_num is not None:
            data = "3" + str(card_num)
            await handle_cleanup(self, data)
            return
    else:
        await handle_cleanup(self, LITE_CARD_ERROR_REPONSE)
        return


async def check_best_try_restcard(self):
    numresp, numsw1sw2 = nfc.send_recv(CMD_GET_PIN_RETRY_COUNT)
    if numsw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return LITE_CARD_ERROR_REPONSE

    if numresp in [b"\x01", b"\x00"] and numsw1sw2 == LITE_CARD_SUCCESS_STATUS:

        _, restsw1sw2 = nfc.send_recv(CMD_RESET_CARD, True)
        if restsw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return LITE_CARD_ERROR_REPONSE
        await handle_cleanup(self, LITE_CARD_HAS_BEEN_RESET)
        return LITE_CARD_ERROR_REPONSE
    return LITE_CARD_SUCCESS_REPONSE


async def start_import_pin_mnemonicmphrase(self, pin):

    card_num, status = await get_card_num(self)
    if status == LITE_CARD_ERROR_REPONSE:
        return
    card_type = get_card_type(card_num)

    if card_type == "OLD":
        _, sw1sw2 = nfc.send_recv(CMD_NEW_APPLET)
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return
    elif card_type == "NEW":
        pass
    else:
        return LITE_CARD_CONNECT_FAILURE

    if card_type == "OLD":
        status = await check_best_try_restcard(self)
        if status == LITE_CARD_ERROR_REPONSE:
            return

    if card_type == "NEW":
        resp, sw1sw2 = nfc.send_recv(CMD_NEW_APPLET)
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return

    if card_type == "NEW":
        status = await check_best_try_restcard(self)
        if status == LITE_CARD_ERROR_REPONSE:
            return

    pinresp, pinsw1sw2 = nfc.send_recv(CMD_GET_PIN_STATUS)
    if pinsw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return
    if pinsw1sw2 == LITE_CARD_SUCCESS_STATUS and pinresp == b"\x02":
        await handle_cleanup(self, LITE_CARD_NO_BACKUP)
        return
    if card_type == "NEW":
        resp, sw1sw2 = nfc.send_recv(CMD_GET_BACKUP_STATUS)
        state = resp[0]
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return
        elif (state & 0x02) != 0x02:
            await handle_cleanup(self, LITE_CARD_NO_BACKUP)
            return
    if card_type == "OLD":
        resp, sw1sw2 = nfc.send_recv(CMD_OLD_APPLET)
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return

    pin_bytes = "".join(pin).encode()
    command_data = CMD_VERIFY_PIN + pin_bytes
    resp, sw1sw2 = nfc.send_recv(command_data, True)
    if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return

    if sw1sw2[0] == 0x63 and (sw1sw2[1] & 0xF0) == 0xC0:
        retry_count = sw1sw2[1] & 0x0F
        print(f"PIN verification failed. Remaining retries: {retry_count}")
        pin_status = f"63C{retry_count:X}"
        await handle_cleanup(self, pin_status)
        return
    if sw1sw2[0] == 0x63 and (sw1sw2[1] & 0xF0) == 0xD0:
        retry_count = sw1sw2[1] & 0x0F
        print(f"PIN verification failed. Remaining retries: {retry_count}")
        pin_status = f"63D{retry_count:X}"
        await handle_cleanup(self, pin_status)
        return

    if card_type == "OLD":
        exportresp, exportsw1sw2 = nfc.send_recv(CMD_EXPORT_DATA)
    else:
        exportresp, exportsw1sw2 = nfc.send_recv(CMD_EXPORT_DATA, True)
    if exportsw1sw2 == LITE_CARD_DISCONECT_STATUS or len(exportresp) < 8:
        await handle_sw1sw2_connect_error(self)
        return
    decoder = MnemonicEncoder()
    encoded_mnemonic_str, _, _ = decoder.parse_card_data(exportresp)
    decoded_mnemonics = decoder.decode_mnemonics(encoded_mnemonic_str)
    word_count = len(decoded_mnemonics.split())
    if word_count in [15, 21]:
        await handle_cleanup(self, LITE_CARD_UNSUPPORTED_WORD_COUNT)
        return
    await handle_cleanup(self, decoded_mnemonics)


async def start_check_pin_mnemonicmphrase(self, pin, mnemonic, card_num):

    card_num_again, status = await get_card_num(self)
    if status == LITE_CARD_ERROR_REPONSE:
        return
    card_type = get_card_type(card_num)

    if card_type == "OLD":
        _, sw1sw2 = nfc.send_recv(CMD_NEW_APPLET)
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return
    elif card_type == "NEW":
        pass
    else:
        return LITE_CARD_CONNECT_FAILURE

    if card_num != card_num_again:
        await handle_cleanup(self, LITE_CARD_NOT_SAME)
        return

    if card_type == "OLD":
        status = await check_best_try_restcard(self)
        if status == LITE_CARD_ERROR_REPONSE:
            return

    if card_type == "OLD":
        _, sw1sw2 = nfc.send_recv(CMD_OLD_APPLET)
    else:
        _, sw1sw2 = nfc.send_recv(CMD_NEW_APPLET)

    if card_type == "NEW":
        status = await check_best_try_restcard(self)
        if status == LITE_CARD_ERROR_REPONSE:
            return

    # verify pin
    pin_bytes = "".join(pin).encode()
    command_data = CMD_VERIFY_PIN + pin_bytes
    _, sw1sw2 = nfc.send_recv(command_data, True)
    if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return
    if sw1sw2[0] == 0x63 and (sw1sw2[1] & 0xF0) == 0xC0:
        retry_count = sw1sw2[1] & 0x0F
        print(f"PIN verification failed. Remaining retries: {retry_count}")
        pin_status = f"63C{retry_count:X}"
        self.stop_animation()
        await handle_cleanup(self, pin_status)
        return retry_count
    if sw1sw2[0] == 0x63 and (sw1sw2[1] & 0xF0) == 0xD0:
        retry_count = sw1sw2[1] & 0x0F
        print(f"PIN verification failed. Remaining retries: {retry_count}")
        pin_status = f"63D{retry_count:X}"
        self.stop_animation()
        await handle_cleanup(self, pin_status)
        return retry_count
    if card_type == "NEW":
        command_data = CMD_SETUP_NEW_PIN + pin_bytes
        print(f"set new pincommand_data: {command_data}")
        _, sw1sw2 = nfc.send_recv(command_data, True)
        print(f"sw1sw2: {sw1sw2}")
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return

    # verify pin
    pin_bytes = "".join(pin).encode()
    command_data = CMD_VERIFY_PIN + pin_bytes
    _, sw1sw2 = nfc.send_recv(command_data, True)

    if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return

    encoder = MnemonicEncoder()
    encoded_mnemonic_str = encoder.encode_mnemonics(mnemonic)
    version = "01"
    lang = "00"
    meta = "ffff" + version + lang
    payload = encoded_mnemonic_str + meta
    payload_bytes = bytes(
        int(payload[i : i + 2], 16) for i in range(0, len(payload), 2)
    )

    seed_length = len(payload_bytes)
    lc = seed_length.to_bytes(1, "big")
    apdu_command = CMD_BACKUP_DATA + lc + payload_bytes
    if card_type == "OLD":
        _, importsw1sw2 = nfc.send_recv(apdu_command)
    else:
        _, importsw1sw2 = nfc.send_recv(apdu_command, True)
    if importsw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return
    if importsw1sw2 == LITE_CARD_SUCCESS_STATUS:
        await handle_cleanup(self, LITE_CARD_OPERATE_SUCCESS)
        return
    self.channel.publish(LITE_CARD_CONNECT_FAILURE)
    await loop.sleep(180)
    self.clean()
    self.destroy()
    return


async def check_card_lock_status():
    """检查卡锁定状态 - 先选择应用，再查询PIN设置状态和锁定状态"""
    print("=== Starting card lock status check ===")
    
    # 1. 先选择应用 (Select Applet)
    print("Step 1: Selecting applet...")
    resp, sw1sw2 = nfc.send_recv(CMD_NEW_APPLET)
    print(f"Select applet response: {resp}")
    
    # 安全地打印状态字
    if isinstance(sw1sw2, bytes):
        hex_str = ''.join(f'{b:02x}' for b in sw1sw2)
        print(f"Select applet status word: {sw1sw2} (hex: {hex_str})")
    else:
        print(f"Select applet status word: {sw1sw2}")
    
    # 检查连接状态
    if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        print("Card disconnection detected during applet selection")
        return LITE_CARD_DISCONECT_STATUS
    
    if sw1sw2 != LITE_CARD_SUCCESS_STATUS:
        print("Failed to select applet")
        return LITE_CARD_ERROR_REPONSE
    
    # 2. 查询PIN设置状态
    print("Step 2: Checking PIN setup status...")
    pin_status_resp, pin_status_sw1sw2 = nfc.send_recv(CMD_GET_PIN_STATUS)
    print(f"PIN status response data: {pin_status_resp}")
    
    # 安全地打印状态字
    if isinstance(pin_status_sw1sw2, bytes):
        hex_str = ''.join(f'{b:02x}' for b in pin_status_sw1sw2)
        print(f"PIN status word: {pin_status_sw1sw2} (hex: {hex_str})")
    else:
        print(f"PIN status word: {pin_status_sw1sw2} (hex: {hex(pin_status_sw1sw2)})")
    
    # 检查连接状态
    if pin_status_sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        print("Card disconnection detected during PIN status check")
        return LITE_CARD_DISCONECT_STATUS
    
    # 检查PIN是否已设置
    if pin_status_sw1sw2 == LITE_CARD_SUCCESS_STATUS:
        if pin_status_resp == b"\x01":
            print("PIN is set")
        elif pin_status_resp == b"\x02":
            print("PIN is not set - card needs PIN setup first")
            return "pin_not_set"
        else:
            print(f"Unknown PIN status response: {pin_status_resp}")
    else:
        print("Failed to get PIN status")
        return LITE_CARD_ERROR_REPONSE
    
    # 3. 查询PIN剩余次数来判断锁定状态
    print("Step 3: Checking PIN retry count for lock status...")
    retry_resp, retry_sw1sw2 = nfc.send_recv(CMD_GET_PIN_RETRY_COUNT)
    print(f"PIN retry response data: {retry_resp}")
    
    # 安全地打印状态字
    if isinstance(retry_sw1sw2, bytes):
        hex_str = ''.join(f'{b:02x}' for b in retry_sw1sw2)
        print(f"PIN retry status word: {retry_sw1sw2} (hex: {hex_str})")
    else:
        print(f"PIN retry status word: {retry_sw1sw2} (hex: {hex(retry_sw1sw2)})")
    
    # 检查连接状态
    if retry_sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        print("Card disconnection detected during PIN retry count check")
        return LITE_CARD_DISCONECT_STATUS
    
    # 检查状态字来判断锁定状态
    if len(retry_sw1sw2) >= 2:
        sw1 = retry_sw1sw2[0]
        sw2 = retry_sw1sw2[1]
        print(f"SW1: 0x{sw1:02X}, SW2: 0x{sw2:02X}")
        
        if sw1 == 0x63:
            retry_count = sw2 & 0x0F
            print(f"PIN retry count: {retry_count}")
            
            if (sw2 & 0xF0) == 0xC0:
                # 63CX - 未锁定状态
                print(f"Card status: Unlocked (63C{retry_count:X})")
                return ("unlocked", retry_count)
            elif (sw2 & 0xF0) == 0xD0:
                # 63DX - 已锁定状态  
                print(f"Card status: Locked (63D{retry_count:X})")
                return ("locked", retry_count)
            else:
                print(f"Unknown 63XX status: 63{sw2:02X}")
        elif retry_sw1sw2 == LITE_CARD_SUCCESS_STATUS:
            # 如果是90 00成功状态，默认为未锁定
            print("Card status: Success status (9000) - default to unlocked")
            return "unlocked"
        elif sw1 == 0x6D and sw2 == 0x00:
            # 6D00 - 指令不支持
            print("Card status: Command not supported (6D00) - card may not support lock feature")
            return "unsupported"
        else:
            print(f"Other status word: {sw1:02X}{sw2:02X}")
    else:
        print(f"Insufficient status word length: {len(retry_sw1sw2)}")
    
    # 如果无法判断，返回错误
    print("Unable to determine card lock status, returning error")
    print("=== Card lock status check completed ===")
    return LITE_CARD_ERROR_REPONSE


async def set_card_lock_state(pin, lock_enable):
    """设置卡锁定状态（使用SCP03安全通道）
    Args:
        pin: PIN码列表
        lock_enable: True为开启锁定，False为关闭锁定
    Returns:
        状态字或错误码
    """
    print(f"=== Setting card lock state: {'Enable' if lock_enable else 'Disable'} ===")
    
    # 重新选择应用
    print("Selecting applet before lock operation...")
    resp, sw1sw2 = nfc.send_recv(CMD_NEW_APPLET)
    if sw1sw2 != LITE_CARD_SUCCESS_STATUS:
        print(f"Failed to select applet: {sw1sw2}")
        return LITE_CARD_ERROR_REPONSE
    
    # 构建PIN数据 - 确保PIN码为6字节
    pin_str = "".join(pin)
    if len(pin_str) != 6:
        print(f"Error: PIN must be 6 digits, got {len(pin_str)}")
        return LITE_CARD_ERROR_REPONSE
    pin_bytes = pin_str.encode()
    
    # 先验证PIN码
    print("Verifying PIN before setting lock state...")
    verify_command = CMD_VERIFY_PIN + pin_bytes
    verify_resp, verify_sw1sw2 = nfc.send_recv(verify_command, True)
    print(f"PIN verification response: {verify_resp}")
    if isinstance(verify_sw1sw2, bytes):
        hex_str = ''.join(f'{b:02x}' for b in verify_sw1sw2)
        print(f"PIN verification status: {verify_sw1sw2} (hex: {hex_str})")
    
    if verify_sw1sw2 != LITE_CARD_SUCCESS_STATUS:
        print(f"PIN verification failed: {verify_sw1sw2}")
        return verify_sw1sw2
    
    control_code = b"\x01" if lock_enable else b"\x00"
    
    # 构建命令数据：PIN(6字节) + 控制码
    command_data = CMD_SET_CARD_LOCK + pin_bytes + control_code
    
    print(f"Command length: {len(command_data)} bytes")
    print(f"Control code: {'Enable' if lock_enable else 'Disable'} (0x{control_code[0]:02x})")
    # 发送命令（使用SCP03安全通道）
    resp, sw1sw2 = nfc.send_recv(command_data, True)  # True表示使用SCP03
    
    print(f"Set lock response data: {resp}")
    if isinstance(sw1sw2, bytes):
        hex_str = ''.join(f'{b:02x}' for b in sw1sw2)
        print(f"Set lock status: {sw1sw2} (hex: {hex_str})")
    
    # 解析响应
    if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        print("Card disconnected")
        return LITE_CARD_DISCONECT_STATUS
    elif sw1sw2 == LITE_CARD_SUCCESS_STATUS:
        # 检查响应数据
        if resp and len(resp) > 0:
            lock_state = resp[0] if isinstance(resp[0], int) else ord(resp[0])
            print(f"Card lock state response: 0x{lock_state:02X} ({'Enabled' if lock_state == 0x01 else 'Disabled'})")
        print("Card lock state changed successfully")
        return LITE_CARD_SUCCESS_STATUS
    else:
        print(f"Failed to set card lock state")
        # 返回错误状态字供调用方处理
        return sw1sw2


async def start_card_lock_workflow():
    """卡锁定工作流程 - 搜索卡片并处理锁定状态"""
    nfc.pwr_ctrl(True)
    
    # 在while循环中搜索卡片
    while True:
        await loop.sleep(1000)
        if nfc.poll_card():
            # 找到卡片，返回成功
            MOTOR_CTL = io.MOTOR()
            perform_ticks(MOTOR_CTL, 80)
            return LITE_CARD_FIND
        else:
            continue


async def start_set_pin_mnemonicmphrase(self, pin, mnemonic, card_num):

    card_num_again, status = await get_card_num(self)
    if status == LITE_CARD_ERROR_REPONSE:
        return
    card_type = get_card_type(card_num_again)
    if card_type == "OLD":
        _, restsw1sw2 = nfc.send_recv(CMD_RESET_CARD, True)
        if restsw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return
    if card_num != card_num_again:
        await handle_cleanup(self, LITE_CARD_NOT_SAME)
        return

    # reset card
    if card_type == "OLD":
        _, sw1sw2 = nfc.send_recv(CMD_RESET_CARD, True)
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return
    # select app
    if card_type == "NEW":
        _, sw1sw2 = nfc.send_recv(CMD_NEW_APPLET)
        if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
            await handle_sw1sw2_connect_error(self)
            return
    # set pin
    pin_bytes = "".join(pin).encode()
    command_data = CMD_SETUP_NEW_PIN + pin_bytes

    print(f"pin_bytes: {pin_bytes}")
    print(f"set new pin command_data: {command_data}")
    
    _, sw1sw2 = nfc.send_recv(command_data, True)
    print(f"sw1sw2: {sw1sw2}")
    
    if sw1sw2 == LITE_CARD_DISCONECT_STATUS:
        await handle_sw1sw2_connect_error(self)
        return

    if card_type == "OLD":
        _, sw1sw2 = nfc.send_recv(CMD_OLD_APPLET)

    # verify pin
    pin_bytes = "".join(pin).encode()
    command_data = CMD_VERIFY_PIN + pin_bytes

    restsw1sw2, sw1sw2 = nfc.send_recv(command_data, True)

    encoder = MnemonicEncoder()
    encoded_mnemonic_str = encoder.encode_mnemonics(mnemonic)
    version = "01"
    lang = "00"
    meta = "ffff" + version + lang
    payload = encoded_mnemonic_str + meta
    payload_bytes = bytes(
        int(payload[i : i + 2], 16) for i in range(0, len(payload), 2)
    )
    seed_length = len(payload_bytes)
    lc = seed_length.to_bytes(1, "big")
    apdu_command = CMD_BACKUP_DATA + lc + payload_bytes
    if card_type == "OLD":
        _, importsw1sw2 = nfc.send_recv(apdu_command)
    else:
        _, importsw1sw2 = nfc.send_recv(apdu_command, True)

    if importsw1sw2 == LITE_CARD_DISCONECT_STATUS:
        self.stop_animation()
        await handle_sw1sw2_connect_error(self)
        return
    if importsw1sw2 == LITE_CARD_SUCCESS_STATUS:
        await handle_cleanup(self, LITE_CARD_OPERATE_SUCCESS)
        return
    await handle_cleanup(self, LITE_CARD_CONNECT_FAILURE)
    return


class MnemonicEncoder:
    def encode_mnemonics(self, seed):
        n = 2048
        words = seed.split()
        i = 0
        while words:
            w = words.pop()
            k = bip39.find(w)
            i = i * n + k
        result_str = str(i)
        if len(result_str) % 2 != 0:
            result_str = "0" + result_str
        return result_str

    def int_to_hex_str(self, num):
        """Convert an integer to a hexadecimal string."""
        hex_str = hex(num)[2:]  # Convert to hex and remove the '0x' prefix
        if len(hex_str) % 2:  # Make sure the length is even
            hex_str = "0" + hex_str
        return hex_str

    def fromhex(self, hex_str):
        """Convert a hex string to a byte array."""
        return bytes(int(hex_str[i : i + 2], 16) for i in range(0, len(hex_str), 2))

    def bytes_to_hex_str(self, byte_data):
        return "".join(f"{byte:02x}" for byte in byte_data)

    def decode_mnemonics(self, encoded_mnemonic_str):
        n = 2048
        encoded_int = int(encoded_mnemonic_str, 10)
        words = []

        while encoded_int > 0:
            index = int(encoded_int % n)
            encoded_int = encoded_int // n
            words.append(bip39.get_word(index))
        # v1 fix
        fix_fill_count = 0
        supported_mnemonic_length = [12, 15, 18, 21, 24]
        for length in supported_mnemonic_length:
            if len(words) == length:
                break
            if len(words) < length:
                fix_fill_count = length - len(words)
                break
        words.extend([bip39.get_word(0)] * fix_fill_count)

        return " ".join(words)

    def parse_card_data(self, data):

        encoded_mnemonic_bytes = data[:-4]
        version_bytes = data[-4:-3]
        lang_bytes = data[-3:-2]
        encoded_mnemonic_str = self.bytes_to_hex_str(encoded_mnemonic_bytes)
        version = self.bytes_to_hex_str(version_bytes)
        lang = self.bytes_to_hex_str(lang_bytes)

        return encoded_mnemonic_str, version, lang


class SearchDeviceScreen(FullSizeWindow):
    def __init__(self):
        super().__init__(
            _(i18n_keys.TITLE__CONNECTING),
            _(i18n_keys.CONTENT__KEEP_LITE_DEVICE_TOGETHER_BACKUP_COMPLETE),
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
            anim_dir=0,
        )
        self.img_bg = lv.img(self.content_area)
        self.img_bg.set_src("A:/res/nfc-bg.png")
        self.img_bg.align_to(self.subtitle, lv.ALIGN.OUT_BOTTOM_MID, 0, 125)
        self.img_searching = lv.img(self.content_area)
        self.img_searching.set_src("A:/res/nfc-icon-searching.png")
        self.img_searching.align_to(self.img_bg, lv.ALIGN.CENTER, 0, 0)
        self.anim = lv.anim_t()
        self.anim.init()
        self.anim.set_var(self.img_bg)
        self.anim.set_values(0, 3600)
        self.anim.set_time(1000)
        self.anim.set_repeat_count(0xFFFF)  # infinite
        self.anim.set_path_cb(lv.anim_t.path_linear)
        self.anim.set_custom_exec_cb(lambda _a, val: self.set_angle(val))
        self.anim_r = lv.anim_t.start(self.anim)
        self.searching = True
        loop.schedule(run_card_search(self))

    def set_angle(self, angle):
        try:
            self.img_bg.set_angle(angle)
        except Exception:
            lv.anim_del(self.anim_r.var, None)


class TransferDataScreen(FullSizeWindow):
    def __init__(self):
        super().__init__(
            _(i18n_keys.TITLE__TRANSFERRING),
            _(i18n_keys.TITLE__TRANSFERRING_DESC),
            cancel_text=_(i18n_keys.BUTTON__CANCEL),
            anim_dir=0,
        )
        self.img_searching = lv.img(self.content_area)
        self.img_searching.set_src("A:/res/nfc-icon-transfering.png")
        self.img_searching.align_to(self.subtitle, lv.ALIGN.OUT_BOTTOM_MID, 0, 237)
        self.searching = True

    def set_angle(self, angle):
        try:
            self.img_bg.set_angle(angle)
        except Exception:
            pass

    def check_card_data(self):
        loop.schedule(check_card_data(self))

    def stop_animation(self):
        self.searching = False

    def set_pin_mnemonicmphrase(self, pin, card_num, mnemonics):
        # mnemonics = "abound abound abound abound abound abound abound abound abound abound abound about"
        loop.schedule(start_set_pin_mnemonicmphrase(self, pin, mnemonics, card_num))

    def check_pin_mnemonicmphrase(self, pin, card_num, mnemonics):

        loop.schedule(start_check_pin_mnemonicmphrase(self, pin, mnemonics, card_num))

    def import_pin_mnemonicmphrase(self, pin):
        loop.schedule(start_import_pin_mnemonicmphrase(self, pin))

    def check_card_lock_status(self):
        """检查卡锁定状态"""
        loop.schedule(self._check_card_lock_status())

    async def _check_card_lock_status(self):
        """检查卡锁定状态的异步实现"""
        lock_status = await check_card_lock_status()
        self.channel.publish(lock_status)
        self.stop_animation()
        
    def set_card_lock_state(self, pin, lock_enable):
        """设置卡锁定状态"""
        loop.schedule(self._set_card_lock_state(pin, lock_enable))
        
    async def _set_card_lock_state(self, pin, lock_enable):
        """设置卡锁定状态的异步实现"""
        result = await set_card_lock_state(pin, lock_enable)
        self.channel.publish(result)
        self.stop_animation()
