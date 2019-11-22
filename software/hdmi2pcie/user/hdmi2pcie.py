#!/usr/bin/env python3

import argparse
import struct

parser = argparse.ArgumentParser()
parser.add_argument("-f", "--file", required=True)
parser.add_argument("-d", "--dev", default='/dev/netv20')
parser.add_argument("-r", "--read", action="store_true")
parser.add_argument("-b", "--buffer", default=0)
parser.add_argument("-x", "--xres", default=800)
parser.add_argument("-y", "--yres", default=600)

buf_base = 0x1000000
buf_size = 0x400000

args = parser.parse_args()

def reverse(buf):
    size = int(len(buf)/4)

    return struct.pack('<{}I'.format(size), *struct.unpack('>{}I'.format(size), buf))

def main():
    if args.read:
        with open(args.dev, 'rb') as dev:
            with open(args.file, 'wb') as f:
                dev.seek(int(buf_base + buf_size * int(args.buffer)), 0)
                data = bytearray(dev.read(int(int(args.xres) * int(args.yres) * 2)))
                f.write(reverse(data))
    else:
        with open(args.dev, 'wb') as dev:
            with open(args.file, 'rb') as f:
                data = bytearray(f.read())
                dev.write(reverse(data))

if __name__ == "__main__":
    main()
