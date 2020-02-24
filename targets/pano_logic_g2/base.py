# Support for the Pano Logic Zero Client G2
from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.soc.interconnect import wishbone
from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *

from litedram.modules import MT47H32M16
from litedram.phy import s6ddrphy
from litedram.core import ControllerSettings

from gateware import info
from gateware import cas

from targets.utils import csr_map_update


class _CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()

        self.reset = Signal()

        f0 = int(125e6)

        clk125 = platform.request(platform.default_clk_name)
        clk125a = Signal()

        self.specials += Instance("IBUFG", i_I=clk125, o_O=clk125a)

        clk125b = Signal()

        self.specials += Instance(
            "BUFIO2", p_DIVIDE=1,
            p_DIVIDE_BYPASS="TRUE", p_I_INVERT="FALSE",
            i_I=clk125a, o_DIVCLK=clk125b)

        unbuf_sdram_full = Signal()
        unbuf_sdram_half_a = Signal()
        unbuf_sdram_half_b = Signal()
        unbuf_encoder = Signal()
        unbuf_sys = Signal()
        unbuf_unused = Signal()

        # PLL signals
        pll_lckd = Signal()
        pll_fb = Signal()
        self.specials.pll = Instance(
            "PLL_ADV",
            name="crg_pll_adv",
            p_SIM_DEVICE="SPARTAN6", p_BANDWIDTH="OPTIMIZED", p_COMPENSATION="INTERNAL",
            p_REF_JITTER=.01,
            i_DADDR=0, i_DCLK=0, i_DEN=0, i_DI=0, i_DWE=0, i_RST=0, i_REL=0,
            p_DIVCLK_DIVIDE=1,
            # Input Clocks (125MHz)
            i_CLKIN1=clk125b,
            p_CLKIN1_PERIOD=platform.default_clk_period,
            i_CLKIN2=0,
            p_CLKIN2_PERIOD=0.,
            i_CLKINSEL=1,
            # Feedback
            # (1000MHz) vco
            i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb, o_LOCKED=pll_lckd,
            p_CLK_FEEDBACK="CLKFBOUT",
            p_CLKFBOUT_MULT=8, p_CLKFBOUT_PHASE=0.,
            # (200MHz) sdram wr rd
            o_CLKOUT0=unbuf_sdram_full, p_CLKOUT0_DUTY_CYCLE=.5,
            p_CLKOUT0_PHASE=0., p_CLKOUT0_DIVIDE=5,
            # (100MHz) unused
            o_CLKOUT1=unbuf_encoder, p_CLKOUT1_DUTY_CYCLE=.5,
            p_CLKOUT1_PHASE=0., p_CLKOUT1_DIVIDE=10,
            # (100MHz) sdram_half - sdram dqs adr ctrl
            o_CLKOUT2=unbuf_sdram_half_a, p_CLKOUT2_DUTY_CYCLE=.5,
            p_CLKOUT2_PHASE=270., p_CLKOUT2_DIVIDE=10,
            # (100MHz) off-chip ddr
            o_CLKOUT3=unbuf_sdram_half_b, p_CLKOUT3_DUTY_CYCLE=.5,
            p_CLKOUT3_PHASE=250., p_CLKOUT3_DIVIDE=10,
            # (100MHz) unused
            o_CLKOUT4=unbuf_unused, p_CLKOUT4_DUTY_CYCLE=.5,
            p_CLKOUT4_PHASE=0., p_CLKOUT4_DIVIDE=10,
            # ( 50MHz) sysclk
            o_CLKOUT5=unbuf_sys, p_CLKOUT5_DUTY_CYCLE=.5,
            p_CLKOUT5_PHASE=0., p_CLKOUT5_DIVIDE=20,
        )

        # power on reset?
        reset = ~platform.request("cpu_reset") | self.reset
        self.clock_domains.cd_por = ClockDomain()
        por = Signal(max=1 << 11, reset=(1 << 11) - 1)
        self.sync.por += If(por != 0, por.eq(por - 1))
        self.specials += AsyncResetSynchronizer(self.cd_por, reset)

        # System clock - 50MHz
        self.specials += Instance("BUFG", name="sys_bufg", i_I=unbuf_sys, o_O=self.cd_sys.clk)
        self.comb += self.cd_por.clk.eq(self.cd_sys.clk)
        self.specials += AsyncResetSynchronizer(self.cd_sys, ~pll_lckd | (por > 0))

        # SDRAM clocks, ddram_b
        # ------------------------------------------------------------------------------
        self.clock_domains.cd_sdram_half_1 = ClockDomain()
        self.clock_domains.cd_sdram_full_wr_1 = ClockDomain()
        self.clock_domains.cd_sdram_full_rd_1 = ClockDomain()

        self.clk4x_wr_strb_1 = Signal()
        self.clk4x_rd_strb_1 = Signal()

        # sdram_full
        self.specials += Instance("BUFPLL", name="sdram_full_bufpll_1",
                                  p_DIVIDE=4,
                                  i_PLLIN=unbuf_sdram_full, i_GCLK=self.cd_sys.clk,
                                  i_LOCKED=pll_lckd,
                                  o_IOCLK=self.cd_sdram_full_wr_1.clk,
                                  o_SERDESSTROBE=self.clk4x_wr_strb_1)
        self.comb += [
            self.cd_sdram_full_rd_1.clk.eq(self.cd_sdram_full_wr_1.clk),
            self.clk4x_rd_strb_1.eq(self.clk4x_wr_strb_1),
        ]
        # sdram_half
        self.specials += Instance("BUFG", name="sdram_half_a_bufpll_1", i_I=unbuf_sdram_half_a, o_O=self.cd_sdram_half_1.clk)
        clk_sdram_half_shifted_1 = Signal()
        self.specials += Instance("BUFG", name="sdram_half_b_bufpll_1", i_I=unbuf_sdram_half_b, o_O=clk_sdram_half_shifted_1)

        output_clk_1 = Signal()
        clk_1 = platform.request("ddram_clock_b")
        self.specials += Instance("ODDR2", p_DDR_ALIGNMENT="NONE",
                                  p_INIT=0, p_SRTYPE="SYNC",
                                  i_D0=1, i_D1=0, i_S=0, i_R=0, i_CE=1,
                                  i_C0=clk_sdram_half_shifted_1,
                                  i_C1=~clk_sdram_half_shifted_1,
                                  o_Q=output_clk_1)
        self.specials += Instance("OBUFDS", i_I=output_clk_1, o_O=clk_1.p, o_OB=clk_1.n)

        # SDRAM clocks, ddram_a
        # ------------------------------------------------------------------------------
        self.clock_domains.cd_sdram_half_0 = ClockDomain()
        self.clock_domains.cd_sdram_full_wr_0 = ClockDomain()
        self.clock_domains.cd_sdram_full_rd_0 = ClockDomain()

        self.clk4x_wr_strb_0 = Signal()
        self.clk4x_rd_strb_0 = Signal()

        # sdram_full
        self.specials += Instance("BUFPLL", name="sdram_full_bufpll_0",
                                  p_DIVIDE=4,
                                  i_PLLIN=unbuf_sdram_full, i_GCLK=self.cd_sys.clk,
                                  i_LOCKED=pll_lckd,
                                  o_IOCLK=self.cd_sdram_full_wr_0.clk,
                                  o_SERDESSTROBE=self.clk4x_wr_strb_0)
        self.comb += [
            self.cd_sdram_full_rd_0.clk.eq(self.cd_sdram_full_wr_0.clk),
            self.clk4x_rd_strb_0.eq(self.clk4x_wr_strb_0),
        ]
        # sdram_half
        self.specials += Instance("BUFG", name="sdram_half_a_bufpll_0", i_I=unbuf_sdram_half_a, o_O=self.cd_sdram_half_0.clk)
        clk_sdram_half_shifted_0 = Signal()
        self.specials += Instance("BUFG", name="sdram_half_b_bufpll_0", i_I=unbuf_sdram_half_b, o_O=clk_sdram_half_shifted_0)

        output_clk_0 = Signal()
        clk_0 = platform.request("ddram_clock_a")
        self.specials += Instance("ODDR2", p_DDR_ALIGNMENT="NONE",
                                  p_INIT=0, p_SRTYPE="SYNC",
                                  i_D0=1, i_D1=0, i_S=0, i_R=0, i_CE=1,
                                  i_C0=clk_sdram_half_shifted_0,
                                  i_C1=~clk_sdram_half_shifted_0,
                                  o_Q=output_clk_0)
        self.specials += Instance("OBUFDS", i_I=output_clk_0, o_O=clk_0.p, o_OB=clk_0.n)

