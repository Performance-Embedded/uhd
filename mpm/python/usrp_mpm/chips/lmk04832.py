#
# Copyright 2019 Ettus Research, a National Instruments Brand
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""
LMK04832 parent driver class
"""

from usrp_mpm.mpmlog import get_logger

class LMK04832():
    """
    Generic driver class for LMK04832 access.
    """
    LMK_CHIP_ID = 6
    LMK_PROD_ID = 0xD163

    def __init__(self, regs_iface, parent_log=None):
        self.log = \
            parent_log.getChild("LMK04832") if parent_log is not None \
            else get_logger("LMK04832")
        self.regs_iface = regs_iface
        assert hasattr(self.regs_iface, 'peek8')
        assert hasattr(self.regs_iface, 'poke8')
        self.poke8 = regs_iface.poke8
        self.peek8 = regs_iface.peek8
        self.enable_3wire_spi = False

    def pokes8(self, addr_vals):
        """
        Apply a series of pokes.
        pokes8([(0,1),(0,2)]) is the same as calling poke8(0,1), poke8(0,2).
        """
        for addr, val in addr_vals:
            self.poke8(addr, val)

    def get_chip_id(self):
        """
        Read back the chip ID
        """
        chip_id = self.peek8(0x03)
        self.log.trace("Chip ID Readback: {}".format(chip_id))
        return chip_id

    def get_product_id(self):
        """
        Read back the product ID
        """
        prod_id_0 = self.peek8(0x04)
        prod_id_1 = self.peek8(0x05)
        prod_id = (prod_id_1 << 8) \
                  | prod_id_0
        self.log.trace("Product ID Readback: 0x{:X}".format(prod_id))
        return prod_id

    def verify_chip_id(self):
        """
        Returns True if the chip ID and product ID matches what we expect, False otherwise.
        """
        chip_id = self.get_chip_id()
        prod_id = self.get_product_id()
        if chip_id != self.LMK_CHIP_ID:
            self.log.error("Wrong Chip ID 0x{:X}".format(chip_id))
            return False
        if prod_id != self.LMK_PROD_ID:
            self.log.error("Wrong Product ID 0x{:X}".format(prod_id))
            return False
        return True

    def check_plls_locked(self, pll='BOTH'):
        """
        Returns True if the specified PLLs are locked, False otherwise.
        """
        pll = pll.upper()
        assert pll in ('BOTH', 'PLL1', 'PLL2'), 'Cannot check lock for invalid PLL'
        result = True
        pll_lock_status = self.peek8(0x183)

        if pll == 'BOTH' or pll == 'PLL1':
            # Lock status for PLL1 should be 0x01 on bits [3:2]
            if (pll_lock_status & 0xC) != 0x04:
                self.log.debug("PLL1 reporting unlocked... Status: 0x{:x}"
                               .format(pll_lock_status))
                result = False
        if pll == 'BOTH' or pll == 'PLL2':
            # Lock status for PLL2 should be 0x01 on bits [1:0]
            if (pll_lock_status & 0x3) != 0x01:
                self.log.debug("PLL2 reporting unlocked... Status: 0x{:x}"
                               .format(pll_lock_status))
                result = False
        return result

    def clr_ld_lost_sticky(self):
        """
        Sets and clears the CLR_PLLX_LD_LOST for PLL1 and PLL2
        """
        self.poke8(0x182, 0x03)
        self.poke8(0x182, 0x00)

    def soft_reset(self, value=True):
        """
        Performs a soft reset of the LMK04832 by setting or unsetting the reset register.
        """
        reset_addr = 0
        if value: # Reset
            reset_byte = 0x80
        else: # Clear Reset
            reset_byte = 0x00
        if not self.enable_3wire_spi:
            reset_byte |= 0x10
        self.poke8(reset_addr, reset_byte)


    def pll1_r_divider_sync(self, sync_pin_callback):
        """
        Run PLL1 R Divider sync according to
        http://www.ti.com/lit/ds/snas688c/snas688c.pdf chapter 8.3.1.1

        Rising edge on sync pin is done by an callback which has to return it's
        success state. If the sync callback was successful, returns PLL1 lock
        state as overall success otherwise the method fails.
        """

        # 1) Setup device for synchronizing PLL1 R
        self.poke8(0x145, 0x50) # PLL1R_SYNC_EN    (6) = 1
                                # PLL1R_SYNC_SRC (5,4) = Sync pin
                                # PLL2R_SYNC_EN    (3) = 0

        # Do NOT change clkin0_TYPE and Clkin[0,1]_DEMUX.
        # Both are set in initialization and remain static.

        # 2) Arm PLL1 R divider for synchronization
        self.poke8(0x177, 0x20)
        self.poke8(0x177, 0)

        # 3) Send rising edge on SYNC pin
        result = sync_pin_callback()

        # reset 0x145 to safe value (no sync enable set, sync src invalidated
        self.poke8(0x145, 0)

        if result:
            return self.wait_for_pll_lock("PLL1")
        else:
            return False

    ## Register bitfield definitions ##

    def pll2_pre_to_reg(self, prescaler, osc_field=0x01, xtal_en=0x0, ref_2x_en=0x0):
        """
        From the prescaler value, returns the register value combined with the other
        register fields.
        """
        # valid prescaler values are 2-8, where 8 is represented as 0x00.
        assert prescaler in range(2, 8+1)
        reg_val = ((prescaler & 0x07) << 5) \
                  | ((osc_field & 0x3) << 2) \
                  | ((xtal_en & 0x1) << 1) \
                  | ((ref_2x_en & 0x1) << 0)
        self.log.trace("From prescaler value 0d{}, writing register as 0x{:02X}."
                       .format(prescaler, reg_val))
        return reg_val
