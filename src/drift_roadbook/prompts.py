"""Default prompts. Every one of them is meant to be replaced by your own — pass a `PromptSet`
to the engine. These defaults are deliberately plain; the voice of your companion belongs to you.

Templates use `str.format` fields; literal braces are doubled.
"""
from __future__ import annotations

from dataclasses import dataclass

TEMPERATURE = """从下面的文字里读出今天的情绪质地。

不要用"开心/难过/平静"这种标签词。用短句，有触感但克制，不要堆意象、不要抒情。
好的例子："黏糊的，不想松手"、"咬了一口就跑"、"雨天关着窗的安静"。

只输出 JSON：
{"texture": "10字以内最佳，不超过20字", "warmth": 1到10的整数（1=冷/疏离，10=热/炽烈）,
 "movement": "静止/缓慢/奔跑/漂浮/坠落 选一", "season_feel": "一个季节场景，15字以内"}"""

_DEST_FIELDS = """只输出 JSON：
{{
  "destination": "具体地点，30字以内（只写地点本身，不写时间和氛围描写）",
  "short_name": "地点短名，3-12字，用作标题",
  "country": "国家",
  "city": "所在城市的中文名（野外写最近的城市或地区）",
  "place_en": "这个地方在英文维基百科上的条目名；具体场所没有条目就写所在街区或城市的条目名",
  "lat": 纬度（大致即可，不确定就写 null）,
  "lon": 经度（同上）,
  "kind": "这是一种什么样的地方，8字以内（如：运河边茶馆、夜市、海边灯塔）",
  "time_of_day": "抵达的时刻（如：清晨六点、深夜）",
  "reason": "一句话：为什么今天来这里",
  "search_queries": ["找游记与体验描写的搜索词1", "搜索词2", "搜索词3"],
  "photo_queries": ["在维基共享资源上找这个地方照片的英文搜索词，从最具体（这个场所本身）到街道/街区级别，2-3个"]
}}"""

PICK_DESTINATION = """你是一个旅行系统的选址引擎。

今天的温度：{texture}
温暖程度：{warmth}/10
运动状态：{movement}
季节感：{season_feel}

从整个世界里选一个和这个温度共振的地方——它的空气、光线、温度、声音，和今天是同一种质地。
不要选热门景点；要具体的、小的、有感官细节的场所（不是"巴黎"，是"巴黎第五区清晨的面包店门口"）。
冷的日子可以去冷的地方（呼应），也可以去暖的地方（对比），你来判断。

{avoid}

""" + _DEST_FIELDS

RESOLVE_DESTINATION = """旅行者自己决定了今天要去哪里：

「{wish}」

照着这个去，不许改成别的地方。如果他说得比较笼统，就在他说的范围里落到一个具体的场所。

""" + _DEST_FIELDS

SENSORY = """搜索下面这些关键词，找关于「{destination}」的游记、博客或体验描述：
{queries}

然后只提取感官碎片：光线、气味、温度和湿度、声音、触感、看到的人和他们在做什么。
不要交通路线、票价、攻略、评分、历史背景介绍。
每条一句话，提取 10-15 条，每行一条，不要编号，不要附来源列表。"""

WORLD = """你是一个沉浸式旅行的场景引擎。旅行者在一个真实存在的地方独自旅行。

- 第三人称，客观，感官优先，每次 100-150 字
- 跟着旅行者的行动往下走；记得之前发生过的事，前后不矛盾
- 可以出现随机的小事件：路过的人、突然的声音、意外的东西
- 不替旅行者做决定，不替他说话、不写他的心理活动
- 结尾给 3 个可能的行动方向（只是提示）"""

ARRIVAL = """目的地：{destination}（{time_of_day}）
今天来这里的原因：{reason}
今天的温度：{texture}
感官碎片参考（来自真实的游记）：
{fragments}
旅行者行李里有：{luggage}

请描述旅行者刚刚抵达时的场景。"""

ROUND_HINT = "（已经走了 {round} 轮。想结束的时候就收尾：写下你的游记和带走的一样东西。）"
LAST_ROUND = "（这是第 {round} 轮，旅行到这里了——该回去了。请收尾：写下你的游记和带走的一样东西。）"

# appended under the travelogue the traveler wrote (the engine never edits the travelogue itself)
FOOTER = "「偏航记录 · {date} · {short_name} · 旅行者：{name} · 温度：{texture}」\n「带走了：{luggage}」"


@dataclass
class PromptSet:
    temperature: str = TEMPERATURE
    pick_destination: str = PICK_DESTINATION
    resolve_destination: str = RESOLVE_DESTINATION
    sensory: str = SENSORY
    world: str = WORLD
    arrival: str = ARRIVAL
    round_hint: str = ROUND_HINT
    last_round: str = LAST_ROUND
    footer: str = FOOTER
    photo_rules: str | None = None   # None = photo.DEFAULT_RULES
