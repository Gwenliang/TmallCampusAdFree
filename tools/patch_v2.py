"""TmallCampus IPA de-ad: method patches + ad-host blackholing (section-scoped, multi-binary)."""
import struct, sys, os, json, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho
import objc_detail as od

INSN_MOV_W0_0 = struct.pack("<I", 0x52800000)
INSN_MOV_X0_0 = struct.pack("<I", 0xD2800000)
INSN_RET      = struct.pack("<I", 0xD65F03C0)
INSN_NOP      = struct.pack("<I", 0xD503201F)

PATCHES = [
    ("TCCampusAdManager",              "-", "enableAd",                                  "bool_false"),
    ("TCCampusAdManager",              "-", "canShowSplashAd",                           "bool_false"),
    ("TCCampusAdManager",              "+", "canShowSplashAdCount",                      "bool_false"),
    ("TCCampusAdManager",              "+", "fetchData",                                 "void_ret"),
    ("TCCampusAdManager",              "+", "isHaveInlistAdModel",                       "bool_false"),
    ("TCCampusAdManager",              "+", "getInlistAdModel",                          "obj_nil"),
    ("TCCampusAdManager",              "+", "getInlistAdModelWithPitID:",                "obj_nil"),
    ("TCUbiXSplashADvertisingManager", "-", "canShowAd",                                 "bool_false"),
    ("TCUbiXSplashADvertisingManager", "-", "loadSplash",                                "void_ret"),
    ("TCUbiXSplashADvertisingManager", "+", "canShowUBIXSplashAd",                       "bool_false"),
    ("TCUbiXSplashADvertisingManager", "+", "canShowSplashAdCount",                      "bool_false"),
    ("TCUbixFeedAdvertisingManager",   "-", "canShowAdWithType:node:",                   "bool_false"),
    ("TCUbixFeedAdvertisingManager",   "-", "canShowAdWithInlistId:",                    "bool_false"),
    ("TCUbixFeedAdvertisingManager",   "-", "canShowADCheckCountWithType:node:",         "bool_false"),
    ("TCUbixFeedAdvertisingManager",   "-", "fetchData",                                 "void_ret"),
    ("TCUbixFeedAdvertisingManager",   "+", "setup",                                     "void_ret"),
    ("TCUbixFeedAdvertisingManager",   "+", "canShowPitADWithPitType:withInlistId:node:", "bool_false"),
]

AD_HOSTS = [
    # UBiX / 阿里妈妈聚合
    "sdk-data.ubixioe.com", "tower.ubixioe.com", "tx-cfg-u1.ubixioe.com", "tx-data-u1.ubixioe.com",
    # 倍孜 BeiZi
    "sdk.beizi.biz", "api-htp.beizi.biz", "api.htp.ad-scope.com.cn", "bid.ad-scope.com.cn",
    # 百度 mobads
    "mobads.baidu.com", "mobads-logs.baidu.com", "cpu.baidu.com", "cpu-openapi.baidu.com",
    "ada.baidu.com", "aden.baidu.com", "union.baidu.com", "cpro.baidustatic.com",
    "mobads-pre-config.bj.bcebos.com", "mobads-pre-config.cdn.bcebos.com",
    # 穿山甲 / 巨量
    "mon.snssdk.com", "mon.toutiao.com", "mon.toutiaocloud.com", "mon.toutiaocloud.net",
    "monsetting.toutiao.com",
    # 快手（主二进制内出现的）
    "api.kuaishouzt.com", "open.e.kuaishou.com", "open.e.kuaishou.cn", "s.e.kuaishou.com",
    "ulog-sdk.gifshow.com", "zt.gifshow.com",
    # 阿里妈妈 / tanx
    "gw.alimama.com", "atanx.alicdn.com", "tanx.com",
]

HOST_RE = re.compile(rb"^[A-Za-z0-9][A-Za-z0-9\-\.]{2,80}\.(?:com|cn|net|biz|io|org|tv|top|xyz|me|cc|info)$")


