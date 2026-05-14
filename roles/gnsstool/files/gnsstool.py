#!/usr/bin/env python3
"""
gnsstool — u-blox GNSS chip status via I2C DDC (bus 1, addr 0x42)

Communicates via I2C only — does not touch /dev/ttyS0 used by TimeBeat.

Usage:
    gnsstool status                    Fix type, position, satellite count, UTC time
    gnsstool satellites                Per-satellite signal strength and constellation breakdown
    gnsstool platform                  Current dynamic platform mode and timing notes
    gnsstool platform set <mode>       Set platform mode: stationary | portable
"""

import argparse
import struct
import sys
import time

import smbus2

BUS  = 1
ADDR = 0x42

GNSS_NAMES = {
    0: 'GPS',
    1: 'SBAS',
    2: 'Galileo',
    3: 'BeiDou',
    4: 'IMES',
    5: 'QZSS',
    6: 'GLONASS',
}

FIX_TYPES = {
    0: 'No fix',
    1: 'Dead reckoning',
    2: '2D fix',
    3: '3D fix',
    4: 'GNSS + dead reckoning',
    5: 'Time only (fixed position mode)',
}

DYNMODEL_NAMES = {
    0:  'Portable (default)',
    2:  'Stationary',
    3:  'Pedestrian',
    4:  'Automotive',
    5:  'Sea',
    6:  'Airborne <1g',
    7:  'Airborne <2g',
    8:  'Airborne <4g',
    9:  'Wrist',
    10: 'Bike',
}

# UBX class / ID pairs
NAV_PVT    = (0x01, 0x07)   # Position, velocity, time
NAV_SAT    = (0x01, 0x35)   # Satellite info
CFG_VALGET = (0x06, 0x8B)   # Get configuration value(s)
CFG_VALSET = (0x06, 0x8A)   # Set configuration value(s)

# Configuration key IDs (u-blox generation 9+)
CFG_NAVSPG_DYNMODEL = 0x20110021  # Dynamic platform model (U1)

DYNMODEL_STATIONARY = 2
DYNMODEL_PORTABLE   = 0


# ---------------------------------------------------------------------------
# UBX framing
# ---------------------------------------------------------------------------

def _ubx_checksum(data):
    ck_a = ck_b = 0
    for b in data:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a, ck_b


def _build_ubx(cls, msg_id, payload=b''):
    header = bytes([cls, msg_id]) + struct.pack('<H', len(payload))
    body   = header + payload
    ck_a, ck_b = _ubx_checksum(body)
    return bytes([0xB5, 0x62]) + body + bytes([ck_a, ck_b])


# ---------------------------------------------------------------------------
# I2C transport
# ---------------------------------------------------------------------------

def _read_available(bus):
    hi = bus.read_byte_data(ADDR, 0xFD)
    lo = bus.read_byte_data(ADDR, 0xFE)
    n  = (hi << 8) | lo
    return 0 if n == 0xFFFF else n


def _flush(bus):
    n = _read_available(bus)
    while n > 0:
        chunk = min(n, 32)
        bus.read_i2c_block_data(ADDR, 0xFF, chunk)
        n -= chunk


def _send_ubx(bus, cls, msg_id, payload=b''):
    frame = _build_ubx(cls, msg_id, payload)
    msg   = smbus2.i2c_msg.write(ADDR, [0xFF] + list(frame))
    bus.i2c_rdwr(msg)


def _collect_response(bus, deadline):
    """Read all available I2C bytes into a buffer until deadline."""
    buf = bytearray()
    while time.monotonic() < deadline:
        n = _read_available(bus)
        if n > 0:
            remaining = n
            while remaining > 0:
                chunk     = min(remaining, 32)
                buf      += bytearray(bus.read_i2c_block_data(ADDR, 0xFF, chunk))
                remaining -= chunk
            return buf
        time.sleep(0.05)
    return buf


