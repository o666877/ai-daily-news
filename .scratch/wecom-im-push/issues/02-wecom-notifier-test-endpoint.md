# 02: 推送面 — 企微 notifier + 测试消息端点

**What to build:** 运营者配置好 webhook 后,能通过"发送测试消息"端点立即在企微群里收到一条真实的 markdown 消息,以此验证 webhook 有效性——不用等第二天定时推送。消息由企微 notifier 模块构建与发送:markdown 渲染、超 4096 字节按条目截断、link_base_url 为空时降级为无链接纯文本、网络失败/限频自动指数退避重试。

**Blocked by:** 01 (im_push 配置基座)

**Status:** ready-for-agent

- [ ] notifier 函数边界:push(issue 或测试载荷, webhooks) → 逐 webhook 结果;不建协议/注册表
- [ ] markdown 消息结构:标题 + 日期 + Top N 条目(标题+一句话摘要)+ 完整日报链接;超限截断保链接;无 link_base_url 降级
- [ ] HTTP 失败与企微限频走 tenacity 重试(3 次,2s/4s/8s)
- [ ] 测试消息端点按设置路由风格挂载,对指定 webhook 发送一条测试 markdown
- [ ] 错误响应不含完整 webhook URL
- [ ] respx mock 企微 HTTP(respx 只挡 qyapi 外部边界):成功、5xx 后重试成功、重试穷尽、限频、超长截断、无链接降级
- [ ] 覆盖率门槛保持通过

---

# Parent

specs/006-wecom-im-push/spec.md
