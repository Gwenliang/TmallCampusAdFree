# 故障排查手册

记录这套 Tweak 从 v1.0.0 到 v1.5.0 踩过的所有故障，以及定位方法。

---

## 一、症状对照表

| 症状 | 最可能原因 | 处理 |
|---|---|---|
| 点图标闪一下回桌面 | dyld 加载失败（签名/依赖问题） | 看 dylib 有没有 `LC_LOAD_DYLIB libSystem` |
| 能进 App 但卡开屏/白屏 | hook 了 void 流程方法，通知发不出来 | 检查是否 hook 了 `fetchData`/`loadSplash`/`setup`/`install` |
| 进首页后闪退 | 楼层过滤返回的对象引用计数错 | 见下文「`new` 前缀必须返回 +1」 |
| 注入后完全没反应 | dylib 没真注入 / 构造函数没跑 | TrollFools 里确认注入列表 |
| 广告还在 | 类名不匹配 / 版本变了 | 跑探针拿真实类名 |
| 登录异常、接口风控 | 阿里聚安全完整性校验 | 卸载 dylib |

---

## 二、三个致命坑

### 坑 1：ARC + `objc_msgSend` 返回值类型错配

**症状**：注入后进特定页面闪退。

```c
// 错误写法
unsigned long n = (unsigned long)objc_msgSend(arr, selCount);
```

`objc_msgSend` 声明返回 `id`，`-fobjc-arc` 下编译器会插入 `objc_retainAutoreleasedReturnValue`，把 `NSUInteger` 当对象指针 retain → 野指针。

**正确写法**：

```c
typedef unsigned long (*Fn_ul_0)(id, SEL);
unsigned long n = ((Fn_ul_0)objc_msgSend)(arr, selCount);
```

**或者**：编译时用 `-fno-objc-arc`。

**验证方法**：检查未定义符号里有没有 `objc_retain` / `objc_release` / `objc_retainAutoreleasedReturnValue`：

```powershell
llvm-nm -u TmallCampusAdFree.dylib
# 如果有 retain/release，说明 ARC 没关干净
```

### 坑 2：`new` 前缀方法必须返回 +1

**症状**：注入后打开首页立刻闪退，但探针 hook 同一个方法却正常。

```c
// 错误写法
id out = objc_msgSend(clsMut, sel_registerName("array"));   // +0 autoreleased
return out;   // 调用方按 +1 处理，release 一次 → 过度释放
```

`newSectionModels` 以 `new` 开头，按 Cocoa 内存管理规则，**调用方负责 release**，被调方必须返回 +1。

```c
// 正确写法
id out = objc_msgSend(clsMut, sel_registerName("alloc"));
out = objc_msgSend(out, sel_registerName("init"));          // +1
return out;
```

**最稳的做法**：没有内容需要修改时直接返回原对象，零风险。

```c
if (dropped == 0) return arr;   // 原样返回
```

**这是 v1.1.0 ~ v1.4.0 全部闪退的真正原因。** 定位线索：探针只读数组、原样返回，从不创建新对象，所以它能跑。

### 坑 3：`-nostdlib` 的两个副作用

**症状**：编译失败报 `BOOL` / `Class` 未定义，或者 dylib 注入后 dyld 拒绝加载。

```c
// 缺少 <objc/objc.h>，要自己补
typedef signed char BOOL;
typedef struct objc_class *Class;
```

```powershell
# dylib 零依赖，要手工补 libSystem
python tools/add_libsystem.py TmallCampusAdFree.dylib
llvm-otool -L TmallCampusAdFree.dylib
#   应看到 /usr/lib/libSystem.B.dylib
```

---

## 三、二分排查流程

出问题时按这个顺序缩小范围：

### 第 1 步：确认注入机制是否工作

注入一个**什么都不做、只写一行日志**的 dylib，能写出来说明注入链路 OK。

或者用现成的探针：

```
FloorMapProbe.dylib  →  能生成 Documents/floor-map.txt 说明注入成功
```

### 第 2 步：确认是广告 hook 还是楼层过滤

```powershell
# 只保留楼层过滤（关掉 11 个广告 hook）
clang ... -DTMALL_DISABLE_AD_HOOKS ...

# 只保留广告 hook（手动注释掉 install_floor_filter 调用）
```

### 第 3 步：逐个 hook 加回来

广告 hook 之间互相独立，可以注释掉一半试。

---

## 四、抓崩溃日志

| 环境 | 位置 |
|---|---|
| 非越狱 | 设置 → 隐私与安全性 → 分析与改进 → 分析数据 → `TmallCampus-*.ips` |
| 越狱 / TrollStore | `/var/mobile/Library/Logs/CrashReporter/` |
| 实时 | `idevicesyslog \| Select-String "TmallCampus"` |
| 3uTools | 工具箱 → 实时日志 |

看 `.ips` 里的关键字段：

- `exception` + 堆栈在 `dyld` → 签名 / 依赖问题
- `EXC_BAD_ACCESS` + 堆栈在 `TmallCampus` → 内存管理问题（坑 1 / 坑 2）
- `EXC_CRASH (SIGABRT)` + 堆栈在 `libobjc` → 向已释放对象发消息

---

## 五、验证 hook 是否生效

### 方式 1：符号表检查

```powershell
llvm-nm -u TmallCampusAdFree.dylib
```

期望（不含任何 retain/release）：

```
_class_getClassMethod
_class_getInstanceMethod
_method_setImplementation
_objc_getClass
_objc_msgSend
_object_getClassName
_sel_registerName
_strcmp
dyld_stub_binder
```

### 方式 2：Frida 实时看

```powershell
frida -H 127.0.0.1:27042 -f com.tmall.campus4iphone -l tools/tmallcampus-probe.js --no-pause
```

正常输出：

```
[hook] TCCampusAdManager: 2 个方法
[hook] TCSplashADvertisingBaseManager: 2 个方法
...
→ -[TCCampusAdManager canShowSplashAd]
← -[TCCampusAdManager canShowSplashAd] = false  (0ms)
```

返回值应该全是 `false`。

### 方式 3：DEBUG 编译

```powershell
clang ... -DTMALL_ADFREE_DEBUG ...
```

然后用 `idevicesyslog` 看：

```
[AdFree] === TmallCampusAdFree loaded ===
[AdFree] hooked -[TCCampusAdManager canShowSplashAd]
...
[AdFree] hooked=11 missed=0
```

`missed > 0` 说明有方法没找到（App 版本变了），但不影响运行。

---

## 六、TrollFools 使用注意

1. 注入前先**移除旧版本**，避免多个 dylib 叠加
2. 注入后如果 App 起不来，用 TrollFools 的「**还原**」一键恢复
3. 两个 dylib **不要同时注入**，出问题分不清是谁导致的
4. 需要重启 App 才生效，TrollFools 通常会自动重启

---

## 七、历史版本记录

| 版本 | 状态 | 说明 |
|---|---|---|
| v1.0.0 | ✅ 可用 | 11 个广告 hook，无楼层过滤 |
| v1.1.0 | ❌ 闪退 | 加楼层过滤；ARC + objc_msgSend 问题 |
| v1.2.0 | ❌ 闪退 | 关 ARC；`new` 前缀返回 +0 问题 |
| v1.3.0 | ❌ 闪退 | 改黑名单；问题同上 |
| v1.4.0 | ❌ 闪退 | 补 libSystem；问题同上 |
| **v1.5.0** | ✅ **可用** | 修好 `new` 前缀 +1 问题，用户确认 |