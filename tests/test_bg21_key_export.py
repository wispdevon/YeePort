"""Execute patched ARM code, with only SDK dispatch/memcpy mocked.

The official vendor reference stays outside the repository. This checks actual
machine code/ABI and gating; it does not emulate radio hardware or bootloader.
"""
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from prepare_bg21_key_export import assemble, APP_BASE, PATCH_ADDRESS

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                  UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
                                  UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_SP,
                                  UC_ARM_REG_LR, UC_ARM_REG_PC)
except ImportError:
    Uc = None


class BG21ExportMachineCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reference = Path(os.environ.get("BG21_REFERENCE", "/tmp/yeegate-knob-bg21-00010000.bin"))
        if Uc is None or not reference.exists():
            raise unittest.SkipTest("Unicorn and external official BG21 reference required")
        cls.reference = reference.read_bytes()
        cls.hook, cls.branch = assemble()

    def execute(self, characteristic, payload, *, patched=True, clobber_request=False):
        app = bytearray(self.reference)
        if patched:
            app[PATCH_ADDRESS - APP_BASE:PATCH_ADDRESS - APP_BASE + 4] = self.branch
            app.extend(self.hook)
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.mem_map(0x10000, 0x50000)
        uc.mem_write(APP_BASE, bytes(app))
        uc.mem_map(0x20000000, 0x10000)
        uc.mem_map(0x0fe00000, 0x1000)
        secret = bytes(range(0x40, 0x50))  # Public fixture, not real credentials.
        uc.mem_write(0x0fe0000e, secret)
        uc.mem_write(0x20008d00, struct.pack("<II", 0x20009000, 0x2000a000))
        uc.mem_write(0x20008000, payload)
        initial = {UC_ARM_REG_R0: 2, UC_ARM_REG_R1: characteristic,
                   UC_ARM_REG_R2: len(payload), UC_ARM_REG_R3: 0x20008000,
                   UC_ARM_REG_R4: 0x44444444, UC_ARM_REG_R5: 0x55555555,
                   UC_ARM_REG_R6: 0x66666666, UC_ARM_REG_R7: 0x77777777,
                   UC_ARM_REG_SP: 0x2000fff0, UC_ARM_REG_LR: 0x50001}
        for register, value in initial.items():
            uc.reg_write(register, value)
        notifications = []
        def callback(machine, address, size, context):
            if address == 0x50000:
                machine.emu_stop()
                return
            if address == 0x42b6e:  # Vendor memcpy
                destination = machine.reg_read(UC_ARM_REG_R0)
                source = machine.reg_read(UC_ARM_REG_R1)
                length = machine.reg_read(UC_ARM_REG_R2)
                machine.mem_write(destination, bytes(machine.mem_read(source, length)))
                machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))
            elif address == 0x2f470:  # Synchronous BGAPI request dispatcher
                pointer = machine.reg_read(UC_ARM_REG_R2)
                connection, attribute, length = struct.unpack("<BHB", machine.mem_read(pointer, 4))
                notifications.append((connection, attribute, bytes(machine.mem_read(pointer + 4, length))))
                if clobber_request:
                    machine.mem_write(0x20009000, bytes(32))
                for register in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3):
                    machine.reg_write(register, 0xaabbccdd)
                machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))
        uc.hook_add(UC_HOOK_CODE, callback)
        uc.emu_start(0x11f69, 0x50000, count=2000)
        self.assertEqual(uc.reg_read(UC_ARM_REG_PC), 0x50000)
        self.assertEqual(uc.reg_read(UC_ARM_REG_R0), 0x2000a004)
        for register in (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_SP):
            self.assertEqual(uc.reg_read(register), initial[register])
        return notifications, secret

    def test_success_exports_only_after_original_reply(self):
        packets, secret = self.execute(0x34, bytes.fromhex("07030164"))
        self.assertEqual(packets, [(2, 0x34, bytes.fromhex("07030164")),
                                   (2, 0x34, b"\x07\x04" + secret)])

    def test_dispatch_clobber_cannot_change_connection_or_gate(self):
        packets, secret = self.execute(0x34, bytes.fromhex("07030164"), clobber_request=True)
        self.assertEqual(packets[-1], (2, 0x34, b"\x07\x04" + secret))

    def test_other_notifications_match_stock_and_never_export(self):
        for attribute, payload in [(0x34, b"\x07\x01" + bytes(128)),
                                   (0x34, bytes.fromhex("07030165")),
                                   (0x34, bytes.fromhex("07020164")),
                                   (0x34, bytes.fromhex("07030164") + b"\0"),
                                   (0x3b, bytes.fromhex("07030164")),
                                   (0x3b, bytes.fromhex("0100")),
                                   (0x48, bytes.fromhex("05010164"))]:
            with self.subTest(attribute=attribute, length=len(payload)):
                patched, _ = self.execute(attribute, payload)
                stock, _ = self.execute(attribute, payload, patched=False)
                self.assertEqual(patched, stock)
                self.assertEqual(len(patched), 1)


if __name__ == "__main__":
    unittest.main()
