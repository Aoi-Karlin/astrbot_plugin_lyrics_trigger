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
class Main(star.Star):
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

    @filter.command("接歌词", alias={"歌词接龙", "lyrics", "jl"}, priority=80)
    async def cmd_lyrics_complete(self, event: AstrMessageEvent, keyword: str = ""):
        """手动触发歌词接龙命令"""
        try:
            if not keyword.strip():
                await event.send(MessageChain([Plain("请提供一句歌词，我来接下一句~\n例如：/接歌词 天青色等烟雨")]))
                return
                
            event.stop_event()
            
            if not self.api:
                await event.send(MessageChain([Plain("插件未正确初始化，请联系管理员检查配置")]))
                return
            
            # 搜索歌曲
            song_data = await self.api.search_song_by_lyrics(keyword.strip())
            if not song_data:
                error_msg = "抱歉，没有找到包含" + keyword + "的歌曲呢..."
                await event.send(MessageChain([Plain(error_msg)]))
                return
                
            # 获取歌词
            song_id = song_data.get("id")
            lyrics = await self.api.get_lyrics(song_id)
            if not lyrics:
                await event.send(MessageChain([Plain("抱歉，没有找到这首歌的歌词呢...")]))
                return
                
            # 匹配歌词
            next_line = self._match_lyrics(keyword.strip(), lyrics)
            if next_line:
                # 缓存结果
                if self.config["enable_cache"]:
                    self.lyric_cache[keyword.strip()] = lyrics
                    # 限制缓存大小
                    if len(self.lyric_cache) > self.config["max_cache_size"]:
                        # 移除最旧的缓存项
                        oldest_key = next(iter(self.lyric_cache))
                        del self.lyric_cache[oldest_key]
                
                # 发送回复
                await event.send(MessageChain([Plain(f"下一句是：{next_line}")]))
                
                # 记录日志
                song_info = self._extract_song_info(song_data)
                logger.info(f"[歌词插件] 命令触发成功: '{keyword}' -> '{next_line}' "
                           f"(歌曲: {song_info['song_name']} - {song_info['artist']})")
            else:
                no_result_msg = "抱歉，在" + keyword + "后面没有找到下一句歌词呢..."
                await event.send(MessageChain([Plain(no_result_msg)]))
                
        except Exception as e:
            logger.error(f"[歌词插件] 命令处理出错: {e}")
            await event.send(MessageChain([Plain("处理请求时出错了，请稍后再试...")]))

    @filter.event_message_type(filter.EventMessageType.MESSAGE)
    async def on_message(self, event: AstrMessageEvent):
        """监听所有消息事件，处理歌词接龙"""
        try:
            message_text = event.message_str.strip()
            
            # 跳过空消息
            if not message_text:
                return
                
            # 跳过命令消息
            if message_text.startswith(('/', '！', '!', '。', '.')):
                return
                
            # 检查消息长度
            if len(message_text) < self.config["search_min_length"]:
                return
            
            # 检查触发概率
            import random
            if random.randint(1, 100) > self.config["trigger_probability"]:
                return
            
            # 首先检查缓存
            cache_key = message_text
            if self.config["enable_cache"] and cache_key in self.lyric_cache:
                cached_lyrics = self.lyric_cache[cache_key]
                next_line = self._match_lyrics(message_text, cached_lyrics)
                
                if next_line:
                    event.stop_event()
                    await event.send(MessageChain([Plain(next_line)]))
                    logger.info(f"[歌词插件] 缓存匹配成功: '{message_text}' -> '{next_line}'")
                    return
            
            # 如果缓存中没有，调用API搜索
            if not self.api:
                logger.warning("[歌词插件] API未初始化")
                return
                
            # 搜索歌曲
            song_data = await self.api.search_song_by_lyrics(message_text)
            if not song_data:
                return
                
            # 获取歌词
            song_id = song_data.get("id")
            if not song_id:
                return
                
            lyrics = await self.api.get_lyrics(song_id)
            if not lyrics:
                return
                
            # 匹配歌词
            next_line = self._match_lyrics(message_text, lyrics)
            if next_line:
                # 缓存结果
                if self.config["enable_cache"]:
                    self.lyric_cache[cache_key] = lyrics
                    # 限制缓存大小
                    if len(self.lyric_cache) > self.config["max_cache_size"]:
                        # 移除最旧的缓存项
                        oldest_key = next(iter(self.lyric_cache))
                        del self.lyric_cache[oldest_key]
                
                # 发送回复
                event.stop_event()
                await event.send(MessageChain([Plain(next_line)]))
                
                # 记录日志
                song_info = self._extract_song_info(song_data)
                logger.info(f"[歌词插件] 歌词接龙成功: '{message_text}' -> '{next_line}' "
                           f"(歌曲: {song_info['song_name']} - {song_info['artist']})")
                
        except Exception as e:
            logger.error(f"[歌词插件] 处理消息事件出错: {e}")
            # 不要停止事件传播，避免影响其他插件