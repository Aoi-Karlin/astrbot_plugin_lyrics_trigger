import os
import json
import re
import aiohttp
import asyncio
from difflib import SequenceMatcher
from typing import Dict, Any, Optional, List

from astrbot.api import star, logger
from astrbot.api.event import AstrMessageEvent, filter, event_handler  # 关键：显式导入 event_handler
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain


# --- API Wrapper (仿照参考代码风格) ---
class NeteaseLyricsAPI:
    """
    简易封装网易云 API，专注于搜索和歌词获取
    """

    def __init__(self, api_url: str, session: aiohttp.ClientSession):
        self.base_url = api_url.rstrip("/")
        self.session = session

    async def search_song_id(self, keyword: str) -> Optional[int]:
        """搜索歌曲返回第一首的 ID"""
        # 使用 cloudsearch 接口通常比 search 更准
        url = f"{self.base_url}/cloudsearch"
        params = {"keywords": keyword, "limit": "1", "type": "1"}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    songs = data.get("result", {}).get("songs", [])
                    if songs:
                        return songs[0]["id"]
        except Exception as e:
            logger.error(f"Lyrics Plugin: Search failed - {e}")
        return None

    async def get_lyrics(self, song_id: int) -> List[str]:
        """获取歌词并解析为纯文本列表"""
        url = f"{self.base_url}/lyric"
        params = {"id": str(song_id)}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    lrc_text = data.get("lrc", {}).get("lyric", "")
                    return self._parse_lrc(lrc_text)
        except Exception as e:
            logger.error(f"Lyrics Plugin: Get lyrics failed - {e}")
        return []

    def _parse_lrc(self, lrc_text: str) -> List[str]:
        """去除时间轴 [00:00.00]，只保留歌词文本"""
        lines = []
        # 正则匹配时间标签
        regex = re.compile(r'\[.*?\]')
        for line in lrc_text.split('\n'):
            # 替换掉时间标签
            clean_line = regex.sub('', line).strip()
            # 过滤掉元数据（如 作词：xxx）和空行
            if clean_line and not clean_line.startswith(("作词", "作曲", "编曲")):
                lines.append(clean_line)
        return lines


# --- Main Plugin Class ---
@star.register("netease_lyrics_join", "YourName", "网易云歌词接龙", "1.0.0")
class LyricsJoinPlugin(star.Star):
    def __init__(self, context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}
        # 默认配置
        self.config.setdefault("api_url", "http://localhost:3000")
        self.config.setdefault("similarity_threshold", 0.75)  # 相似度阈值
        self.config.setdefault("min_length", 5)  # 最小触发长度
        self.config.setdefault("enable_cache", True)

        self.cache_file = os.path.join(os.path.dirname(__file__), "lyric_cache.json")
        self.lyric_cache: Dict[str, List[str]] = {}

        # 占位符
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.api: Optional[NeteaseLyricsAPI] = None

    # --- Lifecycle Hooks (生命周期管理) ---
    async def initialize(self):
        """插件加载时运行：初始化 Session 和加载缓存"""
        self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        self.api = NeteaseLyricsAPI(self.config["api_url"], self.http_session)
        self.lyric_cache = self._load_cache()
        logger.info(f"Lyrics Plugin: Initialized. Loaded {len(self.lyric_cache)} songs in cache.")

    async def terminate(self):
        """插件卸载时运行：关闭 Session"""
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        # 退出前保存一次缓存
        self._save_cache()
        logger.info("Lyrics Plugin: Terminated.")

    # --- Cache Management ---
    def _load_cache(self) -> Dict[str, List[str]]:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Lyrics Plugin: Load cache failed - {e}")
                return {}
        return {}

    def _save_cache(self):
        if not self.config["enable_cache"]:
            return
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.lyric_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Lyrics Plugin: Save cache failed - {e}")

    # --- Logic ---
    def _find_next_line(self, user_text: str, lyrics_list: List[str]) -> Optional[str]:
        """在歌词列表中查找匹配的下一句"""
        threshold = self.config["similarity_threshold"]
        for i, line in enumerate(lyrics_list):
            # 简单的包含关系检查 (提速)
            if len(user_text) > 2 and user_text in line:
                ratio = 1.0
            else:
                # 模糊匹配
                ratio = SequenceMatcher(None, user_text, line).ratio()

            if ratio >= threshold:
                # 找到匹配，返回下一句
                if i + 1 < len(lyrics_list):
                    return lyrics_list[i + 1]
        return None

    # --- Event Handlers ---

    # 使用 event_handler 监听所有消息
    # 注意：这里不使用 filter.command，因为我们要监听自然语言
    @event_handler(AstrMessageEvent)
    async def on_message(self, event: AstrMessageEvent):
        message_obj = event.message_obj

        # 1. 基础过滤
        if not message_obj.text:
            return

        text = message_obj.text.strip()

        # 忽略过短的消息
        if len(text) < self.config["min_length"]:
            return

        # 忽略指令（以 / ! 。 . 开头的消息通常不是歌词）
        if text.startswith(('/', '!', '！', '.', '。')):
            return

        # 2. 先查本地缓存 (速度快，无消耗)
        # 遍历所有缓存的歌曲
        for song_id, lyrics in self.lyric_cache.items():
            next_line = self._find_next_line(text, lyrics)
            if next_line:
                # 命中缓存！
                logger.info(f"Lyrics Match (Cache): {text} -> {next_line}")
                await event.send(MessageChain([Plain(next_line)]))
                return  # 结束，不再请求 API

        # 3. 缓存未命中，请求 API
        if not self.api:
            return

        # 搜索歌曲 ID
        song_id = await self.api.search_song_id(text)
        if not song_id:
            return  # 没搜到

        # 检查是否刚搜过这首歌（防止重复请求）
        if str(song_id) in self.lyric_cache:
            # 已经在缓存里了但刚才没匹配上，说明这句词可能不在歌词里，或者是重复的
            return

            # 获取歌词
        lyrics_list = await self.api.get_lyrics(song_id)
        if not lyrics_list:
            return

        # 存入缓存
        self.lyric_cache[str(song_id)] = lyrics_list
        self._save_cache()  # 立即保存或定期保存

        # 4. 再次尝试匹配
        next_line = self._find_next_line(text, lyrics_list)
        if next_line:
            logger.info(f"Lyrics Match (API): {text} -> {next_line}")
            await event.send(MessageChain([Plain(next_line)]))