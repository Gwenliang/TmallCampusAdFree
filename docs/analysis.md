# 逆向分析笔记

记录天猫校园广告体系与首页结构的静态分析结果，供后续版本适配参考。

---

## 一、广告栈演进

### 3.1.4：阿里妈妈 UBiX 聚合（静态链接）

- 聚合 SDK：`ABUAdSDKManager` / `ABUAdLoader` / `ABUWaterfallAdManager` / `ABUMediationSlotConfig` 等 300+ 类，**静态链接进主二进制**
- 接入的 ADN：穿山甲 CSJ、广点通 GDT、百度 mobads、倍孜 BeiZi
- 快手：`KSAdSDK.framework`（14.9 MB 独立动态库）+ 12 个 `KSU*.bundle`
- 自有广告：`TCCampusAdManager`（开屏 + inlist）、`TCUbiXSplashADvertisingManager`（UBiX 开屏）、`TCUbixFeedAdvertisingManager`（信息流）

主二进制 137,924,880 字节，arm64 单架构，79 个 dylib，11,466 个 ObjC 类。

### 5.8.2：AnyThink(TopOn) 聚合（全动态框架）

| framework | 体积 | 作用 |
|---|---|---|
| `AnyThinkSDK.framework` | 3.7 MB | TopOn/AnyThink 聚合主体 |
| `GDTMobSDK.framework` | 11.8 MB | 广点通 |
| `KSAdSDK.framework` | 17.2 MB | 快手 |
| `QuMengAdSDK.framework` | 4.0 MB | 趣盟 |
| `SmartdigimktSDK.framework` | 6.4 MB | Smartdigimkt |
| `Unicorn.framework` | 6.3 MB | 广告基础库 |
| `JLBmpConvertKit.framework` | 0.55 MB | 图片格式转换 |

**全部是 `LC_LOAD_DYLIB` 强链接**，启动时 dyld 必定加载，一个字节都不能改。

接入层：`ATADX*` / `ATGDT*` / `ATQM*` / `ATSmartdigimkt*` / `UbiXMGDT*` / `MSGDT*`

业务层管理器：

| 类 | 职责 |
|---|---|
| `TCAdvertisingManager` | 广告节点总调度 |
| `TCSplashADvertisingBaseManager` | 开屏基类（TaKu/VOC/ZM 继承） |
| `TCTaKuSplashADvertisingManager` | TaKu 开屏 |
| `TCUbiXSplashADvertisingManager` | UBiX 开屏（**已无 `canShowAd`**） |
| `TCVOCSplashADvertisingManager` / `TCZMSplashADvertisingManager` | 另外两路开屏 |
| `TCCampusAdManager` | 自有开屏 + inlist |
| `TCUbixFeedAdvertisingManager` | UBiX 信息流 |
| `TCCXHAdManager` | CXH 广告位 |

主二进制 364,861,536 字节，arm64，6 段（含 `__LLVM_COV`），121 个 dylib，16,608 个 ObjC 类。

---

## 二、广告域名清单

### 主二进制内（5.8.2，561 个 URL / 65 个广告相关）

**阿里妈妈 UBiX**
```
sdk-data.ubixioe.com      tower.ubixioe.com
tx-cfg-u1.ubixioe.com     tx-data-u1.ubixioe.com
adx-cfg-u1.ubixioe.com    adx-data-u1.ubixioe.com
md-cfg-u1.ubixioe.com     md-data-u1.ubixioe.com
entry-su1.ubixioe.com
```

**倍孜 BeiZi / ADN-Plus / ad-scope**
```
sdk.beizi.biz             sdk-event.beizi.biz
api-htp.beizi.biz         sdk-api.adn-plus.com.cn
api.htp.ad-scope.com.cn   bid.ad-scope.com.cn
```

**百度 mobads**
```
mobads.baidu.com          mobads-logs.baidu.com
cpu.baidu.com             cpu-openapi.baidu.com
ada.baidu.com             aden.baidu.com
union.baidu.com           wn.pos.baidu.com
cpro.baidustatic.com
mobads-pre-config.bj.bcebos.com
mobads-pre-config.cdn.bcebos.com
```

