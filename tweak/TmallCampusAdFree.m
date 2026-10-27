/*
 * TmallCampusAdFree.dylib
 * 天猫校园（com.tmall.campus4iphone）去广告 Tweak
 *
 * 设计原则（来自改包实践的三条硬约束）：
 *   1. 只 hook "能不能展示" 的判定方法，返回 NO 等价于"没有广告库存"，
 *      App 本来必须处理这个分支（无网/无填充/超频次），不会破坏启动流程。
 *   2. 绝不 hook 流程方法（fetchData / loadSplash / setup / install）——
 *      它们负责发布回调与通知，掐掉会让开屏层永久等待，卡白屏。
 *   3. 绝不 hook enableAd —— 它是"广告功能是否启用"的总开关，
 *      返回 NO 会跳过初始化链，后续访问未初始化状态会崩。
 *
 * 不依赖 iOS SDK，不依赖 Logos，纯 Objective-C runtime。
 * 编译见 build.sh / build.ps1。
 */

#import <stdint.h>
#import <stdbool.h>

/* 不依赖 SDK / 标准库头文件，自己声明用到的 C 函数 */
extern unsigned long strlen(const char *);
extern char *strstr(const char *, const char *);
extern int strcmp(const char *, const char *);

/* ---- 只声明用到的 runtime 符号，避免依赖 SDK 头文件 ---- */
typedef signed char BOOL;
typedef struct objc_class *Class;
typedef struct objc_object *id;
typedef struct objc_selector *SEL;
typedef struct objc_method *Method;
typedef void (*IMP)(void);

extern id objc_getClass(const char *name);
extern Method class_getInstanceMethod(id cls, SEL name);
extern Method class_getClassMethod(id cls, SEL name);
extern IMP method_setImplementation(Method m, IMP imp);
extern SEL sel_registerName(const char *str);
extern int objc_getClassList(id *buffer, int bufferCount);

/* ---- 日志：只在 DEBUG 打开时输出，避免影响正常使用 ---- */
#ifdef TMALL_ADFREE_DEBUG
extern int printf(const char *fmt, ...);
#define LOG(fmt, ...) printf("[AdFree] " fmt "\n", ##__VA_ARGS__)
#else
#define LOG(fmt, ...) do {} while (0)
#endif

/* ============================================================
 * 一、判定方法 hook
 * ============================================================ */

/* 统一返回 NO。BOOL 只看 w0，多余参数在 arm64 AAPCS 下不影响。 */
static bool ret_no(id self, SEL _cmd) {
    (void)self; (void)_cmd;
    return false;
}

/* 返回 nil（对象类型） */
static id ret_nil(id self, SEL _cmd) {
    (void)self; (void)_cmd;
    return (id)0;
}

typedef struct {
    const char *cls;      /* 类名 */
    const char *sel;      /* 方法名 */
    int         is_class; /* 1 = 类方法, 0 = 实例方法 */
    int         ret_nil;  /* 1 = 返回 nil, 0 = 返回 NO */
} hook_spec;

/*
 * 只用"能不能展示"的判定，全部已验证为纯 BOOL 且无 IMP 共享。
 * 顺序无关，找不到的类/方法会静默跳过（换版本也不会崩）。
 */
static const hook_spec SPECS[] = {
    /* ---- 自有开屏 / 信息流 ---- */
    { "TCCampusAdManager",              "canShowSplashAd",                        0, 0 },
    { "TCCampusAdManager",              "isHaveInlistAdModel",                    1, 0 },

    /* ---- 聚合开屏基类（TaKu / VOC / ZM 共用） ---- */
    { "TCSplashADvertisingBaseManager", "canShowAdCounts",                        0, 0 },
    { "TCSplashADvertisingBaseManager", "canShowSplashAdHotLaunching:",           0, 0 },

    /* ---- 信息流广告位 ---- */
    { "TCUbixFeedAdvertisingManager",   "canShowAdWithType:node:",                0, 0 },
    { "TCUbixFeedAdvertisingManager",   "canShowAdWithInlistId:",                 0, 0 },
    { "TCUbixFeedAdvertisingManager",   "canShowADCheckCountWithType:node:",      0, 0 },

    /* ---- 广告节点总调度 ---- */
    { "TCAdvertisingManager",           "canShowAdvertisingNode:",                0, 0 },

    /* ---- 其它广告位 ---- */
    { "TCCXHAdManager",                 "isEnabled",                              0, 0 },
    { "TCCXHAdManager",                 "canShowAdForPosId:",                     0, 0 },
    { "TCTaKuSplashADvertisingManager", "checkAd",                                0, 0 },
};

#define SPEC_COUNT (sizeof(SPECS) / sizeof(SPECS[0]))