def blackhole(buf, off_start, off_end, host_list, report, label):
    """Rewrite host tokens inside the cstring area [off_start, off_end).

    Only touches occurrences that are either
      * preceded by "://" (a real URL), or
      * a standalone C string (prev byte NUL, next byte NUL).
    This avoids corrupting JSON allow-lists such as "//*.tanx.com":"1".
    """
    hosts = sorted(set(host_list), key=len, reverse=True)
    n = 0
    for h in hosts:
        hb = h.encode()
        i = off_start
        while True:
            i = buf.find(hb, i, off_end)
            if i < 0:
                break
            prev3 = bytes(buf[max(0, i-3):i])
            nxt = bytes(buf[i+len(hb):i+len(hb)+1])
            is_url = prev3 == b"://"
            is_standalone = (i == 0 or buf[i-1] == 0) and (nxt == b"\x00" or i+len(hb) >= off_end)
            if not (is_url or is_standalone):
                i += len(hb)
                continue
            repl = b"127.0.0.1" if len(hb) >= 9 else b""
            buf[i:i+len(hb)] = repl + b"\x00" * (len(hb) - len(repl))
            report.append({"binary": label, "host": h, "off": hex(i)})
            n += 1
            i += len(hb)
    return n


def scan_hosts(buf, off_start, off_end):
    out = set()
    for part in bytes(buf[off_start:off_end]).split(b"\x00"):
        if HOST_RE.match(part):
            out.add(part.decode())
    return out


def patch_methods(buf, m, index, report, label):
    for cls, kind, sel, ptype in PATCHES:
        imp = index.get((cls, kind, sel))
        if not imp:
            report.append({"binary": label, "class": cls, "kind": kind, "sel": sel, "status": "not-found"})
            continue
        off = m.vm2off(imp)
        new = {"bool_false": INSN_MOV_W0_0 + INSN_RET,
               "void_ret": INSN_RET + INSN_NOP,
               "obj_nil": INSN_MOV_X0_0 + INSN_RET}[ptype]
        old = bytes(buf[off:off+8])
        buf[off:off+8] = new
        report.append({"binary": label, "class": cls, "kind": kind, "sel": sel,
                       "vm": hex(imp), "off": hex(off), "old": old.hex(), "new": new.hex(),
                       "status": "patched"})


def process(path, label, host_mode, report):
    with open(path, "rb") as f:
        buf = bytearray(f.read())
    data, slices = macho.MachO.from_file(path)
    m = slices[0][4]
    r = od.Reader(m)
    index = {(c["name"], k, sel): imp
             for c in r.all_classes()
             for k, lst in (("-", c["inst"]), ("+", c["cls"]))
             for (sel, types, imp) in lst}

    if host_mode == "methods":
        patch_methods(buf, m, index, report, label)

    # blackhole hosts inside __cstring
    cs = m.section("__TEXT", "__cstring")
    if cs:
        start, end = cs.offset, cs.offset + cs.size
        if host_mode == "all":
            hosts = scan_hosts(buf, start, end)
            # skip bundle-identifier-like tokens (com.xxx.yyy.io) and platform domains
            hosts = {h for h in hosts
                     if not h.lower().startswith("com.")
                     and not h.lower().endswith(("apple.com", "localhost"))}
        else:
            hosts = AD_HOSTS
        n = blackhole(buf, start, end, hosts, report, label)
        print("[%s] cstring host rewrites: %d (%d candidate hosts)" % (label, n, len(hosts)))
        if host_mode == "all":
            print("   hosts:", ", ".join(sorted(hosts)))

    with open(path, "wb") as f:
        f.write(buf)


def main():
    app = sys.argv[1]
    rep = []
    process(os.path.join(app, "TmallCampus"), "TmallCampus", "methods", rep)
    process(os.path.join(app, "Frameworks", "KSAdSDK.framework", "KSAdSDK"), "KSAdSDK", "all", rep)
    out = sys.argv[2]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    ok = sum(1 for x in rep if x.get("status") == "patched")
    print("patched methods:", ok, "not-found:", sum(1 for x in rep if x.get("status") == "not-found"))
    print("string rewrites:", sum(1 for x in rep if "off" in x))


if __name__ == "__main__":
    main()
