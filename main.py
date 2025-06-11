from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import os
import json
import re
import random
from typing import Dict, List, Tuple, Set, Optional


@register("lyricnext", "EEEpai", "发送一句歌词，机器人会回复下一句", "1.0.0")
class LyricNextPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 初始化歌词索引
        self.lyrics_dir = os.path.join(os.path.dirname(__file__), "data", "lyrics")
        self.lyrics_index = {}  # 歌词句子 -> [(下一句, 歌名), ...]
        self.lyrics_info = {}  # 歌名 -> 歌曲信息(作者等)

        # 确保歌词目录存在
        os.makedirs(self.lyrics_dir, exist_ok=True)

        # 配置文件路径
        self.config_path = os.path.join(os.path.dirname(__file__), "data", "config.json")

        # 初始化配置
        self.config = self._load_config()

    async def initialize(self):
        """插件初始化，加载所有歌词文件并建立索引"""
        logger.info("正在初始化LyricNext插件...")
        await self._load_lyrics()
        logger.info(
            f"LyricNext插件初始化完成，已加载 {len(self.lyrics_info)} 首歌曲，{len(self.lyrics_index)} 条歌词索引")

    def _load_config(self) -> dict:
        """加载配置文件"""
        default_config = {
            "preprocess_lyrics": True,  # 是否预处理歌词（去除标点等）
            "match_threshold": 0.8,  # 模糊匹配阈值
        }

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置和已有配置
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
            except Exception as e:
                logger.error(f"加载配置文件失败: {str(e)}")

        # 配置文件不存在或加载失败，使用默认配置
        self._save_config(default_config)
        return default_config

    def _save_config(self, config: dict):
        """保存配置文件"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"保存配置文件失败: {str(e)}")

    async def _load_lyrics(self):
        """加载所有歌词文件并建立索引"""
        self.lyrics_index = {}
        self.lyrics_info = {}

        # 获取歌词目录下的所有文件
        try:
            for filename in os.listdir(self.lyrics_dir):
                if filename.endswith(".txt"):
                    song_name = os.path.splitext(filename)[0]
                    file_path = os.path.join(self.lyrics_dir, filename)

                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            lines = [line.strip() for line in f.readlines() if line.strip()]

                            # 存储歌曲信息
                            self.lyrics_info[song_name] = {
                                "total_lines": len(lines)
                            }

                            # 建立歌词索引
                            # 首先将所有行拆分成句子（如果一行内有空格分隔的多句）
                            sentences = []
                            for line in lines:
                                # 先过滤掉明显的信息行和标题行
                                if (':' in line or '：' in line or  # 包含冒号的信息行
                                    ' - ' in line or  # 包含连字符的标题行（歌曲-歌手）
                                    '(' in line and ')' in line):  # 包含括号的标题行
                                    continue
                                
                                # 检测行内是否有空格分隔的多句歌词
                                if ' ' in line.strip():
                                    # 将一行拆分成多句
                                    parts = [part.strip() for part in line.split(' ') if part.strip()]
                                    sentences.extend(parts)
                                else:
                                    sentences.append(line.strip())
                              # 过滤掉空句子和无效句子
                            filtered_sentences = []
                            for sentence in sentences:
                                if (sentence and 
                                    len(sentence) > 1 and  # 过滤单字符
                                    not sentence.isdigit() and  # 过滤纯数字
                                    not all(c in '()[]{}' for c in sentence)):  # 过滤纯括号
                                    filtered_sentences.append(sentence)
                            
                            # 建立句子到下一句的索引
                            for i in range(len(filtered_sentences) - 1):
                                current_sentence = self._preprocess_lyric(filtered_sentences[i]) if self.config["preprocess_lyrics"] else filtered_sentences[i]
                                next_sentence = filtered_sentences[i + 1]

                                if current_sentence not in self.lyrics_index:
                                    self.lyrics_index[current_sentence] = []

                                self.lyrics_index[current_sentence].append((next_sentence, song_name))
                    except Exception as e:
                        logger.error(f"加载歌词文件 {filename} 失败: {str(e)}")
        except Exception as e:
            logger.error(f"遍历歌词目录失败: {str(e)}")

    def _preprocess_lyric(self, lyric: str) -> str:
        """预处理歌词，去除标点符号，统一大小写等"""
        # 去除标点符号
        processed = re.sub(r'[^\w\s]', '', lyric)
        # 去除多余空格
        processed = re.sub(r'\s+', ' ', processed).strip()
        # 转为小写
        processed = processed.lower()
        return processed

    async def _find_next_lyric(self, lyric: str) -> Optional[Tuple[str, str]]:
        """查找歌词的下一句，返回(下一句, 歌曲名)"""
        # 直接查找
        processed_lyric = self._preprocess_lyric(lyric) if self.config["preprocess_lyrics"] else lyric
        if processed_lyric in self.lyrics_index:
            # 如果有多个匹配，随机选择一个
            return random.choice(self.lyrics_index[processed_lyric])

        # 没有找到，返回None
        return None

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """处理所有消息，检查是否是歌词"""
        # 只处理纯文本消息
        message = event.message_str.strip()

        # 忽略命令前缀的消息
        if message.startswith('/'):
            return
        
        # 忽略空消息
        if not message:
            return
            
        # 检查消息链中是否只包含文本消息，过滤掉图片、戳一戳等非文本消息
        message_chain = event.get_messages()
        if not message_chain:
            return
            
        # 检查是否包含非文本消息组件
        for component in message_chain:
            component_type = type(component).__name__.lower()
            # 如果包含图片、戳一戳、语音、视频等非文本组件，则忽略
            if component_type in ['image', 'poke', 'record', 'video', 'face', 'at', 'reply']:
                return
        
        # 过滤掉看起来像HTML/XML的内容
        if '<' in message and '>' in message:
            return
            
        # 过滤掉过短或过长的消息
        if len(message) < 2 or len(message) > 50:
            return

        # 查找下一句歌词
        result = await self._find_next_lyric(message)
        if result:
            next_lyric, song_name = result
            yield event.plain_result(f"{next_lyric}")
            # 阻止事件继续传播，避免被其他插件或LLM处理
            event.stop_event()
    @filter.command_group("lyric")
    def lyric_commands(self):
        """歌词相关命令组"""
        pass

    @lyric_commands.command("help")
    async def help_command(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """歌词接龙插件使用帮助：
