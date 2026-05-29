#!/usr/bin/env python3
# 极速赔率抓取工具 - Kivy Android 版
import sys
import os
import re
import asyncio
import threading
from datetime import datetime, timedelta

os.environ['KIVY_NO_CONSOLELOG'] = '1'

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import platform

import aiohttp
import pandas as pd
from lxml import etree

# -------------------- 常量 --------------------
COMPANY_MAP = {
    '3': '皇冠', '8': 'Bet365', '9': '威廉希尔',
    '31': '利记', '42': '188bet', '47': '平博',
    '1': '澳门', '4': '立博'
}
DEFAULT_CHECKED_IDS = ['1', '3', '8', '9', '31', '47']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.nowscore.com/'
}
ASIAN_HANDICAP_MAP = {
    "四球半": -4.5, "四球/四球半": -4.25, "四球": -4.0, "三球半/四球": -3.75, "三球半": -3.5,
    "三/三球半": -3.25, "三球": -3.0, "两球半/三": -2.75, "两球半": -2.5, "两/两球半": -2.25,
    "两球": -2.0, "球半/两": -1.75, "球半": -1.5, "一/球半": -1.25, "一球": -1.0,
    "半/一": -0.75, "半球": -0.5, "平/半": -0.25,
    "受四球半": 4.5, "受四球/四球半": 4.25, "受四球": 4.0, "受三球半/四球": 3.75, "受三球半": 3.5,
    "受三/三球半": 3.25, "受三球": 3.0, "受两球半/三": 2.75, "受两球半": 2.5, "受两/两球半": 2.25,
    "受两球": 2.0, "受球半/两": 1.75, "受球半": 1.5, "受一/球半": 1.25, "受一球": 1.0,
    "受半/一": 0.75, "受半球": 0.5, "受平/半": 0.25,
    "平手": 0.0
}
OVER_UNDER_MAP = {
    "0/0.5": 0.25, "0.5": 0.5, "0.5/1": 0.75, "1": 1.0, "1/1.5": 1.25, "1.5": 1.5,
    "1.5/2": 1.75, "2": 2.0, "2/2.5": 2.25, "2.5": 2.5, "2.5/3": 2.75, "3": 3.0,
    "3/3.5": 3.25, "3.5": 3.5, "3.5/4": 3.75, "4": 4.0, "4/4.5": 4.25, "4.5": 4.5,
    "4.5/5": 4.75, "5": 5.0, "5/5.5": 5.25, "5.5": 5.5, "5.5/6": 5.75, "6": 6.0,
    "6/6.5": 6.25, "6.5": 6.5, "6.5/7": 6.75, "7": 7.0
}

# -------------------- 辅助函数 --------------------
def normalize_time(raw_time):
    try:
        clean_str = re.sub(r'[^0-9\-/: ]', '', raw_time).strip()
        patterns = [
            (r'(\d{1,2})[-/](\d{1,2})[\s/]*(\d{1,2}:\d{2})', '%m-%d %H:%M'),
            (r'(\d{1,2}:\d{2})', '%H:%M'),
            (r'(\d{4}-\d{2}-\d{2})[\s/]*(\d{2}:\d{2})', '%Y-%m-%d %H:%M')
        ]
        for pattern, fmt in patterns:
            match = re.search(pattern, clean_str)
            if match:
                if fmt == '%m-%d %H:%M':
                    month, day, time_str = match.groups()
                    dt = datetime.strptime(f"{datetime.now().year}-{month}-{day} {time_str}", '%Y-%m-%d %H:%M')
                    return dt.strftime('%m-%d %H:%M')
                elif fmt == '%H:%M':
                    now = datetime.now()
                    dt = datetime.strptime(f"{now.year}-{now.month}-{now.day} {match.group(1)}", '%Y-%m-%d %H:%M')
                    return dt.strftime('%m-%d %H:%M')
                elif fmt == '%Y-%m-%d %H:%M':
                    return match.group(0)
    except Exception:
        pass
    return raw_time

def clean_score(score_str):
    if not score_str:
        return ''
    m = re.match(r'(\d{1,2})月(\d{1,2})日', score_str)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r'(\d+)[:-](\d+)', score_str)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ''

def convert_handicap_value(s, t):
    if t == 'asian':
        return ASIAN_HANDICAP_MAP.get(s, s)
    if t == 'overunder':
        return OVER_UNDER_MAP.get(s, s)
    return s

