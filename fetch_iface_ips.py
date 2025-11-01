#!/usr/bin/env python3
"""
fetch_iface_ips.py (passless SSH)

It connects to each host in the inventory using the simple command `ssh <host> "ip -4 a"`, extracts the IPv4 addresses related to the specified interfaces, and saves the output.

Output:
  ./outputs/hosts/<host>.txt
  ./outputs/interfaces/<iface>.txt
  ./outputs/summary.csv
"""

import argparse
import concurrent.futures
import csv
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

#IFACE_HEADER_RE = re.compile(r"^\s*\d+:\s+([0-9A-Za-z_.\-:@]+):")
#INET_V4_RE = re.compile(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/(?:\d{1,2})\b")

IFACE_HEADER_RE = re.compile(r"^\s*\d+:\s+([0-9A-Za-z_.\-:@]+):")
INET_V4_RE = re.compile(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/(?:\d{1,2})\b")

def read_inventory(path: Path) -> List[str]:
    hosts = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            hosts.append(line)
    if not hosts:
        raise ValueError(f"Inventory '{path}' is empty.")
    return hosts

def build_ssh_cmd(host: str, connect_timeout: int) -> List[str]:
    """
    We use passwordless SSH — assumption: `ssh computeX "ip -4 a"` works.

    - BatchMode=yes to prevent password prompts
    - StrictHostKeyChecking=no to avoid stopping in case of a new HostKey
    - ConnectTimeout is set
    """
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", f"ConnectTimeout={connect_timeout}",
        host,
        "ip -4 a"
    ]

def run_ssh(cmd: List[str], timeout: int) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"TimeoutExpired: {e}"
    except Exception as e:
        return 255, "", f"Exception: {e}"

#---

#----

def parse_ip_output(output: str, wanted_ifaces: List[str]) -> Dict[str, str]:
    """
    Parses the output of `ip -4 a` and returns the IP for the requested interfaces.

    Matching logic:
    1) If the full interface name (raw) exactly matches in wanted ⇒ use that as key.
    2) If base name (part before '@') is in wanted ⇒ use that base as key.

    * If multiple IPs on one interface, returns the first IPv4.
    """
    wanted_set = set(wanted_ifaces)
    result: Dict[str, str] = {}
    current_iface_raw: Optional[str] = None
    current_iface_key: Optional[str] = None  # # The key we write in the result (based on what the user requested)

    for line in output.splitlines():
        m_hdr = IFACE_HEADER_RE.match(line)
        if m_hdr:
            current_iface_raw = m_hdr.group(1)              # Like: 'storage@bond0' or 'bond0'
            base = current_iface_raw.split("@", 1)[0]       # Like: 'storage' or 'bond0'
            # Exact match takes priority
            if current_iface_raw in wanted_set:
                current_iface_key = current_iface_raw
            elif base in wanted_set:
                current_iface_key = base
            else:
                current_iface_key = None
            continue

        if current_iface_key and current_iface_key not in result:
            m_inet = INET_V4_RE.search(line)
            if m_inet:
                result[current_iface_key] = m_inet.group(1)

    return result


def write_host_file(outdir_hosts: Path, host: str, iface_ip_map: Dict[str, str], iface_order: List[str]) -> None:
    outdir_hosts.mkdir(parents=True, exist_ok=True)
    path = outdir_hosts / f"{host}.txt"
    with path.open("w", encoding="utf-8") as f:
        f.write(f"{host}\n")
        for iface in iface_order:
            ip = iface_ip_map.get(iface, "")
            f.write(f"{iface:<12} {ip}\n")

def append_interface_files(outdir_ifaces: Path, host: str, iface_ip_map: Dict[str, str]) -> None:
    outdir_ifaces.mkdir(parents=True, exist_ok=True)
    for iface, ip in iface_ip_map.items():
        path = outdir_ifaces / f"{iface}.txt"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{host} {ip}\n")

def write_summary_csv(outdir: Path, hosts: List[str], iface_order: List[str], data: Dict[str, Dict[str, str]]) -> None:
    path = outdir / "summary.csv"
    outdir.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["host"] + iface_order)
        for h in hosts:
            row = [h] + [data.get(h, {}).get(iface, "") for iface in iface_order]
            writer.writerow(row)

def worker(
    host: str,
    connect_timeout: int,
    cmd_timeout: int,
    wanted_ifaces: List[str],
) -> Tuple[str, Dict[str, str], Optional[str]]:
    cmd = build_ssh_cmd(host=host, connect_timeout=connect_timeout)
    rc, out, err = run_ssh(cmd, timeout=cmd_timeout)
    if rc != 0:
        return host, {}, f"SSH failed (rc={rc}) {err.strip()}"
    parsed = parse_ip_output(out, wanted_ifaces=wanted_ifaces)
    return host, parsed, None

def main():
    parser = argparse.ArgumentParser(description="Collect IPv4 addresses for specific interfaces using passless SSH.")
    parser.add_argument("--inventory", required=True, help="Path to inventory file (one host per line).")
    parser.add_argument("--interfaces", nargs="+", required=True, help="Interface names to collect (e.g., br-mgmt br-storage br-vxlan).")
    parser.add_argument("--connect-timeout", type=int, default=5, help="SSH connect timeout seconds (default: 5).")
    parser.add_argument("--cmd-timeout", type=int, default=15, help="Overall command timeout per host (default: 15).")
    parser.add_argument("--concurrency", type=int, default=10, help="Parallel workers (default: 10).")
    parser.add_argument("--outdir", default="./outputs", help="Output directory (default: ./outputs).")
    args = parser.parse_args()

    inventory_path = Path(args.inventory)
    outdir = Path(args.outdir)
    out_hosts = outdir / "hosts"
    out_ifaces = outdir / "interfaces"
    out_hosts.mkdir(parents=True, exist_ok=True)
    out_ifaces.mkdir(parents=True, exist_ok=True)

    try:
        hosts = read_inventory(inventory_path)
    except Exception as e:
        print(f"[ERROR] Failed to read inventory: {e}", file=sys.stderr)
        sys.exit(2)

    results: Dict[str, Dict[str, str]] = {}
    errors: Dict[str, str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                worker,
                host=h,
                connect_timeout=args.connect_timeout,
                cmd_timeout=args.cmd_timeout,
                wanted_ifaces=args.interfaces,
            )
            for h in hosts
        ]

        for fut in concurrent.futures.as_completed(futures):
            host, iface_map, err = fut.result()
            if err:
                errors[host] = err
                continue
            results[host] = iface_map

    for host in hosts:
        iface_map = results.get(host, {})
        write_host_file(out_hosts, host, iface_map, args.interfaces)
        if iface_map:
            append_interface_files(out_ifaces, host, iface_map)

    write_summary_csv(outdir, hosts, args.interfaces, results)

    # Prints summary to stdout
    print("=== Summary ===")
    for host in hosts:
        row = [host] + [results.get(host, {}).get(iface, "-") for iface in args.interfaces]
        print("  " + "  ".join(row))
    if errors:
        print("\n=== Errors ===", file=sys.stderr)
        for h, e in errors.items():
            print(f"{h}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()