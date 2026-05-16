# timecard-mini-lite

Ansible playbook to configure a Raspberry Pi CM4 + [TimeBeat Mini HAT Essential](https://www.timebeat.app) as a stratum-1 NTP/PTP/NTS timeserver. Runs against a freshly-flashed Raspberry Pi OS Lite (64-bit, Bookworm), replacing the full TimeBeat desktop image with a lightweight, reproducible, config-as-code setup.

Licensed under MIT. The repo is fully public — no secrets are committed.

---

## Architecture

```
GPS/GNSS (/dev/ttyS0) + PPS (eth0 PHC) ─► TimeBeat ─► System clock (nanosecond discipline)
                                           TimeBeat ─► PTP grandmaster (domain 0, multicast)
System clock (stratum 1, refid GPS)     ─► NTPsec  ─► NTP clients (UDP 123)
                                           NTPsec  ─► NTS clients (TCP 4460, TLS cert)
```

- **TimeBeat** disciplines the system clock from GPS/PPS and serves PTP (IEEE 1588) to the network
- **NTPsec** reads the disciplined system clock as a GPS-referenced stratum 1 source and serves NTP and NTS

---

## Hardware

| Component | Details |
|---|---|
| Compute module | Raspberry Pi CM4 |
| HAT | TimeBeat Open Timecard Mini HAT Essential |
| Carrier board | Waveshare CM4-IO-BASE-A |
| Storage | NVMe SSD via PCIe |
| GNSS module | u-blox MAX-F10S (UART on `/dev/ttyS0`, also I2C bus 1 addr 0x42) |

---

## Prerequisites

### Software (on your laptop/control machine)

- [Ansible](https://docs.ansible.com/ansible/latest/installation_guide/index.html) ≥ 2.17
- [1Password CLI (`op`)](https://developer.1password.com/docs/cli/get-started/) — for secret injection
- `make`

Install Ansible collections:
```bash
make deps
```

### 1Password vault setup

Create an item in 1Password with the following structure:

| Vault | Item | Field | Value |
|---|---|---|---|
| System Credentials | Timeserver | `password` | Admin user password (set during Pi Imager flash) |
| System Credentials | Timeserver | `ssh-public-key` | Your SSH public key (`cat ~/.ssh/id_ed25519.pub`) |
| System Credentials | Timeserver | `hostname-fqdn` | e.g. `timeserver.example.com` |
| System Credentials | Timeserver | `hostname-short` | e.g. `timeserver` |
| System Credentials | Timeserver | `gandi-livedns-token` | Gandi Personal Access Token (DNS scope, domain-restricted) |
| System Credentials | Timeserver | `license` | TimeBeat license file contents |
| System Credentials | Timeserver | `ntp-allowed-network` | Network address allowed to query NTP (e.g. `192.168.1.0`) |
| System Credentials | Timeserver | `ntp-allowed-netmask` | Netmask for NTP access control (e.g. `255.255.255.0`) |
| System Credentials | Timeserver | `timebeat-cli-password` | TimeBeat local CLI password (localhost only) |

The Gandi token should be scoped to **DNS permissions only** for the specific domain — see [Gandi PAT documentation](https://docs.gandi.net/en/domain_names/advanced_users/api.html).

### DNS prerequisite

The FQDN (e.g. `timeserver.example.com`) **must resolve** to the device's IP before the first deploy — the TLS role uses DNS-01 challenge to issue the Let's Encrypt certificate.

Add an A record via your DNS provider:
```
timeserver    A    <device IP>
```

---

## Flashing the base image

Use **Raspberry Pi Imager** to flash **Raspberry Pi OS Lite (64-bit, Bookworm)** to the NVMe SSD.

In the Imager customisation settings (click the gear icon):

| Setting | Value |
|---|---|
| Hostname | `timeserver` (or your chosen short hostname) |
| Username | `admin` |
| Password | (the password you stored in 1Password) |
| Locale | GB / UTC |
| SSH | Enable — **Allow password authentication** |
| Wi-Fi | Leave blank (Ethernet only) |

The `deploy-bootstrap` Makefile target connects as the `admin` user using password auth, which is how Pi Imager sets it up. The base role deploys your SSH key; subsequent runs use `deploy` which uses SSH key auth.

---

## First run

```bash
# 1. Clone the repo and install collections
make deps

# 2. Create your inventory from the example
cp inventory.yml.example inventory.yml
# Edit inventory.yml — set ansible_host to the device's IP

# 3. Ensure your 1Password CLI session is active
op signin

# 4. Bootstrap (connects as admin with password, deploys SSH key)
make deploy-bootstrap
```

The first run will:
1. Update packages, harden SSH, deploy your SSH key
2. Configure the hostname and network
3. Update the EEPROM boot order and reboot if needed
4. Issue a Let's Encrypt certificate via Gandi DNS-01
5. Configure NTPsec with NTS
6. Enable UFW firewall
7. Install and configure TimeBeat

---

## Subsequent runs

```bash
make deploy
```

The playbook is idempotent — safe to run multiple times. No changes are made unless something has drifted.

---

## Enabling SSH key-only authentication

Once you've confirmed SSH key login works (`ssh admin@<ip>` with no password prompt), enable password auth lockout:

1. Edit `group_vars/timeservers/vars.yml` and set:
   ```yaml
   disable_password_auth: true
   ```
2. Uncomment the `Harden SSH — disable password authentication` task in `roles/base/tasks/main.yml`
3. Run `make deploy`

---

## Makefile targets

| Target | Description |
|---|---|
| `make deploy` | Normal idempotent run (SSH key auth) |
| `make deploy-bootstrap` | First-run using password auth (`admin` user) |
| `make check` | Dry-run with diff — no changes made |
| `make deps` | Install Ansible collections |
| `make lint` | Run ansible-lint |
| `make clean` | Remove generated vault.yml and fact cache |

---

## Variable reference

All variables are in `group_vars/timeservers/vars.yml`.

| Variable | Default | Purpose |
|---|---|---|
| `admin_user` | `admin` | System admin username |
| `timezone` | `UTC` | System timezone |
| `locale` | `en_GB.UTF-8` | System locale |
| `disable_password_auth` | `false` | Set true to disable SSH password login |
| `network_interface` | `eth0` | Primary network interface |
| `ntp_allowed_network` | *(vault)* | Network allowed to query NTP |
| `ntp_allowed_netmask` | *(vault)* | Netmask for NTP access control |
| `ntp_fallback_servers` | NPL UK | NTP fallback servers (used as cross-check) |
| `boot_order` | `0xf16` | EEPROM boot order (NVMe→eMMC→USB) |
| `pcie_enabled` | `true` | Enable PCIe for NVMe |
| `timebeat_version` | `2.2.20` | TimeBeat package version |
| `timebeat_gnss_device` | `/dev/ttyS0` | GNSS serial device |
| `timebeat_gnss_baud` | `9600` | GNSS baud rate |
| `nts_port` | `4460` | NTS key-exchange port |

---

## NTP / NTS serving

- **NTP**: `udp/123` — standard NTP, no authentication
- **NTS**: `tcp/4460` — Network Time Security, authenticated NTP over TLS

NTS clients must connect using the FQDN (e.g. `timeserver.example.com`), not the IP — the certificate is validated against the hostname.

Example NTPsec client configuration (`/etc/ntpsec/ntp.conf`):
```
server timeserver.example.com nts iburst
```

---

## PTP

TimeBeat serves PTPv2 multicast as a grandmaster on domain 0. Clients on the same L2 segment will receive Sync/Announce/Follow_Up messages every second.

Test from a client:
```bash
sudo ptp4l -i eth0 -m -s
```

---

## TLS certificate

Certificates are issued by Let's Encrypt via DNS-01 challenge using the Gandi LiveDNS API. This works for devices with private IPs as no port 80 exposure is required.

- Certificate stored in: `/etc/letsencrypt/live/<fqdn>/`
- Deployed to NTPsec at: `/etc/ntpsec/ssl/`
- Auto-renewed by: cron job running `certbot renew` at 00:00 and 12:00 daily
- Renewal hook: `/etc/letsencrypt/renewal-hooks/deploy/ntpsec-nts`

---

## Firewall

| Port | Protocol | Service |
|---|---|---|
| 22 | TCP | SSH |
| 123 | UDP | NTP |
| 319 | UDP | PTP event messages |
| 320 | UDP | PTP general messages |
| 4460 | TCP | NTS key exchange |

Default policy: deny inbound, allow outbound.

---

## Verification

After deployment, run these on the device to confirm everything is working:

```bash
# NTP status — expect *LOCAL(0) at stratum 1 with GPS refid, + on NPL servers
ntpq -p

# NTS status
ntpq -c nts

# TimeBeat GPS/PPS lock — look for nanosecond offsets on pps lines
sudo journalctl -u timebeat --no-pager -n 50

# PTP multicast traffic on eth0
sudo tcpdump -i eth0 udp port 319 or port 320 -c 5 --immediate-mode

# I2C GNSS module (expect address 0x42 on bus 1)
sudo i2cdetect -y 1
```

From a client on the network:
```bash
# NTP test (plain)
ntpdate -q <device-ip>

# PTP test
sudo ptp4l -i eth0 -m -s

# Windows NTP test
w32tm /stripchart /computer:<device-ip> /samples:5 /dataonly
```

---

## Troubleshooting

**TimeBeat config not starting** — Test the config by running TimeBeat in the foreground (Ctrl-C to exit):

```bash
sudo /usr/share/timebeat/bin/timebeat \
  -c /etc/timebeat/timebeat.yml \
  -path.home /usr/share/timebeat \
  -path.config /etc/timebeat \
  -path.data /var/lib/timebeat \
  -path.logs /var/log/timebeat \
  -e
```

This prints errors directly to the terminal, making config issues much easier to diagnose than `journalctl`.

**GNSS not locking** — Allow 5–15 minutes for cold GNSS acquisition. Check `journalctl -u timebeat` for lock status.

**PPS not working** — Verify eth0 supports hardware timestamping: `ethtool -T eth0`. TimeBeat uses NIC hardware timestamping for PPS, not GPIO.

**Certificate issuance failing** — Confirm the DNS A record is live (`dig timeserver.example.com`), the Gandi token has DNS write permissions, and the domain is correct in 1Password.

**SSH lockout** — Connect a keyboard/monitor, log in at console. The `admin` user has sudo access. Check `/etc/ssh/sshd_config`.

**EEPROM update fails** — `rpi-eeprom-config` requires the `rpi-eeprom` package. It is included in Pi OS but may need: `sudo apt install rpi-eeprom`.

**NetworkManager profile conflict** — If a "Wired connection 1" profile exists from Pi Imager, the nmcli task may create a duplicate. Check with `nmcli con show` and delete the old profile if needed.

---

## Not in scope

**UniFi NTP/DHCP Option 42** — configure via UniFi web UI:
- NTP servers: Settings → System → Advanced → NTP → Manual → set to device IP
- DHCP Option 42: Settings → Networks → (each network) → Advanced → DHCP Options → add NTP server

---

## Licence

MIT — see [LICENSE](LICENSE)
