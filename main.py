"""
AstrBot 歌词插件 - 最小化测试版本
基于正常工作的点歌插件架构
"""
import os
import json
import re
import aiohttp
from typing import Dict, Any, Optional, List

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain
from astrbot.api import logger


@register(
    "lyrics_catcher_minimal",
    "YourName", 
    "歌词接龙插件（测试版）",
    "1.0.0"
)
class LyricsMinimalPlugin(Star):
    """歌词插件最小化测试版本"""
    
    def __init__(self, context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}
        self.api_url = self.config.get("api_url", "http://localhost:3000")
        logger.info(f"[歌词插件] 最小化版本初始化完成")

    async def initialize(self):
        """插件初始化"""
        logger.info("[歌词插件] 最小化版本已加载")

    async def terminate(self):
        """插件终止"""
        logger.info("[歌词插件] 最小化版本已卸载")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        """处理所有消息事件"""
        try:
            user_text = event.message_str.strip()
            
            # 基础过滤
            if len(user_text) < 2:
                return
                
            if user_text.startswith(('/', '!', '.', '。', '#')):
                return
            
            # 测试响应
            if user_text == "测试歌词插件":
                await event.send(MessageChain([Plain("✅ 歌词插件最小化版本运行正常！")]))
                return
                
            if user_text == "歌词插件状态":
                await event.send(MessageChain([Plain("📊 歌词插件状态：运行正常\n🔧 版本：1.0.0（最小化测试版）")]))
                return
                
            # 简单的歌词检测测试
            if "歌词" in user_text and len(user_text) > 4:
                await event.send(MessageChain([Plain("🎵 检测到歌词内容，插件功能正常！")]))
                
        except Exception as e:
            logger.error(f"[歌词插件] 处理消息出错: {e}")

    @filter.command("lyrics_test")
    async def test_command(self, event: AstrMessageEvent):
        """测试命令"""
        await event.send(MessageChain([Plain("✅ 歌词插件测试命令正常工作！\n🔧 这是最小化测试版本")]))

    @filter.command("lyrics_status")
    async def status_command(self, event: AstrMessageEvent):
        """状态命令"""
        status_text = f"""📊 歌词插件状态报告
━━━━━━━━━━━━━━━
🔧 插件版本：1.0.0（最小化测试版）
🔗 API地址：{self.api_url}
⚡ 运行状态：正常
━━━━━━━━━━━━━━━"""
        await event.send(MessageChain([Plain(status_text)]))