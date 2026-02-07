"""
Lyric Trigger Plugin for AstrBot
- Author: Azured
- Features: Automatically triggers LLM response when lyrics are detected, sending the next line to AI.
"""

import re
import asyncio
import aiohttp
import urllib.parse
from typing import Dict, Any, Optional, Tuple
from difflib import SequenceMatcher

from astrbot.api import star
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api.message_components import Plain


class NeteaseLyricsAPI:
    """
    A wrapper for the NeteaseCloudMusicApi to fetch lyrics.
    """

    def __init__(self, api_url: str, session: aiohttp.ClientSession):
        self.base_url = api_url.rstrip("/")
        self.session = session

    async def search_songs(self, keyword: str, limit: int = 10) -> list:
        """Search for songs by keyword."""
        url = f"{self.base_url}/search?keywords={urllib.parse.quote(keyword)}&limit={limit}&type=1"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    logger.warning(f"Netease API search failed with status {r.status}")
                    return []
                data = await r.json()
                return data.get("result", {}).get("songs", [])
        except aiohttp.ClientError as e:
            logger.error(f"Netease API search client error: {e}")
            return []
        except asyncio.TimeoutError as e:
            logger.error(f"Netease API search timeout: {e}")
            return []
        except Exception as e:
            logger.error(f"Netease API search unexpected error: {e}")
            return []

    async def get_lyrics(self, song_id: int) -> Optional[Dict[str, Any]]:
        """Get lyrics for a song."""
        url = f"{self.base_url}/lyric?id={song_id}"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    logger.warning(f"Netease API lyrics failed with status {r.status}")
                    return None
                data = await r.json()
                
                # Check if lyrics exist
                if data.get("lrc") and data["lrc"].get("lyric"):
                    return data
                return None
        except aiohttp.ClientError as e:
            logger.error(f"Netease API lyrics client error: {e}")
            return None
        except asyncio.TimeoutError as e:
            logger.error(f"Netease API lyrics timeout: {e}")
            return None
        except Exception as e:
            logger.error(f"Netease API lyrics unexpected error: {e}")
            return None

    def parse_lyrics(self, lyric_text: str) -> list[str]:
        """Parse lyrics text into lines, removing timestamps."""
        if not lyric_text:
            return []
        
        lines = []
        for line in lyric_text.split('\n'):
            # Remove timestamp like [00:00.00] or [00:00:00]
            cleaned = re.sub(r'\[\d{2}:\d{2}(:\d{2})?\.?\d*\]', '', line).strip()
            if cleaned:
                lines.append(cleaned)
        return lines


