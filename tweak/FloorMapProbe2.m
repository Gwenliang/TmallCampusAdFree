/*
 * FloorMapProbe2.dylib —— 深层楼层探针
 *
 * 第一版探针只看到首页 6 个顶层 section，其中商品区是：
 *   [04] TCHomeProductHeaderCellModel     商品区标题栏
 *   [05] TCHomeProductControllerCellModel  商品流容器
 *
 * 「猜你喜欢 / 9.9元秒 / 进口好价 / 苹果专区」这些都在这两个容器内部，
 * 第一版看不到。本探针继续往里挖：
 *   1. TCHomeProductViewController 自己的 section 列表
 *   2. TCHomeFunctionContainerCellModel 内部的功能/频道条目
 *   3. TCHomeData 各字段的规模（items/listItems/chanels/gardenStore...）
 *
 * 输出：Documents/floor-map-deep.txt（同样可用「文件」App 或 Filza 取）
 */

typedef signed char BOOL;
typedef struct objc_class *Class;
typedef struct objc_object *id;
typedef struct objc_selector *SEL;
typedef struct objc_method *Method;
typedef void (*IMP)(void);

extern id objc_getClass(const char *name);
extern Method class_getInstanceMethod(id cls, SEL name);
extern IMP method_setImplementation(Method m, IMP imp);
extern SEL sel_registerName(const char *str);
extern id objc_msgSend(id self, SEL op, ...);
extern const char *object_getClassName(id obj);

/* 按真实签名强转，绝不 (unsigned long)objc_msgSend(...) —— ARC 下会崩 */
typedef id            (*Fn_id_0)(id, SEL);
typedef id            (*Fn_id_ul)(id, SEL, unsigned long);
typedef unsigned long (*Fn_ul_0)(id, SEL);
typedef BOOL          (*Fn_b_SEL)(id, SEL, SEL);

#define MSG_ID_0(o, s)     (((Fn_id_0)objc_msgSend)((o), (s)))
#define MSG_ID_UL(o, s, a) (((Fn_id_ul)objc_msgSend)((o), (s), (a)))
#define MSG_UL_0(o, s)     (((Fn_ul_0)objc_msgSend)((o), (s)))
#define MSG_B_SEL(o, s, a) (((Fn_b_SEL)objc_msgSend)((o), (s), (a)))

extern char *getenv(const char *);
extern void *fopen(const char *path, const char *mode);
extern int fclose(void *stream);
extern int fputs(const char *s, void *stream);
extern int fprintf(void *stream, const char *fmt, ...);
extern int snprintf(char *buf, unsigned long n, const char *fmt, ...);

static char g_path[512];
static void *g_f = 0;
static int   g_depth = 0;

static void *open_dump(void) {
    if (g_f) return g_f;
    const char *home = getenv("HOME");
    if (!home) return 0;
    snprintf(g_path, sizeof g_path, "%s/Documents/floor-map-deep.txt", home);
    g_f = fopen(g_path, "w");
    return g_f;
}

static id prop(id obj, const char *name) {
    if (!obj) return 0;
    SEL s = sel_registerName(name);
    SEL rs = sel_registerName("respondsToSelector:");
    if (!MSG_B_SEL(obj, rs, s)) return 0;
    return MSG_ID_0(obj, s);
}

static int is_array(id o) {
    if (!o) return 0;
    SEL c = sel_registerName("count");
    SEL rs = sel_registerName("respondsToSelector:");
    return MSG_B_SEL(o, rs, c) ? 1 : 0;
}