class BaseSoC(SoCSDRAM):
    csr_peripherals = (
        "ddrphy",
        "info",
        "cas",
    )
    csr_map_update(SoCSDRAM.csr_map, csr_peripherals)

    mem_map = {
        #"main_ram":     0x40000000,
        "main_ram_2":   0x44000000,
        "emulator_ram": 0x50000000,  # (default shadow @0xd0000000)
    }
    mem_map.update(SoCSDRAM.mem_map)

    def __init__(self, platform, **kwargs):
        if 'integrated_rom_size' not in kwargs:
            kwargs['integrated_rom_size']=0x8000
        kwargs['integrated_sram_size']=0x8000

        clk_freq = int(50e6)
        SoCSDRAM.__init__(self, platform, clk_freq, **kwargs)

        self.submodules.crg = _CRG(platform)
        self.platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/clk_freq)

        self.submodules.info = info.Info(platform, self.__class__.__name__)
        self.submodules.cas = cas.ControlAndStatus(platform, clk_freq)

        gmii_rst_n = platform.request("gmii_rst_n")

        self.comb += [
            gmii_rst_n.eq(1)
        ]

        if self.cpu_type == "vexriscv" and self.cpu_variant == "linux":
            size = 0x4000
            self.submodules.emulator_ram = wishbone.SRAM(size)
            self.register_mem("emulator_ram", self.mem_map["emulator_ram"], self.emulator_ram.bus, size)

        # sdram, ddram_1
        sdram_module_1 = MT47H32M16(self.clk_freq, "1:2")
        self.submodules.ddrphy_1 = s6ddrphy.S6HalfRateDDRPHY(
            platform.request("ddram_b"),
            sdram_module_1.memtype,
            rd_bitslip=0,
            wr_bitslip=4,
            dqs_ddr_alignment="C0",
            clk_suffix='1')
        controller_settings = ControllerSettings(with_bandwidth=True)

        self.register_sdram(self.ddrphy_1,
                            sdram_module_1.geom_settings,
                            sdram_module_1.timing_settings,
                            controller_settings=controller_settings)

        self.comb += [
            self.ddrphy_1.clk4x_wr_strb.eq(self.crg.clk4x_wr_strb_1),
            self.ddrphy_1.clk4x_rd_strb.eq(self.crg.clk4x_rd_strb_1),
        ]

        # sdram, ddram_0
        sdram_module_0 = MT47H32M16(self.clk_freq, "1:2")
        self.submodules.ddrphy_0 = s6ddrphy.S6HalfRateDDRPHY(
            platform.request("ddram_a"),
            sdram_module_0.memtype,
            rd_bitslip=0,
            wr_bitslip=4,
            dqs_ddr_alignment="C0",
            clk_suffix='0')
        controller_settings = ControllerSettings(with_bandwidth=True)

        self.add_sdram('sdram2',
            phy                     = self.ddrphy_0,
            module                  = sdram_module_0,
            origin                  = self.mem_map['main_ram_2'],
            size                    = self.max_sdram_size,
            controller_settings     = controller_settings,
            l2_cache_size           = self.l2_size,
            l2_cache_min_data_width = self.min_l2_data_width,
            l2_cache_reverse        = self.l2_reverse,
        )

        self.comb += [
            self.ddrphy_0.clk4x_wr_strb.eq(self.crg.clk4x_wr_strb_0),
            self.ddrphy_0.clk4x_rd_strb.eq(self.crg.clk4x_rd_strb_0),
        ]


SoC = BaseSoC
