"""
AstrBot 歌词插件 - 超简版本
完全基于点歌插件架构，确保兼容性
"""
from astrbot.api import star, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain


@star.register(
    "lyrics_simple",
    "YourName",
    "简单歌词插件",
    "1.0.0"
)
class LyricsSimplePlugin(star.Star):
    """超简化歌词插件"""
    
    def __init__(self, context, config=None):
        super().__init__(context)
        self.config = config or {}
        logger.info("[歌词插件] 超简版本初始化完成")

    @filter.command("lyrics_test")
    async def test_cmd(self, event: AstrMessageEvent):
        """测试命令"""
        event.stop_event()
        await event.send(MessageChain([Plain("✅ 歌词插件超简版本正常工作！")]))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_all_messages(self, event: AstrMessageEvent):
        """处理所有消息"""
        try:
            text = event.message_str.strip()
            
            if text == "测试歌词":
                event.stop_event()
                await event.send(MessageChain([Plain("🎵 歌词插件响应正常！")]))
                
        except Exception as e:
            logger.error(f"[歌词插件] 处理消息出错: {e}")