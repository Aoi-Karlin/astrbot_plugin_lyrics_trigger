"""
AstrBot 网易云歌词接龙插件 - 完整功能版本
基于稳定架构，恢复所有原有功能
"""
import os
import json
import re
import aiohttp
import asyncio
from difflib import SequenceMatcher
from typing import Dict, Any, Optional, List

from astrbot.api import star, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain


# --- API 封装类 ---
class NeteaseLyricsAPI:
    """网易云音乐API封装类 - 用于歌词搜索"""
    
    def __init__(self, api_url: str, session: aiohttp.ClientSession):
        self.base_url = api_url.rstrip("/")
        self.session = session

    async def search_song_by_lyrics(self, lyrics_text: str) -> Optional[Dict]:
        """通过歌词搜索歌曲"""
        try:
            search_url = f"{self.base_url}/cloudsearch"
            params = {"keywords": lyrics_text, "limit": 1, "type": 1}
            
            async with self.session.get(search_url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[歌词插件] 搜索API返回状态码: {resp.status}")
                    return None
                
                data = await resp.json()
                songs = data.get("result", {}).get("songs", [])
                
                if not songs:
                    logger.info(f"[歌词插件] 未找到匹配歌曲: {lyrics_text[:20]}...")
                    return None
                    
                return songs[0]
                
        except Exception as e:
            logger.error(f"[歌词插件] 搜索歌曲出错: {e}")
            return None

    async def get_lyrics(self, song_id: int) -> List[str]:
        """获取歌曲歌词"""
        try:
            lyrics_url = f"{self.base_url}/lyric?id={song_id}"
            
            async with self.session.get(lyrics_url) as resp:
                if resp.status != 200:
                    logger.error(f"[歌词插件] 获取歌词API返回状态码: {resp.status}")
                    return []
                
                data = await resp.json()
                lrc_text = data.get("lrc", {}).get("lyric", "")
                
                if not lrc_text:
                    logger.info(f"[歌词插件] 歌曲 {song_id} 无歌词数据")
                    return []
                
                return self._parse_lrc(lrc_text)
                
        except Exception as e:
            logger.error(f"[歌词插件] 获取歌词出错: {e}")
            return []

    def _parse_lrc(self, lrc_text: str) -> List[str]:
        """解析LRC歌词格式"""
        lines = []
        # 移除时间标签 [00:00.00]
        regex = re.compile(r'\[.*?\]')
        
        for line in lrc_text.split('\n'):
            clean_line = regex.sub('', line).strip()
            # 过滤掉空行和制作信息
            if clean_line and not clean_line.startswith(("作词", "作曲", "编曲", "制作")):
                lines.append(clean_line)
        
        return lines


# --- 插件主类 ---
@star.register(
    "lyrics_complete",
    "YourName",
    "网易云歌词接龙插件（完整版）",
    "2.0.0"
)
class LyricsCompletePlugin(star.Star):
    """网易云歌词接龙插件完整版"""
    
    def __init__(self, context, config=None):
        super().__init__(context)
        self.config = config or {}
        
        # 使用 setdefault 设置默认值，不依赖配置文件
        self.config.setdefault("api_url", "http://localhost:3000")
        self.config.setdefault("similarity_threshold", 0.8)
        self.config.setdefault("search_min_length", 5)
        self.config.setdefault("enable_cache", True)
        self.config.setdefault("trigger_probability", 100)
        self.config.setdefault("max_cache_size", 1000)
        
        # 添加默认配置警告
        if self.config["api_url"] == "http://localhost:3000":
            logger.warning("[歌词插件] 使用默认 API URL (localhost:3000)，"
                          "如果您的 API 服务在其他地址，请在配置中修改 api_url")
        
        # 初始化缓存和会话
        self.cache_dir = os.path.join(os.path.dirname(__file__), "data", "lyrics_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache_file = os.path.join(self.cache_dir, "lyrics_cache.json")
        self.lyric_cache = self._load_cache() if self.config["enable_cache"] else {}
        
        self.http_session = None
        self.api = None
        
        logger.info(f"[歌词插件] 完整版初始化完成，缓存大小: {len(self.lyric_cache)}")

    async def initialize(self):
        """插件初始化"""
        try:
            self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            self.api = NeteaseLyricsAPI(self.config["api_url"], self.http_session)
            logger.info("[歌词插件] 完整版初始化成功")
        except Exception as e:
            logger.error(f"[歌词插件] 完整版初始化失败: {e}")
            raise

    async def terminate(self):
        """插件终止"""
        try:
            if self.config["enable_cache"]:
                self._save_cache()
            if self.http_session:
                await self.http_session.close()
            logger.info("[歌词插件] 完整版已正常关闭")
        except Exception as e:
            logger.error(f"[歌词插件] 完整版关闭出错: {e}")

    def _load_cache(self) -> Dict[str, List[str]]:
        """加载歌词缓存"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[歌词插件] 加载缓存失败: {e}")
        return {}

    def _save_cache(self):
        """保存歌词缓存"""
        if not self.config["enable_cache"]:
            return
        try:
            # 限制缓存大小
            if len(self.lyric_cache) > self.config["max_cache_size"]:
                # 保留最新的缓存项
                items = list(self.lyric_cache.items())
                self.lyric_cache = dict(items[-self.config["max_cache_size"]:])
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.lyric_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[歌词插件] 保存缓存失败: {e}")

    def _match_lyrics(self, text: str, lyrics: List[str]) -> Optional[str]:
        """匹配歌词并返回下一句"""
        threshold = self.config["similarity_threshold"]
        
        for i, line in enumerate(lyrics):
            # 精确匹配或相似度匹配
            if text in line or SequenceMatcher(None, text, line).ratio() >= threshold:
                if i + 1 < len(lyrics):
                    return lyrics[i + 1]
        return None

    def _extract_song_info(self, song_data: Dict) -> Dict[str, str]:
        """提取歌曲信息"""
        song_name = song_data.get("name", "未知歌曲")
        artists = song_data.get("artists", [{}])
        artist = artists[0].get("name", "未知歌手") if artists else "未知歌手"
        
        return {
            "song_name": song_name,
            "artist": artist
        }