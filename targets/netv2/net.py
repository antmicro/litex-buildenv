from litex.soc.integration.soc_core import mem_decoder
from litex.soc.integration.soc_sdram import *

from liteeth.core.mac import LiteEthMAC
from liteeth.core.arp import LiteEthARP
from liteeth.core.ip import LiteEthIP
from liteeth.core.udp import LiteEthUDP
from liteeth.core.icmp import LiteEthICMP
from liteeth.phy.rmii import LiteEthPHYRMII
from liteeth.core import LiteEthUDPIPCore
from liteeth.frontend.etherbone import LiteEthEtherbone
from liteeth.common import *

from targets.utils import csr_map_update
from targets.netv2.base import SoC as BaseSoC


class NetSoC(BaseSoC):
    mem_map = {
        "ethmac": 0xb0000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, platform, *args, **kwargs):

        kwargs["integrated_rom_size"] = 0x8000
        kwargs["integrated_sram_size"] = 0x8000

        BaseSoC.__init__(self, platform, *args, **kwargs)

        clk_freq = int(100e6)
        mac_address = 0x10e2d5000001
        ip_address = convert_ip("192.168.100.60")
        dw = 8

        self.submodules.ethphy = LiteEthPHYRMII(
            platform.request("eth_clocks"),
            platform.request("eth"))
        self.add_csr("ethphy")
        
        self.submodules.ethmac = LiteEthMAC(
            phy=self.ethphy, dw=dw, interface="hybrid", endianness=self.cpu.endianness)

        # SoftCPU ethernet
        self.add_memory_region("ethmac", self.mem_map["ethmac"], 0x2000, type="io")
        self.add_wb_slave(self.mem_map["ethmac"], self.ethmac.bus, 0x2000)
        self.add_interrupt("ethmac")
        self.add_csr("ethmac")

        # HW ethernet
        self.submodules.arp = LiteEthARP(self.ethmac, mac_address, ip_address, clk_freq, dw=dw)
        self.submodules.ip = LiteEthIP(self.ethmac, mac_address, ip_address, self.arp.table, dw=dw)
        self.submodules.icmp = LiteEthICMP(self.ip, ip_address, dw=dw)
        self.submodules.udp = LiteEthUDP(self.ip, ip_address, dw=dw)

        # UDP loopback @ 9001
        port = self.udp.crossbar.get_port(9001, dw)
        self.submodules.buf = buf = stream.SyncFIFO(eth_udp_user_description(dw), 1024)
        self.comb += Port.connect(port, buf)

        self.ethphy.crg.cd_eth_rx.clk.attr.add("keep")
        self.ethphy.crg.cd_eth_tx.clk.attr.add("keep")
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_rx.clk, 20.0)
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_tx.clk, 20.0)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.ethphy.crg.cd_eth_rx.clk,
            self.ethphy.crg.cd_eth_tx.clk)

        """
        # ethphy
        self.submodules.ethphy = LiteEthPHYRMII(
            clock_pads = self.platform.request("eth_clocks"),
            pads       = self.platform.request("eth"))
        self.add_csr("ethphy")
        # ethcore
        self.submodules.ethcore = LiteEthUDPIPCore(
            phy         = self.ethphy,
            mac_address = 0x10e2d5000001,
            ip_address  = "192.168.100.50",
            clk_freq    = self.clk_freq)
        # etherbone
        self.submodules.etherbone = LiteEthEtherbone(self.ethcore.udp, 1234)
        self.add_wb_master(self.etherbone.wishbone.bus)
        # timing constraints
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_rx.clk, 1e9/50e6)
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_tx.clk, 1e9/50e6)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.ethphy.crg.cd_eth_rx.clk,
            self.ethphy.crg.cd_eth_tx.clk)
        """

SoC = NetSoC
