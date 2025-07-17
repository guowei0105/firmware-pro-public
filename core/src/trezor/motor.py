import storage.device
from trezor import io, utils

if not utils.EMULATOR:
    MOTOR_CTL = io.MOTOR()

    def vibrate(weak=False):
        if not storage.device.keyboard_haptic_enabled():
            return
        if weak:
            if __debug__:
                print("vibrate weak")
            MOTOR_CTL.play_medium()
        else:
            if __debug__:
                print("vibrate strong")
            MOTOR_CTL.play_heavy()

else:

    def vibrate(weak=False):
        pass