def poll_ubx(bus, cls, msg_id, payload=b'', timeout=3.0):
    """
    Send a UBX poll request and return the response payload.
    Searches the accumulated I2C stream for the matching class/ID,
    ignoring interleaved NMEA sentences and other UBX messages.
    Returns bytes payload or None on timeout.
    """
    _flush(bus)
    _send_ubx(bus, cls, msg_id, payload)

    buf      = bytearray()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        n = _read_available(bus)
        if n > 0:
            remaining = n
            while remaining > 0:
                chunk     = min(remaining, 32)
                buf      += bytearray(bus.read_i2c_block_data(ADDR, 0xFF, chunk))
                remaining -= chunk

        i = 0
        while i <= len(buf) - 8:
            if buf[i] != 0xB5 or buf[i + 1] != 0x62:
                i += 1
                continue
            if buf[i + 2] != cls or buf[i + 3] != msg_id:
                i += 1
                continue
            length = struct.unpack_from('<H', buf, i + 4)[0]
            end    = i + 6 + length + 2
            if len(buf) < end:
                break
            body       = bytes(buf[i + 2: i + 6 + length])
            ck_a, ck_b = _ubx_checksum(body)
            if buf[end - 2] == ck_a and buf[end - 1] == ck_b:
                return bytes(buf[i + 6: i + 6 + length])
            i += 1

        time.sleep(0.05)

    return None


# ---------------------------------------------------------------------------
# CFG-VALGET / CFG-VALSET helpers (u-blox generation 9+ configuration API)
# ---------------------------------------------------------------------------

def _key_value_size(key_id):
    """Return the byte size of a configuration value from its key ID encoding."""
    size_type = (key_id >> 28) & 0xF
    return {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}.get(size_type, 1)


def cfg_valget(bus, key_id, layer=0):
    """
    Read a single configuration item via CFG-VALGET.
    layer: 0=RAM (current), 1=BBR, 2=Flash.
    Returns the value or None on failure.
    """
    req = struct.pack('<BBH', 0, layer, 0) + struct.pack('<I', key_id)
    data = poll_ubx(bus, *CFG_VALGET, payload=req)
    if not data or len(data) < 5:
        return None
    # Response layout: version(1) layer(1) position(2) [key(4) value(N)]...
    off = 4
    while off + 4 <= len(data):
        resp_key = struct.unpack_from('<I', data, off)[0]
        off += 4
        size = _key_value_size(resp_key)
        if off + size > len(data):
            break
        if resp_key == key_id:
            if size == 1:
                return data[off]
            elif size == 2:
                return struct.unpack_from('<H', data, off)[0]
            elif size == 4:
                return struct.unpack_from('<I', data, off)[0]
            elif size == 8:
                return struct.unpack_from('<Q', data, off)[0]
        off += size
    return None


def cfg_valset(bus, key_id, value, layers=1):
    """
    Write a configuration item via CFG-VALSET.
    layers bitmask: bit0=RAM, bit1=BBR, bit2=Flash. Default 1=RAM only (lost on restart).
    Returns True on ACK, False on NAK, None on timeout.
    """
    size      = _key_value_size(key_id)
    key_bytes = struct.pack('<I', key_id)
    if size == 1:
        val_bytes = struct.pack('B', value)
    elif size == 2:
        val_bytes = struct.pack('<H', value)
    elif size == 4:
        val_bytes = struct.pack('<I', value)
    else:
        val_bytes = struct.pack('<Q', value)

    req = struct.pack('<BBH', 0, layers, 0) + key_bytes + val_bytes
    _flush(bus)
    _send_ubx(bus, *CFG_VALSET, req)

    buf      = bytearray()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        n = _read_available(bus)
        if n > 0:
            remaining = n
            while remaining > 0:
                chunk     = min(remaining, 32)
                buf      += bytearray(bus.read_i2c_block_data(ADDR, 0xFF, chunk))
                remaining -= chunk
        i = 0
        while i <= len(buf) - 8:
            if buf[i] != 0xB5 or buf[i + 1] != 0x62:
                i += 1
                continue
            if buf[i + 2] != 0x05:   # ACK class
                i += 1
                continue
            ack_id = buf[i + 3]
            length = struct.unpack_from('<H', buf, i + 4)[0]
            end    = i + 6 + length + 2
            if len(buf) < end:
                break
            if length >= 2 and buf[i + 6] == CFG_VALSET[0] and buf[i + 7] == CFG_VALSET[1]:
                return ack_id == 0x01   # 0x01=ACK → True, 0x00=NAK → False
            i += 1
        time.sleep(0.05)
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_status(_args):
    with smbus2.SMBus(BUS) as bus:
        payload = poll_ubx(bus, *NAV_PVT)

    if not payload or len(payload) < 84:
        print("Error: no NAV-PVT response from chip — check i2cdetect -y 1 shows 0x42")
        return 1

    year, month, day  = struct.unpack_from('<HBB', payload, 4)
    hour, minute, sec = struct.unpack_from('BBB',  payload, 8)
    valid             = payload[11]
    t_acc             = struct.unpack_from('<I', payload, 12)[0]
    fix_type          = payload[20]
    flags             = payload[21]
    num_sv            = payload[23]
    lon               = struct.unpack_from('<i', payload, 24)[0] * 1e-7
    lat               = struct.unpack_from('<i', payload, 28)[0] * 1e-7
    h_msl             = struct.unpack_from('<i', payload, 36)[0] / 1000.0
    h_acc             = struct.unpack_from('<I', payload, 40)[0] / 1000.0
    v_acc             = struct.unpack_from('<I', payload, 44)[0] / 1000.0
    p_dop             = struct.unpack_from('<H', payload, 76)[0] * 0.01

    gnss_fix   = bool(flags & 0x01)
    time_valid = bool(valid & 0x04)
    lat_dir    = 'N' if lat >= 0 else 'S'
    lon_dir    = 'E' if lon >= 0 else 'W'

    print(f"Fix type:    {FIX_TYPES.get(fix_type, f'Unknown ({fix_type})')}")
    print(f"Satellites:  {num_sv} used in fix")
    if gnss_fix:
        print(f"Position:    {abs(lat):.6f}°{lat_dir}  {abs(lon):.6f}°{lon_dir}  ±{h_acc:.1f}m")
        print(f"Altitude:    {h_msl:.1f}m MSL  ±{v_acc:.1f}m")
        print(f"PDOP:        {p_dop:.2f}")
    else:
        print("Position:    No fix yet")
    if time_valid:
        print(f"UTC time:    {year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{sec:02d}  ±{t_acc}ns")
    else:
        print("UTC time:    Not yet valid")
    return 0


