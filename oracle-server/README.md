# Oracle Server (AIWZC Proxy)

Public-facing Flask proxy that sits between remote clients (tablet, browser) and the processing laptop over a WireGuard VPN. Runs on a small cloud VM (e.g. a DigitalOcean droplet) with Nginx in front for TLS termination.

## Architecture

```
[ Tablet / Browser ]
        |
        |  HTTPS (443)
        v
[ Oracle Droplet ]
    Nginx (host, TLS)
        |
        |  HTTP 127.0.0.1:5000
        v
    Flask proxy (Docker, host networking)
        |
        |  HTTP over WireGuard (wg0)
        v
[ Laptop @ 10.8.0.5:5000 ]
    AIWZC recording + inference
```

Key facts:

- The Flask app (`server_proxy.py`) forwards API calls from clients to the laptop's VPN address.
- Nginx on the host terminates TLS; the Flask app itself runs plain HTTP on `:5000` (`ssl_context=None`).
- The container uses `network_mode: host`, so it can reach the host's WireGuard interface directly.
- The laptop VPN IP is hard-coded to `10.8.0.5` at the top of `server_proxy.py`. If your VPN subnet differs, edit that constant.

## Prerequisites

- A cloud VM with a public IPv4 address. Tested on Ubuntu 22.04 on a $6/mo DigitalOcean droplet (1 GB RAM, 1 vCPU). Any small Ubuntu host works.
- Root / sudo access (should come from the ssh key)
- A free hostname from a dynamic DNS provider (this guide uses [No-IP](https://my.noip.com/)).
- The laptop and tablet already running WireGuard clients that you control (so you can update their peer config with the droplet's new public key).

## 1. Create the droplet

1. In the DigitalOcean dashboard, create a new droplet:
   - Image: **Ubuntu 22.04 LTS** (This was what was used originally)
   - Size: Basic, 1 GB / 1 vCPU (cheapest tier is fine, 1GB used to be the cheapest)
   - Datacenter: pick the one closest to the laptop location
   - SSH key: add yours so you can log in without a password
2. Note the droplet's public IPv4 address.
3. SSH in: `ssh root@<DROPLET_IP>`

## 2. Register a free No-IP hostname

1. Sign up / log in at [https://my.noip.com/](https://my.noip.com/).
2. Go to **Dynamic DNS → No-IP Hostnames → Create Hostname**.
3. Pick a hostname (e.g. `aiwzc-proxy.ddns.net`). Any of the free suffixes works.
4. Set the IPv4 address to the droplet's public IP.
5. Save.

**Important:** Free No-IP hostnames expire after 30 days of no activity. You must confirm the hostname via the email they send, or it stops resolving and Let's Encrypt renewals will fail. Set a calendar reminder.


## 3. Install dependencies on the droplet

```bash
# System packages
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    docker.io docker-compose \
    nginx certbot python3-certbot-nginx \
    wireguard git ufw

# Make sure Docker is running
sudo systemctl enable --now docker

# Allow traffic we need through the firewall
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 51820/udp   # WireGuard
sudo ufw --force enable
```

## 4. Configure WireGuard

Generate a fresh server keypair:

```bash
cd /etc/wireguard
umask 077
wg genkey | tee server_private.key | wg pubkey > server_public.key
cat server_public.key   # you will give this to the laptop + tablet
```

Create `/etc/wireguard/wg0.conf`:

```ini
[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = <contents of /etc/wireguard/server_private.key>

[Peer]
# Laptop
PublicKey = <laptop's wireguard public key>
AllowedIPs = 10.8.0.5/32

[Peer]
# Tablet
PublicKey = <tablet's wireguard public key>
AllowedIPs = 10.8.0.3/32
```

Bring the interface up and make it persist across reboots:

```bash
sudo systemctl enable --now wg-quick@wg0
sudo wg show   # should list the interface
```

On the **laptop** and **tablet**, update their WireGuard client configs with:

- `PublicKey` = the droplet's `server_public.key` (from above)
- `Endpoint` = `<DROPLET_IP>:51820`

Once the peers reconnect, `sudo wg show` on the droplet should display a recent handshake for each peer, and `ping 10.8.0.5` from the droplet should reach the laptop.

## 5. Issue the SSL certificate

Set up a minimal Nginx site so certbot can handle the HTTP challenge:

```bash
DOMAIN=aiwzc-proxy.ddns.net   # change to your No-IP hostname

sudo tee /etc/nginx/sites-available/aiwzc >/dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/aiwzc /etc/nginx/sites-enabled/aiwzc
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Request the certificate. Certbot will edit the site config to add the `listen 443 ssl` block and an HTTP→HTTPS redirect automatically:

```bash
sudo certbot --nginx -d $DOMAIN \
    --non-interactive --agree-tos \
    --email you@example.com \
    --redirect
```

Certbot installs a systemd timer (`certbot.timer`) that renews certificates automatically every ~60 days. Verify with:

```bash
sudo systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

## 6. Deploy the Flask proxy

```bash
git clone <this-repo-url> ~/AIWZC
cd ~/AIWZC/oracle-server/flask-app-aiwzc

# Build and start the container
chmod +x deploy.sh
./deploy.sh build
./deploy.sh start

# Confirm
./deploy.sh status
./deploy.sh logs      # Ctrl+C to exit
```

If everything is working:

- `curl http://127.0.0.1:5000/api/health` on the droplet returns JSON with `"laptop": "online"` (assuming the laptop is up and reachable on the VPN).
- `https://<your-domain>/` in a browser shows the login page. Default credentials: `admin` / `AI@WZCProject`. **Change these in `server_proxy.py` before exposing the server publicly.**

## 7. Point the tablet at the new server

Anywhere the tablet app or recording clients had `https://signaling.ddns.net` (or the previous domain) hard-coded, replace it with your new hostname.

## Day-to-day operations

```bash
./deploy.sh logs      # tail container logs
./deploy.sh reload    # restart Python without rebuilding image (after editing server_proxy.py)
./deploy.sh stop      # stop the container
./deploy.sh start     # start it back up
```

The container has `restart: always` in `docker-compose.yml`, so it survives reboots and crashes.

## Configuration you may want to change

All in `flask-app-aiwzc/server_proxy.py`:

| Constant | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | `AI@WZCProject` | JWT signing key — **must match the laptop's key** |
| `LAPTOP_IP` | `10.8.0.5` | Laptop's VPN address |
| `LAPTOP_DEFAULT_PORT` | `5000` | Port the laptop's Flask API listens on |
| Admin credentials | `admin` / `AI@WZCProject` | Hard-coded in `api_login` and `web_login` |

After editing, run `./deploy.sh reload` (no rebuild needed — the file is bind-mounted into the container).

## Troubleshooting

**`https://<domain>/` returns 502 Bad Gateway**
The Flask container isn't running or isn't listening on `:5000`. Check `./deploy.sh status` and `./deploy.sh logs`.

**Dashboard shows "Laptop offline"**
WireGuard isn't passing traffic. On the droplet, run `sudo wg show` — if there's no recent handshake, the laptop's client config is wrong (check endpoint IP and the droplet's public key). Also try `ping 10.8.0.5` from the droplet.

**Certbot fails with "DNS problem: NXDOMAIN looking up A"**
Your No-IP hostname isn't resolving yet (propagation delay) or has expired. Re-confirm it in the No-IP dashboard and wait a few minutes.

**Container keeps restarting**
`./deploy.sh logs` will show the Python traceback. Most common cause: `server_proxy.py` has a syntax error after an edit, or the `/etc/letsencrypt` mount path doesn't exist yet (run certbot first).

**I regenerated the droplet and need new certs**
Let's Encrypt rate-limits to 5 duplicate certs per domain per week. If you're rebuilding repeatedly, use `--staging` with certbot to avoid hitting the limit while you iterate.
