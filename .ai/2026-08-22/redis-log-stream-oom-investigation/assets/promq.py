import sys, json, urllib.request, urllib.parse, datetime as dt
P="http://192.168.10.223:9090"
def rng(q, start, end, step):
    u=P+"/api/v1/query_range?"+urllib.parse.urlencode({"query":q,"start":start,"end":end,"step":step})
    return json.load(urllib.request.urlopen(u, timeout=30))["data"]["result"]
q=sys.argv[1]; start=sys.argv[2]; end=sys.argv[3]; step=sys.argv[4]
for s in rng(q,start,end,step):
    print("##", json.dumps(s["metric"]))
    for t,v in s["values"]:
        print(dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime("%m-%d %H:%MZ"), v)
