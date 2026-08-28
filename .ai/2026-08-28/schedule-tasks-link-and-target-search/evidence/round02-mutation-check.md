# 变异验证:证明 TC-10 / TC-14 的断言确实有牙齿

第 01 轮评审 R-01 判定这两条用例的断言弱于 plan 契约。修正断言后,为避免
"改完仍是形同虚设"的重演,对被测源码故意注入两个 bug,确认用例会变红,
随后完全还原源码。

## 变异 1:防抖回调改为捕获快照(对应 TC-14)

改动 `apps/web/app/(app)/tasks/page.tsx` 的防抖提交:

```diff
-      setFilters((prev) => ({ ...prev, q: searchInput, page: 1 }));
+      setFilters({ ...filters, q: searchInput, page: 1 });
```

结果(命令:`corepack pnpm exec vitest run "app/(app)/tasks/__tests__/tasks.test.tsx" -t "uses the LATEST"`):

```
× TasksPage target search > uses the LATEST filters when the debounce fires, not the ones captured while typing 665ms
  → expected last "spy" call to have been called with [ ObjectContaining{…} ]
AssertionError: expected last "spy" call to have been called with [ ObjectContaining{…} ]
      Tests  1 failed | 15 skipped (16)
```

## 变异 2:防抖窗口由 300ms 改为 150ms(对应 TC-10)

```diff
-const SEARCH_DEBOUNCE_MS = 300;
+const SEARCH_DEBOUNCE_MS = 150;
```

结果(命令:`corepack pnpm exec vitest run "app/(app)/tasks/__tests__/tasks.test.tsx" -t "debounces typing"`):

```
× TasksPage target search > debounces typing and resets to page 1 418ms
  → expected 2 to be 1 // Object.is equality
AssertionError: expected 2 to be 1 // Object.is equality
      Tests  1 failed | 15 skipped (16)
```

即:在 299ms 处已经发出了请求(2 次调用而非 1 次),边界断言正确捕获。

## 还原确认

```
$ cp <备份> "apps/web/app/(app)/tasks/page.tsx"
$ diff <备份> "apps/web/app/(app)/tasks/page.tsx"
源码已完全还原
87:const SEARCH_DEBOUNCE_MS = 300;
160:      setFilters((prev) => ({ ...prev, q: searchInput, page: 1 }));
224:      setFilters((prev) => ({ ...prev, q: searchInput, page: 1 }));
```

还原后本文件同目录的 `round02-*.txt` 系列即为最终全绿证据。
