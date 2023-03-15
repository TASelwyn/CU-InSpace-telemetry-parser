#! /usr/bin/env python3
import datetime
import os
import sys
from collections import Counter

from mbr import MBR
from superblock import SuperBlock
from sd_block import *
from data_block import *


def mt_to_ms(mt):
    """ Convert mission time to milliseconds """
    return mt * (1000 / 1024)


class ParsingException(Exception):
    pass


def write_row(file, data, header=False):
    wrap = '' if header else ''
    file.write(",".join(wrap + i + wrap for i in data.columns) + "\n")


def log_diag_message(block, outfile, index):
    """ DiagnosticDataLogMessageBlock and DebugMessageDataBlock """
    outfile.write(str(block))
    outfile.write("\n")


def log_diag_radio(block, outfile, index):
    """ DiagnosticDataOutgoingRadioPacketBlock and DiagnosticDataIncomingRadioPacketBlock """
    print(f"Log diag radio not yet implemented: {block}")


def log_altitude(block, outfile, index):
    """ AltitudeDataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),Pressure (Pa),Temperature (C),Altitude (m)\n')
    d = block.data
    outfile.write(f"{mt_to_ms(d.mission_time)},{d.pressure},{d.temperature},{d.altitude}\n")


def log_gnss_loc(block, outfile, index):
    """ GNSSLocationBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),Latitude,Longitude,UTC Time,Altitude (m),'
                      'Speed (knots),Course (°),PDOP,HDOP,VDOP,Sats in Fix,Fix Type\n')
    d = block.data
    outfile.write(f"{mt_to_ms(d.mission_time)},{GNSSLocationBlock.coord_to_str(d.latitude)},"
                  f"{GNSSLocationBlock.coord_to_str(d.longitude)},{d.utc_time},{d.altitude},"
                  f"{d.speed},{d.course},{d.pdop},{d.hdop},{d.vdop},{d.sats},{d.fix_type.name}\n")


def log_gnss_meta(block, outfile, index):
    """ GNSSMetadataBlock """
    outfile.write(str(block))
    outfile.write("\n")


def log_kx134(block, outfile, index):
    """ KX134AccelerometerDataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),ODR (Hz),Range (g),LPF Rolloff (ODR/x),'
                      'Resolution (bits),X (g),Y (g),Z (g)\n')
    d = block.data
    for time, x, y, z in block.data.gen_samples():
        outfile.write(f"{time},{d.odr.samples_per_sec}\t±{d.accel_range.acceleration},"
                      f"{'9' if d.rolloff == KX134LPFRolloff.ODR_OVER_9 else '2'},"
                      f"{d.resolution.bits},{x},{y},{z}\n")


def log_mpu9250(block, outfile, index):
    """ MPU9250IMUDataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),Accel/Gyro Sample Rate (Hz),Mag Sample Rate (Hz),'
                      'Accel FSR (g),Gyro FSR (deg/s),Accel Bandwidth (Hz),Gyro '
                      'Bandwidth,Accel X (g),Accel Y (g),Accel Z (g),Gyro X (dps),'
                      'Gyro Y (dps),Gyro Z (dps),Mag X (µT),Mag Y (µT),Mag Z '
                      '(µT),Mag Overflow,Mag Res (bits),Temperature (°C)\n')
    d = block.data
    for time, s in block.data.gen_samples():
        outfile.write(f"{time},{d.ag_sample_rate},{d.mag_sample_rate.samples_per_sec},"
                      f"{d.accel_fsr.acceleration},{d.gyro_fsr.angular_velocity},"
                      f"{d.accel_bw.bandwidth},{d.gyro_bw.bandwidth},{s.accel_x},"
                      f"{s.accel_y},{s.accel_z},{s.gyro_x},{s.gyro_y},{s.gyro_z},{s.mag_x},"
                      f"{s.mag_y},{s.mag_z},{s.mag_ovf},{s.mag_res.bits},{s.temperature}\n")


def log_status(block, outfile, index):
    """ StatusDataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),KX134 State,Altimeter State,IMU State'
                      'SD Card Driver State,Deployment State,SD Blocks Recorded,'
                      'SD Checkouts Missed\n')
    d = block.data
    outfile.write(f"{mt_to_ms(d.mission_time)},{str(d.kx134_state)},{str(d.alt_state)},"
                  f"{str(d.imu_state)},{str(d.sd_state)},{str(d.deployment_state)},"
                  f"{d.sd_blocks_recorded},{d.sd_checkouts_missed}\n")


def log_acceleration(block, outfile, index):
    """ AccelerationDataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),FSR (g),X (g),Y (g),Z (g)\n')
    d = block.data
    outfile.write(f"{mt_to_ms(d.mission_time)},{d.fsr},{d.x},{d.y},{d.z}\n")