def calc_2way(o1, o2):
    try:
        d1, d2 = float(o1) + 1, float(o2) + 1
        if d1 <= 1 or d2 <= 1:
            return "", "", ""
        p1, p2 = 1/d1, 1/d2
        m = p1 + p2
        if m == 0:
            return "", "", ""
        return f"{(1/m)*100:.1f}%", f"{(p1/m)*100:.1f}%", f"{(p2/m)*100:.1f}%"
    except (ValueError, TypeError, ZeroDivisionError):
        return "", "", ""

def calc_3way(o1, o2, o3):
    try:
        d1, d2, d3 = float(o1), float(o2), float(o3)
        if d1 == 0 or d2 == 0 or d3 == 0:
            return "", "", "", ""
        p1, p2, p3 = 1/d1, 1/d2, 1/d3
        m = p1 + p2 + p3
        if m == 0:
            return "", "", "", ""
        return f"{(1/m)*100:.1f}%", f"{(p1/m)*100:.1f}%", f"{(p2/m)*100:.1f}%", f"{(p3/m)*100:.1f}%"
    except (ValueError, TypeError, ZeroDivisionError):
        return "", "", "", ""

# -------------------- 爬虫 --------------------
class AsyncScraper:
    def __init__(self, match_id, log_func):
        self.match_id = match_id
        self.log = log_func

    async def fetch(self, session, url):
        for _ in range(3):
            try:
                async with session.get(url, headers=HEADERS, timeout=15) as r:
                    r.raise_for_status()
                    return await r.text(encoding='utf-8')
            except Exception as e:
                await asyncio.sleep(1)
        return None

    async def get_team_names(self, session):
        html = await self.fetch(session,
            f"https://live.nowscore.com/Odds/count/goalCount.aspx?t=1&sid={self.match_id}&cid=1")
        if not html:
            return "未知", "未知"
        try:
            tree = etree.HTML(html)
            el = tree.xpath('/html/body/table[1]/tbody/tr[1]/td/text()')
            if el:
                m = re.search(r'(.+?)\s+vs\s+(.+?)(?:\s+\[.+\])?$', el[0].strip())
                if m:
                    h = m.group(1).split(':')[-1].strip() if ':' in m.group(1) else m.group(1).strip()
                    return h, m.group(2).strip()
        except Exception:
            pass
        return "未知", "未知"

    async def get_match_details(self, session):
        html = await self.fetch(session,
            f"https://live.nowscore.com/odds/3in1Odds.aspx?companyid=8&id={self.match_id}")
        if not html:
            return "未知"
        try:
            tree = etree.HTML(html)
            for xp in ['//div[@class="lgtime"]', '//*[@id="MatchIntro"]']:
                el = tree.xpath(xp)
                if el:
                    parts = [t.strip() for t in el[0].xpath('.//text()') if t.strip()]
                    if parts:
                        return " ".join(parts)
        except Exception:
            pass
        return "未知"

    def extract_table(self, tree, xpath, htype=None):
        data = []
        tables = tree.xpath(xpath)
        if not tables:
            return data
        for tr in tables[0].xpath('.//tr')[1:]:
            cols = [td.xpath('string(.)').strip() for td in tr.xpath('./td[position() >= 2 and position() <= 7]')]
            if len(cols) < 6 or any('封' in c for c in cols):
                continue
            cols[0] = clean_score(cols[0])
            cols[4] = normalize_time(cols[4])
            if htype and len(cols) > 2:
                cols[2] = convert_handicap_value(cols[2], htype)
            data.append(cols[:6])
        return data

    async def get_company_odds(self, session, cid, cname, is_half):
        url = f"https://live.nowscore.com/odds/3in1Odds.aspx?companyid={cid}&id={self.match_id}"
        if is_half:
            url += "&t=1"
        html = await self.fetch(session, url)
        if not html:
            return None
        tree = etree.HTML(html)
        asian = self.extract_table(tree, '//*[@id="oddsmain"]/div[3]', 'asian')
        ou = self.extract_table(tree, '//*[@id="oddsmain"]/div[4]', 'overunder')
        wdl = self.extract_table(tree, '//*[@id="oddsmain"]/div[5]')
        max_r = max(len(asian), len(ou), len(wdl))
        if max_r == 0:
            return None
        merged = []
        for i in range(max_r):
            row = []
            if i < len(asian):
                a = asian[i]
                r, p1, p2 = calc_2way(a[1], a[3])
                row.extend(a[:4] + [r, p1, p2] + a[4:])
            else:
                row.extend([''] * 9)
            if i < len(ou):
                o = ou[i]
                r, p1, p2 = calc_2way(o[1], o[3])
                row.extend(o[:4] + [r, p1, p2] + o[4:])
            else:
                row.extend([''] * 9)
            if i < len(wdl):
                w = wdl[i]
                r, p1, p2, p3 = calc_3way(w[1], w[2], w[3])
                row.extend(w[:4] + [r, p1, p2, p3] + w[4:])
            else:
                row.extend([''] * 10)
            merged.append(row)
        cols = []
        cols.extend(['让球_比分','让球_主','让球_盘口','让球_客','让球_返还率','让球_主概率','让球_客概率','让球_时间','让球_状态'])
        cols.extend(['大小_比分','大小_大','大小_盘口','大小_小','大小_返还率','大小_大概率','大小_小概率','大小_时间','大小_状态'])
        cols.extend(['胜负_比分','胜负_胜','胜负_平','胜负_负','胜负_返还率','胜负_胜概率','胜负_平概率','胜负_负概率','胜负_时间','胜负_状态'])
        return {'company': cname, 'type': '上半场' if is_half else '全场', 'df': pd.DataFrame(merged, columns=cols)}