1. 直接发送歌词，机器人会回复下一句
2. /lyric search 歌名 [歌手名] [音乐源] - 搜索并添加歌词到歌词库
   - 支持的音乐源: 网易云, QQ音乐, 酷狗
   - 歌手名和音乐源为可选参数
   - 示例: 
     * /lyric search 晴天
     * /lyric search 晴天 周杰伦
     * /lyric search 晴天 周杰伦 QQ音乐
3. /lyric list - 列出所有已添加的歌曲
4. /lyric view 歌曲名 - 查看指定歌曲的完整歌词内容
5. /lyric reload - 重新加载所有歌词文件

💡 提示: 
- 如需批量下载某个歌手的所有歌曲，可运行 tools/fetch_lyrics.py
- 可单独运行 tools/search_lyrics.py 搜索单首歌曲"""
        yield event.plain_result(help_text)

    @lyric_commands.command("reload")
    async def reload_command(self, event: AstrMessageEvent):
        """重新加载所有歌词"""
        await self._load_lyrics()
        yield (((
        (event.plain_result(f"已重新加载歌词库，共 {len(self.lyrics_info)} 首歌曲，{len(self.lyrics_index)} 条歌词索引")))))
    @lyric_commands.command("search")
    async def search_command(self, event: AstrMessageEvent, song_name: str, artist_name: str = "", music_source: str = ""):
        """搜索并添加歌词"""
        # 检查是否有歌曲名
        if not song_name:
            yield event.plain_result("请提供歌曲名称，格式：/lyric search 歌名 [歌手名] [音乐源]")
            return        # 清理参数，将空字符串转为None
        artist_name = artist_name.strip() if artist_name.strip() else None
        music_source = music_source.strip() if music_source.strip() else None
        
        # 记录解析后的参数
        logger.info(f"解析后的参数: 歌名='{song_name}', 歌手='{artist_name}', 音乐源='{music_source}'")

        # 验证音乐源是否有效
        if music_source:
            valid_sources = ["网易云", "netease", "qq", "QQ音乐", "酷狗", "kugou"]
            if music_source.lower() not in [s.lower() for s in valid_sources]:
                yield event.plain_result(f"不支持的音乐源: {music_source}\n支持的音乐源: {', '.join(valid_sources)}")
                return

        # 根据输入的音乐源名称规范化为代码中使用的标识符
        source_mapping = {
            "网易云": "netease",
            "netease": "netease",
            "qq": "qq",
            "qq音乐": "qq",
            "酷狗": "kugou",
            "kugou": "kugou"
        }

        if music_source:
            music_source = source_mapping.get(music_source.lower(), music_source)
            yield event.plain_result(f"正在从{music_source}搜索《{song_name}》的歌词，请稍候...")
        else:
            yield event.plain_result(f"正在搜索《{song_name}》的歌词，请稍候...")
        try:
            # 导入搜索模块
            import sys
            import os
            tool_path = os.path.join(os.path.dirname(__file__), "tools")
            if tool_path not in sys.path:
                sys.path.append(tool_path)

            from search_lyrics import search_and_save_lyrics

            # 执行搜索
            logger.info(f"开始搜索歌词, 歌名:{song_name}, 歌手:{artist_name}, 音乐源:{music_source}")
            success, file_path, preview = search_and_save_lyrics(song_name, artist_name, music_source)
            logger.info(f"搜索结果: 成功={success}, 文件路径={file_path}")
            if success:
                # 重新加载歌词库以包含新添加的歌词
                await self._load_lyrics()

                # 提取文件名作为歌曲名
                song_name = os.path.basename(file_path).replace(".txt", "")

                # 发送成功消息和预览
                result = f"歌词《{song_name}》添加成功！\n\n歌词预览:\n{preview}"
                yield event.plain_result(result)
            else:
                if preview:  # 有歌词但保存失败
                    yield event.plain_result(f"获取到歌词但保存失败，请稍后再试。")
                else:
                    yield event.plain_result(f"未找到《{song_name}》的歌词，请尝试其他关键词或添加歌手名。")
        except Exception as e:
            logger.error(f"搜索歌词过程中发生错误: {str(e)}")
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"错误详情: {error_trace}")
            yield event.plain_result(f"搜索歌词失败: {str(e)}\n请检查日志获取详细信息。")

    @lyric_commands.command("list")
    async def list_command(self, event: AstrMessageEvent):
        """列出所有已添加的歌曲"""
        if not self.lyrics_info:
            yield event.plain_result("歌词库为空，请先添加歌词")
            return

        song_list = "\n".join([f"{i + 1}. {song}" for i, song in enumerate(self.lyrics_info.keys())])
        yield (event.plain_result(f"已添加的歌曲列表（共{len(self.lyrics_info)}首）：\n{song_list}"))
    @lyric_commands.command("view")
    async def view_command(self, event: AstrMessageEvent, song_name: str = ""):
        """查看指定歌曲的完整歌词内容"""
        if not song_name.strip():
            yield event.plain_result("请提供歌曲名称，格式：/lyric view 歌曲名")
            return
        
        # 查找匹配的歌曲
        song_name = song_name.strip()
        exact_matches = []
        fuzzy_matches = []
        
        # 首先尝试精确匹配
        for existing_song in self.lyrics_info.keys():
            if song_name.lower() == existing_song.lower():
                exact_matches.append(existing_song)
        
        # 如果有精确匹配，使用精确匹配结果
        if exact_matches:
            target_song = exact_matches[0]
        else:
            # 没有精确匹配，进行模糊匹配
            for existing_song in self.lyrics_info.keys():
                if song_name.lower() in existing_song.lower():
                    fuzzy_matches.append(existing_song)
            
            if not fuzzy_matches:
                yield event.plain_result(f"未找到包含 '{song_name}' 的歌曲\n使用 /lyric list 查看所有歌曲")
                return
            
            if len(fuzzy_matches) > 1:
                # 多个模糊匹配结果，让用户选择
                song_list = "\n".join([f"  {song}" for song in fuzzy_matches])
                yield event.plain_result(f"找到多首匹配的歌曲：\n\n{song_list}\n\n请使用更精确的歌曲名")
                return
            
            # 唯一模糊匹配
            target_song = fuzzy_matches[0]
        file_path = os.path.join(self.lyrics_dir, f"{target_song}.txt")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lyrics_content = f.read().strip()
            
            if lyrics_content:
                # 限制显示长度，避免消息过长
                if len(lyrics_content) > 2000:
                    lyrics_preview = lyrics_content[:2000] + "\n...\n（歌词内容过长，已截断显示）"
                else:
                    lyrics_preview = lyrics_content
                
                yield event.plain_result(f"🎵 歌曲《{target_song}》的歌词内容：\n\n{lyrics_preview}")
            else:
                yield event.plain_result(f"歌曲《{target_song}》的歌词文件为空")
        except Exception as e:
            logger.error(f"读取歌词文件失败: {str(e)}")
            yield event.plain_result(f"读取歌曲《{target_song}》的歌词失败，请稍后再试")

    async def terminate(self):
        """插件终止时的清理工作"""
        # 保存配置
        self._save_config(self.config)
        logger.info("LyricNext插件已终止")
