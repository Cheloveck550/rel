cat > reality_doctor_min.py <<'PY'
import json, argparse, subprocess, urllib.parse, os, sys

def sh(cmd, input_text=None):
    try:
        p = subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=True)
        return p.stdout.strip()
    except Exception:
        return ""

def urlenc(s): return urllib.parse.quote(s or "", safe="")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="/usr/local/etc/xray/config.json")
    ap.add_argument("-H", "--host", default="64.188.64.214")
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print(f"[!] Не найден config.json: {args.config}", file=sys.stderr); sys.exit(1)

    data = json.load(open(args.config, "r", encoding="utf-8"))

    # ищем inbound с reality
    inb = None
    for ib in data.get("inbounds", []):
        ss = ib.get("streamSettings", {}) or {}
        if ss.get("security") == "reality" or ss.get("realitySettings"):
            inb = ib; break
    if not inb:
        print("[!] В конфиге нет inbound с Reality", file=sys.stderr); sys.exit(1)

    port   = str(inb.get("port"))
    proto  = inb.get("protocol","vless")
    net    = (inb.get("streamSettings",{}) or {}).get("network","tcp")
    rs     = (inb.get("streamSettings",{}) or {}).get("realitySettings",{}) or {}
    sni    = (rs.get("serverNames") or [None])[0]
    sid    = (rs.get("shortIds") or [None])[0]
    pk     = rs.get("privateKey") or ""
    uuid   = ((inb.get("settings",{}) or {}).get("clients") or [{}])[0].get("id") or "YOUR-UUID"

    # пробуем получить pbk через xray (если есть)
    pbk = ""
    if pk:
        out = sh(["bash","-lc", f"printf %s {urllib.parse.quote(pk)} | xray x25519 -i 2>/dev/null || true"])
        # ожидаем строку вида: "Public key: <pbk>"
        if "Public" in out:
            pbk = out.split()[-1].strip()

    qs = f"type={urlenc(net)}&security=reality&fp=chrome&alpn=h2,http/1.1"
    if pbk: qs += f"&pbk={urlenc(pbk)}"
    if sni: qs += f"&sni={urlenc(sni)}"
    if sid: qs += f"&sid={urlenc(sid)}"

    base = f"vless://{uuid}@{args.host}:{port}?{qs}"
    noflow = f"{base}#Reality_NoFlow"
    vision = f"{base}&flow=xtls-rprx-vision#Reality_Vision"

    print("==> ССЫЛКИ ДЛЯ ИМПОРТА (HappVPN сначала NoFlow):")
    print(noflow)
    print(vision)
    print("\nПодсказки:")
    print(" • Если HappVPN «подключается, но нет интернета» — используйте NoFlow.")
    print(" • sni в ссылке должен совпадать с одним из serverNames в config.json.")
    print(" • Если трафика всё равно нет — пришлите пару строк из логов xray.")
if __name__ == "__main__":
    main()
PY

# запустить (если config не в /usr/local/etc/xray/config.json — укажи свой путь)
python3 reality_doctor_min.py -H 64.188.64.214
# пример с явным конфигом:
# python3 reality_doctor_min.py -H 64.188.64.214 -c /etc/xray/config.json