# -------------------- 数据处理器 --------------------
class DataProcessor:
    def __init__(self, cutoff):
        self.cutoff = cutoff
        self.cats = ['让球', '大小', '胜负']

    def process(self, df):
        if df.empty:
            return df
        df = df.copy()
        if self.cutoff:
            for cat in self.cats:
                tc = f'{cat}_时间'
                if tc not in df.columns:
                    continue
                for idx, row in df.iterrows():
                    ts = str(row[tc])
                    if not ts:
                        continue
                    try:
                        dt = datetime.strptime(f"{self.cutoff.year}-{ts}", '%Y-%m-%d %H:%M')
                        if dt > self.cutoff:
                            for c in df.columns:
                                if c.startswith(cat):
                                    df.at[idx, c] = ''
                    except ValueError:
                        pass
        return self._align(df)

    def _align(self, df):
        cols = df.columns.tolist()
        data = {cat: {c: [] for c in cols if c.startswith(cat)} for cat in self.cats}
        for _, row in df.iterrows():
            for cat in self.cats:
                tc = f'{cat}_时间'
                if tc in df.columns and str(row[tc]).strip():
                    for c in cols:
                        if c.startswith(cat):
                            data[cat][c].append(row[c])
        max_r = 0
        for cat in self.cats:
            if data[cat] and next(iter(data[cat].values()), []):
                max_r = max(max_r, len(next(iter(data[cat].values()))))
        if max_r == 0:
            return pd.DataFrame(columns=cols)
        result = {}
        for cat in self.cats:
            for c in cols:
                if c.startswith(cat):
                    v = data[cat].get(c, [])
                    result[c] = v + [''] * (max_r - len(v))
        return pd.DataFrame(result, columns=cols)

    def to_md(self, df):
        if df.empty:
            return ""
        df = df.astype(str).replace('nan', '').replace('None', '')
        for c in df.columns:
            df[c] = df[c].apply(lambda x: x.replace('|', '∣').strip())
        h = df.columns.tolist()
        lines = ['| ' + ' | '.join(h) + ' |', '| ' + ' | '.join(['---'] * len(h)) + ' |']
        for _, r in df.iterrows():
            lines.append('| ' + ' | '.join(r.tolist()) + ' |')
        return '\n'.join(lines)

# -------------------- Kivy App --------------------
class MainLayout(BoxLayout):
    pass

