#!/usr/bin/env python3
# fastoddsv6.py - CLI Version
# 极速赔率抓取工具 (作者微信：imazhuazi)
# 命令行版，适配 Termux/Android 及无 GUI 环境
# -------------------------------------------------
import sys
import os
import asyncio
import aiohttp
import pandas as pd
from lxml import etree
import re
import argparse
from datetime import datetime, timedelta

# -------------------- 异步策略 --------------------
if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# -------------------- 常量定义 --------------------
COMPANY_MAP = {
    '3': '皇冠', '8': 'Bet365', '9': '威廉希尔',
    '31': '利记', '42': '188bet', '47': '平博',
    '1': '澳门', '4': '立博'
}
DEFAULT_CHECKED_IDS = ['1', '3', '8', '9', '31', '47']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
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

# -------------------- 日志输出 --------------------
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    clean = re.sub(r'[✅❌🔍🚀🕒⏳⚠️▶️✔️]', '', msg).strip()
    print(f"[{ts}] {msg}")

# -------------------- 辅助功能 --------------------
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
                dt_str = ""
                if fmt == '%m-%d %H:%M':
                    month, day, time_str = match.groups()
                    current_year = datetime.now().year
                    dt_str = f"{current_year}-{month}-{day} {time_str}"
                    parse_fmt = '%Y-%m-%d %H:%M'
                elif fmt == '%H:%M':
                    now = datetime.now()
                    dt_str = f"{now.year}-{now.month}-{now.day} {match.group(1)}"
                    parse_fmt = '%Y-%m-%d %H:%M'
                elif fmt == '%Y-%m-%d %H:%M':
                    year_month_day, hour_minute = match.groups()
                    dt_str = f"{year_month_day} {hour_minute}"
                    parse_fmt = '%Y-%m-%d %H:%M'
                dt = datetime.strptime(dt_str, parse_fmt)
                return dt.strftime('%m-%d %H:%M')
    except Exception:
        return raw_time
    return raw_time

def clean_score(score_str):
    if not score_str:
        return ''
    date_score = re.match(r'(\d{1,2})月(\d{1,2})日', score_str)
    if date_score:
        return f"{date_score.group(1)}-{date_score.group(2)}"
    normal_score = re.match(r'(\d+)[:-](\d+)', score_str)
    if normal_score:
        return f"{normal_score.group(1)}-{normal_score.group(2)}"
    return ''

def convert_handicap_value(handicap_str, handicap_type):
    if handicap_type == 'asian':
        return ASIAN_HANDICAP_MAP.get(handicap_str, handicap_str)
    elif handicap_type == 'overunder':
        return OVER_UNDER_MAP.get(handicap_str, handicap_str)
    return handicap_str

def calc_2way_probs(o1_str, o2_str):
    try:
        d1 = float(o1_str) + 1
        d2 = float(o2_str) + 1
        if d1 <= 1 or d2 <= 1:
            return "", "", ""
        p1 = 1 / d1
        p2 = 1 / d2
        margin = p1 + p2
        if margin == 0:
            return "", "", ""
        ret = (1 / margin) * 100
        true_p1 = (p1 / margin) * 100
        true_p2 = (p2 / margin) * 100
        return f"{ret:.1f}%", f"{true_p1:.1f}%", f"{true_p2:.1f}%"
    except (ValueError, TypeError, ZeroDivisionError):
        return "", "", ""

def calc_3way_probs(o1_str, o2_str, o3_str):
    try:
        d1 = float(o1_str)
        d2 = float(o2_str)
        d3 = float(o3_str)
        if d1 == 0 or d2 == 0 or d3 == 0:
            return "", "", "", ""
        p1 = 1 / d1
        p2 = 1 / d2
        p3 = 1 / d3
        margin = p1 + p2 + p3
        if margin == 0:
            return "", "", "", ""
        ret = (1 / margin) * 100
        true_p1 = (p1 / margin) * 100
        true_p2 = (p2 / margin) * 100
        true_p3 = (p3 / margin) * 100
        return f"{ret:.1f}%", f"{true_p1:.1f}%", f"{true_p2:.1f}%", f"{true_p3:.1f}%"
    except (ValueError, TypeError, ZeroDivisionError):
        return "", "", "", ""

