# GNSS Survey Tool

Reads satellite count and signal strength from the u-blox MAX-F10S GNSS module via I2C,
without interfering with TimeBeat which owns the UART port.

Useful for comparing antenna placement — run a survey at each location and compare the results.

Installed and managed by Ansible to `/opt/gnss_survey/`.

---

## Running a survey

```bash
gnss_survey [duration_seconds]
```

Default duration is 120 seconds. Results are printed to the terminal and saved automatically to
`~/gnss_surveys/survey_YYYY-MM-DD_HH-MM-SS.txt`.

Example — 5 minute survey:
```bash
gnss_survey 300
```

---

## Viewing saved surveys

```bash
ls ~/gnss_surveys/
cat ~/gnss_surveys/survey_2026-05-12_09-00-00.txt
```

---

## Reading the results

**Satellites in view** — more satellites = better sky coverage. Expect 8–12+ with a clear sky view.

**Signal strength (SNR, dB-Hz)**:

| Range     | Quality   |
|-----------|-----------|
| < 20      | Poor      |
| 20 – 34   | Fair      |
| 35 – 44   | Good      |
| ≥ 45      | Excellent |

**Constellations**: GPS (GP), GLONASS (GL), Galileo (GA), BeiDou (GB). If a whole constellation
drops out between surveys it may indicate directional blockage (e.g. from roof structure or walls).

---

## Cleanup

To remove the tool, disable it in Ansible (`gnss_survey_enabled: false` in vars.yml) and run
`make deploy`, or remove manually:

```bash
sudo rm -rf /opt/gnss_survey
```
