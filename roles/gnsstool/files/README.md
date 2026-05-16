# gnsstool

Query and configure the u-blox GNSS chip via I2C, without interfering with
TimeBeat which owns the UART port.

Installed and managed by Ansible to `/opt/gnsstool/`.

---

## Commands

### `gnsstool status`

Overall status: fix type, position, satellite count, UTC time and accuracy.

```
Fix type:    3D fix
Satellites:  14 used in fix
Position:    51.123456°N  1.234567°W  ±1.2m
Altitude:    42.3m MSL  ±1.8m
PDOP:        0.92
UTC time:    2026-05-14 14:23:01  ±18ns
```

### `gnsstool satellites`

Constellation summary and per-satellite signal strength (SNR, dB-Hz).

```
--- Constellation Summary ---
  Constellation  SVs  Avg SNR  Strong  Fair  Weak
  ------------------------------------------------
  BeiDou           4     38.0       3     1     0
  GPS              8     42.1       6     2     0
  GLONASS          3     38.4       2     1     0
  Galileo          3     40.2       3     0     0

--- Satellites (18 tracked) ---
  Satellite       Elev    Az   SNR   Used
  ----------------------------------------
  GPS/07           72°  134°    47    yes
  GPS/09           61°  289°    45    yes
  ...

  SNR guide: <20 weak | 20-34 fair | 35-44 good | >=45 excellent
```

### `gnsstool platform`

Show the current dynamic platform model and what it means for timing accuracy.

```
Platform mode:  Stationary  (CFG-NAVSPG-DYNMODEL = 2)

The chip is in stationary mode: velocity is constrained to zero and zero-dynamics
are assumed. This is the recommended configuration for a fixed timing antenna.
Expected PPS accuracy: tens of nanoseconds.
```

### `gnsstool platform set stationary`

Switch to stationary mode for best timing accuracy with a fixed antenna.

```
Platform mode set to: Stationary

Note: change is RAM-only and will be lost on chip reset or power cycle.
TimeBeat may override this on restart — check its GNSS configuration.
```

### `gnsstool platform set portable`

Revert to the factory default portable mode.

---

## Timing accuracy and platform mode

The MAX-F10S is a standard precision receiver, not a dedicated timing receiver.
It does not support survey-in or a fixed-position time-only mode (those are features
of receivers like the ZED-F9T). Instead, timing accuracy is governed by the
dynamic platform model (CFG-NAVSPG-DYNMODEL):

**Portable (default, value 0)** — solves for position and time independently each
navigation epoch. Position uncertainty feeds directly into timing uncertainty.
Typical PPS accuracy: hundreds of nanoseconds.

**Stationary (value 2)** — constrains velocity to zero and applies zero-dynamics
assumptions, allowing the position estimate to converge more accurately. The u-blox
integration manual describes this as "Used in timing applications (antenna must be
stationary)." Typical PPS accuracy: tens of nanoseconds.

The platform mode is set in RAM and is lost on chip reset. If TimeBeat is
configured to set the dynamic model itself, its setting will take effect on restart.

---

## Cleanup

```bash
sudo rm -rf /opt/gnsstool
sudo rm /usr/local/bin/gnsstool
```

Or disable in Ansible (`gnsstool_enabled: false` in vars.yml) and run `make deploy`.
