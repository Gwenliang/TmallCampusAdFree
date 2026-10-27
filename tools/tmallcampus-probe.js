/*
 * 天猫校园 广告行为实时探针（Frida）
 *
 * 用途：
 *   1) 实时打印所有广告相关方法的调用 / 参数 / 返回值 / 调用栈
 *   2) 捕获 ObjC 未捕获异常与 abort，直接指出崩在哪个方法
 *   3) 验证改包后广告链路是否真的被切断
 *
 * 用法（越狱 / TrollStore + frida-server）：
 *   frida -H 127.0.0.1:27042 -f com.tmall.campus4iphone -l tmallcampus-probe.js --no-pause
 *   已启动的话：frida -H 127.0.0.1:27042 -n TmallCampus -l tmallcampus-probe.js
 *
 * 只看某个类：
 *   frida ... -l tmallcampus-probe.js -e "PROBE.only('TCCampusAdManager')"
 */

'use strict';

const MAX_DEPTH = 6;
const MAX_ARGS = 3;

// ---- 目标类：广告业务层 + 聚合 SDK 接入层 ----
const AD_CLASSES = [
  // 业务层
  'TCCampusAdManager',
  'TCAdvertisingManager',
  'TCSplashADvertisingBaseManager',
  'TCTaKuSplashADvertisingManager',
  'TCUbiXSplashADvertisingManager',
  'TCVOCSplashADvertisingManager',
  'TCZMSplashADvertisingManager',
  'TCUbixFeedAdvertisingManager',
  'TCCXHAdManager',
  'TCCampusADLaunchView',
  'TCCampusAdView',
  'TCAdInlistUbixCell',
  'TCAdCommonBannerCell',
  'TCAdvertisingBannerView',
  'TCAdvertisingCampusInsertView',
  // AnyThink 聚合
  'ATAdManager',
  'ATSplashAd',
  'ATInterstitial',
  'ATRewardedVideoAd',
  'ATNativeADView',
  'ATBannerView',
  // 各 ADN
  'GDTMobSDKManager',
  'GDTSplashAd',
  'KSAdSDKManager',
  'KSSplashAdView',
  'ATQMSplashAdapter',
  'ATSmartdigimktSplash',
];

// 只关心这些关键字的方法（空数组 = 全都要）
const KEYWORDS = [
  'show', 'load', 'canShow', 'enable', 'ad', 'Ad', 'splash', 'Splash',
  'entry', 'Entry', 'render', 'cache', 'request', 'fetch', 'init', 'setup',
];

let ONLY = null;

function shouldLog(cls, sel) {
  if (ONLY && cls !== ONLY) return false;
  if (KEYWORDS.length === 0) return true;
  return KEYWORDS.some(k => sel.indexOf(k) !== -1);
}

function fmtRet(retval, retType) {
  try {
    if (retType === 'void') return 'void';
    if (retType === 'BOOL' || retType === 'bool') return retval.toInt32() ? 'true' : 'false';
    if (retType.indexOf('*') !== -1 || retType.indexOf('@') !== -1) {
      const p = retval;
      if (p.isNull()) return 'nil';
      try {
        const o = new ObjC.Object(p);
        const d = o.toString();
        return d.length > 80 ? d.substring(0, 80) + '…' : d;
      } catch (e) {
        return p.toString();
      }
    }
    return retval.toString();
  } catch (e) {
    return '<err>';
  }
}

function stack() {
  const bt = Thread.backtrace(this.context, Backtracer.ACCURATE)
    .slice(0, MAX_DEPTH)
    .map(a => {
      const s = DebugSymbol.fromAddress(a);
      return (s.name || '?') + (s.moduleName ? '@' + s.moduleName : '');
    });
  return bt.join('\n      ← ');
}

let hookCount = 0;

