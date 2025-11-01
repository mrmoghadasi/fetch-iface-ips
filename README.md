# Fetch Interface IPs

## What It Does

This script is a quick and dirty tool for pulling IPv4 addresses from specific network interfaces across a fleet of hosts. It assumes you've got passwordless SSH set up (you know, the kind where `ssh computeX "ip -4 a"` just works without nagging for a password). It zips through your inventory file, SSHes into each machine, runs the `ip -4 a` command, parses the output, and spits out the IPs for the interfaces you're after. No frills, just gets the job done.

I built this because manually checking IPs on dozens of servers gets old fast—especially in a cloud or cluster setup where interfaces might have funky names like `storage@bond0`.

## Prerequisites

- **Python 3.6+**: That's it for the script side. It uses built-in libs like `subprocess`, `concurrent.futures`, and `csv`, so no pip installs needed.
- **Passwordless SSH**: Your SSH keys should be in place for all hosts in the inventory. Test it with a quick `ssh <host> "echo 'alive'"` to make sure.
- **Hosts with `ip` command**: Standard on most Linux distros (like Ubuntu, CentOS). If your hosts are exotic, you might need to tweak the command.
- **Write access**: To the output directory (defaults to `./outputs`).



```
python3 fetch_iface_ips.py \
  --inventory ./inventory-compute \
  --interfaces br-mgmt br-storage br-vxlan \
  --concurrency 10 \
  --outdir ./outputs-compute

```

###inventory-compute

```
compute1
compute2
compute3
.
.
.
compute(n)
```
