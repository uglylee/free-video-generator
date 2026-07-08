"""
Agnes Video Generator v2.0 — 单元测试套件

覆盖 AGENTS.md 第二层单元测试清单：
- models/task.py: 序列化/反序列化、多态 parse_task_state
- core/audio/subtitle.py: SRT 格式输出、_split_long_text 多行换行
- core/config.py: 默认配置结构、resolve_font_path CJK 回退
- core/task_manager.py: 旧数据兼容（无 task_type → CREATIVE）
- core/compositor/concatenator.py: 字幕位置解析（bottom-80/top+N）
- core/pipelines/manuscript_video.py: _step_split_text 拆段算法

用法:
    .venv/bin/python -m pytest tests/ -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ═══════════════════════════════════════════════════
# 1. models/task.py
# ═══════════════════════════════════════════════════

class TestSubtitleStyle:
    """SubtitleStyle bg_color 验证器测试。"""

    def test_default_bg_color(self):
        from models.task import SubtitleStyle
        style = SubtitleStyle()
        assert style.bg_color == (0, 0, 0, 128)

    def test_bg_color_with_alpha_string(self):
        from models.task import SubtitleStyle
        style = SubtitleStyle(bg_color="black@0.5")
        assert style.bg_color == (0, 0, 0, 127)

    def test_bg_color_white_alpha(self):
        from models.task import SubtitleStyle
        style = SubtitleStyle(bg_color="white@0.7")
        assert style.bg_color == (255, 255, 255, 178)

    def test_bg_color_transparent(self):
        from models.task import SubtitleStyle
        # SubtitleStyle.bg_color 类型为 tuple，transparent 解析为 None 会触发 Pydantic 类型错误
        with pytest.raises(Exception):
            SubtitleStyle(bg_color="transparent")

    def test_bg_color_tuple_passthrough(self):
        from models.task import SubtitleStyle
        style = SubtitleStyle(bg_color=(100, 100, 100, 200))
        assert style.bg_color == (100, 100, 100, 200)


class TestParseTaskState:
    """parse_task_state 多态反序列化测试。"""

    def test_simple_task(self):
        from models.task import parse_task_state, SimpleVideoTask, TaskType
        data = {
            "task_id": "test001",
            "task_type": TaskType.SIMPLE,
            "prompt": "test prompt",
            "creative_name": "simple_test001",
        }
        state = parse_task_state(data)
        assert isinstance(state, SimpleVideoTask)
        assert state.task_id == "test001"
        assert state.task_type == TaskType.SIMPLE

    def test_creative_task(self):
        from models.task import parse_task_state, CreativeVideoTask, TaskType
        data = {
            "task_id": "test002",
            "task_type": TaskType.CREATIVE,
            "idea": "test idea",
            "creative_name": "creative_test002",
        }
        state = parse_task_state(data)
        assert isinstance(state, CreativeVideoTask)
        assert state.task_type == TaskType.CREATIVE

    def test_manuscript_task(self):
        from models.task import parse_task_state, ManuscriptVideoTask, TaskType
        data = {
            "task_id": "test003",
            "task_type": TaskType.MANUSCRIPT,
            "manuscript_text": "测试文本",
            "creative_name": "manuscript_test003",
        }
        state = parse_task_state(data)
        assert isinstance(state, ManuscriptVideoTask)
        assert state.task_type == TaskType.MANUSCRIPT

    def test_missing_task_type_defaults_to_creative(self):
        """L6 向后兼容：旧数据没有 task_type 字段，默认识别为 CREATIVE。"""
        from models.task import parse_task_state, CreativeVideoTask
        data = {
            "task_id": "legacy001",
            "creative_name": "legacy_task",
            "idea": "legacy idea",
        }
        state = parse_task_state(data)
        assert isinstance(state, CreativeVideoTask)

    def test_serialization_roundtrip(self):
        """序列化 → 反序列化 roundtrip 测试。"""
        from models.task import parse_task_state, SimpleVideoTask, VideoMode
        original = SimpleVideoTask(
            task_id="rt001",
            creative_name="simple_rt001",
            prompt="roundtrip prompt",
            mode=VideoMode.T2V,
            duration=10,
        )
        data = original.model_dump()
        restored = parse_task_state(data)
        assert isinstance(restored, SimpleVideoTask)
        assert restored.prompt == "roundtrip prompt"
        assert restored.duration == 10


# ═══════════════════════════════════════════════════
# 2. core/audio/subtitle.py
# ═══════════════════════════════════════════════════

class TestSplitLongText:
    """_split_long_text 多行换行测试。"""

    def test_short_text_no_split(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator._split_long_text("短视频", 14) == "短视频"

    def test_empty_text(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator._split_long_text("", 14) == ""

    def test_existing_newline_passthrough(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator._split_long_text("已有\n换行", 14) == "已有\n换行"

    def test_long_cjk_split_at_punctuation(self):
        from core.audio.subtitle import SubtitleGenerator
        result = SubtitleGenerator._split_long_text("今天天气真好，我们一起去公园散步吧", 14)
        assert result == "今天天气真好，\n我们一起去公园散步吧", f"Got: {result!r}"

    def test_long_cjk_split_at_mid(self):
        from core.audio.subtitle import SubtitleGenerator
        result = SubtitleGenerator._split_long_text("这是一段比较长的中文字幕文本需要拆分显示在视频上方", 14)
        assert "\n" in result
        lines = result.split("\n")
        assert len(lines) == 2

    def test_long_english_split_at_word_boundary(self):
        from core.audio.subtitle import SubtitleGenerator
        # 需要超过 14 个单词才会拆分
        result = SubtitleGenerator._split_long_text(
            "This is a very long English subtitle text that should definitely be split into two lines when max chars is small", 8
        )
        assert "\n" in result

    def test_short_english_no_split(self):
        from core.audio.subtitle import SubtitleGenerator
        result = SubtitleGenerator._split_long_text("Short text", 14)
        assert result == "Short text"


class TestCueToSrtTime:
    """cue_to_srt_time 时间格式测试。"""

    def test_zero(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator.cue_to_srt_time(0.0) == "00:00:00,000"

    def test_seconds_and_ms(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator.cue_to_srt_time(2.5) == "00:00:02,500"

    def test_minutes(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator.cue_to_srt_time(65.123) == "00:01:05,123"

    def test_hours(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator.cue_to_srt_time(3661.0) == "01:01:01,000"


# ═══════════════════════════════════════════════════
# 3. core/config.py
# ═══════════════════════════════════════════════════

class TestResolveFontPath:
    """resolve_font_path CJK 回退测试。"""

    def test_non_cjk_font_fallback(self):
        from core.config import resolve_font_path, DEFAULT_CHINESE_FONT
        result = resolve_font_path("Arial")
        assert DEFAULT_CHINESE_FONT in result, f"Expected fallback, got: {result}"

    def test_non_cjk_font_case_insensitive(self):
        from core.config import resolve_font_path, DEFAULT_CHINESE_FONT
        result = resolve_font_path("arial")
        assert DEFAULT_CHINESE_FONT in result

    def test_system_font_passthrough(self):
        from core.config import resolve_font_path
        result = resolve_font_path("NotoSansCJK-Regular")
        # 不在 _NON_CJK_FONTS 里，直接返回系统字体名
        assert result == "NotoSansCJK-Regular"

    def test_absolute_path_existing_file(self):
        from core.config import resolve_font_path, font_dir, DEFAULT_CHINESE_FONT
        abs_path = os.path.join(font_dir(), DEFAULT_CHINESE_FONT)
        if os.path.exists(abs_path):
            assert resolve_font_path(abs_path) == abs_path


class TestDefaultSubtitleStyle:
    """默认字幕样式配置测试。"""

    def test_default_position_is_bottom_80(self):
        from core.config import get_default_subtitle_style
        style = get_default_subtitle_style()
        assert style.position == ("center", "bottom-80")

    def test_default_font_is_cjk(self):
        from core.config import get_default_subtitle_style, DEFAULT_CHINESE_FONT
        style = get_default_subtitle_style()
        assert style.font == DEFAULT_CHINESE_FONT

    def test_default_fontsize(self):
        from core.config import get_default_subtitle_style
        style = get_default_subtitle_style()
        assert style.fontsize == 48


# ═══════════════════════════════════════════════════
# 4. core/compositor/concatenator.py
# ═══════════════════════════════════════════════════

class TestResolveSubtitlePosition:
    """_resolve_subtitle_position 字幕位置解析测试（M1 修复验证）。"""

    def test_bottom_80_with_height(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "bottom-80"), video_height=1152
        )
        assert pos == ("center", 1072)

    def test_top_plus_50(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "top+50"), video_height=1152
        )
        assert pos == ("center", 50)

    def test_plain_bottom(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "bottom"), video_height=1152
        )
        assert pos == ("center", "bottom")

    def test_plain_top(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "top"), video_height=1152
        )
        assert pos == ("center", "top")

    def test_string_bottom(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position("bottom", video_height=1152)
        assert pos == ("center", "bottom")

    def test_string_bottom_80(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position("bottom-80", video_height=1152)
        assert pos == ("center", 1072)

    def test_string_top_plus(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position("top+100", video_height=768)
        assert pos == ("center", 100)

    def test_no_height_fallback(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "bottom-80"), video_height=0
        )
        # 无 video_height 时，bottom-80 无法计算像素，回退到普通 bottom
        assert pos == ("center", "bottom")

    def test_numeric_position_passthrough(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", 500), video_height=1152
        )
        assert pos == ("center", 500)

    def test_default_position(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(None, video_height=1152)
        assert pos == ("center", "bottom")


# ═══════════════════════════════════════════════════
# 5. server.py 辅助函数
# ═══════════════════════════════════════════════════

class TestParseBgColor:
    """_parse_bg_color 解析测试。"""

    def test_black_at_half(self):
        from server import _parse_bg_color
        result = _parse_bg_color("black@0.5")
        assert result == (0, 0, 0, 127)

    def test_white_at_full(self):
        from server import _parse_bg_color
        result = _parse_bg_color("white@1.0")
        assert result == (255, 255, 255, 255)

    def test_transparent(self):
        from server import _parse_bg_color
        assert _parse_bg_color("transparent") is None

    def test_tuple_passthrough(self):
        from server import _parse_bg_color
        assert _parse_bg_color((100, 100, 100, 200)) == (100, 100, 100, 200)

    def test_parenthesis_format(self):
        from server import _parse_bg_color
        result = _parse_bg_color("(50, 60, 70, 80)")
        assert result == (50, 60, 70, 80)


class TestBuildPosition:
    """_build_position 位置构建测试。"""

    def test_top(self):
        from server import _build_position
        assert _build_position("top") == ("center", "top")

    def test_bottom(self):
        from server import _build_position
        assert _build_position("bottom") == ("center", "bottom")

    def test_default_is_bottom(self):
        from server import _build_position
        assert _build_position("something_else") == ("center", "bottom")


class TestParseDuration:
    """_parse_duration 时长解析测试。"""

    def test_each_scene_seconds(self):
        from server import _parse_duration
        assert _parse_duration("3个场景，每个场景5秒") == 5

    def test_each_segment_seconds(self):
        from server import _parse_duration
        assert _parse_duration("每段10秒的视频") == 10

    def test_no_duration_defaults_to_5(self):
        from server import _parse_duration
        assert _parse_duration("一段精彩的视频") == 5


# ═══════════════════════════════════════════════════
# 6. core/pipelines/manuscript_video.py
# ═══════════════════════════════════════════════════

class TestStepSplitText:
    """稿件文本拆分测试（_step_split_text）。"""

    def _make_pipeline(self):
        """构建带 mock _state 的最小化 ManuscriptVideoPipeline 实例。"""
        from core.pipelines.manuscript_video import ManuscriptVideoPipeline
        from models.task import ManuscriptVideoTask
        pipeline = ManuscriptVideoPipeline.__new__(ManuscriptVideoPipeline)
        pipeline._state = ManuscriptVideoTask(
            task_id="test",
            creative_name="test",
            manuscript_text="",
        )
        return pipeline

    def test_short_text_single_paragraph(self):
        pipeline = self._make_pipeline()
        paragraphs = pipeline._step_split_text("这是短句。")
        assert len(paragraphs) >= 1
        assert all(p.text.strip() for p in paragraphs)

    def test_multi_sentence_split(self):
        text = "春天来了。花开了。小鸟在唱歌。孩子们在玩耍。"
        pipeline = self._make_pipeline()
        paragraphs = pipeline._step_split_text(text)
        assert len(paragraphs) >= 1
        combined = "".join(p.text for p in paragraphs)
        assert "春天来了" in combined

    def test_newline_split(self):
        # 使用足够长的段落确保拆分（贪心合并上限 ~12s ≈ 48 字）
        text = (
            "这是第一段内容，讲述了春天的美丽景色，花红柳绿，"
            "小鸟在树枝上唱歌，孩子们在公园里开心地玩耍。\n\n"
            "这是第二段内容，讲述了夏天的故事，阳光灸热，"
            "蝉在树上呜叫，大家在树荫下乘凉，享受着冰凉的西瓜。\n\n"
            "这是第三段内容，讲述了秋天的丰收，金黄的稻田，"
            "红艳艳的苹果挂满枝头，农民们开心地收获着一年的成果。"
        )
        pipeline = self._make_pipeline()
        paragraphs = pipeline._step_split_text(text)
        assert len(paragraphs) >= 2

    def test_empty_text(self):
        pipeline = self._make_pipeline()
        paragraphs = pipeline._step_split_text("")
        assert len(paragraphs) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
