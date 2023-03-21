#! /usr/bin/env python3
import datetime
import os
import sys
from collections import Counter
from pathlib import Path
from io import BufferedReader

from mbr import MBR
from superblock import SuperBlock, Flight
from sd_block import *
from data_block import *


MISSION_EXTENSION = "cuinspace"

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
                      'Speed (knots),Course (degs),PDOP,HDOP,VDOP,Sats in Fix,Fix Type\n')
    d = block.data
    outfile.write(f"{mt_to_ms(d.mission_time)},{d.latitude / 600000},"
                  f"{d.longitude / 600000},{d.utc_time},{d.altitude},"
                  f"{d.speed},{d.course},{d.pdop},{d.hdop},{d.vdop},{d.sats},{d.fix_type.name}\n")


def log_gnss_meta(block, outfile, index):
    """ GNSSMetadataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),GPS sats in use,GLONASS sats in use, Sats in view\n')
    d = block.data

    # Alternative sats_in_view output
    sat_string = ""
    for sat in d.sats_in_view:
        sat_string += ' '.join(str(item) for item in list(dict(sat).values())) + " "

    outfile.write(f"{mt_to_ms(d.mission_time)},[{' '.join(str(sat) for sat in d.gps_sats_in_use)}],"
                  f"[{' '.join(str(sat) for sat in d.glonass_sats_in_use)}],"
                  f"[{' '.join(str(dict(sat)['id']) for sat in d.sats_in_view)}]\n")


def log_kx134(block, outfile, index):
    """ KX134AccelerometerDataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),ODR (Hz),Range (g),LPF Rolloff (ODR/x),'
                      'Resolution (bits),X (g),Y (g),Z (g)\n')
    d = block.data
    for time, x, y, z in block.data.gen_samples():
        outfile.write(f"{time},{d.odr.samples_per_sec},{d.accel_range.acceleration},"
                      f"{'9' if d.rolloff == KX134LPFRolloff.ODR_OVER_9 else '2'},"
                      f"{d.resolution.bits},{x},{y},{z}\n")


def log_mpu9250(block, outfile, index):
    """ MPU9250IMUDataBlock """
    if index == 0:
        # write header
        outfile.write('Mission Time (ms),Accel/Gyro Sample Rate (Hz),Mag Sample Rate (Hz),'
                      'Accel FSR (g),Gyro FSR (deg/s),Accel Bandwidth (Hz),Gyro '
                      'Bandwidth,Accel X (g),Accel Y (g),Accel Z (g),Gyro X (dps),'
                      'Gyro Y (dps),Gyro Z (dps),Mag X (uT),Mag Y (uT),Mag Z '
                      '(uT),Mag Overflow,Mag Res (bits),Temperature (°C)\n')
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


def sanitize_superblock(superblock, flights_to_keep: list[Flight]):
    """ Sanitizes the superblock by shifting flights and only keeping specified flights for telemetry mission """
    flight_blocks_stored = 1
    # Loop over every flight spot
    for i in range(32):
        # Location of flight struct in superblock
        flight_start = 0x60 + (12 * i)

        # Zero out unused flight data holders
        if len(flights_to_keep) == 0:
            superblock[flight_start:flight_start + 12] = b'\x00'*12
            break

        # Shift flight block numbering to properly match
        flight = flights_to_keep[0]
        flight.first_block = flight_blocks_stored
        flight_blocks_stored += flight.num_blocks

        # Output adjusted flight to superblock
        superblock[flight_start:flight_start + 12] = flight.to_bytes()

        # Remove flight shifted
        flights_to_keep.pop(0)
    return superblock


def create_telemetry_mission(file: BufferedReader, mission_filename: str, superblock_addr: int,
                             flights_list: list[Flight]):
    """ CONSTRUCT TELEMETRY MISSION FILE FROM SD CARD IMAGE FILE """
    """ FIRST BLOCK IS A SUPERBLOCK, FOLLOWED BY SD DATA BLOCKS """

    missions_dir = Path.cwd().joinpath("missions")
    missions_dir.mkdir(parents=True, exist_ok=True)
    output_file_path = missions_dir.joinpath(f"{mission_filename}.{MISSION_EXTENSION}")

    # Generates the new telemetry mission file
    with open(output_file_path, "wb") as outfile:
        # Sanitize superblock
        file.seek(superblock_addr * 512)
        new_sb = sanitize_superblock(bytearray(file.read(512)), flights_list.copy())
        outfile.write(new_sb)

        # Show user the new flight details
        print("NEW TELEMETRY FLIGHT DETAILS")
        SuperBlock(new_sb).output()

        # Output corresponding flight blocks to output file
        for flight_to_copy in flights_list:
            file.seek((superblock_addr + flight_to_copy.first_block) * 512)

            # Copy each block to new file
            for i in range(flight_to_copy.num_blocks):
                outfile.write(file.read(512))


