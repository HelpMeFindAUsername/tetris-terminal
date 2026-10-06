#!/usr/bin/env bash
# Install/update the headless server as an unprivileged systemd service.
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Uso: sudo bash scripts/install-server-debian.sh --public-ip IP [opzioni]

  --public-ip IP        IPv4 pubblico incluso nel certificato TLS generato
  --port PORTA          Porta TCP da 1024 a 65535 (default: 45454)
  --tls-cert FILE       Usa un certificato PEM esistente (insieme a --tls-key)
  --tls-key FILE        Usa una chiave PEM esistente
  --plain-tcp           Disabilita TLS, per reti locali
  --open-firewall       Aggiunge la porta a UFW, solo se gia attivo
  -h, --help            Mostra questo messaggio

TLS e attivo per impostazione predefinita. Senza certificati esistenti,
--public-ip e obbligatorio. L'IP deve essere assegnato o inoltrato al server.
EOF
}

fail() { printf 'Errore: %s\n' "$*" >&2; exit 1; }
need_value() { [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || fail "Manca il valore di $1"; }

public_ip=''
port=45454
tls_cert=''
tls_key=''
plain_tcp=false
open_firewall=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --public-ip) need_value "$@"; public_ip=$2; shift 2 ;;
        --port) need_value "$@"; port=$2; shift 2 ;;
        --tls-cert) need_value "$@"; tls_cert=$2; shift 2 ;;
        --tls-key) need_value "$@"; tls_key=$2; shift 2 ;;
        --plain-tcp) plain_tcp=true; shift ;;
        --open-firewall) open_firewall=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Opzione sconosciuta: $1 (usa --help)" ;;
    esac
done