/* 递归打印一个 sectionModel 数组 */
static void dump_sections(void *f, id arr, const char *tag, int depth) {
    if (!is_array(arr)) return;
    SEL selCount = sel_registerName("count");
    SEL selObjAt = sel_registerName("objectAtIndex:");
    unsigned long n = MSG_UL_0(arr, selCount);
    if (!n) return;

    fprintf(f, "%s %lu 层\n", tag, n);
    for (unsigned long i = 0; i < n; i++) {
        id sec = MSG_ID_UL(arr, selObjAt, i);
        if (!sec) continue;
        fprintf(f, "  [%02lu] %s\n", i, object_getClassName(sec));

        id hdr = prop(sec, "headerCell");
        if (hdr) fprintf(f, "        header: %s\n", object_getClassName(hdr));

        id cms = prop(sec, "cellModels");
        if (!is_array(cms)) continue;
        unsigned long cn = MSG_UL_0(cms, selCount);
        fprintf(f, "        cellModels %lu:\n", cn);
        for (unsigned long j = 0; j < cn && j < 20; j++) {
            id cm = MSG_ID_UL(cms, selObjAt, j);
            if (!cm) continue;
            fprintf(f, "          - %s\n", object_getClassName(cm));

            /* 再往里看一层：cellModel 里有没有子数组 */
            if (depth > 0) {
                const char *subs[] = {"items", "goods", "products", "list", "dataList",
                                      "channels", "chanels", "children", "subItems", 0};
                for (int k = 0; subs[k]; k++) {
                    id sub = prop(cm, subs[k]);
                    if (!is_array(sub)) continue;
                    unsigned long sn = MSG_UL_0(sub, selCount);
                    if (!sn) continue;
                    fprintf(f, "              .%s = %lu 个:", subs[k], sn);
                    for (unsigned long m = 0; m < sn && m < 6; m++) {
                        id it = MSG_ID_UL(sub, selObjAt, m);
                        if (!it) continue;
                        fprintf(f, " %s", object_getClassName(it));
                    }
                    fprintf(f, "\n");
                }
            }
        }
        if (cn > 20) fprintf(f, "          ... 还有 %lu\n", cn - 20);
    }
    fprintf(f, "\n");
}

/* ---------- 1. 顶层 6 层 + 深挖 ---------- */
static id (*orig_newSectionModels)(id, SEL);
static id hook_newSectionModels(id self, SEL _cmd) {
    id arr = orig_newSectionModels ? orig_newSectionModels(self, _cmd) : (id)0;
    if (arr) {
        void *f = open_dump();
        if (f) {
            fprintf(f, "======== 顶层 newSectionModels ========\n");
            dump_sections(f, arr, "顶层", 1);
            fputs("\n（如需要更多信息可反复下拉刷新，本文件每次覆盖）\n", f);
        }
    }
    return arr;
}

/* ---------- 2. TCHomeProductViewController 自己的楼层 ---------- */
static id (*orig_prod_newSectionModels)(id, SEL);
static id hook_prod_newSectionModels(id self, SEL _cmd) {
    id arr = orig_prod_newSectionModels ? orig_prod_newSectionModels(self, _cmd) : (id)0;
    if (arr) {
        void *f = open_dump();
        if (f) {
            fprintf(f, "\n======== 商品容器 TCHomeProductViewController ========\n");
            dump_sections(f, arr, "商品区", 1);
        }
    }
    return arr;
}

/* ---------- 3. TCHomeData 字段规模 ---------- */
static id (*orig_homeData)(id, SEL);
static id hook_homeData(id self, SEL _cmd) {
    id d = orig_homeData ? orig_homeData(self, _cmd) : (id)0;
    if (d) {
        void *f = open_dump();
        if (f) {
            static const char *fields[] = {
                "allModules","loadModules","items","listItems","chanels","gardenStore",
                "associatedStore","storeBenefits","normalBanners","fixBanners","quicks",
                "waist","bridalGift","personalAssetData","inviteStudent","redFlowerData", 0
            };
            fprintf(f, "\n======== TCHomeData 字段 ========\n");
            for (int i = 0; fields[i]; i++) {
                id v = prop(d, fields[i]);
                if (!v) continue;
                if (is_array(v)) {
                    fprintf(f, "  %-18s = %lu 个\n", fields[i], MSG_UL_0(v, sel_registerName("count")));
                } else {
                    fprintf(f, "  %-18s = <%s>\n", fields[i], object_getClassName(v));
                }
            }
            fprintf(f, "\n");
        }
    }
    return d;
}

static void hook_one(const char *cls, const char *sel, void **orig, IMP repl) {
    id c = objc_getClass(cls);
    if (!c) return;
    Method m = class_getInstanceMethod(c, sel_registerName(sel));
    if (!m) return;
    *orig = (void *)method_setImplementation(m, repl);
}

__attribute__((constructor))
static void deep_init(void) {
    hook_one("TCHomeViewModel", "newSectionModels",
             (void **)&orig_newSectionModels, (IMP)(void *)hook_newSectionModels);
    hook_one("TCHomeProductViewController", "newSectionModels",
             (void **)&orig_prod_newSectionModels, (IMP)(void *)hook_prod_newSectionModels);
    hook_one("TCHomeViewModel", "homeData",
             (void **)&orig_homeData, (IMP)(void *)hook_homeData);
}