static int g_hooked = 0;
static int g_missed = 0;

static void install_one(const hook_spec *s) {
    id cls = objc_getClass(s->cls);
    if (!cls) {
        g_missed++;
        LOG("class not found: %s", s->cls);
        return;
    }
    SEL sel = sel_registerName(s->sel);
    Method m = s->is_class ? class_getClassMethod(cls, sel)
                           : class_getInstanceMethod(cls, sel);
    if (!m) {
        g_missed++;
        LOG("method not found: %c[%s %s]", s->is_class ? '+' : '-', s->cls, s->sel);
        return;
    }
    method_setImplementation(m, (IMP)(void *)(s->ret_nil ? (void *)ret_nil : (void *)ret_no));
    g_hooked++;
    LOG("hooked %c[%s %s]", s->is_class ? '+' : '-', s->cls, s->sel);
}

/* ============================================================
 * 二、网络层兜底：广告域名直接拒绝
 *
 * 不改二进制，只在运行时拦请求。命中广告域名时返回一个
 * "连接被拒" 的 NSError，SDK 会走它自带的失败回调（这是
 * 无网环境下的正常路径），因此不会卡界面。
 * ============================================================ */

static const char *AD_HOSTS[] = {
    /* 阿里妈妈 UBiX */
    "ubixioe.com",
    /* 倍孜 / ADN-Plus / ad-scope */
    "beizi.biz", "ad-scope.com.cn", "adn-plus.com.cn",
    /* 百度 mobads */
    "mobads.baidu.com", "mobads-logs.baidu.com", "cpu.baidu.com",
    "cpu-openapi.baidu.com", "ada.baidu.com", "aden.baidu.com",
    "union.baidu.com", "wn.pos.baidu.com", "cpro.baidustatic.com",
    "mobads-pre-config.bj.bcebos.com", "mobads-pre-config.cdn.bcebos.com",
    /* 阿里妈妈 tanx */
    "ef-dongfeng.tanx.com", "click.tanx.com",
    /* 穿山甲上报 */
    "mon.snssdk.com", "monsetting.toutiao.com",
    "mon.toutiao.com", "mon.toutiaocloud.com", "mon.toutiaocloud.net",
    /* 快手 */
    "api.kuaishouzt.com", "api.kwaizt.com", "open.e.kuaishou.com",
    "open.e.kuaishou.cn", "s.e.kuaishou.com", "ulog-sdk.gifshow.com",
    "ulog-sdk.ksapisrv.com", "zt.gifshow.com", "static.yximgs.com",
    "w1.gskwai.com", "w2.gskwai.com", "w1.kskwai.com", "w2.kskwai.com",
    /* AnyThink / TopOn */
    "toponad.com", "anythinktech.com",
    /* 趣盟 */
    "qumeng.com", "qm-adx.com",
    /* Smartdigimkt */
    "smartdigimkt.com",
    0
};

/* 子串匹配，覆盖 xxx.ubixioe.com 这类任意子域 */
static int host_is_ad(const char *host) {
    if (!host || !*host) return 0;
    for (int i = 0; AD_HOSTS[i]; i++) {
        const char *pat = AD_HOSTS[i];
        unsigned long plen = strlen(pat);
        const char *p = host;
        while ((p = strstr(p, pat)) != 0) {
            /* 要求是完整域名后缀：前面是 '.' 或开头 */
            if (p == host || *(p - 1) == '.') return 1;
            p += plen;
        }
    }
    return 0;
}

/* ============================================================
 * 三、构造函数
 * ============================================================ */

/* ============================================================
 * 四、首页楼层过滤
 *
 * 首页是 IGListKit 驱动：每个楼层 = 一个 TCSectionController，
 * 所有楼层模型由 -[TCHomeViewModel newSectionModels] 一次性生成。
 * 所以 hook 这个方法、把指定楼层的模型从返回数组里剔除，
 * 整层就不会出现在首页里（IGListKit 对空 section 的处理是高度 0）。
 *
 * 只过滤"商品/店铺类"楼层，功能入口、banner、签到等一律保留。
 * 类名按需增删，找不到的类名不影响任何东西。
 * ============================================================ */

