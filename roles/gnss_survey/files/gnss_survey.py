#!/usr/bin/env python3
"""
gnss_survey.py — GNSS signal survey via u-blox MAX-F10S I2C DDC interface (bus 1, addr 0x42)

Reads satellite count and signal strength without touching /dev/ttyS0 (used by TimeBeat).
Results are saved to /opt/gnss_survey/surveys/survey_YYYY-MM-DD_HH-MM-SS.txt and printed to
the terminal.

Usage:
    sudo /opt/gnss_survey/venv/bin/python3 /opt/gnss_survey/gnss_survey.py [duration_seconds]

Default duration is 120 seconds.
"""

import smbus2
import time
import sys
import os
from collections import defaultdict
from datetime import datetime, timezone

BUS  = 1
ADDR = 0x42

CONSTELLATION = {
    'GP': 'GPS',
    'GL': 'GLONASS',
    'GA': 'Galileo',
    'GB': 'BeiDou',
    'GQ': 'QZSS',
    'GN': 'Mixed',
}


class Tee:
    """Write to both stdout and a file simultaneously."""
    def __init__(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self._file = open(filepath, 'w')
        self._stdout = sys.stdout
        sys.stdout = self

    def write(self, text):
        self._stdout.write(text)
        self._file.write(text)

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self):
        sys.stdout = self._stdout
        self._file.close()


def read_i2c_nmea(bus):
    """Read all available bytes from u-blox DDC stream register."""
    try:
        hi = bus.read_byte_data(ADDR, 0xFD)
        lo = bus.read_byte_data(ADDR, 0xFE)
        available = (hi << 8) | lo
        if available == 0 or available == 0xFFFF:
            return ""
        data = []
        remaining = available
        while remaining > 0:
            chunk = min(remaining, 32)
            data += bus.read_i2c_block_data(ADDR, 0xFF, chunk)
            remaining -= chunk
        return bytes(b for b in data if b not in (0x00, 0xFF)).decode('ascii', errors='ignore')
    except Exception:
        return ""


def parse_gsv(line):
    """
    Parse a $xxGSV sentence.
    Returns (talker, total_msgs, msg_num, total_sats, [(prn, snr_or_None), ...])
    or None on parse failure.
    """
    try:
        if '*' in line:
            line = line[:line.index('*')]
        parts = line.split(',')
        if len(parts) < 4:
            return None
        talker     = parts[0][1:3]
        total_msgs = int(parts[1])
        msg_num    = int(parts[2])
        total_sats = int(parts[3])
        sats = []
        i = 4
        while i + 3 <= len(parts):
            prn     = parts[i].strip()
            snr_str = parts[i + 3].strip() if (i + 3) < len(parts) else ''
            if prn:
                snr = int(snr_str) if snr_str else None
                sats.append((prn, snr))
            i += 4
        return talker, total_msgs, msg_num, total_sats, sats
    except (ValueError, IndexError):
        return None


def survey(duration_seconds):
    start_time = datetime.now(timezone.utc)
    outdir     = os.path.expanduser("~/gnss_surveys")
    outfile    = os.path.join(outdir, start_time.strftime("survey_%Y-%m-%d_%H-%M-%S.txt"))

    tee = Tee(outfile)

    try:
        _run_survey(duration_seconds, start_time, outfile)
    finally:
        tee.close()

    print(f"\nSaved to: {outfile}")


def _run_survey(duration_seconds, start_time, outfile):
    print(f"Saving to: {outfile}")
    print(f"Surveying GNSS for {duration_seconds}s — Ctrl-C to finish early")
    print(f"Started:   {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    try:
        bus = smbus2.SMBus(BUS)
    except Exception as e:
        print(f"Cannot open I2C bus {BUS}: {e}")
        print("Check: ls /dev/i2c-*  and  sudo i2cdetect -y 1  (expect 0x42)")
        return

    snr_samples        = defaultdict(list)   # "GP/01" → [snr, ...]
    in_view_per_talker = defaultdict(list)   # "GP"    → [total_sats, ...]

    buf        = ""
    end_time   = time.time() + duration_seconds
    last_print = time.time()

    try:
        while time.time() < end_time:
            buf += read_i2c_nmea(bus)

            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                line = line.strip()
                if not line.startswith('$') or len(line) < 6 or line[3:6] != 'GSV':
                    continue
                result = parse_gsv(line)
                if not result:
                    continue
                talker, total_msgs, msg_num, total_sats, sats = result

                for prn, snr in sats:
                    if snr is not None and snr > 0:
                        snr_samples[f"{talker}/{prn.zfill(2)}"].append(snr)

                if msg_num == total_msgs:
                    in_view_per_talker[talker].append(total_sats)

            if time.time() - last_print >= 10:
                elapsed = duration_seconds - (end_time - time.time())
                in_view = sum(s[-1] for s in in_view_per_talker.values() if s)
                print(f"  {elapsed:.0f}s elapsed — {in_view} sats in view, "
                      f"{len(snr_samples)} unique sats tracked")
                last_print = time.time()

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n(stopped early)")
    finally:
        bus.close()

    print()
    print_report(snr_samples, in_view_per_talker)


def print_report(snr_samples, in_view_per_talker):
    sep = "=" * 62
    print(sep)
    print("GNSS SURVEY RESULTS")
    print(f"Completed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(sep)

    if not snr_samples:
        print("\nNo GNSS data received — check i2cdetect -y 1 shows 0x42")
        return

    print("\n--- Satellites in View ---")
    total_avg = 0.0
    for talker in sorted(in_view_per_talker):
        if talker == 'GN':
            continue
        samples = in_view_per_talker[talker]
        if not samples:
            continue
        avg = sum(samples) / len(samples)
        total_avg += avg
        name = CONSTELLATION.get(talker, talker)
        print(f"  {name:<10} ({talker})  avg {avg:4.1f}  max {max(samples):3d}  min {min(samples):3d}")
    print(f"  {'Total':<16}  avg {total_avg:4.1f}")

    print("\n--- Signal Strength per Satellite (SNR, dB-Hz) ---")
    print(f"  {'Satellite':<14} {'Samples':>7}  {'Avg':>5}  {'Max':>5}  {'Min':>5}")
    print(f"  {'-' * 46}")
    for sat_id, samples in sorted(snr_samples.items(),
                                   key=lambda x: -(sum(x[1]) / len(x[1]))):
        talker, prn = sat_id.split('/')
        label = f"{CONSTELLATION.get(talker, talker)}/{prn}"
        avg = sum(samples) / len(samples)
        print(f"  {label:<14} {len(samples):>7}  {avg:>5.1f}  {max(samples):>5}  {min(samples):>5}")

    all_snr = [s for samples in snr_samples.values() for s in samples]
    if all_snr:
        avg_all = sum(all_snr) / len(all_snr)
        strong  = sum(1 for s in all_snr if s >= 35)
        fair    = sum(1 for s in all_snr if 20 <= s < 35)
        weak    = sum(1 for s in all_snr if s < 20)
        total   = len(all_snr)
        print("\n--- Overall Signal Quality ---")
        print(f"  Average SNR: {avg_all:.1f} dB-Hz")
        print(f"  Strong (>=35 dB-Hz): {strong * 100 // total:3d}%")
        print(f"  Fair   (20-34):      {fair   * 100 // total:3d}%")
        print(f"  Weak   (<20):        {weak   * 100 // total:3d}%")

    print("\n  SNR guide: <20 poor | 20-34 fair | 35-44 good | >=45 excellent")
    print(sep)


if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    survey(duration)
