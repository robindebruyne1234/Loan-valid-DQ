# Putting the walkthrough on an Oracle Always Free box, at a DuckDNS name

The brief warns against spending the time on infrastructure, and this guide
agrees with it: the interesting part of this project is the cleaning and the
access model, not the hosting. So this is deliberately the short road — one
VM, one reverse proxy, one database container, one service — and it ends with
a frank section on what this deployment is **not** safe for.

Expect **45–60 minutes**, most of it waiting for Oracle.

---

## 1. Pick the right shape, or nothing else matters

Oracle's Always Free tier gives you two different things:

| Shape | What you get | Verdict |
|---|---|---|
| **VM.Standard.A1.Flex** (Ampere, ARM) | up to 4 OCPU and **24 GB RAM**, free forever | **Use this.** |
| VM.Standard.E2.1.Micro (AMD) | 1 OCPU, **1 GB RAM** | Too small. |

The micro shape will not do. Loading 1.06 m transactions, building the star
schema and running a language model in 1 GB means swapping, and the profile
step alone takes 45 seconds on a healthy machine.

Ask for **4 OCPU / 24 GB** of the Ampere shape. Oracle frequently answers
*"Out of host capacity"* in popular regions — that is normal and not
something you have done wrong. Either retry over a few days, or pick a less
busy region when you create the account (the region cannot be changed later).

**Image:** Canonical Ubuntu 24.04 (aarch64).

When you create the instance, **save the private key** it offers you. There
is no second chance, and without it the VM is a paperweight.

```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<the public IP>
```

---

## 2. Open the ports — in *both* places

This is the step that wastes everyone's afternoon. Oracle filters traffic in
two independent layers, and the images ship with the second one closed.

**2a. The virtual cloud network.** In the console: *Networking → Virtual
Cloud Networks → your VCN → Subnets → your subnet → Security Lists → Default
→ Add Ingress Rules.* Add two, both stateless = No, source `0.0.0.0/0`:

| Protocol | Destination port | For |
|---|---|---|
| TCP | 80 | Let's Encrypt's HTTP challenge |
| TCP | 443 | the site |

**2b. The instance's own firewall.** Oracle's Ubuntu images carry iptables
rules that drop everything except SSH, and they survive reboots. On the VM:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

> If the site is unreachable and the security list looks right, it is this.
> Check with `sudo iptables -L INPUT -n --line-numbers`.

**Do not open 5432.** The database is reached over the loopback interface by
the app on the same machine, and has no business being on the internet.

---

## 3. A name, from DuckDNS

