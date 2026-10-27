/*
 * 天猫校园 首页楼层结构探针
 *
 * 目的：把首页每一个楼层（section）对应的类名、标题、内容数量打印出来，
 *      据此确定"猜你喜欢 / 9.9元秒 / 进口好价 / 苹果专区 / 影音娱乐 / 生活日用 / 美食团购"
 *      各自是哪个 CellModel，然后写精确的过滤规则。
 *
 * 用法：
 *   frida -H 127.0.0.1:27042 -f com.tmall.campus4iphone -l explore-home.js --no-pause
 *   然后：进首页 → 下拉刷新一次 → 看控制台输出的表格 → 把整段贴回来
 */

'use strict';

const TARGET_VC = 'TCHomeViewModel';
const TARGET_SC = 'TCSectionController';

function clsName(obj) {
  try { return obj.$className; } catch (e) { return '<nil>'; }
}

function desc(obj, max) {
  try {
    let s = obj.toString();
    if (s.length > (max || 120)) s = s.substring(0, max || 120) + '…';
    return s.replace(/\n/g, ' ');
  } catch (e) { return '<err>'; }
}

/* ---------- 1. 抓 newSectionModels 的返回 ---------- */
function hookSectionModels() {
  const K = ObjC.classes[TARGET_VC];
  if (!K) { console.log('[!] 找不到 ' + TARGET_VC); return; }
  const m = K['- newSectionModels'];
  if (!m) { console.log('[!] 找不到 -newSectionModels'); return; }

  Interceptor.attach(m.implementation, {
    onLeave(retval) {
      if (retval.isNull()) { console.log('\n[newSectionModels] nil'); return; }
      let arr;
      try { arr = new ObjC.Object(retval); } catch (e) { return; }
      if (!arr.$className || arr.$className.indexOf('Array') === -1) return;

      const n = arr.count().valueOf();
      console.log(`\n===== newSectionModels: ${n} 个楼层 =====`);
      for (let i = 0; i < n; i++) {
        let it;
        try { it = arr.objectAtIndex_(i); } catch (e) { continue; }
        const cn = clsName(it);
        console.log(`  [${String(i).padStart(2, '0')}] ${cn}`);
        console.log(`       ${desc(it, 200)}`);
      }
      console.log('===== end =====\n');
    },
  });
  console.log('[hook] ' + TARGET_VC + ' -newSectionModels');
}

/* ---------- 2. 抓每个 section 绑定的 object 与 cellModel ---------- */
function hookSectionController() {
  const K = ObjC.classes[TARGET_SC];
  if (!K) { console.log('[!] 找不到 ' + TARGET_SC); return; }

  const upd = K['- didUpdateToObject:'];
  if (upd) {
    Interceptor.attach(upd.implementation, {
      onEnter(args) {
        let o;
        try { o = new ObjC.Object(args[2]); } catch (e) { return; }
        console.log(`\n[section] object = ${clsName(o)}`);
        console.log(`          ${desc(o, 240)}`);
      },
    });
    console.log('[hook] ' + TARGET_SC + ' -didUpdateToObject:');
  }

  const setvm = K['- setViewModels:'];
  if (setvm) {
    Interceptor.attach(setvm.implementation, {
      onEnter(args) {
        let arr;
        try { arr = new ObjC.Object(args[2]); } catch (e) { return; }
        if (!arr || arr.$className.indexOf('Array') === -1) return;
        const n = arr.count().valueOf();
        const types = {};
        for (let i = 0; i < n; i++) {
          try {
            const it = arr.objectAtIndex_(i);
            const c = clsName(it);
            types[c] = (types[c] || 0) + 1;
          } catch (e) {}
        }
        const keys = Object.keys(types);
        if (keys.length) {
          console.log(`    viewModels(${n}): ` + keys.map(k => `${k}×${types[k]}`).join(', '));
        }
      },
    });
    console.log('[hook] ' + TARGET_SC + ' -setViewModels:');
  }

  const filt = K['- filterCellModels:'];
  if (filt) {
    Interceptor.attach(filt.implementation, {
      onEnter(args) {
        this._in = 0;
        try {
          const a = new ObjC.Object(args[2]);
          this._in = a.count().valueOf();
        } catch (e) {}
      },
      onLeave(retval) {
        let out = 0;
        try { out = new ObjC.Object(retval).count().valueOf(); } catch (e) {}
        if (this._in !== out) {
          console.log(`    filterCellModels: ${this._in} -> ${out}  （App 自己过滤掉了 ${this._in - out} 个）`);
        }
      },
    });
    console.log('[hook] ' + TARGET_SC + ' -filterCellModels:');
  }
}

/* ---------- 3. 抓 TCHomeData 的字段规模 ---------- */
function dumpHomeData() {
  const K = ObjC.classes['TCHomeViewModel'];
  if (!K) return;
  const g = K['- homeData'];
  if (!g) return;
  Interceptor.attach(g.implementation, {
    onLeave(retval) {
      if (retval.isNull()) return;
      let d;
      try { d = new ObjC.Object(retval); } catch (e) { return; }
      const fields = ['allModules', 'loadModules', 'items', 'listItems', 'chanels',
                      'gardenStore', 'associatedStore', 'storeBenefits', 'normalBanners',
                      'fixBanners', 'quicks', 'waist', 'bridalGift'];
      const parts = [];
      for (const f of fields) {
        try {
          const v = d[f]();
          if (v && v.$className && v.$className.indexOf('Array') !== -1) {
            parts.push(`${f}=${v.count().valueOf()}`);
          } else if (v && v.$className) {
            parts.push(`${f}=<${v.$className}>`);
          }
        } catch (e) {}
      }
      if (parts.length) console.log('\n[TCHomeData] ' + parts.join('  '));
    },
  });
  console.log('[hook] TCHomeViewModel -homeData');
}

function main() {
  console.log('=== 天猫校园 首页楼层探针 ===');
  hookSectionModels();
  hookSectionController();
  dumpHomeData();
  console.log('\n>>> 现在进首页 / 下拉刷新，观察上面的输出 <<<\n');
}

setTimeout(main, 1000);
