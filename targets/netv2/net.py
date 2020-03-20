from litex.soc.integration.soc_core import mem_decoder
from litex.soc.integration.soc_sdram import *

from liteeth.core.mac import LiteEthMAC
from liteeth.core.arp import LiteEthARP
from liteeth.core.ip import LiteEthIP
from liteeth.core.udp import LiteEthUDP
from liteeth.core.icmp import LiteEthICMP
from liteeth.phy.rmii import LiteEthPHYRMII
from liteeth.frontend.etherbone import LiteEthEtherbone
from liteeth.frontend.rtp import LiteEthRTP
from litedram.frontend.dma import LiteDRAMDMAReader
from liteeth.common import *
from liteeth.core import LiteEthUDPIPCore

from targets.utils import csr_map_update
from targets.netv2.base import SoC as BaseSoC

class FrameGen(Module):
    def __init__(self, width=1024, height=512, bpp=2):
        self.source = source = stream.Endpoint([("data", 8)])
        cnt = Signal(32)
        dst = width*height*bpp
        data = Signal(8)

        self.comb += [
            source.valid.eq(1),
            source.first.eq(0),
            source.data.eq(data),
            source.last.eq(cnt == dst-1),
        ]

        self.sync += [
            If(source.valid & source.ready,
                If(cnt == dst-1, cnt.eq(0)).Else(cnt.eq(cnt+1))
            ),
            If(source.last, data.eq(data+16)),
        ]

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
        ip_address = convert_ip("192.168.1.30")
        cpu_ip = "192.168.1.31"
        target_ip = convert_ip("192.168.1.200")
        dw = 8

        for i in range(4):
            self.add_constant("LOCALIP{}".format(i+1), int(cpu_ip.split(".")[i]))

        self.submodules.ethphy = LiteEthPHYRMII(
            platform.request("eth_clocks"),
            platform.request("eth"))
        self.add_csr("ethphy")

        hybrid=False
        
        if hybrid:
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
            udp = self.udp
        else:
            self.submodules.ethcore = LiteEthUDPIPCore(
                phy = self.ethphy,
                mac_address = mac_address,
                ip_address = ip_address,
                clk_freq = clk_freq,
            )
            udp = self.ethcore.udp

        # Etherbone
        #self.submodules.etherbone = LiteEthEtherbone(self.ethcore.udp, 1234, mode="master")
        #self.add_wb_master(self.etherbone.wishbone.bus)

        # RTP TX @ 9000
        self.submodules.rtp = rtp = LiteEthRTP(udp, ip_address=target_ip, pkt_size=1024)

        rtp_gen=False

        if rtp_gen:
            self.submodules.gen = gen = FrameGen(1024, 768, 2)
            self.comb += gen.source.connect(rtp.sink)
        else:
            cnt = Signal(32)
            rtp_tx_port = self.sdram.crossbar.get_port(
                mode="read",
                data_width=8,
                reverse=True,
            )

            self.sync += If(rtp.sink.last, cnt.eq(0)).Else(cnt.eq(cnt+1))
            self.comb += rtp.sink.last.eq(cnt == (1024*768*2-1))

            self.submodules.rtp_tx_dma = LiteDRAMDMAReader(rtp_tx_port)
            self.rtp_tx_dma.add_csr()
            self.add_csr("rtp_tx_dma")
            self.comb += self.rtp_tx_dma.source.connect(rtp.sink)

        self.ethphy.crg.cd_eth_rx.clk.attr.add("keep")
        self.ethphy.crg.cd_eth_tx.clk.attr.add("keep")
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_rx.clk, 20.0)
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_tx.clk, 20.0)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.ethphy.crg.cd_eth_rx.clk,
            self.ethphy.crg.cd_eth_tx.clk)


SoC = NetSoC
