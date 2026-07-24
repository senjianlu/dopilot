# 0013:Python 脚本以 `.whl` 接入：无 venv、无依赖解析

- 日期:阶段 2 规划（2026-06 下旬），阶段 2b 落地
- 背景:Python 脚本类任务需要一个可上传、可校验、可缓存的打包格式，以及
  一个尽量简单、可预测的 agent 侧运行模型；按脚本建 venv/解析依赖会带来
  不可控的安装时间与失败面。
- 决定:阶段 2 使用 **`.whl`** 作为 Python 脚本构建产物格式。agent 侧按
  sha256 安装一次：

  ```bash
  pip install --no-deps --target <cache>/python_wheel/<sha256>/site <wheel>
  ```

  **不创建 venv、不做依赖解析、不写 console-script 入口**。运行时把该 site
  目录注入 `PYTHONPATH`，以 `/bin/sh -c "<command>"`（独立进程组）启动
  （如 `python -m main`），强制 `PYTHONUNBUFFERED=1`，stdout/stderr 合并经
  Redis log stream 实时推送，以子进程退出码收敛执行状态（0 → succeeded，
  非 0 → failed；取消 SIGTERM→grace→SIGKILL → canceled）。
- 影响:
  - wheel 之外的依赖须操作者预先装入 agent 环境——这是运维契约，不是缺陷。
  - 第一版不要求脚本 SDK/心跳协议；agent 以子进程生命周期为状态权威。
