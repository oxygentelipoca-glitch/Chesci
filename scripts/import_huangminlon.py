#!/usr/bin/env python3
"""导入黄鸣龙还原反应系列"""
import sys, json, requests

API = "http://localhost:8001"

# 登录获取 token
r = requests.post(f"{API}/auth/login", json={"username": "demo", "password": "demo"})
token = r.json()["data"]["token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# 黄鸣龙反应系列
reactions = """苯乙酮 + 水合肼 → 苯乙酮腙 (类型:缩合, 溶剂:乙醇, 温度:80°C, 时间:1h, 收率:95%)
苯乙酮腙 + KOH → 乙苯 + N₂ (名称:黄鸣龙还原, 类型:还原, 溶剂:二甘醇, 温度:200°C, 时间:3h, 收率:85%)
环己酮 + 水合肼 → 环己酮腙 (类型:缩合, 温度:80°C, 收率:93%)
环己酮腙 + KOH → 环己烷 + N₂ (名称:黄鸣龙还原, 类型:还原, 溶剂:三甘醇, 温度:195°C, 时间:4h, 收率:82%)
苯甲醛 + 水合肼 → 苯甲醛腙 (类型:缩合, 收率:90%)
苯甲醛腙 + KOH → 甲苯 + N₂ (名称:黄鸣龙还原, 类型:还原, 溶剂:二甘醇, 温度:190°C, 时间:2h, 收率:78%)"""

r = requests.post(f"{API}/api/chemistry/reactions/upload", json={"text": reactions}, headers=headers)
data = r.json()
print(f"解析: {data['data']['parsed_count']} 条")
print(f"新增化合物: {data['data']['compounds_added']}")
print(f"新增反应: {data['data']['reactions_added']}")

# 验证 stats
r2 = requests.get(f"{API}/api/chemistry/stats")
s = r2.json()["data"]
print(f"\n知识库: {s['compounds']} 化合物, {s['reactions']} 反应, {s['total_nodes']} 节点")
