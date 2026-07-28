# Plan 评审:第 02 轮

## 问题清单
- [major] R-01 方案漏改 healthcheck 测试的环境隔离逻辑，完整测试可能受宿主环境污染。
  - 详情:定位：plan.md:51-69、121-127、248；apps/agent/tests/test_healthcheck.py:30-33。`_use_config()` 当前清除 `AGENT_ID`/`AGENT_WORKDIR`；加载器改读新变量后，它必须改为清除 `DOPILOT_AGENT_ID`/`DOPILOT_AGENT_WORKDIR`，否则运行环境若已设置这些常规部署变量，healthcheck 测试会覆盖测试 TOML，尤其“缺少 agent_id 应失败”的用例可能错误通过。plan 将全部 tests 排除为普通常量并仅列出 `test_config.py`，没有覆盖这一实际 env 操作；TC-07 在干净环境通过也无法证明隔离正确。请把 `apps/agent/tests/test_healthcheck.py` 纳入改动范围并更新该 helper，同时修正预计文件数及 TC-03 对 tests 的排除说明。

## 总评
方案的改名路径、异常用例和证据契约整体自洽：7 条用例均逐条声明 A 档及证据形态，C 档为 0。修正上述测试范围遗漏后，可避免实现阶段因测试污染问题返工。

VERDICT: fail