**阿里妈妈 tanx**
```
ef-dongfeng.tanx.com      click.tanx.com
```

**穿山甲上报**
```
mon.snssdk.com            monsetting.toutiao.com
mon.toutiao.com           mon.toutiaocloud.com
mon.toutiaocloud.net
```

**快手**（`KSAdSDK.framework` 内）
```
api.kuaishouzt.com        api.kwaizt.com
w1.gskwai.com             w2.gskwai.com
w1.kskwai.com             w2.kskwai.com
zt.gifshow.com            ulog-sdk.gifshow.com
ulog-sdk.ksapisrv.com     static.yximgs.com
open.e.kuaishou.com       open.e.kuaishou.cn
s.e.kuaishou.com          live.kuaishou.com
```

---

## 三、首页结构（5.8.2 实测）

首页是**原生 IGListKit** 驱动，不是 H5 / Weex：

- `TCHomeViewController` — 首页 VC
- `TCSectionController` — 唯一 section controller，所有楼层复用
- `TCSectionModel` — 楼层包装对象，含 `cellModels` 数组
- `-[TCHomeViewModel newSectionModels]` — **所有楼层的唯一生成点**
- `-[TCSectionController filterCellModels:]` — App 自带的 cellModel 过滤机制

### 6 层实测结果

| # | 类名 | 作用 | 建议 |
|---|---|---|---|
| 00 | `TCHomeFixBannerCellModel` | 顶部固定 banner | 保留 |
| 01 | `TCHomeFunctionContainerCellModel` | 功能入口（校园卡/签到） | 保留 |
| 02 | `TCPersonalAssetContainerCellModel` | 个人资产 | 保留 |
| 03 | `TCAdCommonBannerCellModel` | 广告 banner | 删 |
| 04 | `TCHomeProductHeaderCellModel` | 商品区标题栏 | 删 |
| 05 | `TCHomeProductControllerCellModel` | 商品流容器 | 删 |

### 关键结论

**「猜你喜欢 / 9.9元秒 / 进口好价 / 苹果专区」不直接出现在这 6 层里**，它们嵌套在第 05 层 `TCHomeProductControllerCellModel` 内部的 `TCHomeProductViewController` 子控制器。所以删掉第 04 + 05 层 = 清空整个下方商品区。

**「影音娱乐 / 生活日用 / 美食团购」** 是第 01 层功能容器里的频道入口，删整层会连校园卡、签到一起没。

### 楼层标题是服务端下发的

在主二进制里按 UTF-8 和 UTF-16LE 两种编码扫描这些中文标题，**全部 0 次命中**：

```
猜你喜欢    utf8=0  utf16=0
9.9元秒     utf8=0  utf16=0
进口好价    utf8=0  utf16=0
苹果专区    utf8=0  utf16=0
影音娱乐    utf8=0  utf16=0
生活日用    utf8=0  utf16=0
美食团购    utf8=0  utf16=0
```

所以只能按类名筛选，不能按文字匹配。

---

## 四、TCHomeData 数据字段

```
allModules      loadModules     items         listItems
chanels         gardenStore     associatedStore  storeBenefits
normalBanners   fixBanners      quicks        waist
bridalGift      personalAssetData  inviteStudent  redFlowerData
```

`newSectionModels` 内部会逐一读取这些字段构造 section（`homeData` 被调用 22 次，`sectionModelWithCellModels:` 8 次）。

---

## 五、安全校验

阿里聚安全 SecurityGuard 存在：

- 152 处 `SecurityGuard` 字符串
- 52 个 `SG*` / `AliSecX*` 类
- `yw_1222.jpg`（密钥文件）1 处
- `wua` 47 处、`umid` 26 处
- `__DATA, AliServiceHubSec` 段

注入 dylib 后若出现登录态异常或接口风控，卸载即可恢复。这是阿里系 App 的通病，与广告无关。