def cmd_satellites(_args):
    with smbus2.SMBus(BUS) as bus:
        payload = poll_ubx(bus, *NAV_SAT)

    if not payload or len(payload) < 8:
        print("Error: no NAV-SAT response from chip")
        return 1

    num_svs = payload[5]
    sats    = []

    for i in range(num_svs):
        off = 8 + i * 12
        if off + 12 > len(payload):
            break
        gnss_id = payload[off]
        sv_id   = payload[off + 1]
        cno     = payload[off + 2]
        elev    = struct.unpack_from('b',  payload, off + 3)[0]
        azim    = struct.unpack_from('<h', payload, off + 4)[0]
        flags   = struct.unpack_from('<I', payload, off + 8)[0]
        used    = bool(flags & 0x08)
        name    = GNSS_NAMES.get(gnss_id, f'Unknown({gnss_id})')
        sats.append(dict(gnss=name, sv_id=sv_id, cno=cno, elev=elev, azim=azim, used=used))

    from collections import defaultdict
    by_gnss = defaultdict(list)
    for s in sats:
        if s['gnss'] not in ('SBAS', 'IMES', 'Mixed'):
            by_gnss[s['gnss']].append(s)

    print("--- Constellation Summary ---")
    print(f"  {'Constellation':<12} {'SVs':>4}  {'Avg SNR':>7}  {'Strong':>6}  {'Fair':>5}  {'Weak':>5}")
    print(f"  {'-' * 48}")
    for name in sorted(by_gnss):
        group = by_gnss[name]
        snrs  = [s['cno'] for s in group if s['cno'] > 0]
        if not snrs:
            continue
        avg    = sum(snrs) / len(snrs)
        strong = sum(1 for s in snrs if s >= 35)
        fair   = sum(1 for s in snrs if 20 <= s < 35)
        weak   = sum(1 for s in snrs if s < 20)
        print(f"  {name:<12} {len(group):>4}  {avg:>7.1f}  {strong:>6}  {fair:>5}  {weak:>5}")

    tracked = sorted(
        [s for s in sats if s['cno'] > 0 and s['gnss'] not in ('SBAS', 'IMES', 'Mixed')],
        key=lambda s: -s['cno'],
    )

    print(f"\n--- Satellites ({len(tracked)} tracked) ---")
    print(f"  {'Satellite':<14} {'Elev':>5}  {'Az':>4}  {'SNR':>4}  {'Used':>5}")
    print(f"  {'-' * 40}")
    for s in tracked:
        label = f"{s['gnss']}/{s['sv_id']:02d}"
        used  = 'yes' if s['used'] else '-'
        print(f"  {label:<14} {s['elev']:>4}°  {s['azim']:>3}°  {s['cno']:>4}  {used:>5}")

    print(f"\n  SNR guide: <20 weak | 20-34 fair | 35-44 good | >=45 excellent")
    return 0


