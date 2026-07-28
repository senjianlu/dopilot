# Kubernetes / k3s 部署:dopilot agent(参考清单)

本目录是 **agent-only** 接入清单的通用参考版,与
[`deploy/docker/docker-compose.agent.yml`](../../docker/docker-compose.agent.yml)
同一角色:一个或多个**纯出站** worker agent,接入一个单独部署的 server。
agent 消费 server 的 Redis 命令、向 server POST 心跳,**无入站 HTTP、不绑任何
端口**,因此这里刻意没有 Service。

server 侧的部署仍走
[`docker-compose.server.yml`](../../docker/docker-compose.server.yml)
(或你自有的 server 编排),本清单只管 agent。

## 文件

| 文件 | 内容 |
|---|---|
| `statefulset.yaml` | Namespace `dopilot` + StatefulSet `dopilot-agent`(单容器、hostNetwork、控制面排除 + 每节点一实例反亲和、exec 探针、`DOPILOT_AGENT_ID` 取 pod 名、20Gi PVC volumeClaimTemplate) |
| `secret.example.yaml` | Secret `dopilot-agent` 占位示例(`agent-token` / `redis-url`);**填真值的副本绝不入库** |

## 部署

```bash
# 1) 先建 namespace —— Secret 与 StatefulSet 都落在 dopilot 下,必须先存在
#    (若已存在可跳过本步):
kubectl create namespace dopilot

# 2) 创建凭据 Secret(优先命令式,磁盘上不留文件、无从误提交):
kubectl -n dopilot create secret generic dopilot-agent \
  --from-literal=agent-token='<server-agent-token>' \
  --from-literal=redis-url='redis://:<redis-pass>@<server-host>:6379/0'
#    server-agent-token 在 server 主机上取:
#      docker compose -f docker-compose.server.yml exec server \
#        dopilot-server agent-token print
#    非空 token 必须 >= 16 字符;agent 永不获得 admin token。

# 3) 改 statefulset.yaml 里的 DOPILOT_SERVER_URL 占位为 agent 可达的地址,
#    例如 http://<server-ip-or-dns>:5000 或 https://dopilot.example.com。

# 4) apply(statefulset.yaml 顶部内置 Namespace 文档,kubectl apply 会幂等
#    重复应用,已存在则显示 unchanged,不报错;若嫌重复可先删该文档段):
kubectl apply -f statefulset.yaml
```

必填项(缺一 agent 无法入群):`namespace dopilot`、`Secret dopilot-agent`
(agent-token + redis-url)、`DOPILOT_SERVER_URL`。K8s 没有 compose 那种 `:?`
快速失败,**探针也不会暴露坏 URL**:`dopilot-agent-healthcheck` 只校验配置
加载与本地 scrapyd,不测 server 连通性。所以 `DOPILOT_SERVER_URL` 忘改时
**Pod 照样 Ready**,但 agent 心跳连不上 server、**从未真正入群**(静默失败)。
务必先改 URL 再 apply,并在 server 侧确认入群:节点应出现/刷新在
`nodes.last_seen_at`(即运维清理页 `/maintenance` 的 agent 板块),不能凭
Pod Ready 判定已入群。

安全口径(与 compose 接入栈一致):

- token 认证**不是**传输加密。agent → server 的 Redis 与 HTTP 跨主机时,
  须走私网 / VPN,或在反代处终止 TLS。
- agent **永不**注入 `DOPILOT_ADMIN_API_TOKEN`(admin 专用)。

## PVC 即 agent 磁盘硬顶

`volumeClaimTemplates` 的 20Gi 就是该 agent 本地磁盘的硬上限,运维清理页面
(`/maintenance`)的每-agent 板块显示的正是该卷的用量 / 容量。请把容量设到
`artifact_cache_max_bytes` + 工作集余量之上;应用层的清扫与缓存淘汰口径见
[docs/architecture/04-configuration.md](../../../docs/architecture/04-configuration.md)。

## 待办(本期未做,按需自行加)

本清单先照现网结构原样入库,以下防膨胀 / 加固项**尚未写入**,按你的集群
策略择机补:

- **容器 resources**:给 `agent` 容器加 `resources.requests/limits`
  (cpu / memory),避免单 agent 抢占节点资源。示例:
  ```yaml
  resources:
    requests: { cpu: 250m, memory: 256Mi }
    limits:   { cpu: "1",  memory: 1Gi }
  ```
- **ephemeral-storage 限额**:给容器 `resources` 加
  `ephemeral-storage` 请求 / 上限,防止写爆节点 rootfs(agent 的大文件应
  落在 20Gi PVC 的 `/agent-data`,而非容器可写层)。
- **容器 stdout/stderr 日志轮转**:K8s 下容器日志由 **kubelet** 管,不是
  docker 的 `json-file`。k3s 在 `/etc/rancher/k3s/config.yaml` 设 kubelet-arg
  即可全节点生效:
  ```yaml
  kubelet-arg:
    - "container-log-max-size=10Mi"
    - "container-log-max-files=3"
  ```
  这两个 kubelet-arg flag 等价于 KubeletConfiguration 的 `containerLogMaxSize`
  / `containerLogMaxFiles` 字段(用独立 kubelet config 文件时写字段名)。
  改后重启 k3s 服务。这一项对齐 compose 侧 `json-file max-size=10m /
  max-file=3` 的宿主机磁盘保护(应用层上限见
  [docs/architecture/05-deployment.md](../../../docs/architecture/05-deployment.md)
  「资源硬上限」)。

## 扩展:secrets 注入 sidecar

本清单是通用版,不含任何 secrets 注入 sidecar。若你的 agent 运行的爬虫需要
额外机密(例如把 `config.env` 注入到 `/run/secrets/`),按你的基础设施在
`agent` 容器上自行叠加:加对应的 init/sidecar 容器、`serviceAccountName`、
共享 `emptyDir` 卷与 `volumeMounts`。这些属站点侧扩展,与 dopilot 的入群
口径正交,不影响上面的 token / redis / server-url 三项必填。
