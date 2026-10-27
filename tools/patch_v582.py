"""5.8.2 去广告补丁：只做纯 BOOL 判定 + 主二进制域名黑洞。

硬约束（前几轮踩过的坑）：
  1. 绝不修改 Frameworks 下任何二进制 —— AnyThink/GDT/KS/QuMeng/Smartdigimkt/JLBmp/nuisdk/Tquic/Unicorn/libpag
     全是 LC_LOAD_DYLIB 强链接，改一个字节就可能 dyld 拒绝加载 → 启动闪退。
  2. 绝不 patch void 流程方法（fetchData / loadSplash / setup / install）——
     它们负责发布回调与通知，改成 ret 会让开屏层永久等待 → 卡白屏。
  3. 不使用 -[TCCampusAdManager enableAd] —— D 版 11 判定打不开的最大嫌疑，
     它很可能是"广告功能是否启用"的总开关，返回 NO 会跳过 install/setupData。
  4. 域名替换只动 "scheme://host" 形态，且不碰 JSON 白名单（"//*.tanx.com":"1"）。
"""
import struct, sys, os, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho
import objc_detail as od

INSN_MOV_W0_0 = struct.pack("<I", 0x52800000)
INSN_RET      = struct.pack("<I", 0xD65F03C0)
INSN_NOP      = struct.pack("<I", 0xD503201F)

# 四个纯判定：语义都是"当前没有广告可放"，App 本来必须处理该分支
PATCHES = [
    ("TCCampusAdManager",                "-", "canShowSplashAd",           "bool_false"),  # 自有开屏
    ("TCSplashADvertisingBaseManager",   "-", "canShowAdCounts",           "bool_false"),  # 聚合开屏基类(TaKu/VOC/ZM)
    ("TCUbixFeedAdvertisingManager",     "-", "canShowAdWithType:node:",   "bool_false"),  # 信息流
    ("TCAdvertisingManager",             "-", "canShowAdvertisingNode:",   "bool_false"),  # 广告节点总判
]

AD_HOSTS = [
    # 阿里妈妈 UBiX（5.8.2 新增 adx-/md-/entry- 系列）
    "sdk-data.ubixioe.com", "tower.ubixioe.com",
    "tx-cfg-u1.ubixioe.com", "tx-data-u1.ubixioe.com",
    "adx-cfg-u1.ubixioe.com", "adx-data-u1.ubixioe.com",
    "md-cfg-u1.ubixioe.com", "md-data-u1.ubixioe.com",
    "entry-su1.ubixioe.com",
    # 倍孜 BeiZi + ADN-Plus + ad-scope
    "sdk.beizi.biz", "sdk-event.beizi.biz", "api-htp.beizi.biz",
    "sdk-api.adn-plus.com.cn", "api.htp.ad-scope.com.cn", "bid.ad-scope.com.cn",
    # 百度 mobads
    "mobads.baidu.com", "mobads-logs.baidu.com",
    "cpu.baidu.com", "cpu-openapi.baidu.com",
    "ada.baidu.com", "aden.baidu.com", "union.baidu.com", "wn.pos.baidu.com",
    "cpro.baidustatic.com",
    "mobads-pre-config.bj.bcebos.com", "mobads-pre-config.cdn.bcebos.com",
    # 阿里妈妈 tanx
    "ef-dongfeng.tanx.com", "click.tanx.com",
    # 穿山甲 / 巨量上报
    "mon.snssdk.com", "monsetting.toutiao.com",
    "mon.toutiao.com", "mon.toutiaocloud.com", "mon.toutiaocloud.net",
    # 快手（主二进制内如存在）
    "api.kuaishouzt.com", "open.e.kuaishou.com", "open.e.kuaishou.cn",
    "s.e.kuaishou.com", "ulog-sdk.gifshow.com", "zt.gifshow.com",
]


def blackhole_url_hosts(buf, sec, hosts, report):
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
            report.append({"host": h, "off": hex(i)})
            n += 1
            i += len(hb)
    return n


def main():
    app, out = sys.argv[1], sys.argv[2]
    binpath = os.path.join(app, "TmallCampus")
    with open(binpath, "rb") as f:
        buf = bytearray(f.read())

    data, slices = macho.MachO.from_file(binpath)
    m = slices[0][4]
    r = od.Reader(m)
    index = {(c["name"], k, sel): imp
             for c in r.all_classes()
             for k, lst in (("-", c["inst"]), ("+", c["cls"]))
             for (sel, types, imp) in lst}

    text = m.section("__TEXT", "__text")
    report = {"binary": "TmallCampus", "arch": m.arch_name(), "methods": [], "hosts": []}

    for cls, kind, sel, ptype in PATCHES:
        imp = index.get((cls, kind, sel))
        if not imp:
            print("MISS %s%s[%s]" % (kind, cls, sel))
            report["methods"].append({"class": cls, "sel": sel, "status": "not-found"})
            continue
        if not (text.addr <= imp < text.addr + text.size):
            print("OUT-OF-TEXT %s%s[%s] %#x" % (kind, cls, sel, imp))
            report["methods"].append({"class": cls, "sel": sel, "status": "outside-text"})
            continue
        off = m.vm2off(imp)
        new = INSN_MOV_W0_0 + INSN_RET if ptype == "bool_false" else INSN_RET + INSN_NOP
        old = bytes(buf[off:off+8])
        buf[off:off+8] = new
        print("PATCH %s%s[%s] vm=%#x off=%#x %s -> %s" % (kind, cls, sel, imp, off, old.hex(), new.hex()))
        report["methods"].append({"class": cls, "kind": kind, "sel": sel, "vm": hex(imp),
                                  "off": hex(off), "old": old.hex(), "new": new.hex(),
                                  "status": "patched"})

    cs = m.section("__TEXT", "__cstring")
    n = blackhole_url_hosts(buf, cs, AD_HOSTS, report["hosts"])
    print("cstring URL-host rewrites: %d" % n)

    with open(binpath, "wb") as f:
        f.write(buf)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("patched methods: %d, hosts: %d -> %s" % (
        sum(1 for x in report["methods"] if x.get("status") == "patched"), n, out))


if __name__ == "__main__":
    main()
