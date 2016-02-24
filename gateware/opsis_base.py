#!/usr/bin/env python3

import argparse
import os
import importlib

from litex.gen import *
from litex.gen.genlib.io import CRG

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *

import opsis_platform

class BaseSoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform,
            clk_freq=int((1/(platform.default_clk_period))*1000000000),
            integrated_rom_size=0x8000,
            integrated_main_ram_size=0x8000,
            **kwargs)
        self.submodules.crg = CRG(platform.request(platform.default_clk_name))

def main():
    parser = argparse.ArgumentParser(description="Opsis LiteX SoC")
    builder_args(parser)
    soc_core_args(parser)
    parser.add_argument("--build", action="store_true",
                        help="build bitstream")
    parser.add_argument("--load", action="store_true",
                        help="load bitstream")
    args = parser.parse_args()

    platform = opsis_platform.Platform()
    soc = BaseSoC(platform, **soc_core_argdict(args))
    builder = Builder(soc, **builder_argdict(args))

    if args.build:
        builder.build()

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.output_dir, "gateware", "top.bit"))

if __name__ == "__main__":
    main()
