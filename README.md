# TmallCampusAdFree

天猫校园 iOS 去广告 Tweak。用 Objective-C runtime 在运行时 hook 广告判定方法，不改二进制、不破坏签名，支持 TrollStore / TrollFools 注入、越狱 deb 安装，以及注入好 dylib 的 IPA 直接签名安装。

> 目标版本：天猫校园 5.8.2（`com.tmall.campus4iphone`）
> 编译环境：Windows + LLVM 18.1.8，**不需要 macOS / Xcode / Theos / iOS SDK**

---

## 功能

### 一、广告屏蔽（11 个判定 hook）

全部 hook「能不能展示」这类 BOOL 判定，返回 `NO` 等价于「当前没有广告库存」。这是每个真实用户都会遇到的正常状态（无网、无填充、超频次），App 本来就必须处理这个分支，所以不会破坏启动流程。

| 类 | 方法 | 管什么 |
|---|---|---|
| `TCCampusAdManager` | `canShowSplashAd` | 自有开屏广告 |
| `TCCampusAdManager` | `isHaveInlistAdModel` | 信息流广告模型 |
| `TCSplashADvertisingBaseManager` | `canShowAdCounts` | 聚合开屏频次（TaKu/VOC/ZM 共用基类） |
| `TCSplashADvertisingBaseManager` | `canShowSplashAdHotLaunching:` | 热启动开屏 |
| `TCUbixFeedAdvertisingManager` | `canShowAdWithType:node:` | 信息流广告位 |
| `TCUbixFeedAdvertisingManager` | `canShowAdWithInlistId:` | inlist 广告位 |
| `TCUbixFeedAdvertisingManager` | `canShowADCheckCountWithType:node:` | 信息流频次 |
| `TCAdvertisingManager` | `canShowAdvertisingNode:` | 广告节点总调度 |
| `TCCXHAdManager` | `isEnabled` | CXH 广告位开关 |
| `TCCXHAdManager` | `canShowAdForPosId:` | CXH 坑位判定 |
| `TCTaKuSplashADvertisingManager` | `checkAd` | TaKu 开屏判定 |

`TCSplashADvertisingBaseManager` 是基类，TaKu / VOC / ZM 三个开屏管理器都继承它，hook 一个方法覆盖三路。

### 二、首页商品楼层清理

首页是原生 IGListKit 驱动，所有楼层由 `-[TCHomeViewModel newSectionModels]` 一次性生成。hook 这个方法，按 `TCSectionModel.cellModels` 的元素类型过滤，整层全命中才丢弃：

```c
static const char *FLOOR_BLACKLIST[] = {
    "TCHomeProductHeaderCellModel",      /* 商品区标题栏 */
    "TCHomeProductControllerCellModel",  /* 商品流容器（猜你喜欢/9.9元秒/进口好价/苹果专区） */
    "TCAdCommonBannerCellModel",         /* 广告 banner */
    /* 预留：其它版本可能出现的类名 */
    "TCHomeCommodityCellModel", "TCHomeGiftCellModel",
    "TCHomeListControllerCellModel", "TCHomeOperationPositionCellModel",
    "TCGardenStoreContainerCellModel", "TCAssociatedShopContainerCellModel",
    "TCStoreContainerCellModel", "TCReachStoreContainerCellModel",
    0
};
```

实测首页 6 层的结构（`floor-map.txt` 探针输出）：

| # | 类名 | 作用 | 处理 |
|---|---|---|---|
| 00 | `TCHomeFixBannerCellModel` | 顶部固定 banner | 保留 |
| 01 | `TCHomeFunctionContainerCellModel` | 功能入口（校园卡/签到） | 保留 |
| 02 | `TCPersonalAssetContainerCellModel` | 个人资产 | 保留 |
| 03 | `TCAdCommonBannerCellModel` | 广告 banner | **删** |
| 04 | `TCHomeProductHeaderCellModel` | 商品区标题栏 | **删** |
| 05 | `TCHomeProductControllerCellModel` | 商品流容器 | **删** |

「影音娱乐 / 生活日用 / 美食团购」是第 01 层功能容器里的频道**入口**，删掉会连校园卡、签到一起没，所以保留入口、只删它下面的商品。

---

## 三个关键设计约束

这三条都是踩坑换来的，改代码前务必先读。

### 1. 绝不 hook 流程方法

`fetchData` / `loadSplash` / `setup` / `install` 这类 void 方法负责发布 `splashLoadCompleteSubject` / `splashMissSubject` 通知。改成 `ret` 立即返回，会让开屏层永远等不到回调 —— **卡白屏**，比闪退更难查。

### 2. 绝不 hook `enableAd`

它是「广告功能是否启用」的总开关，返回 `NO` 会跳过 `install` / `setupData` 整条初始化链，后续访问未初始化状态直接崩。

### 3. 绝不修改 `Frameworks/` 下的二进制

5.8.2 的广告 SDK 全是强链接动态框架：

