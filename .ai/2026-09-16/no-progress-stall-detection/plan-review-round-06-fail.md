# Plan 评审:第 06 轮

## 问题清单
- [major] R-01 超时收尾后才收到 cleanup_logs 的路径没有持久保存清理意图。
  - 详情:定位：plan.md §4.5 第2、5条及 §4.7。超时后 state 为 done、kill_pending=True；此时首次收到 cleanup_logs，第2条会直接调用 _do_cleanup，与第5条禁止清理冲突。即使按第5条跳过清理，也未设置 cleanup_pending，命令被 ACK 后，进程退出时不会再清理。cancel 的清理命令通常正是在终态报告后才到达，属于正常路径。应将 kill_pending=True 也纳入持久挂起清理的条件，并新增“先超时收尾、后收到 cleanup、最终退出”的 A 档用例。现有 TC-37~39 均预先设置 cleanup_pending，未覆盖该路径。
- [major] R-02 先 mark_done 再设置 kill_pending 留下重启后丢失回收任务的窗口。
  - 详情:定位：plan.md §4.3 第3步（218~220行）。规定的顺序是 mark_done + emit，随后才设置 kill_pending。若在两次持久化之间退出，重启后 state 已是 done，但 kill_pending 仍为默认 False；§4.7 不会继续杀进程，若 cleanup_pending=True 还会直接删除映射。应在同一次原子状态写入中保存 done、结果和 kill_pending=True，再报告终态；明确该持久化边界，并增加此处故障注入及重启恢复的 A 档用例。
- [major] R-03 TC-30 的验收结果与持续回收设计直接矛盾。
  - 详情:定位：plan.md TC-30（406行）与 §4.3、§4.4、§4.7。TC-30 要求 scrapyd 持续 unknown、超过确认期限后真正执行延期清理；设计则要求未确认退出时保留映射、设置 kill_pending，unknown 期间禁止清理。两者无法同时通过，且 rawf-implement 禁止实现者自行改写验收预期。应修改 TC-30：超时仅完成相应终态处理，保留 state、映射及 cleanup_pending；继续 unknown 时不清理，恢复并确认退出后才清理，并分别覆盖 cancel/reclaim。

## 总评
方案的进度信号隔离方向合理，测试均逐条声明 A 档及证据形态，符合证据契约。停止后的清理交错、回收状态持久化和一条矛盾验收仍会导致实现返工，需修订后重评；本次仅做只读核验，未运行测试。

VERDICT: fail
