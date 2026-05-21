# Generated at deploy time by: op inject -i vault.yml.tpl -o vault.yml
# DO NOT commit vault.yml — it is git-ignored
#
# 1Password item: System Credentials/Timeserver
# Fields required:
#   password              — admin user password (set via Pi Imager, used for idempotent hash)
#   ssh-public-key        — admin SSH public key (e.g. ssh-ed25519 AAAA...)
#   hostname-fqdn         — fully qualified hostname (e.g. timeserver.example.com)
#   hostname-short        — short hostname (e.g. timeserver)
#   gandi-livedns-token   — Gandi Personal Access Token (DNS-only scope, domain-restricted)
#   license               — TimeBeat license file contents
#   ntp-allowed-network   — network address allowed to query NTP (e.g. 192.168.1.0)
#   ntp-allowed-netmask   — netmask for NTP access control (e.g. 255.255.255.0)
#   timebeat-cli-password     — TimeBeat local CLI password (localhost only)
#   timebeat-elasticsearch-host — Elasticsearch host URL (e.g. http://hostname:9200)

vault_admin_password:        "{{ op://System Credentials/Timeserver/password }}"
vault_admin_ssh_key:         "{{ op://System Credentials/Timeserver/ssh-public-key }}"
vault_hostname_fqdn:         "{{ op://System Credentials/Timeserver/hostname-fqdn }}"
vault_hostname_short:        "{{ op://System Credentials/Timeserver/hostname-short }}"
vault_gandi_token:           "{{ op://System Credentials/Timeserver/gandi-livedns-token }}"
vault_timebeat_license:      "{{ op://System Credentials/Timeserver/license }}"
vault_ntp_allowed_network:   "{{ op://System Credentials/Timeserver/ntp-allowed-network }}"
vault_ntp_allowed_netmask:   "{{ op://System Credentials/Timeserver/ntp-allowed-netmask }}"
vault_timebeat_cli_password:        "{{ op://System Credentials/Timeserver/timebeat-cli-password }}"
vault_timebeat_elasticsearch_host: "{{ op://System Credentials/Timeserver/timebeat-elasticsearch-host }}"