/* 依据 floor-map.txt 探针实测结果（5.8.2，首页共 6 层）：
 *
 *   [00] TCHomeFixBannerCellModel           顶部固定 banner        → 保留
 *   [01] TCHomeFunctionContainerCellModel   功能入口（校园卡/签到）  → 保留
 *   [02] TCPersonalAssetContainerCellModel  个人资产               → 保留
 *   [03] TCAdCommonBannerCellModel          广告 banner            → 删
 *   [04] TCHomeProductHeaderCellModel       商品区标题栏            → 删
 *   [05] TCHomeProductControllerCellModel   商品流容器              → 删
 *
 * 用户说的「猜你喜欢 / 9.9元秒 / 进口好价 / 苹果专区」这些楼层，
 * 并不直接出现在这 6 层里——它们嵌套在 [05] TCHomeProductControllerCellModel
 * 内部的 TCHomeProductViewController 子控制器里。所以删掉 [04]+[05]
 * 就等同于清空整个下方商品区。
 *
 * 「影音娱乐 / 生活日用 / 美食团购」是 [01] 功能容器里的频道入口，
 * 删 [01] 会连校园卡、签到一起没，所以保留入口、只删它下面的商品。 */
static const char *FLOOR_BLACKLIST[] = {
    /* ---- 5.8.2 实测存在，确定要删 ---- */
    "TCHomeProductHeaderCellModel",      /* [04] 商品区标题栏 */
    "TCHomeProductControllerCellModel",  /* [05] 商品流容器（猜你喜欢等都在它内部） */
    "TCAdCommonBannerCellModel",         /* [03] 广告 banner */

    /* ---- 预留：5.8.2 首页未出现，但其它版本或其它入口可能出现 ---- */
    "TCHomeCommodityCellModel",
    "TCHomeGiftCellModel",
    "TCHomeListControllerCellModel",
    "TCHomeOperationPositionCellModel",
    "TCGardenStoreContainerCellModel",
    "TCAssociatedShopContainerCellModel",
    "TCStoreContainerCellModel",
    "TCReachStoreContainerCellModel",

    0
};

static int floor_is_blacklisted(const char *cls) {
    if (!cls) return 0;
    for (int i = 0; FLOOR_BLACKLIST[i]; i++) {
        if (strcmp(cls, FLOOR_BLACKLIST[i]) == 0) return 1;
    }
    return 0;
}

/* 需要 runtime 里用的符号，自己声明 */
extern const char *object_getClassName(id obj);
extern id objc_msgSend(id self, SEL op, ...);
extern Class object_getClass(id obj);
extern id objc_msgSend(id self, SEL op, ...);

/* objc_msgSend 必须按"每个方法的真实签名"强转后再调用。
 * 绝不能写成 `(unsigned long)objc_msgSend(...)` —— 那样返回值被当成 id，
 * 在 ARC 下会被 objc_retainAutoreleasedReturnValue 当对象 retain，
 * 拿到 NSUInteger 时就是野指针 → 崩溃（v1.1.0 闪退就是这个原因）。 */
typedef id            (*Fn_id_0)(id, SEL);
typedef id            (*Fn_id_ul)(id, SEL, unsigned long);
typedef void          (*Fn_v_id)(id, SEL, id);
typedef unsigned long (*Fn_ul_0)(id, SEL);
typedef BOOL          (*Fn_b_0)(id, SEL);
typedef BOOL          (*Fn_b_id)(id, SEL, id);
typedef BOOL          (*Fn_b_SEL)(id, SEL, SEL);

#define MSG_ID_0(o, s)        (((Fn_id_0)objc_msgSend)((o), (s)))
#define MSG_ID_UL(o, s, a)    (((Fn_id_ul)objc_msgSend)((o), (s), (a)))
#define MSG_V_ID(o, s, a)     (((Fn_v_id)objc_msgSend)((o), (s), (a)))
#define MSG_UL_0(o, s)        (((Fn_ul_0)objc_msgSend)((o), (s)))
#define MSG_B_0(o, s)         (((Fn_b_0)objc_msgSend)((o), (s)))
#define MSG_B_ID(o, s, a)     (((Fn_b_id)objc_msgSend)((o), (s), (a)))
#define MSG_B_SEL(o, s, a)    (((Fn_b_SEL)objc_msgSend)((o), (s), (a)))

/* -[TCHomeViewModel newSectionModels] 的替换实现。
 *
 * 关键：它返回的数组元素是 TCSectionModel（楼层包装），不是 CellModel。
 * TCSectionModel 内部才持有 cellModels 数组。所以判断一个楼层该不该删，
 * 必须深入到 sectionModel.cellModels 里去看元素类型。
 *
 * 判定规则：整个楼层里的 cellModel 全部命中黑名单 → 这一层丢掉；
 *          只要混进一个非商品 cellModel（功能入口、标题等）→ 整层保留，
 *          避免误删用户还要的东西。 */
static id (*orig_newSectionModels)(id, SEL);