class Main(star.Star):
    """
    Lyric Trigger Plugin Main Class
    """
    
    # Command prefixes for lyric matching
    COMMAND_PREFIXES = ["/歌词匹配", "/lyric", "/匹配歌词", "/lyricmatch"]
    
    # Default configuration values
    DEFAULT_API_URL = "http://127.0.0.1:3000"
    DEFAULT_SIMILARITY_THRESHOLD = 0.6
    DEFAULT_MAX_SEARCH_RESULTS = 5
    DEFAULT_TRIGGER_PROMPT = "歌词：'{lyric}'，下一句是：'{next_line}'。请输出后半句歌词，并简短地表达你的情感。"

    def __init__(self, context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        
        # Validate and set configuration
        self._validate_and_set_config()
        
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.api: Optional[NeteaseLyricsAPI] = None
    
    def _validate_and_set_config(self):
        """Validate and set configuration parameters."""
        # API URL
        api_url = self.config.get("api_url", self.DEFAULT_API_URL)
        if not isinstance(api_url, str) or not api_url.startswith(("http://", "https://")):
            raise ValueError("api_url 必须是有效的 HTTP/HTTPS URL")
        self.config["api_url"] = api_url
        
        # Similarity threshold (0.0 to 1.0)
        threshold = self.config.get("similarity_threshold", self.DEFAULT_SIMILARITY_THRESHOLD)
        if not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
            raise ValueError("similarity_threshold 必须是 0.0 到 1.0 之间的数字")
        self.config["similarity_threshold"] = float(threshold)
        
        # Max search results (positive integer)
        max_results = self.config.get("max_search_results", self.DEFAULT_MAX_SEARCH_RESULTS)
        if not isinstance(max_results, int) or max_results < 1:
            raise ValueError("max_search_results 必须是正整数")
        self.config["max_search_results"] = max_results
        
        # Trigger prompt
        trigger_prompt = self.config.get("trigger_prompt", self.DEFAULT_TRIGGER_PROMPT)
        if not isinstance(trigger_prompt, str) or not trigger_prompt.strip():
            raise ValueError("trigger_prompt 必须是非空字符串")
        self.config["trigger_prompt"] = trigger_prompt
        
        # Show warning if using default API URL
        if self.config["api_url"] == self.DEFAULT_API_URL:
            logger.warning("Lyric Trigger plugin: 使用默认API URL (127.0.0.1:3000)，请在配置中修改如果您的API服务在其他地址")
    
    def safe_format_prompt(self, template: str, **kwargs: Any) -> str:
        """Safely format prompt template with provided values, ignoring missing placeholders."""
        try:
            # Use string.Formatter to safely handle missing keys
            from string import Formatter
            
            # Get all placeholder fields from template
            fields = [field_name for _, field_name, _, _ in Formatter().parse(template) if field_name]
            
            # Only include kwargs that exist in template
            valid_kwargs = {k: v for k, v in kwargs.items() if k in fields}
            
            # Format with valid kwargs only
            return template.format(**valid_kwargs)
        except Exception as e:
            logger.warning(f"Lyric Trigger plugin: 提示词格式化失败，使用原始模板: {e}")
            return template

    async def initialize(self):
        """Initialize the plugin."""
        self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        self.api = NeteaseLyricsAPI(self.config["api_url"], self.http_session)
        logger.info("Lyric Trigger plugin: 初始化成功")

    async def terminate(self):
        """Clean up resources when the plugin is unloaded."""
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
            logger.info("Lyric Trigger plugin: HTTP session 已关闭")
        await super().terminate()

    def calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings using SequenceMatcher.
        
        This is a lightweight CPU operation that doesn't need to be run in a thread pool.
        """
        if not str1 or not str2:
            return 0.0
        
        # Convert to lowercase and remove spaces for better matching
        str1_clean = str1.lower().replace(" ", "")
        str2_clean = str2.lower().replace(" ", "")
        
        if not str1_clean or not str2_clean:
            return 0.0
            
        return SequenceMatcher(None, str1_clean, str2_clean).ratio()

    async def find_matching_lyric(self, user_text: str) -> Optional[Tuple[str, str, str, int]]:
        """
        Find matching lyrics in Netease Music.
        Returns: (song_name, matched_line, next_line, song_id) or None
        """
        # Search for songs using the user text as keyword
        songs = await self.api.search_songs(user_text, self.config["max_search_results"])
        
        if not songs:
            return None
        
        # Check lyrics for each song
        for song in songs:
            song_id = song.get("id")
            song_name = song.get("name", "未知歌曲")
            
            if not song_id:
                continue
            
            # Get lyrics for this song
            lyrics_data = await self.api.get_lyrics(song_id)
            if not lyrics_data:
                continue
            
            # Parse lyrics lines
            lyric_text = lyrics_data["lrc"]["lyric"]
            lines = self.api.parse_lyrics(lyric_text)
            
            if len(lines) < 2:
                continue
            
            # Find matching line
            for i, line in enumerate(lines[:-1]):  # Don't check the last line
                similarity = self.calculate_similarity(user_text, line)
                
                if similarity >= self.config["similarity_threshold"]:
                    next_line = lines[i + 1]
                    return song_name, line, next_line, song_id
        
        return None

    def _extract_lyric_from_command(self, message: str) -> str:
        """Extract lyric content from command message."""
        # Remove command prefix to get lyric content
        # Sort prefixes by length (descending) to match longest first
        lyric_text = message
        sorted_prefixes = sorted(self.COMMAND_PREFIXES, key=len, reverse=True)
        for prefix in sorted_prefixes:
            if message.startswith(prefix):
                lyric_text = message[len(prefix):].strip()
                break
        return lyric_text
    
    async def _get_llm_response(self, event: AstrMessageEvent, prompt: str, song_name: str, 
                               matched_line: str, next_line: str) -> bool:
        """Get LLM response and send it to user."""
        try:
            # Get current chat provider ID for this session
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            
            if not provider_id:
                await event.send(MessageChain([Plain("❌ 无法获取当前会话的LLM配置，请确保已配置LLM提供商。")]))
                return False
            
            # Get the default persona for this session using persona_manager
            persona_mgr = self.context.persona_manager
            persona_v3 = await persona_mgr.get_default_persona_v3(umo=umo)
            
            # Extract system prompt from persona v3 format
            system_prompt = None
            if persona_v3 and 'prompt' in persona_v3:
                system_prompt = persona_v3['prompt']
                logger.info(f"Lyric Trigger plugin: 使用当前会话人格 - {persona_v3.get('name', '默认人格')}")
            else:
                logger.info("Lyric Trigger plugin: 未找到自定义人格，使用默认配置")
            
            # Use llm_generate for all calls, with or without system_prompt
            logger.debug(f"Lyric Trigger plugin: 人格系统提示词 - {system_prompt[:30] if system_prompt else '默认'}")
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,  # This is the trigger_prompt with lyric data
                system_prompt=system_prompt,  # This is from persona (or None for default)
            )
            
            # Send LLM's response
            if llm_resp and llm_resp.completion_text:
                await event.send(MessageChain([Plain(llm_resp.completion_text)]))
                logger.info(f"Lyric Trigger plugin: 已触发LLM回复（使用当前人格），歌曲: {song_name}, 歌词: {matched_line} -> {next_line}")
                return True
            else:
                await event.send(MessageChain([Plain("❌ LLM未返回有效回复。")]))
                return False
        except Exception as llm_error:
            logger.error(f"Lyric Trigger plugin: LLM调用失败: {llm_error}")
            await event.send(MessageChain([Plain(f"❌ LLM调用失败：{str(llm_error)}")]))
            return False
    
    @filter.command("歌词匹配", alias={"lyric", "匹配歌词", "lyricmatch"}, priority=100)
    async def cmd_lyric_match(self, event: AstrMessageEvent):
        """指令触发歌词匹配和AI回复。使用方法：/歌词匹配 <歌词内容>"""
        event.stop_event()
        
        # Extract lyric content from command
        lyric_text = self._extract_lyric_from_command(event.message_str)
        
        # Check if lyric text is provided
        if not lyric_text:
            await event.send(MessageChain([Plain("请提供要匹配的歌词内容。\n使用方法：/歌词匹配 <歌词内容>\n例如：/歌词匹配 天青色等烟雨")]))
            return
        
        try:
            # Try to find matching lyrics
            result = await self.find_matching_lyric(lyric_text)
            
            if result:
                song_name, matched_line, next_line, song_id = result
                
                logger.info(f"Lyric Trigger plugin: 匹配到歌词 '{matched_line}' 来自歌曲 '{song_name}'")
                
                # Prepare the prompt for LLM
                prompt_template = self.config.get("trigger_prompt", "")
                prompt = self.safe_format_prompt(
                    prompt_template,
                    lyric=matched_line,
                    next_line=next_line,
                    song_name=song_name
                )
                
                # Get LLM response and send it
                await self._get_llm_response(event, prompt, song_name, matched_line, next_line)
            else:
                # No match found
                error_msg = f"❌ 未找到匹配的歌词。\n\n可能的原因：\n• 相似度低于阈值（当前：{self.config['similarity_threshold']})\n• 未在搜索结果中找到匹配歌曲\n• 歌词内容可能不够独特\n\n建议：尝试更长的歌词片段或调整配置参数。"
                await event.send(MessageChain([Plain(error_msg)]))
        except Exception as e:
            logger.error(f"Lyric Trigger plugin: 处理失败: {e}")
            await event.send(MessageChain([Plain(f"处理失败：{str(e)}")]))
