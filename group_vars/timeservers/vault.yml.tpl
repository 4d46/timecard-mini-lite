# Generated at deploy time by: op inject -i vault.yml.tpl -o vault.yml
# DO NOT commit vault.yml — it is git-ignored
#
# 1Password item: Homelab/Timeserver
# Fields required:
#   password              — admin user password (set via Pi Imager, used for idempotent hash)
#   ssh-public-key        — admin SSH public key (e.g. ssh-ed25519 AAAA...)
#   hostname-fqdn         — fully qualified hostname (e.g. nimrod.flbr.uk)
#   hostname-short        — short hostname (e.g. nimrod)
#   acme-email            — email for Let's Encrypt registration
#   gandi-livedns-token   — Gandi Personal Access Token (DNS-only scope, domain-restricted)
#   license               — TimeBeat license file contents
#   ntp-allowed-network   — network address allowed to query NTP (e.g. 192.168.1.0)
#   ntp-allowed-netmask   — netmask for NTP access control (e.g. 255.255.255.0)

vault_admin_password:        "{{ op://Homelab/Timeserver/password }}"
vault_admin_ssh_key:         "{{ op://Homelab/Timeserver/ssh-public-key }}"
vault_hostname_fqdn:         "{{ op://Homelab/Timeserver/hostname-fqdn }}"
vault_hostname_short:        "{{ op://Homelab/Timeserver/hostname-short }}"
vault_acme_email:            "{{ op://Homelab/Timeserver/acme-email }}"
vault_gandi_token:           "{{ op://Homelab/Timeserver/gandi-livedns-token }}"
vault_timebeat_license:      "{{ op://Homelab/Timeserver/license }}"
vault_ntp_allowed_network:   "{{ op://Homelab/Timeserver/ntp-allowed-network }}"
vault_ntp_allowed_netmask:   "{{ op://Homelab/Timeserver/ntp-allowed-netmask }}"
