# 01: 设置面 — im_push 配置基座

**What to build:** 用户(自部署运营者)能通过设置 API 配置企业微信推送偏好:总开关、条目数、日报链接基地址、最多 5 个群机器人 webhook。读取设置时 webhook 地址脱敏回显(仅尾 4 位可见);提交时若 webhook 值等于脱敏占位符则保留原值不修改。从未配置过的存量用户升级后一切照旧(默认关闭)。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] settings 存储新增 im_push JSON 列,alembic 迁移可从存量库平滑升级,旧行为空对象
- [ ] 严格校验:enabled 布尔、top_n ∈ [3,10]、webhooks 最多 5 个、name 1–20 字符、url 匹配 qyapi.weixin.qq.com webhook 正则、link_base_url 为合法 URL 或空
- [ ] GET 设置返回脱敏 webhook(尾 4 位可见);日志与错误信息不含完整 URL
- [ ] 提交脱敏占位符时该 webhook 的原值保留不变
- [ ] 存量设置行(无 im_push)读写兼容,默认 enabled=false
- [ ] 单测覆盖校验规则、脱敏回显、占位符透传、存量兼容(纯函数 + 现有 settings 集成测试接缝)
- [ ] 覆盖率门槛(80%)保持通过

---

# Parent

specs/006-wecom-im-push/spec.md
