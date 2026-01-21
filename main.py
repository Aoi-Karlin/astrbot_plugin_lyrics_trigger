"""
AstrBot 网易云歌词接龙插件 - 测试版本
最小化版本用于验证基本功能
"""
import os
import json
import re
import aiohttp
from difflib import SequenceMatcher
from typing import Dict, Any, Optional, List

from astrbot.api import star, logger
from astrbot.api.model import MessageEvent
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain


@star.register("netease_lyrics_join", "YourName", "网易云歌词接龙", "1.1.2")
class LyricsJoinPlugin(star.Star):
    """网易云歌词接龙插件主类"""
    
    def __init__(self, context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}
        
        # 配置项设置
        self.api_url = self.config.get("api_url", "http://localhost:3000")
        self.similarity_threshold = self.config.get("similarity_threshold", 0.8)
        self.search_min_length = self.config.get("search_min_length", 5)
        self.enable_cache = self.config.get("enable_cache", True)
        
        # 初始化缓存和会话
        self.cache_file = os.path.join(os.path.dirname(__file__), "lyric_cache.json")
        self.lyric_cache = self._load_cache() if self.enable_cache else {}
        self.http_session = None
        
        logger.info(f"[歌词插件] 插件初始化完成，API地址: {self.api_url}")

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

    @star.on_message
    async def handle_lyrics(self, event: MessageEvent):
        """处理消息事件，检测歌词并接龙"""
        try:
            # 获取消息文本
            user_text = event.message_str.strip()
            
            # 基础过滤
            if len(user_text) < self.search_min_length:
                return
                
            # 过滤命令消息
            if user_text.startswith(('/', '!', '.', '。', '#')):
                return
            
            logger.debug(f"[歌词插件] 检测消息: {user_text[:30]}...")
            
            # 简单的模拟响应用于测试
            if "测试" in user_text:
                await event.send(MessageChain([Plain("测试成功！插件正常运行")]))
                return
                
            # 这里可以添加实际的歌词搜索逻辑
            # 为了测试，我们只响应包含"歌词"的消息
            if "歌词" in user_text:
                await event.send(MessageChain([Plain("检测到歌词关键词，插件功能正常！")]))
                
        except Exception as e:
            logger.error(f"[歌词插件] 处理消息出错: {e}")

    @star.command("lyrics_test")
    async def test_command(self, event: MessageEvent):
        """测试命令"""
        await event.send(MessageChain([Plain("✅ 歌词插件测试命令正常工作！")]))

    @star.command("lyrics_stats")
    async def get_stats(self, event: MessageEvent):
        """获取插件统计信息"""
        stats_text = f"""📊 歌词接龙插件统计
━━━━━━━━━━━━━━━
🗂️ 缓存歌曲数: {len(self.lyric_cache)}
🎯 最小长度: {self.search_min_length}
📊 相似度阈值: {self.similarity_threshold}
💾 缓存状态: {'开启' if self.enable_cache else '关闭'}
🔗 API地址: {self.api_url}
━━━━━━━━━━━━━━━"""
        await event.send(MessageChain([Plain(stats_text)]))