# -------------------- 异步爬虫类 --------------------
class AsyncScraper:
    def __init__(self, match_id, log_func):
        self.match_id = match_id
        self.base_url = "https://live.nowscore.com/odds/3in1Odds.aspx"
        self.log = log_func

    async def fetch_text(self, session, url):
        for attempt in range(3):
            try:
                async with session.get(url, headers=HEADERS, timeout=15) as response:
                    response.raise_for_status()
                    return await response.text(encoding='utf-8')
            except Exception as e:
                if attempt == 2:
                    self.log(f"请求失败 {url}: {e}")
                    return None
                await asyncio.sleep(1)

    async def get_team_names(self, session):
        url = f"https://live.nowscore.com/Odds/count/goalCount.aspx?t=1&sid={self.match_id}&cid=1"
        html = await self.fetch_text(session, url)
        if not html:
            return "未知", "未知"
        try:
            tree = etree.HTML(html)
            title_element = tree.xpath('/html/body/table[1]/tbody/tr[1]/td/text()')
            if title_element:
                full_title = title_element[0].strip()
                match = re.search(r'(.+?)\s+vs\s+(.+?)(?:\s+\[.+\])?$', full_title)
                if match:
                    home = match.group(1).split(':')[-1].strip() if ':' in match.group(1) else match.group(1).strip()
                    away = match.group(2).strip()
                    return home, away
        except Exception:
            pass
        return "未知", "未知"

    async def get_match_details(self, session):
        url = f"{self.base_url}?companyid=8&id={self.match_id}"
        html = await self.fetch_text(session, url)
        if not html:
            return "未知"
        try:
            tree = etree.HTML(html)
            xpaths_to_try = ['//div[@class="lgtime"]', '//*[@id="MatchIntro"]', '//*[@id="headVs"]/tbody/tr[2]/td[1]']
            for xpath in xpaths_to_try:
                elements = tree.xpath(xpath)
                if elements:
                    info_parts = [text.strip() for text in elements[0].xpath('.//text()') if text.strip()]
                    return " ".join(info_parts)
        except Exception:
            pass
        return "未知"

    def extract_table(self, tree, xpath, handicap_type=None):
        data = []
        tables = tree.xpath(xpath)
        if not tables:
            return data
        table = tables[0]
        for tr in table.xpath('.//tr')[1:]:
            raw_cols = [td.xpath('string(.)').strip() for td in tr.xpath('./td[position() >= 2 and position() <= 7]')]
            if len(raw_cols) < 6:
                continue
            if any('封' in col for col in raw_cols):
                continue
            raw_cols[0] = clean_score(raw_cols[0])
            raw_cols[4] = normalize_time(raw_cols[4])
            if handicap_type and len(raw_cols) > 2:
                raw_cols[2] = convert_handicap_value(raw_cols[2], handicap_type)
            data.append(raw_cols[:6])
        return data

    async def get_company_odds(self, session, company_id, company_name, is_half):
        suffix = "&t=1" if is_half else ""
        url = f"{self.base_url}?companyid={company_id}&id={self.match_id}{suffix}"
        html = await self.fetch_text(session, url)
        if not html:
            return None
        tree = etree.HTML(html)
        asian = self.extract_table(tree, '//*[@id="oddsmain"]/div[3]', 'asian')
        overunder = self.extract_table(tree, '//*[@id="oddsmain"]/div[4]', 'overunder')
        winloss = self.extract_table(tree, '//*[@id="oddsmain"]/div[5]')
        max_rows = max(len(asian), len(overunder), len(winloss))
        if max_rows == 0:
            return None
        merged_data = []
        for i in range(max_rows):
            row = []
            if i < len(asian):
                a_row = asian[i]
                ret, p1, p2 = calc_2way_probs(a_row[1], a_row[3])
                new_a_row = a_row[:4] + [ret, p1, p2] + a_row[4:]
                row.extend(new_a_row)
            else:
                row.extend([''] * 9)
            if i < len(overunder):
                o_row = overunder[i]
                ret, p1, p2 = calc_2way_probs(o_row[1], o_row[3])
                new_o_row = o_row[:4] + [ret, p1, p2] + o_row[4:]
                row.extend(new_o_row)
            else:
                row.extend([''] * 9)
            if i < len(winloss):
                w_row = winloss[i]
                ret, p1, p2, p3 = calc_3way_probs(w_row[1], w_row[2], w_row[3])
                new_w_row = w_row[:4] + [ret, p1, p2, p3] + w_row[4:]
                row.extend(new_w_row)
            else:
                row.extend([''] * 10)
            merged_data.append(row)
        headers = []
        headers.extend(['亚洲让球_比分', '亚洲让球_主', '亚洲让球_盘口', '亚洲让球_客', '亚洲让球_返还率', '亚洲让球_主概率', '亚洲让球_客概率', '亚洲让球_变化时间', '亚洲让球_状态'])
        headers.extend(['大小球_比分', '大小球_大于', '大小球_盘口', '大小球_小于', '大小球_返还率', '大小球_大概率', '大小球_小概率', '大小球_变化时间', '大小球_状态'])
        headers.extend(['胜平负_比分', '胜平负_胜赔率', '胜平负_平赔率', '胜平负_负赔率', '胜平负_返还率', '胜平负_胜概率', '胜平负_平概率', '胜平负_负概率', '胜平负_变化时间', '胜平负_状态'])
        df = pd.DataFrame(merged_data, columns=headers)
        return {'company': company_name, 'type': '上半场赔率表' if is_half else '全场赔率表', 'df': df}