def cmd_platform_status(_args):
    with smbus2.SMBus(BUS) as bus:
        dynmodel = cfg_valget(bus, CFG_NAVSPG_DYNMODEL)

    if dynmodel is None:
        print("Error: no response from chip — check i2cdetect -y 1 shows 0x42")
        return 1

    name = DYNMODEL_NAMES.get(dynmodel, f'Unknown ({dynmodel})')
    print(f"Platform mode:  {name}  (CFG-NAVSPG-DYNMODEL = {dynmodel})")
    print()
    if dynmodel == DYNMODEL_STATIONARY:
        print("The chip is in stationary mode: velocity is constrained to zero and zero-dynamics")
        print("are assumed. This is the recommended configuration for a fixed timing antenna.")
        print("Expected PPS accuracy: tens of nanoseconds.")
    elif dynmodel == DYNMODEL_PORTABLE:
        print("The chip is in portable mode (factory default): position and time are solved")
        print("independently each fix. Position uncertainty adds directly to timing error.")
        print("For better PPS accuracy with a fixed antenna:")
        print("  gnsstool platform set stationary")
    else:
        print(f"Mode {dynmodel} is not optimised for static timing. For best PPS accuracy:")
        print("  gnsstool platform set stationary")
    return 0


def cmd_platform_set(args):
    mode_map = {'stationary': DYNMODEL_STATIONARY, 'portable': DYNMODEL_PORTABLE}
    value    = mode_map[args.mode]
    name     = DYNMODEL_NAMES[value]

    with smbus2.SMBus(BUS) as bus:
        result = cfg_valset(bus, CFG_NAVSPG_DYNMODEL, value, layers=1)   # RAM only

    if result is True:
        print(f"Platform mode set to: {name}")
        print()
        print("Note: change is RAM-only and will be lost on chip reset or power cycle.")
        if value == DYNMODEL_STATIONARY:
            print("TimeBeat may override this on restart — check its GNSS configuration.")
    elif result is False:
        print("Error: chip rejected the configuration (NAK)")
        return 1
    else:
        print("Error: no ACK from chip — change may not have taken effect")
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog='gnsstool',
        description='u-blox GNSS chip status and configuration via I2C',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  gnsstool status\n"
            "  gnsstool satellites\n"
            "  gnsstool platform\n"
            "  gnsstool platform set stationary\n"
            "  gnsstool platform set portable\n"
        ),
    )
    sub = parser.add_subparsers(dest='command', metavar='command')
    sub.required = True

    sub.add_parser('status',     help='Fix type, position, satellite count, UTC time')
    sub.add_parser('satellites', help='Per-satellite signal strength and constellation breakdown')

    platform_p   = sub.add_parser('platform', help='Dynamic platform mode (affects timing accuracy)')
    platform_sub = platform_p.add_subparsers(dest='platform_command', metavar='subcommand')

    platform_sub.add_parser('status', help='Show current platform mode and timing notes')

    set_p = platform_sub.add_parser('set', help='Set platform mode (RAM only, lost on restart)')
    set_p.add_argument('mode', choices=['stationary', 'portable'],
                       help='stationary: timing-optimised | portable: factory default')

    args = parser.parse_args()

    try:
        if args.command == 'status':
            sys.exit(cmd_status(args))
        elif args.command == 'satellites':
            sys.exit(cmd_satellites(args))
        elif args.command == 'platform':
            platform_cmd = getattr(args, 'platform_command', None)
            if platform_cmd is None or platform_cmd == 'status':
                sys.exit(cmd_platform_status(args))
            elif platform_cmd == 'set':
                sys.exit(cmd_platform_set(args))
    except PermissionError:
        print("Error: cannot open I2C bus — check you are in the i2c group (run: id | grep i2c)")
        sys.exit(1)
    except OSError as e:
        print(f"Error: I2C error — {e}")
        print("Check: ls /dev/i2c-*  and  i2cdetect -y 1  (expect 0x42)")
        sys.exit(1)


if __name__ == '__main__':
    main()
