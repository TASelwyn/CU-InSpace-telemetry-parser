#! /usr/bin/env python3
import os
import struct
import datetime
import sys


class Flight:
    def __init__(self, entry):
        parts = struct.unpack("<III", entry)
        self.first_block = parts[0]
        self.num_blocks = parts[1]
        self.time = datetime.datetime.fromtimestamp(parts[2], datetime.timezone.utc)
        self.timestamp = parts[2]

    def to_bytes(self):
        return struct.pack("<III", self.first_block, self.num_blocks, self.timestamp)


class SuperBlock:
    MAGIC = b'CUInSpac'

    def __init__(self, block):
        if len(block) != 512:
            raise ValueError("Invalid Superblock")

        if block[0x0:0x8] != SuperBlock.MAGIC or block[0x1f8:0x200] != SuperBlock.MAGIC:
            raise ValueError("Invalid Superblock")

        self.version = block[0x09]
        self.continued = not not (block[0x09] & 1)

        self.partition_length = struct.unpack("<I", block[0x0c:0x10])[0]

        self.flights = list()

        for i in range(32):
            flight_start = 0x60 + (12 * i)
            flight_entry = block[flight_start:flight_start + 12]
            self.flights.append(Flight(flight_entry))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        # No arguments
        exit(0)

    # File size
    file_size = os.stat(sys.argv[1]).st_size

    with open(sys.argv[1], "rb") as f:

        # Skip MBR and the rest of first sector to get to superblock
        # (512 bytes is just MBR, anything larger should be a full flight and blocks)
        #if file_size > 512:
            #f.seek(512 * 2048)

        sb = SuperBlock(f.read(512))

        print(f"Version: {sb.version}")
        print(f"First flight continued from previous partition: {'yes' if sb.continued else 'no'}")
        print(f"Partition length: {sb.partition_length}")
        print()

        last_block = 0
        for i, flight in enumerate(sb.flights):
            print(f"Flight {i} -> start: {flight.first_block}, length: {flight.num_blocks}, time: {flight.timestamp}")
            if flight.num_blocks != 0:
                last_block = flight.first_block + flight.num_blocks

        print()
        print(f"Last block: {last_block}")
        print(f"To copy full SD card image, use:    dd if=[disk] of=full bs=512 count={last_block + 2049}")