# -------------------- 数据处理器 --------------------
class DataProcessor:
    def __init__(self, cutoff_time):
        self.cutoff_datetime = cutoff_time
        self.categories = ['亚洲让球', '大小球', '胜平负']

    def process(self, df):
        if df.empty:
            return df
        df_filtered = df.copy()
        if self.cutoff_datetime:
            for cat in self.categories:
                time_col = f'{cat}_变化时间'
                if time_col not in df.columns:
                    continue
                for idx, row in df_filtered.iterrows():
                    time_str = str(row[time_col])
                    if not time_str:
                        continue
                    try:
                        row_dt = datetime.strptime(f"{self.cutoff_datetime.year}-{time_str}", '%Y-%m-%d %H:%M')
                        if row_dt > self.cutoff_datetime:
                            for c in df.columns:
                                if c.startswith(cat):
                                    df_filtered.at[idx, c] = ''
                    except ValueError:
                        continue
        return self.align_to_top(df_filtered)

    def align_to_top(self, df):
        all_cols = df.columns.tolist()
        cat_data = {cat: {col: [] for col in all_cols if col.startswith(cat)} for cat in self.categories}
        for _, row in df.iterrows():
            for cat in self.categories:
                time_col = f'{cat}_变化时间'
                if time_col in df.columns and str(row[time_col]).strip() != '':
                    for col in all_cols:
                        if col.startswith(cat):
                            cat_data[cat][col].append(row[col])
        max_rows = 0
        for cat in self.categories:
            if cat_data[cat]:
                first_col = next(iter(cat_data[cat].values()), [])
                max_rows = max(max_rows, len(first_col))
        if max_rows == 0:
            return pd.DataFrame(columns=all_cols)
        final_data = {}
        for cat in self.categories:
            for col in all_cols:
                if col.startswith(cat):
                    col_values = cat_data[cat].get(col, [])
                    final_data[col] = col_values + [''] * (max_rows - len(col_values))
        return pd.DataFrame(final_data, columns=df.columns)

    def df_to_markdown(self, df):
        if df.empty:
            return ""
        fmt_df = df.astype(str).replace('nan', '').replace('None', '')
        for col in fmt_df.columns:
            fmt_df[col] = fmt_df[col].apply(lambda x: x.replace('|', '∣').strip())
        headers = fmt_df.columns.tolist()
        lines = []
        lines.append('| ' + ' | '.join(headers) + ' |')
        lines.append('| ' + ' | '.join(['---'] * len(headers)) + ' |')
        for _, row in fmt_df.iterrows():
            lines.append('| ' + ' | '.join(row.tolist()) + ' |')
        return '\n'.join(lines)