function hookClass(name) {
  const K = ObjC.classes[name];
  if (!K) return false;
  let n = 0;

  // 实例方法：先看自己声明的，再看整个类的（含继承）
  const methods = K.$ownMethods.concat(K.$methods.filter(m => K.$ownMethods.indexOf(m) === -1));
  for (const full of methods) {
    const isClass = full.startsWith('+');
    const sel = full.substring(1);
    if (!shouldLog(name, sel)) continue;

    let impl;
    try {
      impl = isClass ? K[full].implementation : K['- ' + sel] ? K['- ' + sel].implementation : null;
      if (!impl) impl = (isClass ? ObjC.classes[name][full] : null);
    } catch (e) { /* ignore */ }
    if (!impl) {
      try { impl = (isClass ? K[full] : K['- ' + sel]).implementation; } catch (e) { continue; }
    }
    if (!impl) continue;

    try {
      Interceptor.attach(impl, {
        onEnter(args) {
          this.t0 = Date.now();
          this.cls = name;
          this.sel = (isClass ? '+' : '-') + sel;
          this.trace = stack.call(this);
          let line = `[${this.sel} ${name}]`;
          // 打印前几个参数里能读成对象的
          try {
            const types = (isClass ? K[full] : K['- ' + sel]).argumentTypes || [];
            const shown = [];
            for (let i = 2; i < Math.min(types.length, 2 + MAX_ARGS); i++) {
              const t = types[i].name || '';
              if (t.indexOf('@') !== -1 || t.indexOf('*') !== -1) {
                try {
                  const o = new ObjC.Object(args[i]);
                  let d = o.toString();
                  if (d.length > 60) d = d.substring(0, 60) + '…';
                  shown.push(`arg${i - 1}=${d}`);
                } catch (e) { shown.push(`arg${i - 1}=<ptr>`); }
              } else {
                shown.push(`arg${i - 1}=${args[i]}`);
              }
            }
            if (shown.length) line += '  ' + shown.join(' ');
          } catch (e) { /* ignore */ }
          console.log('→ ' + line);
        },
        onLeave(retval) {
          const ms = Date.now() - this.t0;
          let r;
          try {
            const types = (isClass ? K[full] : K['- ' + sel]).returnType;
            r = fmtRet(retval, types.name || types);
          } catch (e) { r = retval.toString(); }
          console.log(`← ${this.sel} ${this.cls} = ${r}  (${ms}ms)`);
          if (ms > 300) {
            console.log(`   ⏱ 慢调用 ${ms}ms，调用栈：\n      ${this.trace}`);
          }
        },
      });
      n++;
    } catch (e) { /* ignore */ }
  }
  if (n) {
    console.log(`[hook] ${name}: ${n} 个方法`);
    hookCount += n;
  }
  return n > 0;
}

// ---- 异常与崩溃捕获 ----
function hookCrashes() {
  try {
    const throwFn = Module.findExportByName(null, 'objc_exception_throw');
    if (throwFn) {
      Interceptor.attach(throwFn, {
        onEnter(args) {
          let desc = '<unknown>';
          try { desc = new ObjC.Object(args[0]).toString(); } catch (e) {}
          console.log('\n💥 ObjC 异常抛出: ' + desc);
          console.log('   调用栈:\n      ' + stack.call(this));
        },
      });
      console.log('[hook] objc_exception_throw');
    }
  } catch (e) {}

  for (const sym of ['abort', '__assert_rtn', '__stack_chk_fail']) {
    try {
      const p = Module.findExportByName(null, sym);
      if (!p) continue;
      Interceptor.attach(p, {
        onEnter(args) {
          console.log(`\n💀 ${sym} 被调用`);
          console.log('   调用栈:\n      ' + stack.call(this));
        },
      });
      console.log('[hook] ' + sym);
    } catch (e) {}
  }
}

function dumpLoadedAdFrameworks() {
  const want = ['AnyThinkSDK', 'GDTMobSDK', 'KSAdSDK', 'QuMengAdSDK', 'SmartdigimktSDK', 'Unicorn'];
  const found = [];
  Process.enumerateModules().forEach(m => {
    if (want.some(w => m.name.indexOf(w) !== -1)) found.push(m.name);
  });
  console.log('[modules] 已加载的广告框架: ' + (found.length ? found.join(', ') : '无'));
  const missing = want.filter(w => !found.some(f => f.indexOf(w) !== -1));
  if (missing.length) console.log('[modules] 未加载: ' + missing.join(', ') + '（若与预期不符说明 dyld 已跳过）');
}

function main() {
  console.log('=== 天猫校园 广告探针 ===');
  dumpLoadedAdFrameworks();
  hookCrashes();

  let n = 0;
  for (const c of AD_CLASSES) if (hookClass(c)) n++;
  console.log(`[hook] 共挂钩 ${n} 个类 / ${hookCount} 个方法`);

  // 定时输出仍然存活，方便确认探针在工作
  setInterval(() => {
    console.log(`[alive] ${new Date().toLocaleTimeString()} 仍在监听`);
  }, 30000);
}

global.PROBE = {
  only(name) { ONLY = name; console.log('[probe] 只监听 ' + name); },
  classes: AD_CLASSES,
};

// 等 App 把 ObjC 类注册完再挂钩
setTimeout(main, 800);
