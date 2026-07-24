### TC-07 (round-05 regenerated): plan keyword set present
$ /usr/bin/grep -niE "resources|ephemeral-storage|containerLogMaxSize" deploy/kubernetes/agent/README.md; echo "exit=$?"
71:- **容器 resources**:给 `agent` 容器加 `resources.requests/limits`
74:  resources:
78:- **ephemeral-storage 限额**:给容器 `resources` 加
79:  `ephemeral-storage` 请求 / 上限,防止写爆节点 rootfs(agent 的大文件应
89:  这两个 kubelet-arg flag 等价于 KubeletConfiguration 的 `containerLogMaxSize`
exit=0