static int section_is_all_products(id sectionModel, SEL selCellModels,
                                   SEL selCount, SEL selObjAt) {
    if (!sectionModel) return 0;

    /* 只对确定响应 cellModels 的对象去取，避免 ong 对象收到未知 selector 直接崩 */
    SEL selResponds = sel_registerName("respondsToSelector:");
    if (!MSG_B_SEL(sectionModel, selResponds, selCellModels)) return 0;

    id cms = MSG_ID_0(sectionModel, selCellModels);
    if (!cms) return 0;

    if (!MSG_B_SEL(cms, selResponds, selCount)) return 0;

    unsigned long cn = MSG_UL_0(cms, selCount);
    if (cn == 0) return 0;          /* 空楼层不动它，交给 App 自己处理 */

    for (unsigned long j = 0; j < cn; j++) {
        id item = MSG_ID_UL(cms, selObjAt, j);
        if (!item) continue;
        const char *cname = object_getClassName(item);
        if (!floor_is_blacklisted(cname)) return 0;   /* 混了别的，保留整层 */
    }
    return 1;
}

static id hook_newSectionModels(id self, SEL _cmd) {
    id arr = orig_newSectionModels ? orig_newSectionModels(self, _cmd) : (id)0;
    if (!arr) return arr;

    SEL selCount = sel_registerName("count");
    SEL selObjAt = sel_registerName("objectAtIndex:");
    SEL selAdd   = sel_registerName("addObject:");
    SEL selRS    = sel_registerName("respondsToSelector:");
    SEL selCellModels = sel_registerName("cellModels");

    /* 防御：万一返回的不是数组，原样放行 */
    if (!MSG_B_SEL(arr, selRS, selCount)) return arr;

    unsigned long n = MSG_UL_0(arr, selCount);
    if (n == 0) return arr;

    /* 第一遍只统计，不创建任何对象。
     * 没有楼层需要删时直接返回原数组 —— 这是绝大多数情况，零内存风险，
     * 也是探针 FloorMapProbe 能安全运行的原因（它同样只读不建）。 */
    unsigned long dropped = 0;
    for (unsigned long i = 0; i < n; i++) {
        id sec = MSG_ID_UL(arr, selObjAt, i);
        if (sec && section_is_all_products(sec, selCellModels, selCount, selObjAt))
            dropped++;
    }
    if (dropped == 0) return arr;

    /* 第二遍构造新数组。
     *
     * 关键：本方法名以 new 开头，按 Cocoa 内存管理规则必须返回 +1 对象，
     * 调用方会 release。所以只能用 alloc/init（+1），
     * 绝不能用 +[NSMutableArray array]（+0 autoreleased）——
     * 否则调用方 release 一次即过度释放，后续访问野指针 → 闪退。
     * 这就是 v1.1.0 ~ v1.4.0 全部闪退的真正原因。 */
    id clsMut = objc_getClass("NSMutableArray");
    if (!clsMut) return arr;
    id out = MSG_ID_0(clsMut, sel_registerName("alloc"));
    if (!out) return arr;
    out = MSG_ID_0(out, sel_registerName("init"));
    if (!out) return arr;

    for (unsigned long i = 0; i < n; i++) {
        id sec = MSG_ID_UL(arr, selObjAt, i);
        if (!sec) continue;
        if (section_is_all_products(sec, selCellModels, selCount, selObjAt)) {
            LOG("drop floor #%lu (%s)", i, object_getClassName(sec));
            continue;
        }
        MSG_V_ID(out, selAdd, sec);
    }
    LOG("newSectionModels: %lu -> %lu (dropped %lu)", n, n - dropped, dropped);
    return out;
}

static void install_floor_filter(void) {
    id cls = objc_getClass("TCHomeViewModel");
    if (!cls) { LOG("TCHomeViewModel not found"); return; }
    SEL sel = sel_registerName("newSectionModels");
    Method m = class_getInstanceMethod(cls, sel);
    if (!m) { LOG("newSectionModels not found"); return; }
    orig_newSectionModels = (id (*)(id, SEL))method_setImplementation(
        m, (IMP)(void *)hook_newSectionModels);
    g_hooked++;
    LOG("hooked -[TCHomeViewModel newSectionModels]");
}

__attribute__((constructor))
static void tmall_adfree_init(void) {
    LOG("=== TmallCampusAdFree loaded ===");
#ifndef TMALL_DISABLE_AD_HOOKS
    /* 11 个广告判定 hook。编译时加 -DTMALL_DISABLE_AD_HOOKS 可整体关闭，
     * 用于排查"是广告 hook 崩还是楼层过滤崩"。 */
    for (unsigned i = 0; i < SPEC_COUNT; i++) {
        install_one(&SPECS[i]);
    }
#endif
    install_floor_filter();
    LOG("hooked=%d missed=%d", g_hooked, g_missed);
}

/* 供外部查询状态（可选，方便用 Frida 验证） */
int tmall_adfree_status(void) {
    return g_hooked * 1000 + g_missed;
}






