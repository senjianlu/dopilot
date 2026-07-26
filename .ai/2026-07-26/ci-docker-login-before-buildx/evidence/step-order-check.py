#!/usr/bin/env python3
"""TC-01:断言 docker workflow 中 Login 步骤早于 QEMU 与 Buildx。

用法(cwd 必须是仓库根):
    python3 <本脚本> <workflow yaml 路径>

对 base / app 两个 job 分别取步骤 name 序列,断言:
    idx(Login to Docker Hub) < idx(Set up QEMU)
    idx(Login to Docker Hub) < idx(Set up Docker Buildx)
退出码:0=全部满足;1=有 job 违例或步骤缺失;2=用法/解析错误。

TC-03 的反向自检会拿旧顺序副本调用本脚本,断言其非零退出。
"""

import sys

import yaml

JOBS = ("base", "app")
LOGIN = "Login to Docker Hub"
QEMU = "Set up QEMU"
BUILDX = "Set up Docker Buildx"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("用法:python3 step-order-check.py <workflow yaml 路径>", file=sys.stderr)
        return 2

    path = argv[0]
    try:
        with open(path, encoding="utf-8") as fh:
            wf = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        print(f"YAML 解析失败:{exc}", file=sys.stderr)
        return 2

    # 注:PyYAML 按 YAML 1.1 把裸 `on:` 解析成布尔 True,故顶层 key 混有
    # bool 与 str,不能直接 sorted();统一转字符串再排序。
    print(f"== 解析 {path} ==")
    print("  YAML 合法,顶层 keys:", sorted(map(str, wf.keys())))

    failed = False
    for job in JOBS:
        print()
        print(f"== job: {job} ==")
        if job not in wf.get("jobs", {}):
            print(f"  FAIL  workflow 中不存在 job [{job}]")
            failed = True
            continue

        names = [s.get("name", f"<无 name, uses={s.get('uses')}>")
                 for s in wf["jobs"][job]["steps"]]
        for i, n in enumerate(names):
            print(f"    [{i}] {n}")

        idx = {}
        for label in (LOGIN, QEMU, BUILDX):
            if label not in names:
                print(f"  FAIL  缺少步骤:{label}")
                failed = True
            else:
                idx[label] = names.index(label)

        if len(idx) != 3:
            continue

        print(f"  下标:{LOGIN}={idx[LOGIN]}  {QEMU}={idx[QEMU]}  {BUILDX}={idx[BUILDX]}")
        for later in (QEMU, BUILDX):
            if idx[LOGIN] < idx[later]:
                print(f"  OK    {LOGIN}({idx[LOGIN]}) < {later}({idx[later]})")
            else:
                print(f"  FAIL  {LOGIN}({idx[LOGIN]}) 未早于 {later}({idx[later]})"
                      " —— 该步骤的镜像拉取仍是匿名的")
                failed = True

    print()
    print("RESULT: FAIL" if failed else "RESULT: PASS —— 两个 job 均为 login 前置")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
