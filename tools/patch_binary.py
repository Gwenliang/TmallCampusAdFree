"""Apply ad-neutralisation patches to TmallCampus Mach-O binary.

Patch kinds:
  bool_false : mov w0, #0 ; ret      (0x52800000, 0xD65F03C0)
  void_ret   : ret                   (0xD65F03C0)
  obj_nil    : mov x0, #0 ; ret      (0xD2800000, 0xD65F03C0)
  kill_str   : overwrite a host string with 127.0.0.1 (NUL padded)
"""
import struct, sys, os, json, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho
import objc_detail as od

INSN_MOV_W0_0 = struct.pack("<I", 0x52800000)
INSN_MOV_X0_0 = struct.pack("<I", 0xD2800000)
INSN_RET      = struct.pack("<I", 0xD65F03C0)

# (class, method_kind ('-' or '+'), selector, patch_kind)
PATCHES = [
    ("TCCampusAdManager",                 "-", "enableAd",                            "bool_false"),
    ("TCCampusAdManager",                 "-", "canShowSplashAd",                     "bool_false"),
    ("TCCampusAdManager",                 "+", "canShowSplashAdCount",                "bool_false"),
    ("TCCampusAdManager",                 "+", "fetchData",                           "void_ret"),
    ("TCUbiXSplashADvertisingManager",    "-", "canShowAd",                           "bool_false"),
    ("TCUbiXSplashADvertisingManager",    "-", "loadSplash",                          "void_ret"),
    ("TCUbiXSplashADvertisingManager",    "+", "canShowUBIXSplashAd",                 "bool_false"),
    ("TCUbiXSplashADvertisingManager",    "+", "canShowSplashAdCount",                "bool_false"),
    ("TCUbixFeedAdvertisingManager",      "-", "canShowAdWithType:node:",             "bool_false"),
    ("TCUbixFeedAdvertisingManager",      "-", "canShowAdWithInlistId:",              "bool_false"),
    ("TCUbixFeedAdvertisingManager",      "-", "canShowADCheckCountWithType:node:",   "bool_false"),
    ("TCUbixFeedAdvertisingManager",      "-", "fetchData",                           "void_ret"),
    ("TCUbixFeedAdvertisingManager",      "+", "canShowPitADWithPitType:withInlistId:node:", "bool_false"),
]

# hosts to blackhole (exact host token, will match inside longer strings)
AD_HOSTS = [
    "sdk-data.ubixioe.com", "tower.ubixioe.com", "tx-cfg-u1.ubixioe.com", "tx-data-u1.ubixioe.com",
    "sdk.beizi.biz", "api-htp.beizi.biz", "api.htp.ad-scope.com.cn", "bid.ad-scope.com.cn",
    "mobads.baidu.com", "mobads-logs.baidu.com", "cpu.baidu.com", "cpu-openapi.baidu.com",
    "ada.baidu.com", "aden.baidu.com", "union.baidu.com", "cpro.baidustatic.com",
    "mobads-pre-config.bj.bcebos.com", "mobads-pre-config.cdn.bcebos.com",
    "mon.snssdk.com", "mon.toutiao.com", "mon.toutiaocloud.com", "mon.toutiaocloud.net",
    "monsetting.toutiao.com",
    "api.kuaishouzt.com", "open.e.kuaishou.com", "open.e.kuaishou.cn", "s.e.kuaishou.com",
    "ulog-sdk.gifshow.com", "zt.gifshow.com",
]

REPL = b"127.0.0.1"


def load_classes(path):
    data, slices = macho.MachO.from_file(path)
    m = slices[0][4]
    r = od.Reader(m)
    return data, m, {(c["name"], kind, sel): imp
                     for c in r.all_classes()
                     for kind, lst in (("-", c["inst"]), ("+", c["cls"]))
                     for (sel, types, imp) in lst}, r


def main():
    binpath = sys.argv[1]
    with open(binpath, "rb") as f:
        raw = bytearray(f.read())

    data, m, index, r = load_classes(binpath)
    print("arch=%s cpusub=%#x classes=%d" % (m.arch_name(), m.cpusubtype, len(index)))

    report = {"binary": os.path.basename(binpath), "arch": m.arch_name(), "method_patches": [], "string_patches": []}

    for cls, kind, sel, ptype in PATCHES:
        imp = index.get((cls, kind, sel))
        if not imp:
            print("MISS  %s%s[%s %s]" % (kind, cls, kind, sel))
            report["method_patches"].append({"class": cls, "kind": kind, "sel": sel, "status": "not-found"})
            continue
        off = m.vm2off(imp)
        if off is None:
            print("NOOFF %s%s[%s]" % (kind, cls, sel))
            continue
        if ptype == "bool_false":
            new = INSN_MOV_W0_0 + INSN_RET
        elif ptype == "void_ret":
            new = INSN_RET + b"\x1f\x20\x03\xd5"   # ret ; nop
        elif ptype == "obj_nil":
            new = INSN_MOV_X0_0 + INSN_RET
        old = bytes(raw[off:off+8])
        raw[off:off+8] = new
        print("PATCH %s%s[%s %s] @%#x -> %s" % (kind, cls, kind, sel, off, new.hex()))
        report["method_patches"].append({"class": cls, "kind": kind, "sel": sel,
                                         "vm": hex(imp), "off": hex(off),
                                         "old": old.hex(), "new": new.hex(), "status": "patched"})

    # ---- string blackholes ----
    hits = 0
    for host in AD_HOSTS:
        hb = host.encode()
        start = 0
        while True:
            i = raw.find(hb, start)
            if i < 0:
                break
            # only patch occurrences that look like a standalone host inside a URL/allocation string
            raw[i:i+len(hb)] = REPL + b"\x00" * (len(hb) - len(REPL))
            hits += 1
            report["string_patches"].append({"host": host, "off": hex(i)})
            start = i + len(hb)
    print("string hits:", hits)

    with open(binpath, "wb") as f:
        f.write(raw)

    out = os.path.join(os.path.dirname(binpath), "..", "..", "..", "analysis", "patch-report.json")
    with open(os.path.normpath(out), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("report ->", os.path.normpath(out))


if __name__ == "__main__":
    main()
