"""
AstrBot 网易云歌词接龙插件 - 完整修复版本
基于正常工作的点歌插件架构
"""
import os
import json
import re
import aiohttp
import asyncio
from difflib import SequenceMatcher
from typing import Dict, Any, Optional, List

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain
from astrbot.api import logger


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
@register(
    "lyrics_catcher_complete",
    "YourName", 
    "网易云歌词接龙（完整版）",
    "2.0.0"
)
class LyricsCompletePlugin(Star):
    """网易云歌词接龙插件完整版"""
    
    def __init__(self, context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}
        
        # 配置项设置
        self.api_url = self.config.get("api_url", "http://localhost:3000")
        self.similarity_threshold = self.config.get("similarity_threshold", 0.8)
        self.search_min_length = self.config.get("search_min_length", 5)
        self.enable_cache = self.config.get("enable_cache", True)
        self.trigger_probability = self.config.get("trigger_probability", 100)
        
        # 初始化缓存和会话
        self.cache_dir = os.path.join(os.path.dirname(__file__), "data", "lyrics_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache_file = os.path.join(self.cache_dir, "lyrics_cache.json")
        self.lyric_cache = self._load_cache() if self.enable_cache else {}
        
        self.http_session = None
        self.api = None
        
        logger.info(f"[歌词插件] 完整版初始化完成，API地址: {self.api_url}")

    async def initialize(self):
        """插件初始化"""
        try:
            self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            self.api = NeteaseLyricsAPI(self.api_url, self.http_session)
            logger.info("[歌词插件] 完整版初始化成功")
        except Exception as e:
            logger.error(f"[歌词插件] 完整版初始化失败: {e}")
            raise

    async def terminate(self):
        """插件终止"""
        try:
            if self.enable_cache:
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
        if not self.enable_cache:
            return
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.lyric_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[歌词插件] 保存缓存失败: {e}")

    def _match_lyrics(self, text: str, lyrics: List[str]) -> Optional[str]:
        """匹配歌词并返回下一句"""
        threshold = self.similarity_threshold
        
        for i, line in enumerate(lyrics):
            # 精确匹配或相似度匹配
            if text in line or SequenceMatcher(None, text, line).ratio() >= threshold:
                if i + 1 < len(lyrics):
                    return lyrics[i + 1]
        return None

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_lyrics(self, event: AstrMessageEvent):
        """处理消息事件，检测歌词并接龙"""
        try:
            user_text = event.message_str.strip()
            
            # 基础过滤
            if len(user_text) < self.search_min_length:
                return
                
            if user_text.startswith(('/', '!', '.', '。', '#')):
                return
            
            # 触发概率控制
            import random
            if random.randint(1, 100) > self.trigger_probability:
                return
            
            logger.debug(f"[歌词插件] 检测消息: {user_text[:30]}...")
            
            # 1. 先检查缓存
            for cache_key, lyrics in self.lyric_cache.items():
                next_line = self._match_lyrics(user_text, lyrics)
                if next_line:
                    await event.send(MessageChain([Plain(next_line)]))
                    logger.info(f"[歌词插件] 缓存命中，发送接龙: {next_line[:20]}...")
                    return
            
            # 2. API搜索
            if self.api:
                song_info = await self.api.search_song_by_lyrics(user_text)
                if song_info:
                    lyrics_list = await self.api.get_lyrics(song_info["id"])
                    if lyrics_list:
                        # 存入缓存
                        cache_key = f"song_{song_info['id']}"
                        self.lyric_cache[cache_key] = lyrics_list
                        
                        # 尝试匹配
                        next_line = self._match_lyrics(user_text, lyrics_list)
                        if next_line:
                            song_name = song_info.get("name", "未知歌曲")
                            artist = song_info.get("artists", [{}])[0].get("name", "未知歌手")
                            
                            reply = f"{next_line}\n\n♪ {song_name} - {artist}"
                            await event.send(MessageChain([Plain(reply)]))
                            logger.info(f"[歌词插件] API搜索成功，发送接龙: {song_name} - {artist}")
                            
        except Exception as e:
            logger.error(f"[歌词插件] 处理消息出错: {e}")

    @filter.command("lyrics_stats")
    async def get_stats(self, event: AstrMessageEvent):
        """获取插件统计信息"""
        stats_text = f"""📊 歌词接龙插件统计
━━━━━━━━━━━━━━━
🗂️ 缓存歌曲数: {len(self.lyric_cache)}
🎯 最小长度: {self.search_min_length}
📊 相似度阈值: {self.similarity_threshold}
💾 缓存状态: {'开启' if self.enable_cache else '关闭'}
🔗 API地址: {self.api_url}
🎲 触发概率: {self.trigger_probability}%
━━━━━━━━━━━━━━━"""
        await event.send(MessageChain([Plain(stats_text)]))

    @filter.command("lyrics_clear")
    async def clear_cache(self, event: AstrMessageEvent):
        """清空歌词缓存"""
        try:
            self.lyric_cache.clear()
            if self.enable_cache and os.path.exists(self.cache_file):
                os.remove(self.cache_file)
            await event.send(MessageChain([Plain("✅ 歌词缓存已清空")]))
            logger.info("[歌词插件] 缓存已清空")
        except Exception as e:
            logger.error(f"[歌词插件] 清空缓存失败: {e}")
            await event.send(MessageChain([Plain("❌ 清空缓存失败")]))

    @filter.command("lyrics_test")
    async def test_command(self, event: AstrMessageEvent):
        """测试命令"""
        await event.send(MessageChain([Plain("✅ 歌词插件完整版测试命令正常工作！\n🎵 插件版本：2.0.0")]))