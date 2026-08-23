"""Streaming RDB (v9-v12) scanner: per-key type/size; stream listpack sampling.
usage: rdbscan.py dump.rdb [sample_every_n_listpacks]"""
import sys, struct, re, collections, json
import lzf

f = open(sys.argv[1], "rb")
SAMPLE_N = int(sys.argv[2]) if len(sys.argv) > 2 else 0
pos = 0
def rd(n):
    global pos
    b = f.read(n); pos += n
    if len(b) != n: raise EOFError
    return b
def rlen():
    b = rd(1)[0]; t = b >> 6
    if t == 0: return b & 0x3f, None
    if t == 1: return ((b & 0x3f) << 8) | rd(1)[0], None
    if t == 2:
        if b == 0x80: return struct.unpack(">I", rd(4))[0], None
        if b == 0x81: return struct.unpack(">Q", rd(8))[0], None
        raise ValueError("bad len byte %x" % b)
    return None, b & 0x3f  # special encoding
def rstr(want=True):
    """returns (bytes_or_None, stored_len, logical_len)"""
    n, enc = rlen()
    if enc is None:
        data = rd(n) if want else (f.seek(n, 1), None)[1]
        if not want: 
            global pos; pos += n
        return data, n, n
    if enc == 0: return str(struct.unpack("<b", rd(1))[0]).encode(), 1, 1
    if enc == 1: return str(struct.unpack("<h", rd(2))[0]).encode(), 2, 2
    if enc == 2: return str(struct.unpack("<i", rd(4))[0]).encode(), 4, 4
    if enc == 3:
        clen, _ = rlen(); ulen, _ = rlen()
        comp = rd(clen)
        if want:
            return lzf.decompress(comp, ulen), clen, ulen
        return None, clen, ulen
    raise ValueError("bad str enc %d" % enc)

TYPE_NAMES = {0:"string",1:"list",2:"set",3:"zset",4:"hash",5:"zset2",9:"hash_zl",10:"list_zl",11:"set_intset",12:"zset_zl",13:"hash_zl",14:"list_ql",15:"stream_lp",16:"hash_lp",17:"zset_lp",18:"list_ql2",19:"stream_lp2",20:"set_lp",21:"stream_lp3"}
RE_EXEC = re.compile(rb'"execution_id":"([^"]+)"')
RE_TASK = re.compile(rb'"task_id":"([^"]+)"')
RE_AGENT = re.compile(rb'"agent_id":"([^"]+)"')
RE_SIZE = re.compile(rb'"size_bytes":(\d+)')
RE_TYPE = re.compile(rb'"type":"([^"]+)"')
RE_CREATED = re.compile(rb'"created_at":"([^"]+)"')

