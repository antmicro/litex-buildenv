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
    csr_peripherals = (
        "ethphy",
        "ethmac",
    )
    csr_map_update(BaseSoC.csr_map, csr_peripherals)

    mem_map = {
        "ethmac": 0x30000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, platform, *args, **kwargs):
        BaseSoC.__init__(self, platform, integrated_rom_size=0x10000, *args, **kwargs)

        clk_freq = int(100e6)
        mac_address = 0x10e2d5000001
        ip_address = convert_ip("192.168.100.60")
        dw = 32

        self.submodules.ethphy = LiteEthPHYRMII(
            platform.request("eth_clocks"),
            platform.request("eth"))
        
        self.submodules.ethmac = LiteEthMAC(
            phy=self.ethphy, dw=dw, interface="hybrid", endianness=self.cpu.endianness)

        self.submodules.arp = LiteEthARP(self.ethmac, mac_address, ip_address, clk_freq, dw=dw)
        self.submodules.ip = LiteEthIP(self.ethmac, mac_address, ip_address, self.arp.table, dw=dw)
        self.submodules.icmp = LiteEthICMP(self.ip, ip_address, dw=dw)
        self.submodules.udp = LiteEthUDP(self.ip, ip_address, dw=dw)

        # UDP loopback @ 9001
        port = self.udp.crossbar.get_port(9001, dw)
        self.submodules.buf = buf = stream.SyncFIFO(eth_udp_user_description(dw), 2048)
        self.comb += Port.connect(port, buf)

        self.add_wb_slave(mem_decoder(self.mem_map["ethmac"]), self.ethmac.bus)
        self.add_memory_region("ethmac",
            self.mem_map["ethmac"] | self.shadow_base, 0x2000)


        self.ethphy.crg.cd_eth_rx.clk.attr.add("keep")
        self.ethphy.crg.cd_eth_tx.clk.attr.add("keep")
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_rx.clk, 40.0)
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_tx.clk, 40.0)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.ethphy.crg.cd_eth_rx.clk,
            self.ethphy.crg.cd_eth_tx.clk)

        self.add_interrupt("ethmac")

SoC = NetSoC
