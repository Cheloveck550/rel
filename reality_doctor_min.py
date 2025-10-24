#!/usr/bin/env python3
import json, argparse, subprocess, urllib.parse, os

def run(cmd, inp=None):
    try:
        r = subprocess.run(cmd, input=inp, text=True, capture_output=True)
        return r.stdout.strip()
    except Exception:
        return ""

def urlenc(s): return urllib.parse.quote(s or "", safe="")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("-c", "--config", default="/usr/local/etc/xray/config.json")
    p.add_argument("-H", "--host", default="64.188.64.214")
    a = p.parse_args()

    if not os.path.exists(a.config):
        print(f"[!] Не найден конфиг {a.config}")
        return

    with open(a.config, encoding="utf-8") as f:
        conf = json.load(f)

    inbound = None
    for ib in conf.get("inbounds", []):
        s = ib.get("streamSettings", {}) or {}
        if s.get("security") == "reality" or s.get("realitySettings"):
            inbound = ib
            break

    if not inbound:
        print("[!] inbound с Reality не найден")
        return

    port = inbound.get("port")
    proto = inbound.get("protocol", "vless")
    net = inbound.get("streamSettings", {}).get("network", "tcp")
    rs = inbound.get("streamSettings", {}).get("realitySettings", {}) or {}
    sni = (rs.get("serverNames") or [None])[0]
    sid = (rs.get("shortIds") or [None])[0]
    pk = rs.get("privateKey") or ""
    uuid = ((inbound.get("settings", {}) or {}).get("clients") or [{}])[0].get("id", "YOUR-UUID")

    # пробуем вычислить pbk
    pbk = ""
    if pk:
        out = run(["xray", "x25519", "-i"], inp=pk)
        for w in out.split():
            if len(w) > 20 and not any(x in w for x in ("Private", "key:")):
                pbk = w.strip()
                break

    qs = f"type={net}&security=reality&fp=chrome&alpn=h2,http/1.1"
    if pbk: qs += f"&pbk={urlenc(pbk)}"
    if sni: qs += f"&sni={urlenc(sni)}"
    if sid: qs += f"&sid={urlenc(sid)}"

    noflow = f"vless://{uuid}@{a.host}:{port}?{qs}#Reality_NoFlow"
    vision = f"vless://{uuid}@{a.host}:{port}?{qs}&flow=xtls-rprx-vision#Reality_Vision"

    print("\n=== ССЫЛКИ ДЛЯ ИМПОРТА (сначала без flow — для HappVPN) ===\n")
    print(noflow)
    print(vision)
    print("\nПодсказки:")
    print(" • Если HappVPN подключается, но нет интернета — используй NoFlow.")
    print(" • sni должно совпадать с serverNames в config.json.")
    print(" • Проверь pbk/sid — они должны быть идентичны серверным.")
    print()

if __name__ == "__main__":
    main()
