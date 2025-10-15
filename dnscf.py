import requests
import traceback
import time
import os
import json

# === 环境变量 ===
CF_API_TOKEN = os.environ["CF_API_TOKEN"]
CF_ZONE_ID   = os.environ["CF_ZONE_ID"]

# 支持多个域名：CF_DNS_NAME="a.example.com,b.example.net,c.example.org"
CF_DNS_NAMES = [x.strip() for x in os.environ.get("CF_DNS_NAME", "").split(",") if x.strip()]
if not CF_DNS_NAMES:
    print("❌ 没有检测到 CF_DNS_NAME，请设置（可逗号分隔多个域名）")
    exit(1)

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

headers = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json",
}

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

# —— 方案1：按 name+type 精确过滤（推荐，避免翻页问题）——
def get_dns_records(name):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records"
    params = {
        "type": "A",
        "name": name,
        "per_page": 100,  # 保险起见
    }
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

# 若你更喜欢完整翻页方案，可替换为：
# def get_dns_records(name):
#     url = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records"
#     page = 1
#     ids = []
#     try:
#         while True:
#             r = requests.get(url, headers=headers, params={"page": page, "per_page": 100}, timeout=15)
#             if r.status_code != 200:
#                 print("Error fetching DNS records:", r.text)
#                 return ids
#             data = r.json()
#             for rec in data.get("result", []):
#                 if rec.get("name") == name and rec.get("type") == "A":
#                     ids.append(rec["id"])
#             info = data.get("result_info", {}) or {}
#             if page >= info.get("total_pages", 1):
#                 break
#             page += 1
#         return ids
#     except Exception as e:
#         traceback.print_exc()
#         print("Error fetching DNS records:", e)
#         return ids

def update_dns_record(record_id, name, cf_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record_id}"
    data = {
        "type": "A",
        "name": name,
        "content": cf_ip,
    }
    r = requests.put(url, headers=headers, json=data)
    if r.status_code == 200:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"cf_dns_change success: ---- Time: {ts} ---- ip：{cf_ip} ---- name：{name}")
        return f"ip:{cf_ip} 解析 {name} 成功"
    else:
        traceback.print_exc()
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"cf_dns_change ERROR: ---- Time: {ts} ---- MESSAGE: {r.text}")
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
    body = json.dumps(data).encode("utf-8")
    headers_local = {"Content-Type": "application/json"}
    try:
        requests.post(url, data=body, headers=headers_local, timeout=10)
    except Exception:
        traceback.print_exc()

def main():
    # 获取最新优选IP（逗号分隔）
    ip_addresses_str = get_cf_speed_test_ip()
    if not ip_addresses_str:
        print("❌ 未获取到优选 IP 列表")
        return
    ip_addresses = [x.strip() for x in ip_addresses_str.split(",") if x.strip()]
    if not ip_addresses:
        print("❌ 解析优选 IP 列表为空")
        return

    all_push_lines = []

    for dns_name in CF_DNS_NAMES:
        print(f"🔄 正在更新域名：{dns_name}")
        dns_records = get_dns_records(dns_name)
        if not dns_records:
            print(f"⚠️ 未在 Zone({CF_ZONE_ID}) 中找到 {dns_name} 的 A 记录")
            all_push_lines.append(f"{dns_name}: 未找到记录，跳过")
            continue

        # 使用 zip 防越界：以“记录数”和“IP数”的最小值为准
        updated = 0
        for record_id, cf_ip in zip(dns_records, ip_addresses):
            msg = update_dns_record(record_id, dns_name, cf_ip)
            print(msg)
            all_push_lines.append(f"{dns_name} -> {cf_ip}: {msg}")
            updated += 1

        print(f"✅ {dns_name} 已更新 {updated} 条 A 记录\n")

    # 如不需要推送，请注释掉
    push_plus("\n".join(all_push_lines))

if __name__ == "__main__":
    main()
