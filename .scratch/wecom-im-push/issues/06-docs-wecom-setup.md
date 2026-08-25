# 06: 文档 — SETUP/README/接口文档更新

**What to build:** 新用户按 SETUP.md 从零创建企微群机器人并完成推送配置,全程不需要看代码;开源仓库访客从 README 功能列表得知该能力;后端接口文档覆盖新设置字段、两个新端点与推送记录表。

**Blocked by:** 04 (手动重推 + 日报页), 05 (设置页配置区)

**Status:** ready-for-agent

- [ ] SETUP.md 新增"企业微信群机器人"配置节:创建机器人、复制 webhook、填入设置页、发送测试消息
- [ ] README 功能列表新增 IM 推送一行
- [ ] 后端接口文档:im_push 设置字段说明(含脱敏规则)、测试消息端点、手动重推端点、推送记录表结构
- [ ] link_base_url 的说明含内网穿透/公网部署两种场景与"留空则纯摘要"行为
- [ ] 文档中的示例不含任何真实 webhook key

---

# Parent

specs/006-wecom-im-push/spec.md
