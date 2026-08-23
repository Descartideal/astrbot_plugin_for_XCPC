"""洛谷用户和比赛图片卡片。"""

import datetime
import html
import time

from .models import LuoguContestResult, LuoguUserProfile


BASE_STYLE = """
* { box-sizing: border-box; }
body { margin: 0; padding: 28px; background: #eef6f1; font-family: -apple-system,
  BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; color: #21322a; }
.card { width: 880px; margin: 0 auto; overflow: hidden; border-radius: 28px;
  background: #fff; border: 1px solid #dce9e1; box-shadow: 0 20px 52px rgba(28, 91, 55, .13); }
.head { padding: 30px 36px; color: #fff; background: linear-gradient(135deg, #2f9e62, #167a4a); }
.brand { font-size: 18px; font-weight: 800; letter-spacing: 1px; opacity: .9; }
.title { margin-top: 8px; font-size: 34px; line-height: 1.2; font-weight: 850; overflow-wrap: anywhere; }
.content { padding: 28px 36px 32px; }
.muted { color: #718078; }
.footer { padding: 16px 36px 22px; color: #8b9b92; font-size: 14px; display: flex;
  justify-content: space-between; border-top: 1px solid #edf3ef; }
"""


class LuoguUserCardRenderer:
    TEMPLATE = """
<!doctype html><html><head><meta charset="utf-8"><style>""" + BASE_STYLE + """
.profile { display: grid; grid-template-columns: 132px 1fr; gap: 26px; align-items: center; }
.avatar { width: 132px; height: 132px; border-radius: 25px; object-fit: cover; background: #edf3ef;
  border: 5px solid rgba(255,255,255,.65); box-shadow: 0 10px 28px rgba(0,0,0,.15); }
.uid { margin-top: 8px; font-size: 17px; opacity: .88; }
.badge { display: inline-block; margin-top: 11px; padding: 6px 12px; border-radius: 999px;
  background: rgba(255,255,255,.18); font-size: 15px; font-weight: 750; }
.slogan { margin-top: 16px; color: rgba(255,255,255,.9); font-size: 17px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.stat { min-height: 102px; padding: 18px; border-radius: 18px; background: #f5faf7; border: 1px solid #e2eee7; }
.label { color: #708078; font-size: 15px; font-weight: 700; }
.value { margin-top: 9px; color: #176c43; font-size: 26px; font-weight: 850; overflow-wrap: anywhere; }
.note { margin-top: 18px; padding: 14px 17px; border-radius: 14px; background: #fff8e8;
  color: #7e6425; font-size: 15px; }
</style></head><body><div class="card">
<div class="head"><div class="profile">
{% if avatar %}<img class="avatar" src="{{ avatar }}">{% else %}<div class="avatar"></div>{% endif %}
<div><div class="brand">LUOGU · 用户信息</div><div class="title">{{ name }}</div>
<div class="uid">UID {{ uid }}</div>{% if badge %}<span class="badge">{{ badge }}</span>{% endif %}
{% if slogan %}<div class="slogan">{{ slogan }}</div>{% endif %}</div></div></div>
<div class="content"><div class="stats">
<div class="stat"><div class="label">咕值（Rating）</div><div class="value">{{ gu_value }}</div></div>
<div class="stat"><div class="label">全站排名</div><div class="value">{{ ranking }}</div></div>
<div class="stat"><div class="label">社区贡献</div><div class="value">{{ contribution }}</div></div>
<div class="stat"><div class="label">关注</div><div class="value">{{ following }}</div></div>
<div class="stat"><div class="label">粉丝</div><div class="value">{{ followers }}</div></div>
<div class="stat"><div class="label">通过题目</div><div class="value">{{ passed }}</div></div>
</div><div class="note">最近在线：洛谷官网未公开此字段　·　咕值更新时间：{{ gu_updated }}</div></div>
<div class="footer"><span>{{ generated_at }}</span><span>github.com/Descartideal/astrbot_plugin_for_XCPC</span></div>
</div></body></html>"""

    @staticmethod
    def _display(value) -> str:
        return "未知" if value is None else str(value)

    def build(self, profile: LuoguUserProfile) -> tuple[str, dict, dict]:
        gu_updated = "未知"
        if profile.gu_updated_at is not None:
            gu_updated = datetime.datetime.fromtimestamp(profile.gu_updated_at).strftime("%Y-%m-%d %H:%M")
        data = {
            "avatar": html.escape(profile.avatar or "", quote=True),
            "name": html.escape(profile.name, quote=True),
            "uid": profile.uid,
            "badge": html.escape(profile.badge or "", quote=True),
            "slogan": html.escape(profile.slogan or "", quote=True),
            "gu_value": self._display(profile.gu_value),
            "ranking": self._display(profile.ranking),
            "contribution": self._display(profile.contribution),
            "following": self._display(profile.following_count),
            "followers": self._display(profile.follower_count),
            "passed": self._display(profile.passed_problem_count),
            "gu_updated": gu_updated,
            "generated_at": datetime.datetime.now().strftime("生成时间：%Y-%m-%d %H:%M:%S"),
        }
        return self.TEMPLATE, data, {
            "full_page": True,
            "type": "png",
            "animations": "disabled",
            "viewport_width": 936,
            "viewport_height": 720,
            "device_scale_factor_level": "high",
            "timeout": 30000,
        }


