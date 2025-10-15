import requests
import traceback
import time
import os
import json

# API 密钥
CF_API_TOKEN    =   os.environ["CF_API_TOKEN"]
CF_ZONE_ID      =   os.environ["CF_ZONE_ID"]
# 支持多个域名：CF_DNS_NAME="a.example.com,b.example.net,c.example.org"
CF_DNS_NAMES = [x.strip() for x in os.environ.get("CF_DNS_NAME","").split(",") if x.strip()]
if not CF_DNS_NAMES:
    print("❌ 没有检测到 CF_DNS_NAME，请设置（可逗号分隔多个域名）")
    exit(1)


# pushplus_token
PUSHPLUS_TOKEN  =   os.environ["PUSHPLUS_TOKEN"]



headers = {
    'Authorization': f'Bearer {CF_API_TOKEN}',
    'Content-Type': 'application/json'
}

def get_cf_speed_test_ip(timeout=10, max_retries=5):
    for attempt in range(max_retries):
        try:
            # 发送 GET 请求，设置超时
            response = requests.get('https://ip.164746.xyz/ipTop10.html', timeout=timeout)
            # 检查响应状态码
            if response.status_code == 200:
                return response.text
        except Exception as e:
            traceback.print_exc()
            print(f"get_cf_speed_test_ip Request failed (attempt {attempt + 1}/{max_retries}): {e}")
    # 如果所有尝试都失败，返回 None 或者抛出异常，根据需要进行处理
    return None

# 获取 DNS 记录
def get_dns_records(name):
    def_info = []
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        records = response.json()['result']
        for record in records:
            if record['name'] == name:
                def_info.append(record['id'])
        return def_info
    else:
        print('Error fetching DNS records:', response.text)

# 更新 DNS 记录
def update_dns_record(record_id, name, cf_ip):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record_id}'
    data = {
        'type': 'A',
        'name': name,
        'content': cf_ip
    }

    response = requests.put(url, headers=headers, json=data)

    if response.status_code == 200:
        print(f"cf_dns_change success: ---- Time: " + str(
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())) + " ---- ip：" + str(cf_ip))
        return "ip:" + str(cf_ip) + "解析" + str(name) + "成功"
    else:
        traceback.print_exc()
        print(f"cf_dns_change ERROR: ---- Time: " + str(
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())) + " ---- MESSAGE: " + str(response))
        return "ip:" + str(cf_ip) + "解析" + str(name) + "失败"

# 消息推送
def push_plus(content):
    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选DNSCF推送",
        "content": content,
        "template": "markdown",
        "channel": "wechat"
    }
    body = json.dumps(data).encode(encoding='utf-8')
    headers = {'Content-Type': 'application/json'}
    requests.post(url, data=body, headers=headers)

# 主函数
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

        # 只更新“记录数”和“IP数”两者的最小个数，避免越界
        updated = 0
        for record_id, cf_ip in zip(dns_records, ip_addresses):
            msg = update_dns_record(record_id, dns_name, cf_ip)
            print(msg)
            all_push_lines.append(f"{dns_name} -> {cf_ip}: {msg}")
            updated += 1

        # 可选：如果希望每个域名都把所有 IP 用完，但记录不够，你也可以在这里补充创建记录的逻辑
        print(f"✅ {dns_name} 已更新 {updated} 条 A 记录\n")

    # 如你不需要推送，可直接注释掉下面一行
    push_plus("\n".join(all_push_lines))

if __name__ == '__main__':
    main()