def parse_stream(t, key):
    info = collections.OrderedDict()
    nlp, _ = rlen()
    stored = 0; logical = 0
    per_exec = collections.Counter(); per_exec_bytes = collections.Counter(); per_task = collections.Counter()
    per_agent = collections.Counter(); per_type = collections.Counter(); created = []
    sampled = 0
    for i in range(nlp):
        _nodekey, s1, _ = rstr(True)
        want = SAMPLE_N and (i % SAMPLE_N == 0)
        data, s2, l2 = rstr(want)
        stored += s1 + s2; logical += 16 + l2
        if want and data:
            sampled += 1
            ex = RE_EXEC.findall(data); 
            for e in ex: per_exec[e] += 1
            for tk in RE_TASK.findall(data): per_task[tk] += 1
            for a in RE_AGENT.findall(data): per_agent[a] += 1
            for ty in RE_TYPE.findall(data): per_type[ty] += 1
            # size_bytes follows execution_id in the JSON; pair them in order
            sizes = RE_SIZE.findall(data)
            for e, sz in zip(ex, sizes): per_exec_bytes[e] += int(sz)
            cr = RE_CREATED.findall(data)
            if cr: created.append((cr[0].decode(), cr[-1].decode()))
    length, _ = rlen(); last_ms, _ = rlen(); last_seq, _ = rlen()
    info.update(listpacks=nlp, stored_bytes=stored, logical_bytes=logical, length=length, last_id=f"{last_ms}-{last_seq}")
    if t >= 19:
        fms,_=rlen(); fseq,_=rlen(); dms,_=rlen(); dseq,_=rlen(); added,_=rlen()
        info.update(first_id=f"{fms}-{fseq}", entries_added=added)
    ng, _ = rlen(); groups = []
    for _ in range(ng):
        name, _, _ = rstr(True); gms,_=rlen(); gseq,_=rlen()
        g = dict(name=name.decode(errors="replace"), last_delivered=f"{gms}-{gseq}")
        if t >= 19: g["entries_read"], _ = rlen()
        npel, _ = rlen(); g["pel"] = npel
        for _ in range(npel):
            rd(16); rd(8); rlen()
        nc, _ = rlen(); cons = []
        for _ in range(nc):
            cname, _, _ = rstr(True); rd(8)
            if t >= 21: rd(8)
            cpel, _ = rlen(); rd(16 * cpel)
            cons.append(dict(name=cname.decode(errors="replace"), pel=cpel))
        g["consumers"] = cons; groups.append(g)
    info["groups"] = groups
    if sampled:
        info["sample"] = dict(listpacks_sampled=sampled,
            per_agent={k.decode():v for k,v in per_agent.most_common()}, per_type={k.decode():v for k,v in per_type.most_common(10)},
            top_exec_entries=[(k.decode(),v) for k,v in per_exec.most_common(15)], top_exec_rawbytes=[(k.decode(),v) for k,v in per_exec_bytes.most_common(15)],
            distinct_exec=len(per_exec), top_task=[(k.decode(),v) for k,v in per_task.most_common(15)], distinct_task=len(per_task),
            created_first=created[0] if created else None, created_last=created[-1] if created else None)
    return info

def skip_value(t):
    if t == 0: rstr(False); return
    if t in (9,10,11,12,13,16,17,20): rstr(False); return
    if t in (1,2): n,_=rlen(); [rstr(False) for _ in range(n)]; return
    if t == 4: n,_=rlen(); [ (rstr(False), rstr(False)) for _ in range(n)]; return
    if t == 3: n,_=rlen(); [ (rstr(False), rd(rd(1)[0] if False else 0)) for _ in range(n)]; raise NotImplementedError("zset")
    if t == 5: n,_=rlen(); [ (rstr(False), rd(8)) for _ in range(n)]; return
    if t == 14: n,_=rlen(); [rstr(False) for _ in range(n)]; return
    if t == 18: n,_=rlen(); [ (rlen(), rstr(False)) for _ in range(n)]; return
    raise NotImplementedError("type %d" % t)

magic = rd(9); print("header", magic)
db = None; expire = None
while True:
    op = rd(1)[0]
    if op == 0xFF: print("EOF at", pos); break
    if op == 0xFA: k,_,_ = rstr(); v,_,_ = rstr(); print("aux", k, v); continue
    if op == 0xFE: db,_ = rlen(); print("SELECTDB", db); continue
    if op == 0xFB: a,_=rlen(); b,_=rlen(); print("RESIZEDB keys=%d expires=%d" % (a,b)); continue
    if op == 0xFD: expire = struct.unpack("<I", rd(4))[0]; continue
    if op == 0xFC: expire = struct.unpack("<Q", rd(8))[0]; continue
    if op == 0xF5: rd(1); continue
    if op == 0xF4: rlen(); continue
    if op == 0xF3: rstr(False); continue
    if op == 0xF4: rlen(); continue
    t = op
    key,_,_ = rstr(True)
    start = pos
    if t in (15,19,21):
        info = parse_stream(t, key)
        print(json.dumps({"key": key.decode(errors="replace"), "type": TYPE_NAMES.get(t,t), "expire": expire, "file_bytes": pos-start, **info}, indent=1, default=str))
    else:
        skip_value(t)
        print(json.dumps({"key": key.decode(errors="replace"), "type": TYPE_NAMES.get(t,t), "expire": expire, "file_bytes": pos-start}))
    expire = None
