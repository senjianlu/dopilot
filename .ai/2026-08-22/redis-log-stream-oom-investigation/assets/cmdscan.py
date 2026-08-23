import sys, re, json, collections, datetime as dt
sys.argv = [sys.argv[0], "dump.rdb", "1"]
src = open("rdbscan.py").read()
# monkeypatch: only decompress listpacks for command streams; collect raw payload JSON for them
src = src.replace("want = SAMPLE_N and (i % SAMPLE_N == 0)", "want = (b':commands' in key)")
src = src.replace("        if want and data:\n            sampled += 1", "        if want and data:\n            sampled += 1\n            CMDS.setdefault(key, []).append(data)")
CMDS = {}
g = {"CMDS": CMDS}
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(src, "rdbscan_patched", "exec"), g)
RE = re.compile(rb'\{"command_id":"[^"]+","type":"(run|stop|cleanup_logs)","agent_id":"([^"]+)","task_id":"([^"]+)","execution_id":"([^"]+)","task_type":"([^"]+)","intent":(null|"[a-z]+"),"payload":(\{.*?\}),"created_at":"([^"]+)"\}')
rows = []
for key, lps in g["CMDS"].items():
    for data in lps:
        for m in RE.finditer(data):
            typ, agent, task, ex, ttype, intent, payload, created = [x.decode() for x in m.groups()]
            spider = re.search(r'"spider":"([^"]+)"', payload); project = re.search(r'"project":"([^"]+)"', payload)
            rows.append(dict(stream=key.decode(), type=typ, agent=agent, task=task, execution=ex, intent=intent.strip('"'),
                             project=project.group(1) if project else None, spider=spider.group(1) if spider else None, created=created))
print("commands decoded:", len(rows))
json.dump(rows, open("evidence/rdb-commands-decoded.json", "w"))
rows.sort(key=lambda r: r["created"])
win = [r for r in rows if "2026-08-21T10:00" <= r["created"] <= "2026-08-22T03:30"]
print("window 08-21T10:00..08-22T03:30:", len(win))
print("--- by type:", collections.Counter(r["type"] for r in win))
print("--- run commands per hour (all / steammarket):")
hr = collections.Counter(); sm = collections.Counter()
for r in win:
    if r["type"] != "run": continue
    h = r["created"][:13]; hr[h] += 1
    if (r["project"] or "") .startswith("steammarket") or (r["spider"] or "").startswith("steammarket"): sm[h] += 1
for h in sorted(hr): print(f"  {h}  run={hr[h]:4d}  steammarket={sm[h]:4d}")
print("--- steammarket projects/spiders in window:")
print(collections.Counter((r["project"], r["spider"]) for r in win if r["type"]=="run" and "steammarket" in (r["project"] or "")+(r["spider"] or "")).most_common(30))
print("--- the 5 giant executions:")
for r in rows:
    if r["execution"] in ("7e52e2092a714a85aeedec114cab021c","77455002db4b4d658b73dbae8b0ccfa9","69a7ee968b004b57b919a22b3e2a70b8","68c3466be3ad4dfa93ebbe82f5ebe564","7b98eb548030427985758a32d568c6f9"):
        print("  ", r)
print("--- stop commands in window:", [ (r["created"][:19], r["agent"], r["intent"], r["execution"][:8]) for r in win if r["type"]=="stop"][:40])
