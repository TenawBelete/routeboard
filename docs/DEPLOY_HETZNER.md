# Deploying to a Hetzner server (about 20 euro per month)

Fixed cost: one server (CX43: 8 vCPU, 16 GB RAM, about EUR 16 + EUR 0.50 for the IPv4 address + VAT, roughly EUR 20 in Spain; check the order page)
plus a domain (~EUR 10-15 per year). Nothing here is metered, so the bill cannot grow.

## 1. Create the server
1. hetzner.com/cloud > new project > Add server. Location Falkenstein or Nuremberg,
   image **Ubuntu 24.04**, type **CX43** (CX33 also works with `SAMPLE_EVERY=100`).
2. Add your SSH key (Mac: `ssh-keygen -t ed25519` then paste `~/.ssh/id_ed25519.pub`).
3. Note the server's IPv4 address.

## 2. Point a domain at it
At your domain registrar create an **A record**: `bgp` (or `@`) -> the server IP.
Wait a few minutes. Check: `ping bgp.yourdomain.com` shows the server IP.

## 3. Install Docker and get the code
```bash
ssh root@SERVER_IP
curl -fsSL https://get.docker.com | sh
apt-get install -y make git
git clone https://github.com/YOUR_USER/bgp-pipeline.git && cd bgp-pipeline
```
(No GitHub yet? On your Mac: `scp -r ~/projects/bgp-pipeline root@SERVER_IP:~/` instead.)

## 4. Configure and start
```bash
make setup                                  # random passwords
echo "SITE_ADDRESS=bgp.yourdomain.com" >> .env
make prod-up                                # first start 5-10 minutes
make health
```
Open https://bgp.yourdomain.com. The certificate is issued automatically (needs
ports 80 and 443 reachable and the DNS record from step 2).

## 5. Firewall, SSH and updates
**Best: no open web ports at all.** Run `cloudflared` on the server exactly as on the Mac
(docs/DEPLOY_CLOUDFLARE.md). The tunnel connects outwards, so the Hetzner Cloud Firewall only needs
inbound TCP 22 from your own IP, and nobody can reach the site without passing Cloudflare's rules.

**If you serve 80/443 directly instead**, allow them only from Cloudflare's address ranges
(https://www.cloudflare.com/ips/), not from everyone. Otherwise anyone who finds the server's IP can
skip the WAF and rate limits (security review, item 2). Caddy then needs a certificate that works
behind Cloudflare: a Cloudflare Origin Certificate, or the Cloudflare DNS challenge.

SSH: create a normal user and stop logging in as root.
```bash
adduser deploy && usermod -aG sudo,docker deploy
mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ && chown -R deploy: /home/deploy/.ssh
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/; s/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh
apt-get install -y fail2ban unattended-upgrades
```
From then on: `ssh deploy@SERVER_IP`. Test the new login in a second window before closing the first.

Updating later: `git pull && make prod-up`.

## Backups (optional)
Postgres holds the permanent KPIs and events: `make backup` writes a compressed dump to `backups/`. Copy it off the server now and then (`scp`).
The lake is re-created from the live stream and is intentionally not backed up.

## Cheaper and free options (checked 15 Nov 2026; confirm prices before paying)

The stack needs about 8 GB of memory at its peak and runs on ARM as well as Intel/AMD.

| Option | Cost | What to know |
|---|---|---|
| Oracle Cloud "Always Free" ARM server | EUR 0 | 2 cores, 12 GB since June 2026. Needs a payment card to sign up, free capacity is often unavailable in popular regions, and 2 cores is tight for Spark: expect it to work but lag. Not tested with this project. |
| Hetzner CX33 (4 cores, 8 GB) | about EUR 11 / month with VAT | Cheapest dependable choice. Use the small-server settings below. |
| Hetzner CX43 (8 cores, 16 GB) | about EUR 20 / month with VAT | Comfortable; no tuning needed. |
| Azure for Students | USD 100 credit, no card | Enough for roughly one to two months of a suitable server, so a demo period, not a home. |

Domain: the GitHub Student Developer Pack includes one year of a domain (for example a `.me` from Namecheap).
Without a domain, a free DuckDNS name (`yourname.duckdns.org`) works with the automatic HTTPS certificate too.

### Small-server settings (8 GB)

Add these lines to `.env` on the server before `make prod-up`:

```
SAMPLE_EVERY=100
SPARK_DRIVER_MEMORY=1g
SPARK_CONTAINER_MEMORY=2g
ANALYTICS_CONTAINER_MEMORY=1800m
ANALYTICS_DRIVER_MEMORY=1100m
REDPANDA_MEMORY=768M
```

`SAMPLE_EVERY=100` halves the data read, which halves disk growth and Spark's work. Quiet countries will show
less. These values are a starting point and have not been load-tested on an 8 GB server; watch `make health`
and `docker stats` for the first day.