class OddsApp(App):
    def build(self):
        self.title = '极速赔率抓取'
        Window.size = (480, 800)

        root = BoxLayout(orientation='vertical', spacing=4, padding=[8, 8, 8, 8])

        # Row 1: ID input
        row1 = BoxLayout(orientation='horizontal', size_hint_y=0.07, spacing=6)
        row1.add_widget(Label(text='比赛ID:', size_hint_x=0.2, halign='right'))
        self.id_input = TextInput(size_hint_x=0.4, multiline=False, input_filter='int')
        row1.add_widget(self.id_input)
        self.analyze_btn = Button(text='开始分析', size_hint_x=0.4)
        self.analyze_btn.bind(on_press=self.on_analyze)
        row1.add_widget(self.analyze_btn)
        root.add_widget(row1)

        # Row 2: Info
        self.info_label = Label(text='等待输入比赛ID...', size_hint_y=0.09, halign='left', valign='top',
                                text_size=(Window.width - 30, None))
        root.add_widget(self.info_label)

        # Row 3: Companies
        comp_box = BoxLayout(orientation='vertical', size_hint_y=0.22)
        comp_box.add_widget(Label(text='选择公司', size_hint_y=0.25, bold=True))
        comp_grid = GridLayout(cols=4, size_hint_y=0.5, spacing=4)
        self.company_cbs = {}
        for cid, cname in COMPANY_MAP.items():
            cb = CheckBox(active=(cid in DEFAULT_CHECKED_IDS))
            self.company_cbs[cid] = cb
            comp_grid.add_widget(cb)
            comp_grid.add_widget(Label(text=cname))
        comp_box.add_widget(comp_grid)
        btn_row = BoxLayout(orientation='horizontal', size_hint_y=0.25, spacing=10)
        select_all = Button(text='全选')
        select_all.bind(on_press=lambda x: self.toggle_companies(True))
        deselect_all = Button(text='全不选')
        deselect_all.bind(on_press=lambda x: self.toggle_companies(False))
        btn_row.add_widget(select_all)
        btn_row.add_widget(deselect_all)
        comp_box.add_widget(btn_row)
        root.add_widget(comp_box)

        # Row 4: Type + Timers
        row4 = BoxLayout(orientation='vertical', size_hint_y=0.12)
        type_row = BoxLayout(orientation='horizontal', size_hint_y=0.4, spacing=10)
        self.full_cb = CheckBox(active=True)
        self.half_cb = CheckBox(active=False)
        type_row.add_widget(Label(text='全场'))
        type_row.add_widget(self.full_cb)
        type_row.add_widget(Label(text='上半场'))
        type_row.add_widget(self.half_cb)
        type_row.add_widget(Label(text=''))
        row4.add_widget(type_row)

        timer_row = BoxLayout(orientation='horizontal', size_hint_y=0.6, spacing=6)
        self.timer_btns = {}
        for m in [15, 30, 45, 60, 90]:
            btn = Button(text=f'{m}min', disabled=True)
            btn.bind(on_press=lambda x, mm=m: self.start_timer(mm))
            self.timer_btns[m] = btn
            timer_row.add_widget(btn)
        row4.add_widget(timer_row)
        root.add_widget(row4)

        # Row 5: Log
        log_box = BoxLayout(orientation='vertical', size_hint_y=0.50)
        log_box.add_widget(Label(text='日志', size_hint_y=0.06, bold=True))
        sv = ScrollView(size_hint_y=0.94)
        self.log_label = Label(text='准备就绪', size_hint_y=None, halign='left', valign='top',
                               text_size=(Window.width - 30, None))
        self.log_label.bind(texture_size=lambda *x: setattr(self.log_label, 'height',
                            max(self.log_label.texture_size[1], sv.height)))
        sv.add_widget(self.log_label)
        log_box.add_widget(sv)
        root.add_widget(log_box)

        self._kickoff = None
        self._team_str = ''
        self._detail_str = ''

        return root

    def toggle_companies(self, state):
        for cb in self.company_cbs.values():
            cb.active = state

    def log(self, msg):
        def update(dt):
            old = self.log_label.text
            self.log_label.text = f'{old}\n[{datetime.now().strftime("%H:%M:%S")}] {msg}' if old != '准备就绪' else f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'
        Clock.schedule_once(update)

    def set_info(self, text):
        def update(dt):
            self.info_label.text = text
        Clock.schedule_once(update)

    def enable_timers(self, enable=True):
        def update(dt):
            for btn in self.timer_btns.values():
                btn.disabled = not enable
        Clock.schedule_once(update)

    def on_analyze(self, instance):
        mid = self.id_input.text.strip()
        if not mid.isdigit():
            self.log('错误：比赛ID必须是纯数字')
            return
        self.analyze_btn.disabled = True
        self.enable_timers(False)
        self._kickoff = None
        threading.Thread(target=self._run_analysis, args=(mid,), daemon=True).start()

    def _run_analysis(self, mid):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self._async_analysis(loop, mid)
        finally:
            loop.close()

    def _async_analysis(self, loop, mid):
        self.log('正在获取比赛信息...')
        async def task():
            async with aiohttp.ClientSession() as session:
                scraper = AsyncScraper(mid, self.log)
                home, away = await scraper.get_team_names(session)
                details = await scraper.get_match_details(session)
                self._team_str = f'{home} vs {away}'
                self._detail_str = details
                self.set_info(f'球队: {self._team_str}\n赛事: {details}')
                self.log(f'主客队: {self._team_str}')
                self.log(f'赛事信息: {details}')

                m = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', details)
                if m:
                    self._kickoff = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M')
                    self.log(f'开赛时间: {self._kickoff}')
                    self.enable_timers(True)
                    # Auto run -1 min
                    await self._do_scrape(session, mid, 1)
                else:
                    self.log('错误：无法识别开赛时间')
                self.analyze_btn.disabled = False
        loop.run_until_complete(task())

    async def _do_scrape(self, session, mid, minutes_before):
        cutoff = self._kickoff - timedelta(minutes=minutes_before)
        self.log(f'执行赛前{minutes_before}分钟抓取...')

        companies = [cid for cid, cb in self.company_cbs.items() if cb.active]
        include_half = self.half_cb.active

        scraper = AsyncScraper(mid, self.log)
        processor = DataProcessor(cutoff)

        save_dir = os.path.join(self._get_save_dir(), self._safe_name())
        os.makedirs(save_dir, exist_ok=True)

        tasks = []
        for cid in companies:
            cname = COMPANY_MAP.get(cid, cid)
            tasks.append(scraper.get_company_odds(session, cid, cname, False))
            if include_half:
                tasks.append(scraper.get_company_odds(session, cid, cname, True))

        if not tasks:
            self.log('未选择任何公司')
            return

        results = [r for r in await asyncio.gather(*tasks) if r]
        self.log(f'成功抓取 {len(results)} 个赔率表')

        results.sort(key=lambda x: (x['company'], 0 if '全场' in x['type'] else 1))

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        fname = f"{self._safe_name()}-{minutes_before}-{ts}.md"

        md = [f'# {self._team_str}', f'## {self._detail_str}',
              f'**截止**: {cutoff.strftime("%Y-%m-%d %H:%M")} | **执行**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n---']
        for item in results:
            df = processor.process(item['df'])
            if not df.empty:
                md.append(f'## {item["company"]} - {item["type"]}')
                md.append(processor.to_md(df))
                md.append('\n---\n')

        path = os.path.join(save_dir, fname)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))
        self.log(f'已保存: {path}')

    def start_timer(self, minutes):
        if not self._kickoff:
            self.log('错误：请先获取比赛信息')
            return
        target = self._kickoff - timedelta(minutes=minutes)
        delay = (target - datetime.now()).total_seconds()
        if delay < 0:
            self.log(f'倒计时-{minutes}分钟已过时')
            return
        self.log(f'已设置倒计时-{minutes}分钟，将在{target.strftime("%H:%M")}执行')
        self.timer_btns[minutes].disabled = True
        self.timer_btns[minutes].text = f'{minutes}min✓'
        threading.Thread(target=self._wait_and_scrape, args=(minutes, delay), daemon=True).start()

    def _wait_and_scrape(self, minutes, delay):
        import time as _time
        _time.sleep(delay)
        self._kickoff = self._kickoff  # use cached
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def task():
            async with aiohttp.ClientSession() as session:
                await self._do_scrape(session, self.id_input.text.strip(), minutes)
        loop.run_until_complete(task())
        loop.close()

    def _get_save_dir(self):
        if platform == 'android':
            from jnius import autoclass
            Environment = autoclass('android.os.Environment')
            return Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).getAbsolutePath()
        return os.path.join(os.path.expanduser('~'), '赔率数据')

    def _safe_name(self):
        return re.sub(r'[\\/:*?"<>|]', '_', self._team_str)

if __name__ == '__main__':
    OddsApp().run()
