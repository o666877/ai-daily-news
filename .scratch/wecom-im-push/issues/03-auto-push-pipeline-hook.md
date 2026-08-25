# 03: 自动链路 — 生成挂点 + 推送记录 + 防重

**What to build:** 每当一期日报状态迁移为 ready(定时任务或手动重新生成,任何路径),系统自动把当期 Top N 条目推送到所有已启用的企微 webhook;每个 webhook 的推送结果落库可查;同一期对同一 webhook 只自动成功推送一次(重复触发生成不刷屏);推送最终失败只记录状态,绝不阻塞或破坏日报生成本身。

**Blocked by:** 02 (企微 notifier + 测试端点)

**Status:** ready-for-agent

- [ ] 挂点在生成流程状态迁移为 ready 的路径上,与生成入口无关
- [ ] enabled=false 或未配置 webhook 时零行为、零报错
- [ ] 推送记录表:issue 标识 + webhook 标识 + 状态 + 错误摘要 + 时间;多 webhook 多行
- [ ] 自动防重:该 issue + webhook 已有 success 记录则跳过
- [ ] 推送异常被捕获并落库,issue 仍为 ready,生成主流程不受影响
- [ ] 推送的条目为当期得分最高的 Top N(取自 im_push.top_n)
- [ ] 集成测试(现有接缝 + respx):生成后自动推送、重复生成防重、部分 webhook 失败不影响其他、推送失败不改变 issue 状态
- [ ] 覆盖率门槛保持通过

---

# Parent

specs/006-wecom-im-push/spec.md
