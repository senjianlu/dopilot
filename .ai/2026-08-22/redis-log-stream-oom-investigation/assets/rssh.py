#!/home/rabbir/.claude/jobs/067151cf/tmp/venv/bin/python
"""usage: rssh.py <host> <cmd...>  (password via env RSSH_PW)"""
import os, sys, paramiko
host = sys.argv[1]
cmd = " ".join(sys.argv[2:])
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, username="rabbir", password=os.environ["RSSH_PW"], timeout=15, banner_timeout=30)
_, out, err = c.exec_command(cmd, timeout=600)
sys.stdout.write(out.read().decode(errors="replace"))
e = err.read().decode(errors="replace")
if e:
    sys.stdout.write("[stderr]\n" + e)
rc = out.channel.recv_exit_status()
c.close()
sys.exit(rc)