[[ "$port" =~ ^[0-9]{4,5}$ ]] || fail 'Porta non valida: usa 1024-65535'
port=$((10#$port))
(( port >= 1024 && port <= 65535 )) || fail 'La porta deve essere tra 1024 e 65535'
if [[ -n "$public_ip" ]]; then
    [[ "$public_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || fail 'Serve un indirizzo IPv4 valido'
    IFS='.' read -r -a ip_parts <<< "$public_ip"
    for part in "${ip_parts[@]}"; do
        [[ "$part" == 0 || "$part" != 0* ]] || fail 'Indirizzo IPv4 non valido: evita gli zeri iniziali'
        (( 10#$part <= 255 )) || fail 'Indirizzo IPv4 non valido'
    done
fi
if [[ -n "$tls_cert" || -n "$tls_key" ]]; then
    [[ -n "$tls_cert" && -n "$tls_key" ]] || fail 'Usa --tls-cert e --tls-key insieme'
    [[ -r "$tls_cert" && -r "$tls_key" ]] || fail 'Certificato o chiave illeggibili'
    [[ "$plain_tcp" == false ]] || fail '--plain-tcp non puo essere combinato con certificati TLS'
elif [[ "$plain_tcp" == false && -z "$public_ip" ]]; then
    fail 'Specifica --public-ip oppure --tls-cert e --tls-key (vedi --help)'
fi
(( EUID == 0 )) || fail 'Avvia questo script con sudo'
[[ -f /etc/debian_version ]] || fail 'Questo installer richiede Debian o una distribuzione derivata'
[[ -d /run/systemd/system ]] || fail 'Serve una macchina avviata con systemd'

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
for module in tetris_server.py tetris_game.py tetris_network.py; do
    [[ -r "$repo_dir/$module" ]] || fail "File mancante nella repo: $module"
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 openssl ca-certificates
if ! id terminal-tetris >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin terminal-tetris
fi

install -d -m 0755 /opt/terminal-tetris
install -d -o root -g terminal-tetris -m 0750 /etc/terminal-tetris
tls_args=()
if [[ "$plain_tcp" == false ]]; then
    if [[ -n "$tls_cert" ]]; then
        openssl x509 -in "$tls_cert" -noout -checkend 60
        openssl pkey -in "$tls_key" -passin pass: -noout
        # Stage first, so using the already installed paths remains safe.
        stage_dir=$(mktemp -d)
        trap 'rm -rf -- "$stage_dir"' EXIT
        openssl x509 -in "$tls_cert" -pubkey -noout > "$stage_dir/cert.pub"
        openssl pkey -in "$tls_key" -passin pass: -pubout > "$stage_dir/key.pub"
        cmp -s "$stage_dir/cert.pub" "$stage_dir/key.pub" || fail 'Chiave e certificato non corrispondono'
        install -m 0644 "$tls_cert" "$stage_dir/server.crt"
        install -m 0600 "$tls_key" "$stage_dir/server.key"
        install -o root -g terminal-tetris -m 0644 "$stage_dir/server.crt" /etc/terminal-tetris/server.crt
        install -o root -g terminal-tetris -m 0640 "$stage_dir/server.key" /etc/terminal-tetris/server.key
    elif [[ -f /etc/terminal-tetris/server.crt && -f /etc/terminal-tetris/server.key ]]; then
        openssl x509 -in /etc/terminal-tetris/server.crt -noout -checkip "$public_ip" \
            || fail 'Il certificato esistente usa un altro IP: fornisci nuovi certificati con --tls-cert/--tls-key'
        openssl x509 -in /etc/terminal-tetris/server.crt -noout -checkend 60 \
            || fail 'Certificato scaduto: fornisci nuovi certificati con --tls-cert/--tls-key'
    else
        openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
            -keyout /etc/terminal-tetris/server.key -out /etc/terminal-tetris/server.crt \
            -subj "/CN=$public_ip" -addext "subjectAltName=IP:$public_ip" \
            -addext 'basicConstraints=critical,CA:TRUE' \
            -addext 'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign' \
            -addext 'extendedKeyUsage=serverAuth'
    fi
    chown root:terminal-tetris /etc/terminal-tetris/server.key /etc/terminal-tetris/server.crt
    chmod 0640 /etc/terminal-tetris/server.key
    chmod 0644 /etc/terminal-tetris/server.crt
    # Public certificate can be downloaded without access to the private key.
    install -m 0644 /etc/terminal-tetris/server.crt /opt/terminal-tetris/server.crt
    tls_args=(--cert /etc/terminal-tetris/server.crt --key /etc/terminal-tetris/server.key)
fi
for module in tetris_server.py tetris_game.py tetris_network.py; do
    install -o root -g root -m 0644 "$repo_dir/$module" "/opt/terminal-tetris/$module"
done

cat > /etc/systemd/system/terminal-tetris.service <<EOF
[Unit]
Description=Tetris terminal multiplayer lobby server
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=terminal-tetris
Group=terminal-tetris
WorkingDirectory=/opt/terminal-tetris
ExecStart=/usr/bin/python3 -B -u /opt/terminal-tetris/tetris_server.py --bind 0.0.0.0 --port $port ${tls_args[*]}
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_INET AF_UNIX
CapabilityBoundingSet=
UMask=0077
MemoryMax=256M
TasksMax=16
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable terminal-tetris.service
systemctl restart terminal-tetris.service
if [[ "$open_firewall" == true ]]; then
    if command -v ufw >/dev/null 2>&1 && LC_ALL=C ufw status | grep -q '^Status: active'; then
        ufw allow "$port/tcp"
    else
        printf 'UFW non attivo: nessuna modifica al firewall. Apri la porta TCP %s nel firewall del server/provider.\n' "$port"
    fi
fi
systemctl --no-pager --full status terminal-tetris.service
printf '\nServer installato. Consenti la porta TCP %s anche nel firewall del provider.\n' "$port"
if [[ "$plain_tcp" == false ]]; then
    printf 'Distribuisci ai giocatori solo /opt/terminal-tetris/server.crt.\n'
    printf 'Client: python3 tetris.py --server %s --port %s --ca-file server.crt --nickname NOME\n' "${public_ip:-NOME_DEL_SERVER}" "$port"
else
    printf 'Client: python3 tetris.py --server %s --port %s --no-tls --nickname NOME\n' "${public_ip:-IP_DEL_SERVER}" "$port"
fi
printf 'Log: sudo journalctl -u terminal-tetris -f\n'
