import requests
import traceback
import time
import os
import json

CF_API_TOKEN = os.environ["CF_API_TOKEN"]

# 可选：如果只传了一个 Zone ID，仍可作为默认值使用（比如所有域名都在同一 Zone）
CF_ZONE_ID_DEFAULT = os.environ.get("CF_ZONE_ID", "").strip()

CF_DNS_NAMES = [x.strip() for x in os.environ.get("CF_DNS_NAME","").split(",") if x.strip()]
if not CF_DNS_NAMES:
    print("❌ 没有检测到 CF_DNS_NAME，请设置（可逗号分隔多个域名）")
    exit(1)

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN","")

headers = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json",
}

# === NEW: 列出账户下的全部 zones（分页） ===
def list_all_zones():
    zones = []
    page = 1
    while True:
        r = requests.get(
            "https://api.cloudflare.com/client/v4/zones",
            headers=headers,
            params={"page": page, "per_page": 50},
            timeout=15
        )
        if r.status_code != 200:
            print("Error listing zones:", r.text)
            break
        data = r.json()
        zones.extend(data.get("result", []))
        info = data.get("result_info") or {}
        if page >= info.get("total_pages", 1):
            break
        page += 1
    return zones

# === NEW: 基于域名选择所属 Zone（最长后缀匹配） ===
def get_zone_id_for_dns_name(dns_name, zones_cache=None):
    """
    在账号内找到与 dns_name 匹配的 zone：
    - 如果提供了 CF_ZONE_ID_DEFAULT 且该 Zone 的名字确实是 dns_name 的后缀，也可直接用默认值
    - 否则枚举账户下所有 zones，选取名字（zone.name）是 dns_name 后缀的最长者
    """
    if CF_ZONE_ID_DEFAULT:
        # 验证默认 Zone 是否真匹配（例如 zone.name = example.com，dns_name = a.example.com）
        try:
            # 取默认 zone 的 name（为了严格校验，可查询一次）
            r = requests.get(
                f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID_DEFAULT}",
                headers=headers, timeout=10
            )
            if r.status_code == 200:
                z = r.json().get("result") or {}
                zone_name = (z.get("name") or "").lower()
                if zone_name and dns_name.lower().endswith(zone_name):
                    return CF_ZONE_ID_DEFAULT
        except Exception:
            traceback.print_exc()

    if zones_cache is None:
        zones_cache = list_all_zones()

    best = None
    dns_lower = dns_name.lower()
    for z in zones_cache:
        zn = (z.get("name") or "").lower()
        if zn and dns_lower.endswith(zn):
            # 选择最长匹配的 zone.name
            if best is None or len(zn) > len(best.get("name","")):
                best = z
    return best.get("id") if best else None

def get_cf_speed_test_ip(timeout=10, max_retries=5):
    for attempt in range(max_retries):
        try:
            r = requests.get("https://ip.164746.xyz/ipTop10.html", timeout=timeout)
            if r.status_code == 200 and r.text:
                return r.text
        except Exception as e:
            traceback.print_exc()
            print(f"get_cf_speed_test_ip Request failed (attempt {attempt + 1}/{max_retries}): {e}")
    return None

# === CHG: 带 zone_id 的查询（按 name+type 精确过滤） ===
def get_dns_records(name, zone_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    params = {"type": "A", "name": name, "per_page": 100}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            print("Error fetching DNS records:", r.text)
            return []
        data = r.json()
        return [rec["id"] for rec in data.get("result", []) if rec.get("name") == name and rec.get("type") == "A"]
    except Exception as e:
        traceback.print_exc()
        print("Error fetching DNS records:", e)
        return []

# === CHG: 带 zone_id 的更新 ===
def update_dns_record(record_id, name, cf_ip, zone_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    data = {"type": "A", "name": name, "content": cf_ip}
    r = requests.put(url, headers=headers, json=data, timeout=15)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    if r.status_code == 200:
        print(f"cf_dns_change success: ---- Time: {ts} ---- name: {name} ---- ip: {cf_ip}")
        return f"ip:{cf_ip} 解析 {name} 成功"
    else:
        print(f"cf_dns_change ERROR: ---- Time: {ts} ---- {r.text}")
        return f"ip:{cf_ip} 解析 {name} 失败"

def push_plus(content):
    if not PUSHPLUS_TOKEN:
        return
    url = "http://www.pushplus.plus/send"
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选DNSCF推送",
        "content": content,
        "template": "markdown",
        "channel": "wechat",
    }
    try:
        requests.post(url, data=json.dumps(data).encode("utf-8"),
                      headers={"Content-Type":"application/json"}, timeout=10)
    except Exception:
        traceback.print_exc()

def main():
    ip_addresses_str = get_cf_speed_test_ip()
    if not ip_addresses_str:
        print("❌ 未获取到优选 IP 列表")
        return
    ip_addresses = [x.strip() for x in ip_addresses_str.split(",") if x.strip()]
    if not ip_addresses:
        print("❌ 解析优选 IP 列表为空")
        return

    all_push_lines = []
    zones_cache = None  # 懒加载

    for dns_name in CF_DNS_NAMES:
        if zones_cache is None:
            zones_cache = list_all_zones()

        zone_id = get_zone_id_for_dns_name(dns_name, zones_cache)
        if not zone_id:
            print(f"❌ 账户下未找到可匹配 {dns_name} 的 Zone（请检查该域名是否在此 Cloudflare 账户内）")
            all_push_lines.append(f"{dns_name}: 未匹配到 Zone，跳过")
            continue

        print(f"🔄 正在更新域名：{dns_name}  (zone: {zone_id})")
        dns_records = get_dns_records(dns_name, zone_id)
        if not dns_records:
            print(f"⚠️ 在 Zone({zone_id}) 中没有找到 {dns_name} 的 A 记录（只更新现有记录，不自动新增）")
            all_push_lines.append(f"{dns_name}: 未找到 A 记录，跳过")
            continue

        updated = 0
        for record_id, cf_ip in zip(dns_records, ip_addresses):
            msg = update_dns_record(record_id, dns_name, cf_ip, zone_id)
            print(msg)
            all_push_lines.append(f"{dns_name} -> {cf_ip}: {msg}")
            updated += 1

        print(f"✅ {dns_name} 已更新 {updated} 条 A 记录\n")

    push_plus("\n".join(all_push_lines))

if __name__ == "__main__":
    main()
