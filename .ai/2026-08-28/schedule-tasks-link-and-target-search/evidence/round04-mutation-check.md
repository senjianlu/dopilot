# 变异验证:TC-11 是否真能抓到"过期响应覆盖新结果"

第 03 轮评审 R-01 判定 TC-11 的断言存在"提前通过窗口"——`first.resolve()`
之后直接 `waitFor` 一个本来就不存在的 `task-old`,可能在旧 Promise 回调与
React 渲染发生之前就通过。该判定成立。

重写后(等待过期 Promise 与其回调链在 `act` 内完全结算,再断言;并让过期
响应的 `total` 与新响应不同,使"被应用"在页码上也可见),做变异验证。

## 变异 1:只移除请求序号守卫 → 用例仍通过

```diff
       .then((res) => {
-        if (!alive || seq !== reqSeq.current) return;
+        if (!alive) return;
```

```
✓ TasksPage target search > discards a stale response that lands after a newer one 800ms
      Tests  1 passed | 15 skipped (16)
```

**这暴露了一个实现事实**:`alive` 才是实际生效的那道防护。请求只由那个
以 `filters` 为依赖的 effect 发出,发新请求必然意味着 effect 重跑,而重跑
之前 cleanup 已把旧闭包的 `alive` 置为 `false`。因此"序号过期"与
"`alive` 为 false"在本设计中**逻辑等价**,`reqSeq` 是冗余的第二道守卫。

## 变异 2:两道守卫都移除 → 用例失败

```diff
       .then((res) => {
-        if (!alive || seq !== reqSeq.current) return;
```

```
× TasksPage target search > discards a stale response that lands after a newer one 907ms
  → expected <td data-slot="table-cell" …(2)></td> to be null
AssertionError: expected <td data-slot="table-cell" …(2)></td> to be null
      Tests  1 failed | 15 skipped (16)
```

即:去掉全部防护后,过期的 `task-old` 行确实会渲染出来并被用例捕获。
TC-11 对 plan 要求的行为("A 晚于 B resolve 后最终仍显示 B")确有约束力。

## 还原确认

```
$ cp <备份> "apps/web/app/(app)/tasks/page.tsx"
$ diff <备份> "apps/web/app/(app)/tasks/page.tsx"
源码已完全还原
181:        if (!alive || seq !== reqSeq.current) return;
187:        if (!alive || seq !== reqSeq.current) return;
```
