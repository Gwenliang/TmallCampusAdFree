/*
 * FloorMapProbe.dylib —— 首页楼层结构探针（dylib 版，不需要 Frida）
 *
 * 注入方式：TrollFools 注入到「天猫校园」
 * 输出位置：App 沙盒 Documents/floor-map.txt
 *           （该 App 开了 UIFileSharingEnabled，可用 iOS「文件」App 直接打开）
 *
 * 作用：把首页每一个楼层（TCSectionModel）内部的 cellModels 类名、
 *      数量、diffIdentifier、headerCell 全部写出来，用来确定
 *      「猜你喜欢 / 9.9元秒 / 进口好价 / 苹果专区 / 影音娱乐 / 生活日用 / 美食团购」
 *      分别对应哪个 CellModel 类。
 *
 * 纯观察，不改任何行为，看完删掉即可。
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

/* objc_msgSend 必须按真实签名强转后再调。绝不写 (unsigned long)objc_msgSend(...)，
 * 那样返回值被当 id，ARC 下会被 retain，拿 NSUInteger 时就是野指针 → 崩。 */
typedef id            (*Fn_id_0)(id, SEL);
typedef id            (*Fn_id_ul)(id, SEL, unsigned long);
typedef unsigned long (*Fn_ul_0)(id, SEL);
typedef BOOL          (*Fn_b_0)(id, SEL);
typedef BOOL          (*Fn_b_id)(id, SEL, id);
typedef BOOL          (*Fn_b_SEL)(id, SEL, SEL);

#define MSG_ID_0(o, s)     (((Fn_id_0)objc_msgSend)((o), (s)))
#define MSG_ID_UL(o, s, a) (((Fn_id_ul)objc_msgSend)((o), (s), (a)))
#define MSG_UL_0(o, s)     (((Fn_ul_0)objc_msgSend)((o), (s)))
#define MSG_B_ID(o, s, a)  (((Fn_b_id)objc_msgSend)((o), (s), (a)))
#define MSG_B_SEL(o, s, a) (((Fn_b_SEL)objc_msgSend)((o), (s), (a)))

/* libc（不引头文件，自己声明） */
extern char *getenv(const char *);
extern void *fopen(const char *path, const char *mode);
extern int fclose(void *stream);
extern int fputs(const char *s, void *stream);
extern int fprintf(void *stream, const char *fmt, ...);
extern int snprintf(char *buf, unsigned long n, const char *fmt, ...);

static char g_path[512];
static int  g_calls = 0;

static void *open_dump(void) {
    if (!g_path[0]) {
        const char *home = getenv("HOME");
        if (!home) return 0;
        snprintf(g_path, sizeof g_path, "%s/Documents/floor-map.txt", home);
    }
    return fopen(g_path, "w");
}

/* 取对象属性，拿不到就返回 0 */
static id prop(id obj, const char *name) {
    if (!obj) return 0;
    SEL s = sel_registerName(name);
    SEL rs = sel_registerName("respondsToSelector:");
    if (!MSG_B_SEL(obj, rs, s)) return 0;
    return MSG_ID_0(obj, s);
}

static void dump_array(id arr) {
    void *f = open_dump();
    if (!f) return;

    SEL selCount  = sel_registerName("count");
    SEL selObjAt  = sel_registerName("objectAtIndex:");
    SEL selRS     = sel_registerName("respondsToSelector:");

    if (!arr || !MSG_B_SEL(arr, selRS, selCount)) {
        fputs("newSectionModels 返回的不是数组，跳过\n", f);
        fclose(f);
        return;
    }

    unsigned long n = MSG_UL_0(arr, selCount);
    fprintf(f, "TmallCampus 首页楼层结构 (%lu 层)\n", n);
    fprintf(f, "========================================\n\n");

    for (unsigned long i = 0; i < n; i++) {
        id sec = MSG_ID_UL(arr, selObjAt, i);
        if (!sec) continue;

        fprintf(f, "[%02lu] %s\n", i, object_getClassName(sec));

        id diff = prop(sec, "diffIdentifier");
        if (diff) {
            /* 用 %s 打 description 不安全，简单标记有无 */
            fprintf(f, "     diffIdentifier: <有>\n");
        }

        id hdr = prop(sec, "headerCell");
        if (hdr) fprintf(f, "     headerCell: %s\n", object_getClassName(hdr));

        id ftr = prop(sec, "footerCell");
        if (ftr) fprintf(f, "     footerCell: %s\n", object_getClassName(ftr));

        id cms = prop(sec, "cellModels");
        if (!cms) {
            fprintf(f, "     cellModels: <nil>\n\n");
            continue;
        }

        unsigned long cn = MSG_UL_0(cms, selCount);
        fprintf(f, "     cellModels: %lu 个\n", cn);

        for (unsigned long j = 0; j < cn && j < 12; j++) {
            id cm = MSG_ID_UL(cms, selObjAt, j);
            if (!cm) continue;
            const char *c = object_getClassName(cm);

            /* 试着读几个可能是标题的字段，只判断有无 */
            const char *extra = "";
            id t = prop(cm, "title");
            if (!t) t = prop(cm, "name");
            if (!t) t = prop(cm, "text");
            if (t) extra = "  [有 title/name/text]";

            fprintf(f, "       - %s%s\n", c ? c : "?", extra);
        }
        if (cn > 12) fprintf(f, "       ... 还有 %lu 个\n", cn - 12);
        fprintf(f, "\n");
    }

    fprintf(f, "========================================\n");
    fprintf(f, "说明：\n");
    fprintf(f, "  把这整份文件内容发回来，即可确定每个楼层对应的 CellModel 类名。\n");
    fprintf(f, "  商品楼层通常是 cellModels 里反复出现同一个 *Commodity/*Product/*Gift/*Store 类。\n");
    fprintf(f, "  频道楼层（影音娱乐/生活日用/美食团购）通常是同层里多个 *Function/*Channel 类实例。\n");

    fclose(f);
}

static id (*orig_newSectionModels)(id, SEL);

static id hook_newSectionModels(id self, SEL _cmd) {
    id arr = orig_newSectionModels ? orig_newSectionModels(self, _cmd) : (id)0;
    g_calls++;
    if (arr) dump_array(arr);
    return arr;
}

__attribute__((constructor))
static void floormap_init(void) {
    id cls = objc_getClass("TCHomeViewModel");
    if (!cls) return;
    SEL sel = sel_registerName("newSectionModels");
    Method m = class_getInstanceMethod(cls, sel);
    if (!m) return;
    orig_newSectionModels = (id (*)(id, SEL))method_setImplementation(
        m, (IMP)(void *)hook_newSectionModels);
}