block_handlers = {
    LoggingMetadataSpacerBlock: (None, None),
    DiagnosticDataLogMessageBlock: (log_diag_message, "log_messages"),
    DebugMessageDataBlock: (log_diag_message, "log_messages"),
    DiagnosticDataOutgoingRadioPacketBlock: (log_diag_radio, "outgoing_radio_packets"),
    DiagnosticDataIncomingRadioPacketBlock: (log_diag_radio, "incoming_radio_packets"),
    AltitudeDataBlock: (log_altitude, "altitude"),
    GNSSLocationBlock: (log_gnss_loc, "gnss_location"),
    GNSSMetadataBlock: (log_gnss_meta, "gnss_metadata"),
    KX134AccelerometerDataBlock: (log_kx134, "kx134_accelerometer"),
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
            # print(count, ((num_blocks * 512) - 4), block_length, num_blocks*512)
            return

        count = count + block_length
        if count > (num_blocks * 512):
            raise ParsingException(f"Read block of length {block_length} would read {count} bytes "
                                   f"from {num_blocks * 512} byte flight")

        block = header + file.read(block_length - 4)
        # print(block.hex().upper())
        #        print(SDBlock.from_bytes(block))
        yield SDBlock.from_bytes(block), block


def parse_flight(file, imagedir: Path, part_offset, flight_num, flight):
    print(f"############### Flight {flight_num} ###############")
    print(f"Starts at block: {flight.first_block}, {flight.num_blocks} "
          f"block{'s' if flight.num_blocks != 1 else ''} long, time: {flight.timestamp}")

    # Create flight
    flightdir = imagedir.joinpath(f"flight_{flight_num}")
    try:
        flightdir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(f"Flight {i} has already been parsed. Not parsing again.")
        return

    # Open output files for writing
    outfiles = dict((k, open(os.path.join(flightdir, f"{v[1]}.csv"), "w")) for (k, v) in
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

infile = sys.argv[1]
# Create output directory
outdir = Path.cwd().joinpath("out")
outdir.mkdir(parents=True, exist_ok=True)

image_directory = outdir.joinpath(infile)
image_directory.mkdir(parents=True, exist_ok=True)

# Read input file
with open(infile, "rb") as file:
    # Read MBR
    superblock_addr = None
    try:
        mbr = MBR(file.read(512))
    except ValueError as e:
        print("No valid MBR found, assuming that first block is superblock.")
        superblock_addr = 0
    else:
        # Look for a valid partition
        for part in mbr.partitions:
            if part.type == 0x89:
                superblock_addr = part.first_sector_lba
                break

        if superblock_addr is None:
            exit("No CUInSpace partition found in MBR.")

    # Parse superblock
    file.seek(superblock_addr * 512)
    try:
        sb = SuperBlock(file.read(512))
    except ValueError:
        exit("Could not parse superblock.")

    # Output superblock
    sb.output()

    cmd = 0
    flights_selected = list(range(len(sb.flights)))

    while cmd != 4:
        print(f"Telemetry Parser commands                 Selected [{','.join(str(num) for num in flights_selected)}]\n"
              "1) Select flights\n"
              "2) Generate .cuinspace mission file\n"
              "3) Parse telemetry into CSV files\n"
              "4) Exit")
        cmd = int(input("What would you like to do? ").strip())

        match cmd:
            case 1:
                # Select certain flights to generate mission file from or parse into csv
                flights_selected = input("Flights to select (CSVs): ").strip().split(",")
                flights_selected = [] if flights_selected == [""] else [int(num) for num in flights_selected if
                                                                        int(num) in range(len(sb.flights))]
                flights_selected.sort()
            case 2:
                # Generate cuinspace mission file
                if len(flights_selected) == 0:
                    print("No flights selected. Please select at least one flight.")
                else:
                    mission_name = input("Mission name: ").strip()
                    mission_flights = list()
                    print("##### FLIGHTS TO KEEP #####")
                    for num in flights_selected:
                        flight = sb.flights[num]
                        mission_flights.append(flight)
                        print(f"Flight {num} -> start: {flight.first_block}, length: {flight.num_blocks}, time: {flight.timestamp}")
                    print("###########################")

                    create_telemetry_mission(file, mission_name, superblock_addr, mission_flights)
            case 3:
                # Parse telemetry to CSV Files
                if len(flights_selected) == 0:
                    # Empty flights list
                    print("No flights selected. Please select at least one flight.")
                else:
                    # Parse each selected flight
                    for i, flight in enumerate(sb.flights):
                        if int(i) in flights_selected:
                            parse_flight(file, image_directory, superblock_addr, i, flight)
                    print("########################################")
                    print(f"Successfully parsed flights selected [{','.join(str(num) for num in flights_selected)}]\n")