Sign in at [duckdns.org](https://www.duckdns.org) with any of the providers it
offers, claim a subdomain (say `berka-demo`), and copy your token.

Point it at the instance's **public IP** once in the web form, then keep it
pointed with a timer — Oracle's ephemeral IPs can change, and a reserved one
is a separate thing to configure:

```bash
mkdir -p ~/duckdns
cat > ~/duckdns/duck.sh <<'EOF'
#!/usr/bin/env bash
# Keep the DuckDNS record pointed at whatever address this host has now.
# Leaving the ip= parameter empty tells DuckDNS to use the source address of
# this request, which is the correct answer even behind a changed IP.
curl -fsS "https://www.duckdns.org/update?domains=berka-demo&token=YOUR-TOKEN&ip=" \
  -o ~/duckdns/duck.log
EOF
chmod 700 ~/duckdns/duck.sh && ~/duckdns/duck.sh && cat ~/duckdns/duck.log   # expect: OK
( crontab -l 2>/dev/null; echo "*/5 * * * * $HOME/duckdns/duck.sh >/dev/null 2>&1" ) | crontab -
```

`berka-demo.duckdns.org` now resolves to your box.

---

## 4. The machine itself

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git make python3-venv python3-pip docker.io docker-compose-v2
sudo usermod -aG docker ubuntu && newgrp docker

git clone https://github.com/robindebruyne1234/Loan-valid-DQ.git
cd Loan-valid-DQ && git checkout ccr-46f6f45a-t9wtd4

python3 -m venv .venv && source .venv/bin/activate
make deps
make up
make build          # ~6 minutes; 202 tests at the end
```

If `make build` passes, everything below is plumbing. Sanity-check the app
before exposing it:

```bash
make web &
curl -s localhost:8080/api/health     # expect "database": true
```

---

## 5. A small model that fits

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:1.5b
```

Choose by what you have spare, remembering PostgreSQL wants a few GB:

| Model | RAM | Honest expectation on the ten questions |
|---|---|---|
| `llama3.2:1b` | ~1.5 GB | Fast. Often malformed output; the page will say so. |
| **`qwen2.5-coder:1.5b`** | ~2 GB | **The sweet spot here.** Trained on code, so the JSON-and-SQL shape usually holds. |
| `qwen2.5-coder:7b` | ~6 GB | Noticeably better SQL, ~4× slower on these cores. |

Point the app at it:

```bash
export LLM_PROVIDER=ollama
export LLM_MODEL=qwen2.5-coder:1.5b
```

A small model will get some of the ten wrong. **That is worth showing rather
than hiding**: a wrong query returns a wrong answer *about data the logged-in
persona is allowed to see*, never somebody else's, and the page shows the SQL
so a visitor can see where it went astray.

---

## 6. Run it as a service

```bash
sudo tee /etc/systemd/system/berka-web.service >/dev/null <<EOF
[Unit]
Description=Berka governed data product walkthrough
After=network.target docker.service
Wants=docker.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/Loan-valid-DQ
Environment=LLM_PROVIDER=ollama
Environment=LLM_MODEL=qwen2.5-coder:1.5b
Environment=PYTHONUNBUFFERED=1
# Loopback only. Caddy is the only thing that talks to it, and it terminates
# TLS. Binding 0.0.0.0 here would publish the app unencrypted on port 8080.
ExecStart=/home/ubuntu/Loan-valid-DQ/.venv/bin/python -m src.webapp --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload && sudo systemctl enable --now berka-web
systemctl status berka-web --no-pager
```

The database container restarts itself (`docker compose` sets a restart
policy), so after a reboot both come back.

---

## 7. TLS, in four lines

Caddy gets a certificate from Let's Encrypt automatically and renews it.

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
berka-demo.duckdns.org {
    encode gzip
    reverse_proxy 127.0.0.1:8080
}
EOF
sudo systemctl reload caddy
```

Open **https://berka-demo.duckdns.org**. If the certificate fails, it is
almost always §2 — port 80 must be reachable from the internet for the
challenge, in the security list *and* in iptables.

---

## 8. What this deployment is not safe for

Read this before showing anyone the link.

1. **The page prints the one-time codes.** A visitor can log in as any
   persona. That is the point of a demo and it is the opposite of security.
   The moment the data stops being a 1999 research release, delete
   `/api/code` and hand people a real enrolment.
2. **The passwords are `demo_pw`.** Every persona shares it, and it is in the
   repository.
3. **There is no rate limit.** Anyone can hold the question queue. A real
   deployment puts Caddy's `rate_limit` in front, or basic auth around the
   whole site:
   ```
   berka-demo.duckdns.org {
       basicauth { demo $2a$14$...hash... }   # caddy hash-password
       reverse_proxy 127.0.0.1:8080
   }
   ```
4. **There is no read audit.** The model controls who *can* read; nothing
   records who did. For real data that is a regulatory gap, not a
   simplification.
5. **`http.server` is not a production server.** It is threaded and has no
   request limits or slow-client protection. Behind Caddy, for a demo, it is
   adequate; for real traffic it should be a WSGI app behind gunicorn. That
   is a half-day of work and was deliberately not spent, because the brief
   warns about exactly this.
6. **The data is public.** Berka is a 1999 research release. Nothing here is
   a real person's finances, which is the only reason any of the above is
   acceptable.

### If you want it a bit safer, in fifteen minutes

```bash
# Basic auth over the whole site
caddy hash-password --plaintext 'something-long'   # paste into the Caddyfile

# Rotate the demo passwords off the committed default
export DEMO_USER_PASSWORD='a-long-random-string'
make entitlements && sudo systemctl restart berka-web

# Reissue the opaque client references under a secret of your own
export BERKA_REF_SALT='another-long-random-string'
make model && make entitlements
```

---

## 9. Staying inside the free tier

| Thing | Free allowance | What this uses |
|---|---|---|
| Ampere compute | 4 OCPU / 24 GB, always | all of it, one VM |
| Block storage | 200 GB total | ~20 GB |
| Outbound transfer | 10 TB/month | nothing like it |
| Public IP | 1 ephemeral free | 1 |

The real risk is not cost, it is **reclamation**: Oracle may stop idle
Always Free compute instances. Keeping the walkthrough reachable at a DuckDNS
name and visiting it occasionally is usually enough; if the box has been
stopped, the console will restart it.

---

## 10. When it does not work

| Symptom | Cause | Fix |
|---|---|---|
| SSH works, website does not | iptables on the instance | §2b |
| Caddy cannot get a certificate | port 80 blocked, or DNS not pointed yet | §2, then `dig berka-demo.duckdns.org` |
| Page loads, says "pipeline not built" | `make build` not run, or run as a different user | `cd ~/Loan-valid-DQ && source .venv/bin/activate && make build` |
| Ask step says NOT EXECUTED | Ollama not running or model not pulled | `systemctl status ollama`, `ollama list` |
| Ask step times out | the model is too big for the box | pull a smaller one and update the unit file |
| Everything is slow after a reboot | the database container is still starting | `docker ps`, wait, then `sudo systemctl restart berka-web` |
| "Out of host capacity" on create | Oracle has no free ARM capacity in that region | retry, or use a quieter region |

Logs:

```bash
journalctl -u berka-web -f          # the app
journalctl -u caddy -f              # TLS and routing
docker compose logs -f db           # the database
```