```
AnyThinkSDK / GDTMobSDK / KSAdSDK / QuMengAdSDK / SmartdigimktSDK / Unicorn / JLBmpConvertKit
```

它们都是 `LC_LOAD_DYLIB`，启动瞬间 dyld 必定加载。改一个字节就可能让签名失效 → dyld 拒绝加载 → **启动闪退**。所以 dylib 方案只改主二进制（注入一条 load command）或完全不动二进制（TrollFools 注入）。

---

## 编译

### 依赖

只需要 **LLVM 18.1.8 Windows 版**（含 `clang.exe` 和 `ld64.lld.exe`）。

下载：<https://github.com/llvm/llvm-project/releases/download/llvmorg-18.1.8/clang+llvm-18.1.8-x86_64-pc-windows-msvc.tar.xz>

解压到 `toolchain/llvm/`，然后：

```powershell
cd tweak
.\build.bat
```

或手动：

```powershell
clang -target arm64-apple-ios12.0 -dynamiclib -nostdlib -fuse-ld=lld `
      -fno-objc-arc -O2 `
      -Wl,-undefined,dynamic_lookup `
      -Wl,-install_name,@rpath/TmallCampusAdFree.dylib `
      -o TmallCampusAdFree.dylib TmallCampusAdFree.m
```

### 为什么不需要 iOS SDK

用 `-nostdlib` + `-Wl,-undefined,dynamic_lookup`，所有外部符号（`objc_getClass`、`objc_msgSend`、`sel_registerName` 等）在运行时由 dyld 从已加载的 `libobjc` / `libSystem` 解析。源码里也不 `#import` 任何系统头文件，全部自己声明。

### 编译后必须补依赖

`-nostdlib` 产出的 dylib 是零依赖的，但里面有大量未定义符号。iOS 上这些必须由 libSystem 提供，缺了这条依赖 dyld 会加载失败。用脚本补上：

```powershell
python tools/add_libsystem.py TmallCampusAdFree.dylib
```

验证：

```powershell
llvm-otool -L TmallCampusAdFree.dylib
# 应看到两行：
#   @rpath/TmallCampusAdFree.dylib
#   /usr/lib/libSystem.B.dylib
```

### 编译开关

```powershell
# 只保留首页楼层过滤，关掉 11 个广告 hook（排查用）
clang ... -DTMALL_DISABLE_AD_HOOKS ...
```

---

## 使用

### 方式 A：TrollFools 注入（推荐）