class LuoguContestCardRenderer:
    TEMPLATE = """
<!doctype html><html><head><meta charset="utf-8"><style>""" + BASE_STYLE + """
.list { display: grid; gap: 14px; }
.item { display: grid; grid-template-columns: 62px 1fr 190px; gap: 16px; align-items: center;
  padding: 17px; border-radius: 18px; background: #f6faf7; border: 1px solid #e1ede6; }
.index { width: 52px; height: 52px; display: flex; align-items: center; justify-content: center;
  border-radius: 15px; background: #258b55; color: #fff; font-size: 23px; font-weight: 850; }
.name { font-size: 20px; line-height: 1.25; font-weight: 800; overflow-wrap: anywhere; }
.meta { margin-top: 9px; color: #6e7c74; font-size: 14px; }
.side { text-align: right; }
.phase { color: #177044; font-size: 17px; font-weight: 850; }
.start { margin-top: 8px; color: #52635a; font-size: 15px; }
</style></head><body><div class="card">
<div class="head"><div class="brand">LUOGU · 比赛日历</div><div class="title">近期洛谷比赛</div></div>
<div class="content"><div class="list">{% for contest in contests %}<div class="item">
<div class="index">{{ contest.index }}</div><div><div class="name">{{ contest.name }}</div>
<div class="meta">ID {{ contest.id }}　·　{{ contest.host }}　·　{{ contest.duration }}</div></div>
<div class="side"><div class="phase">{{ contest.phase }}</div><div class="start">{{ contest.start }}</div>
<div class="meta">{{ contest.before_start }}</div></div></div>{% endfor %}</div></div>
<div class="footer"><span>{{ generated_at }}</span><span>github.com/Descartideal/astrbot_plugin_for_XCPC</span></div>
</div></body></html>"""

    @staticmethod
    def _duration(seconds: int) -> str:
        hours, remainder = divmod(max(0, seconds), 3600)
        minutes = remainder // 60
        return f"{hours} 小时 {minutes} 分钟"

    @staticmethod
    def _before(start_time: int, now: int) -> str:
        delta = start_time - now
        if delta <= 0:
            return "已经开始"
        days, remainder = divmod(delta, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        return f"距开赛 {days} 天 {hours} 小时" if days else f"距开赛 {hours} 小时 {minutes} 分钟"

    def build(self, result: LuoguContestResult) -> tuple[str, dict, dict]:
        now = int(time.time())
        contests = []
        for index, contest in enumerate(result.contests or [], 1):
            contests.append(
                {
                    "index": index,
                    "id": contest.id,
                    "name": html.escape(contest.name, quote=True),
                    "host": html.escape(contest.host_name or "未知主办方", quote=True),
                    "duration": self._duration(contest.end_time - contest.start_time),
                    "phase": "进行中" if contest.start_time <= now <= contest.end_time else "未开始",
                    "start": datetime.datetime.fromtimestamp(contest.start_time).strftime("%Y-%m-%d %H:%M"),
                    "before_start": self._before(contest.start_time, now),
                }
            )
        min_height = max(620, 230 + len(contests) * 115)
        return self.TEMPLATE, {
            "contests": contests,
            "generated_at": datetime.datetime.now().strftime("生成时间：%Y-%m-%d %H:%M:%S"),
        }, {
            "full_page": True,
            "type": "png",
            "animations": "disabled",
            "viewport_width": 936,
            "viewport_height": min_height,
            "device_scale_factor_level": "high",
            "timeout": 30000,
        }
