/*
 * 天猫校园 首页楼层 → 类名 对照表
 *
 * 在 newSectionModels 返回之后，把每个楼层的 cellModel 类名、数量、
 * 以及能被读出来的标题文本全部打印出来。跑一次就能确定
 * "猜你喜欢 / 9.9元秒 / 进口好价 / 苹果专区 / 影音娱乐 / 生活日用 / 美食团购"
 * 分别是哪几个类，然后直接改 Tweak 里的 FLOOR_BLACKLIST。
 *
 * 用法：
 *   frida -H 127.0.0.1:27042 -f com.tmall.campus4iphone -l floor-map.js --no-pause
 *   进首页，等数据加载完 / 下拉刷新一次
 */

'use strict';

const VM = 'TCHomeViewModel';

function cn(o) { try { return o.$className; } catch (e) { return '<nil>'; } }

function short(o, n) {
  try {
    let s = String(o);
    if (s.length > (n || 60)) s = s.substring(0, n || 60) + '…';
    return s.replace(/[\r\n\t]+/g, ' ');
  } catch (e) { return ''; }
}

/* 尝试从 cellModel 里读出可能是标题的字段 */
function guessTitle(cm) {
  const fields = ['title', 'titleString', 'name', 'text', 'subTitle', 'moduleTitle', 'headerTitle'];
  for (const f of fields) {
    try {
      const sel = ObjC.selector(f);
      if (!cm.respondsToSelector_(sel)) continue;
      const v = cm[f]();
      if (!v) continue;
      if (typeof v === 'string' && v.length) return `${f}="${v}"`;
      if (v.$className && v.$className.indexOf('String') !== -1) {
        const s = String(v);
        if (s.length) return `${f}="${s}"`;
      }
    } catch (e) {}
  }
  return '';
}

function main() {
  const K = ObjC.classes[VM];
  if (!K) { console.log('[!] 未找到 ' + VM); return; }
  const m = K['- newSectionModels'];
  if (!m) { console.log('[!] 未找到 -newSectionModels'); return; }

  Interceptor.attach(m.implementation, {
    onLeave(retval) {
      if (retval.isNull()) return;
      let arr;
      try { arr = new ObjC.Object(retval); } catch (e) { return; }
      const n = arr.count().valueOf();
      if (!n) return;

      console.log('\n════════ 楼层对照表 (' + n + ' 层) ════════');
      for (let i = 0; i < n; i++) {
        const sec = arr.objectAtIndex_(i);
        const secCls = cn(sec);

        let cms = null;
        try { cms = sec.cellModels(); } catch (e) {}
        const cn2 = cms ? cms.count().valueOf() : -1;

        // 统计 cellModel 类型
        const types = {};
        let sample = '';
        if (cms && cn2 > 0) {
          for (let j = 0; j < cn2; j++) {
            try {
              const cm = cms.objectAtIndex_(j);
              const k = cn(cm);
              types[k] = (types[k] || 0) + 1;
              if (!sample) sample = guessTitle(cm) || short(cm, 50);
            } catch (e) {}
          }
        }
        const typeStr = Object.keys(types).map(k => `${k}×${types[k]}`).join(', ');

        console.log(`\n[${String(i).padStart(2, '0')}] ${secCls}`);
        console.log(`     cellModels ${cn2} 个: ${typeStr || '(空)'}`);
        if (sample) console.log(`     样本: ${sample}`);

        // header / footer 提示
        try { const h = sec.headerCell(); if (h) console.log(`     header: ${cn(h)}`); } catch (e) {}
        try { const d = sec.diffIdentifier(); if (d) console.log(`     diffId: ${short(d, 40)}`); } catch (e) {}
      }
      console.log('\n════════ end ════════\n');
    },
  });
  console.log('=== 首页楼层对照探针已挂载，进首页等待数据 ===');
}

setTimeout(main, 1200);