def log_angular_velocity(block, outfile, index):
    """ AngularVelocityDataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),FSR (dps),X (dps),Y (dps),Z (dps)\n')
    d = block.data
    outfile.write(f"{mt_to_ms(d.mission_time)},{d.fsr},{d.x},{d.y},{d.z}\n")


def log_telemetry_mission(rawblock, file, index, flight=None):
    """ TELEMETRY MISSION """

    with open(file, "a") as outfile:
        if index == 0:
            # write header
            if flight is not None:
                # = datetime.datetime.strptime("2022-11-14 14:01:18+00:00", "%Y-%M-%D %H:%M:%")
                outfile.write(f'{0},{flight.timestamp}\n')
                print(0, flight.timestamp)

        block_head = struct.unpack("<HH", rawblock[0:4])
        block_type = block_head[0] >> 6
        # block_length = block_head[1]

        # NEVER LOGS TELEMETRY TYPE. JUST SUBTYPE IN ITS PLACE. ? ? ?
        datablock_subtype = block_type
        # THEREFORE ASSUMING ITS ALWAYS A DATA PACKET {Not CONTROL OR COMMAND}

        payload = rawblock[4:]
        msg_to_write = f"{','.join([str('2'), str(datablock_subtype), payload.hex()])}\n"
        #print(msg_to_write)
        outfile.write(msg_to_write)
        outfile.close()


block_handlers = {
    LoggingMetadataSpacerBlock: (None, None),
    DiagnosticDataLogMessageBlock: (log_diag_message, "log_messages"),
    DebugMessageDataBlock: (log_diag_message, "log_messages"),
    DiagnosticDataOutgoingRadioPacketBlock: (log_diag_radio, "outgoing_radio_packets"),
    DiagnosticDataIncomingRadioPacketBlock: (log_diag_radio, "incoming_radio_packets"),
    AltitudeDataBlock: (log_altitude, "altitude"),
    GNSSLocationBlock: (log_gnss_loc, "gnss_location"),
    GNSSMetadataBlock: (log_gnss_meta, "gnss_metadata"),
    KX134AccelerometerDataBlock: (log_kx134, "kx134_accel"),
    MPU9250IMUDataBlock: (log_mpu9250, "mpu9250_imu"),
    StatusDataBlock: (log_status, "status"),
    AccelerationDataBlock: (log_acceleration, "acceleration"),
    AngularVelocityDataBlock: (log_angular_velocity, "angular_velocity"),
}


def gen_blocks(file, first_block, num_blocks):
    # Seek to start of flight
    count = 0

    while count <= ((num_blocks * 512) - 4):
        header = file.read(4)

        try:
            block_length = SDBlock.parse_length(header)

        except SDBlockException:
            # END OF FILE EXCEPTION
            #print(count, ((num_blocks * 512) - 4), block_length, num_blocks*512)
            return

        count = count + block_length
        if count > (num_blocks * 512):
            raise ParsingException(f"Read block of length {block_length} would read {count} bytes "
                                   f"from {num_blocks * 512} byte flight")

        block = header + file.read(block_length - 4)
        # print(block.hex().upper())
        #        print(SDBlock.from_bytes(block))
        yield SDBlock.from_bytes(block), block


def parse_flight(file, outdir, part_offset, flight_num, flight):
    print(f"##### Flight {flight_num} #####")
    print(f"Starts at block: {flight.first_block}, {flight.num_blocks} "
          f"block{'s' if flight.num_blocks != 1 else ''} long, time: {flight.timestamp}")

    # Create flight directory
    flightdir = os.path.join(outdir, f"flight_{flight_num}")
    try:
        os.mkdir(flightdir)
    except FileExistsError:
        pass

    telem_mission_file = os.path.join(flightdir, "telemetry.mission")

    # Open output files for writing
    outfiles = dict((k, open(os.path.join(flightdir, v[1]), "w")) for (k, v) in
                    block_handlers.items() if v[1] is not None)

    # Read blocks and record data
    block_type_counts = Counter()
    spacer_bytes = 0
    num_blocks = 0
    total_bytes = 0
    first_time = None
    last_time = None


    file.seek((part_offset + flight.first_block) * 512)


    for block, rawblock in gen_blocks(file, flight.first_block, flight.num_blocks):
        num_blocks += 1

        cls = type(block)
        if cls == TelemetryDataBlock:
            cls = type(block.data)

            if first_time is None:
                first_time = mt_to_ms(block.data.mission_time)

            last_time = mt_to_ms(block.data.mission_time)

            # TELEM MISSION DATA FILE
            index = block_type_counts["telemetry"]
            block_type_counts["telemetry"] = index + 1


            log_telemetry_mission(rawblock, telem_mission_file, index, flight)

        # Increment count for block type
        block_type = (type(block), cls)
        index = block_type_counts[block_type]

        block_type_counts[block_type] = index + 1

        # If this is a spacer, add to the total
        if cls == LoggingMetadataSpacerBlock:
            spacer_bytes += block.length

        try:
            handler = block_handlers[cls][0]
            handler_name = block_handlers[cls][1]

            if handler is not None:
                handler(block, outfiles[cls], index)


        except KeyError as e:
            print(f"No handler for block of type {e.args[0].type_desc()}")

    # Close output files
    for f in outfiles.values():
        f.close()

    print(f"Read {num_blocks} entries, output to {flightdir}.")


if len(sys.argv) < 2:
    # No arguments
    exit(0)

outdir = "./out"
infile = sys.argv[1]

# Create output directory


# Read input file
with open(infile, 'rb') as f:
    # Read MBR
    try:
        mbr = MBR(f.read(512))
    except ValueError as e:
        print("No valid MBR found, assuming that first block is superblock.")
        superblock_addr = 0
    else:
        # Look for a valid partition
        part = None
        for p in mbr.partitions:
            if p.type == 0x89:
                part = p
                break
        if part is None:
            exit("No CUInSpace partition found in mbr.")
        superblock_addr = part.first_sector_lba

    # Parse superblock
    f.seek(superblock_addr * 512)
    try:
        sb = SuperBlock(f.read(512))
    except ValueError:
        exit("Could not parse superblock.")

    # Create output directory
    try:
        os.mkdir(outdir)
    except FileExistsError:
        exit("Output dir already exists.")

    # Parse flights

    print(sb.length)

    for i, flight in enumerate(sb.flights):
        print(i, flight, "AHHHHHHHH")
        if flight.num_blocks == 0:
            if i == 0:
                print("No flights.")
            break

        # ONLY PARSE FIRST FLIGHT
        if i == 1:
            parse_flight(f, outdir, superblock_addr, i, flight)