# -------------------- 核心抓取逻辑 --------------------
async def async_fetch_and_save(match_id, companies, include_half, kickoff_datetime,
                                minutes_before, output_dir, team_names_str, details,
                                session, log_func):
    exec_time = datetime.now()
    cutoff_time = kickoff_datetime - timedelta(minutes=minutes_before)
    log_func(f"执行抓取: 截止={cutoff_time.strftime('%m-%d %H:%M')}, 赛前{minutes_before}分钟")

    scraper = AsyncScraper(match_id, log_func)
    processor = DataProcessor(cutoff_time)

    tasks = []
    for cid in companies:
        cname = COMPANY_MAP.get(cid, cid)
        tasks.append(scraper.get_company_odds(session, cid, cname, is_half=False))
        if include_half:
            tasks.append(scraper.get_company_odds(session, cid, cname, is_half=True))

    if not tasks:
        log_func("未选择公司")
        return

    results = await asyncio.gather(*tasks)
    odds_results = [r for r in results if r is not None]
    log_func(f"成功抓取 {len(odds_results)} 个赔率表")

    sanitized_team_names = re.sub(r'[\\/:*?"<>|]', '_', team_names_str)
    if kickoff_datetime:
        folder_name = f"{kickoff_datetime.strftime('%Y-%m-%d')}_{sanitized_team_names}"
    else:
        folder_name = sanitized_team_names
    folder_name = re.sub(r'[\\/:*?"<>|]', '_', folder_name)
    save_dir = os.path.join(output_dir, folder_name)
    os.makedirs(save_dir, exist_ok=True)

    timestamp = exec_time.strftime('%Y%m%d_%H%M%S')
    base_filename = f"{sanitized_team_names}-{minutes_before}-{timestamp}"

    md_content = []
    md_content.append(f"# {team_names_str}")
    md_content.append(f"## {details}")
    md_content.append(
        f"**抓取节点**: 开赛前 {minutes_before} 分钟 | **筛选截止时间**: {cutoff_time.strftime('%Y-%m-%d %H:%M')}"
    )
    md_content.append(f"**执行时间**: {exec_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    md_content.append("---")

    odds_results.sort(key=lambda x: (x['company'], 0 if '全场' in x['type'] else 1))
    for item in odds_results:
        company = item['company']
        o_type = item['type']
        df = item['df']
        processed_df = processor.process(df)
        if not processed_df.empty:
            md_table = processor.df_to_markdown(processed_df)
            md_content.append(f"## {company} - {o_type}")
            md_content.append(md_table)
            md_content.append("\n---\n")

    md_path = os.path.join(save_dir, f"{base_filename}.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_content))
    log_func(f"已保存: {md_path}")

# -------------------- 主入口 --------------------
async def main():
    parser = argparse.ArgumentParser(
        description='极速赔率抓取工具 - 命令行版',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python v8.py 123456\n"
            "  python v8.py 123456 --companies 1,3,8\n"
            "  python v8.py 123456 --half --schedule 15,30,45\n"
            "  python v8.py 123456 --minutes-before 5\n"
        )
    )
    parser.add_argument('match_id', help='比赛ID')
    parser.add_argument('--companies', default=','.join(DEFAULT_CHECKED_IDS),
                        help=f'公司ID，逗号分隔 (默认: {",".join(DEFAULT_CHECKED_IDS)})')
    parser.add_argument('--half', action='store_true', help='同时抓取上半场赔率')
    parser.add_argument('--minutes-before', type=int, default=1,
                        help='筛选截止：赛前N分钟 (默认 1)')
    parser.add_argument('--schedule', default='',
                        help='额外定时任务，逗号分隔 (如 15,30,45)')
    default_out = os.path.join(os.path.expanduser('~'), '赔率数据')
    parser.add_argument('--output', default=default_out, help=f'输出目录 (默认: {default_out})')
    args = parser.parse_args()

    match_id = args.match_id.strip()
    if not match_id.isdigit():
        print("错误：比赛ID必须是纯数字")
        sys.exit(1)

    companies = [c.strip() for c in args.companies.split(',') if c.strip()]
    include_half = args.half
    minutes_before = args.minutes_before
    schedule_list = [int(m.strip()) for m in args.schedule.split(',') if m.strip()]
    output_dir = args.output

    log(f"比赛ID: {match_id}")
    log(f"公司: {', '.join(COMPANY_MAP.get(c, c) for c in companies)}")
    log(f"场次: {'全场+上半场' if include_half else '仅全场'}")

    async with aiohttp.ClientSession() as session:
        scraper = AsyncScraper(match_id, log)
        log("获取比赛基本信息...")
        home, away = await scraper.get_team_names(session)
        details = await scraper.get_match_details(session)
        team_str = f"{home} vs {away}"
        log(f"主客队: {team_str}")
        log(f"赛事信息: {details}")

        kickoff_datetime = None
        time_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', details)
        if time_match:
            kickoff_datetime = datetime.strptime(time_match.group(1), '%Y-%m-%d %H:%M')
            log(f"开赛时间: {kickoff_datetime}")
        else:
            log("错误：无法识别开赛时间")
            sys.exit(1)

        all_tasks = list(set([minutes_before] + schedule_list))
        all_tasks.sort()

        for mb in all_tasks:
            target_time = kickoff_datetime - timedelta(minutes=mb)
            now = datetime.now()
            delay = (target_time - now).total_seconds()

            if delay > 10:
                log(f"等待 {int(delay)} 秒后执行倒计时-{mb}分钟任务...")
                await asyncio.sleep(delay)
            elif delay < -120:
                log(f"跳过倒计时-{mb}分钟任务，已过时 ({target_time})")
                continue

            await async_fetch_and_save(
                match_id, companies, include_half, kickoff_datetime,
                mb, output_dir, team_str, details, session, log
            )

    log("全部任务完成")

if __name__ == "__main__":
    asyncio.run(main())
