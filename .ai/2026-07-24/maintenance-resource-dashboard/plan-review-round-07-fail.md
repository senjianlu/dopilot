# Plan 评审:第 07 轮

## 问题清单
- [major] R-01 年龄指标的告警规则存在重叠，部分合法配置下无法确定应返回 ok 还是 critical
  - 详情:定位：plan.md「实现方案 §2 → 统一状态契约 → 年龄类」。方案同时规定 `age ≤ limit + grace → ok` 和 `age > 2 × limit → critical`，其中 `grace = 2 × sweep_interval_seconds`。当 `grace > limit` 时，两者会重叠；例如 limit=100、grace=200、age=250 同时满足 ok 与 critical。当前配置模型未约束保留窗口必须大于 grace，TC-02 也未覆盖该重叠区间，实施者将不得不自行决定判断顺序，可能造成积压被错误显示为正常。请在方案中明确互斥且有优先级的分段规则（例如 critical 优先，或以 `max(limit + grace, 2 × limit)` 定义 critical 边界），并在 TC-02 增加 `grace > limit` 的参数化边界用例。

## 总评
方案整体与 rawf 工作流及证据契约相符：17 条用例均逐条声明档位和证据形态，全部可自动化项为 A 档，C 档为 0，并覆盖了主要故障路径。但年龄告警核心算法在合法配置下存在互相矛盾的判定，必须先明确规则并补充边界测试，因此本轮评审失败。

VERDICT: fail
