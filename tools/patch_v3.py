"""De-ad patch v3 — staged, risk-tiered variants.

modes:
  none     : 原样重打包（对照包，验证签名/打包链路）
  minimal  : 只黑洞广告域名（仅 URL 形态，不动裸域名词），不改任何代码
  safe     : minimal + 3 个纯 BOOL 判定方法（只决定"能不能展示"，没有流程副作用）
"""
import struct, sys, os, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho
import objc_detail as od

INSN_MOV_W0_0 = struct.pack("<I", 0x52800000)
INSN_RET      = struct.pack("<I", 0xD65F03C0)
INSN_NOP      = struct.pack("<I", 0xD503201F)

SAFE_PATCHES = [
    ("TCCampusAdManager",              "-", "canShowSplashAd",        "bool_false"),
    ("TCUbiXSplashADvertisingManager", "-", "canShowAd",              "bool_false"),
    ("TCUbixFeedAdvertisingManager",   "-", "canShowAdWithType:node:", "bool_false"),
]

# 只含"能不能展示"的布尔判定，语义等价于"当前没有广告可放"，
# 不改变任何流程触发/回调/数据装载，App 本来就要处理无广告分支。
STRONG_PATCHES = SAFE_PATCHES + [
    ("TCCampusAdManager",              "-", "enableAd",                                    "bool_false"),
    ("TCCampusAdManager",              "+", "canShowSplashAdCount",                         "bool_false"),
    ("TCCampusAdManager",              "+", "isHaveInlistAdModel",                          "bool_false"),
    ("TCUbiXSplashADvertisingManager", "+", "canShowUBIXSplashAd",                          "bool_false"),
    ("TCUbiXSplashADvertisingManager", "+", "canShowSplashAdCount",                         "bool_false"),
    ("TCUbixFeedAdvertisingManager",   "-", "canShowAdWithInlistId:",                       "bool_false"),
    ("TCUbixFeedAdvertisingManager",   "-", "canShowADCheckCountWithType:node:",            "bool_false"),
    ("TCUbixFeedAdvertisingManager",   "+", "canShowPitADWithPitType:withInlistId:node:",    "bool_false"),
]

# 只替换 "scheme://host" 形态里的 host，避免影响 hasSuffix / 白名单等裸串比较
AD_HOSTS = [
    "sdk-data.ubixioe.com", "tower.ubixioe.com", "tx-cfg-u1.ubixioe.com", "tx-data-u1.ubixioe.com",
    "sdk.beizi.biz", "api-htp.beizi.biz", "api.htp.ad-scope.com.cn", "bid.ad-scope.com.cn",
    "mobads.baidu.com", "mobads-logs.baidu.com", "cpu.baidu.com", "cpu-openapi.baidu.com",
    "ada.baidu.com", "aden.baidu.com", "union.baidu.com", "cpro.baidustatic.com",
    "mobads-pre-config.bj.bcebos.com", "mobads-pre-config.cdn.bcebos.com",
    "mon.snssdk.com", "monsetting.toutiao.com", "mon.toutiao.com",
    "mon.toutiaocloud.com", "mon.toutiaocloud.net",
    "api.kuaishouzt.com", "open.e.kuaishou.com", "open.e.kuaishou.cn", "s.e.kuaishou.com",
    "ulog-sdk.gifshow.com", "zt.gifshow.com",
]
KS_HOSTS = [
    "api.kuaishouzt.com", "api.kwaizt.com", "w1.gskwai.com", "w2.gskwai.com",
    "w1.kskwai.com", "w2.kskwai.com", "zt.gifshow.com", "ulog-sdk.gifshow.com",
    "ulog-sdk.ksapisrv.com", "static.yximgs.com", "live.kuaishou.com",
]


def blackhole_url_hosts(buf, sec, hosts, report, label):
    """Replace host only when immediately preceded by '://'."""
    hosts = sorted(set(hosts), key=len, reverse=True)
    n = 0
    start, end = sec.offset, sec.offset + sec.size
    for h in hosts:
        hb = h.encode()
        i = start
        while True:
            i = buf.find(hb, i, end)
            if i < 0:
                break
            if bytes(buf[i-3:i]) != b"://":
                i += len(hb)
                continue
            repl = b"127.0.0.1"
            buf[i:i+len(hb)] = repl + b"\x00" * (len(hb) - len(repl))
            report.append({"binary": label, "host": h, "off": hex(i)})
            n += 1
            i += len(hb)
    return n


def patch_methods(buf, m, index, report, label, patches):
    for cls, kind, sel, ptype in patches:
        imp = index.get((cls, kind, sel))
        if not imp:
            report.append({"binary": label, "class": cls, "kind": kind, "sel": sel, "status": "not-found"})
            continue
        off = m.vm2off(imp)
        new = INSN_MOV_W0_0 + INSN_RET if ptype == "bool_false" else INSN_RET + INSN_NOP
        old = bytes(buf[off:off+8])
        buf[off:off+8] = new
        report.append({"binary": label, "class": cls, "kind": kind, "sel": sel,
                       "vm": hex(imp), "off": hex(off), "old": old.hex(), "new": new.hex(),
                       "status": "patched"})


def process(path, label, mode, report):
    if mode == "none":
        return
    with open(path, "rb") as f:
        buf = bytearray(f.read())
    data, slices = macho.MachO.from_file(path)
    m = slices[0][4]
    r = od.Reader(m)
    index = {(c["name"], k, sel): imp
             for c in r.all_classes()
             for k, lst in (("-", c["inst"]), ("+", c["cls"]))
             for (sel, types, imp) in lst}

    if mode in ("safe", "strong") and label == "TmallCampus":
        patch_methods(buf, m, index, report, label,
                      STRONG_PATCHES if mode == "strong" else SAFE_PATCHES)

    cs = m.section("__TEXT", "__cstring")
    if cs:
        hosts = AD_HOSTS if label == "TmallCampus" else KS_HOSTS
        n = blackhole_url_hosts(buf, cs, hosts, report, label)
        print("[%s] %s mode: %d URL-host rewrites" % (label, mode, n))

    with open(path, "wb") as f:
        f.write(buf)


def main():
    app, mode, out = sys.argv[1], sys.argv[2], sys.argv[3]
    rep = []
    process(os.path.join(app, "TmallCampus"), "TmallCampus", mode, rep)
    process(os.path.join(app, "Frameworks", "KSAdSDK.framework", "KSAdSDK"), "KSAdSDK",
            "minimal" if mode in ("minimal", "safe", "strong") else "none", rep)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print("mode=%s methods=%d strings=%d" % (
        mode,
        sum(1 for x in rep if x.get("status") == "patched"),
        sum(1 for x in rep if "host" in x)))


if __name__ == "__main__":
    main()