1. 装 [TrollFools](https://github.com/Lessica/TrollFools)
2. 把 `TmallCampusAdFree.dylib` 传到手机（微信文件传输 / Filza / AirDrop）
3. TrollFools → 找到「天猫校园」→ 注入 → 选 dylib
4. TrollFools 自动重建签名并重启 App

> 出问题可以用 TrollFools 的「还原」一键恢复原 App。

### 方式 B：deb 安装（越狱）

```bash
dpkg -i TmallCampusAdFree.deb
killall -9 TmallCampus
```

deb 内容：

```
Library/MobileSubstrate/DynamicLibraries/TmallCampusAdFree.dylib   (0755)
Library/MobileSubstrate/DynamicLibraries/TmallCampusAdFree.plist   (0644, Filter: com.tmall.campus4iphone)
```

### 方式 C：注入好的 IPA

`F-5.8.2-Tweak注入版.ipa` 已经把 dylib 放进 `Frameworks/` 并在主二进制加了一条 `LC_LOAD_DYLIB`，签名后直接装：

- **Sideloadly**（Windows + Apple ID，7 天有效）
- **Esign / Feather**（自备证书）
- **TrollStore**（丢进去，自己 ldid 签名）

---

## 调试

### 首页楼层探针

`FloorMapProbe.dylib` 把首页每层的 `cellModels` 类名、`diffIdentifier`、`headerCell` 写进 App 沙盒的 `Documents/floor-map.txt`。

该 App 开了 `UIFileSharingEnabled`，所以可以直接用 iOS「文件」App 打开：**文件 → 浏览 → 我的 iPhone → 天猫校园 → floor-map.txt**。

`FloorMapProbe2.dylib` 会继续往 `TCHomeProductViewController` 内部挖，输出 `floor-map-deep.txt`。

### Frida 实时探针

能跑 frida-server 的话用这个更实时：

```powershell
frida -H 127.0.0.1:27042 -f com.tmall.campus4iphone -l tools/tmallcampus-probe.js --no-pause
frida -H 127.0.0.1:27042 -f com.tmall.campus4iphone -l tools/floor-map.js --no-pause
```

`tmallcampus-probe.js` 会打印所有广告方法的调用 / 参数 / 返回值 / 耗时，以及 `objc_exception_throw` / `abort` 的完整调用栈。

---

## 工具链

`tools/` 下是逆向天猫校园过程中写的通用工具，可复用到其它 iOS App：

| 脚本 | 作用 |
|---|---|
| `macho.py` | Mach-O 解析（段/节/load command/symbol/entitlements，vm↔file offset 互转） |
| `objc_dump.py` | 导出全部 ObjC 类与方法 |
| `objc_detail.py` | **区分实例方法 / 类方法**并给出 IMP（类方法在 metaclass 的 class_ro 里） |
| `verify_imps.py` | 用 `LC_FUNCTION_STARTS` 校验 IMP 是否为真实函数入口 |
| `repack.py` | 重打包 IPA，**保留 unix 权限位**（iOS 必需 0100755） |
| `inject_dylib.py` | 往 Mach-O 注入 `LC_LOAD_DYLIB`，利用 header padding 不移动段 |
| `add_libsystem.py` | 给零依赖 dylib 补 `libSystem` |
| `build_deb.py` | 不依赖 dpkg-deb，手写 ar + tar.gz 生成 deb |
| `patch_v582.py` | 5.8.2 改包补丁（4 个判定 + 68 处广告域名） |
| `patch_binary.py` / `patch_v2.py` / `patch_v3.py` | 3.1.4 各阶段补丁 |
| `xref.py` | arm64 ADRP/LDR 交叉引用扫描 |
| `floor-map.js` / `explore-home.js` / `tmallcampus-probe.js` | Frida 探针 |

---

## 踩坑记录

写这套东西踩过的坑，按踩到的顺序：

### 1. ARC + `objc_msgSend` 返回值类型错配

```c
// 错误：objc_msgSend 声明返回 id，ARC 会插 objc_retainAutoreleasedReturnValue
unsigned long n = (unsigned long)objc_msgSend(arr, selCount);
```

`count` 实际返回 `NSUInteger`，被当成对象指针 retain → 野指针 → 闪退。

**正确做法**：按真实签名强转后再调。

```c
typedef unsigned long (*Fn_ul_0)(id, SEL);
unsigned long n = ((Fn_ul_0)objc_msgSend)(arr, selCount);
```

或者直接 `-fno-objc-arc` 编译。两者都做最稳。

### 2. `new` 前缀方法必须返回 +1

```c
// 错误：+[NSMutableArray array] 是 +0 autoreleased
id out = objc_msgSend(clsMut, selArray);
return out;   // 调用方按 +1 处理，release 一次 → 过度释放 → 野指针
```

`newSectionModels` 以 `new` 开头，按 Cocoa 内存管理规则，调用方会负责 release。必须返回 `alloc/init`（+1）。

```c
id out = MSG_ID_0(clsMut, sel_registerName("alloc"));
out = MSG_ID_0(out, sel_registerName("init"));
```

**这是 v1.1.0 ~ v1.4.0 全部闪退的真正原因。** 排查时的一个关键线索：探针 hook 同一个方法却能跑 —— 因为它只读数组、原样返回，从不创建新对象。

### 3. `-nostdlib` 的两个副作用

- dylib 零依赖，需要手工补 `LC_LOAD_DYLIB /usr/lib/libSystem.B.dylib`
- 没有 `<objc/objc.h>`，`BOOL` 和 `Class` 未定义，要自己 `typedef`

### 4. `-fobjc-arc` 下能编过、`-fno-objc-arc` 下报错

`-fobjc-arc` 会隐式提供一些 ObjC 类型定义，关掉之后 `BOOL` / `Class` 就找不到了。别以为编译通过就没事，切换编译选项要重测。

### 5. 改 framework 一定闪退

强链接框架改一个字节，重签工具未必能递归覆盖到，dyld 校验失败就闪退。只改主二进制。

---

## 已知限制

1. **H5 / Weex 页面内的推广卡片**是服务端下发的业务内容，不是 SDK 广告位，Tweak 拦不住。要去只能走网络规则拦截。
2. **阿里聚安全（SecurityGuard）** 有自身完整性校验（`yw_1222.jpg` + `TCSafeKit`）。注入 dylib 后若出现登录态异常或接口风控，卸载 dylib 即可恢复。
3. **App 升级后类名可能变**。`floor_is_blacklisted` 只做字符串比对，匹配不到就跳过 —— 楼层会回到界面，但**不会崩**。
4. **黑名单依赖实测**。`floor-map.txt` 探针就是为了确认真实类名，别凭类名猜（我一开始猜了 10 个，8 个根本不存在）。

---

## 目录结构

```
.
├── README.md
├── LICENSE
├── .gitignore
├── tweak/
│   ├── TmallCampusAdFree.m      # 主插件源码
│   ├── FloorMapProbe.m          # 首页楼层探针
│   ├── FloorMapProbe2.m         # 深层探针
│   └── build.bat                # 一键编译
├── tools/                       # 通用逆向工具
└── docs/                        # 详细文档
```

---

## 免责声明

本项目仅供**个人学习与研究 iOS 逆向工程**使用。

- 请勿用于商业用途或二次分发修改后的 App
- 修改 App 可能违反其用户协议，请自行评估
- 使用本工具产生的一切后果由使用者自行承担
- 如果喜欢天猫校园，请支持官方版本

---

## License

MIT
