# 0003:单管理员，无多用户/RBAC

- 日期:2026-06-17
- 背景:dopilot 定位自托管、个人/小团队运维一套调度平台；多用户与角色体系
  会显著增加认证、审计与 UI 复杂度，而目标场景只有一个运维者。
- 决定:**单用户、唯一管理员**。不做多用户、不做 RBAC、不做注册流程；认证
  简化为单管理员登录（含 opaque access token 与静态 admin API token，细则见
  [0011](0011-auth-boundaries.md)）。
- 影响:
  - API/Web/数据模型均不含 user/role 维度；第一版也不做 mTLS/token 轮换。
  - 该决策与单实例约束（[0010](0010-single-instance-server.md)）共同定义了
    dopilot 的"自托管单管理员"产品边界，不再复议。
