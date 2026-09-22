"""Tests for encoding modes, H.265 10-bit settings, and audio stream copying."""

import unittest
from crunchyroll import resolve_encoding_config, EncodingConfig, get_filter_complex
import config


class TestEncodingModes(unittest.TestCase):
    def test_lossy_mode_defaults(self):
        """Lossy mode should encode video in H.265 10-bit and copy audio losslessly."""
        cfg = resolve_encoding_config(
            mode="lossy",
            use_watermark=True,
            crf=20,
            preset="medium",
            pix_fmt="yuv420p10le",
            output_format="mkv"
        )
        self.assertEqual(cfg.mode, "lossy")
        self.assertEqual(cfg.video_codec, "libx265")
        self.assertEqual(cfg.audio_codec, "copy")
        self.assertTrue(cfg.use_watermark)
        self.assertIn("-pix_fmt", cfg.extra_video_args)
        self.assertIn("yuv420p10le", cfg.extra_video_args)
        self.assertIn("-crf", cfg.extra_video_args)
        self.assertIn("20", cfg.extra_video_args)
        self.assertIn("-preset", cfg.extra_video_args)
        self.assertIn("medium", cfg.extra_video_args)

        args = cfg.get_ffmpeg_args_list()
        self.assertEqual(args, [
            "-c:v", "libx265",
            "-pix_fmt", "yuv420p10le",
            "-crf", "20",
            "-preset", "medium",
            "-c:a", "copy",
            "-c:s", "copy"
        ])

    def test_lossy_aliases(self):
        """Aliases like 'lossyy', 'h265', 'h265_10bit' should normalize to lossy."""
        for alias in ["lossyy", "h265", "h265_10bit", "hevc", "compressed"]:
            cfg = resolve_encoding_config(mode=alias)
            self.assertEqual(cfg.mode, "lossy", f"Failed for alias: {alias}")
            self.assertEqual(cfg.video_codec, "libx265")
            self.assertEqual(cfg.audio_codec, "copy")

    def test_lossy_mp4_tag(self):
        """MP4 output format with libx265 should include -tag:v hvc1."""
        cfg = resolve_encoding_config(mode="lossy", output_format="mp4")
        self.assertIn("-tag:v", cfg.extra_video_args)
        self.assertIn("hvc1", cfg.extra_video_args)

    def test_lossless_mode(self):
        """Lossless mode should use stream copy for video and audio and disable watermark."""
        cfg = resolve_encoding_config(mode="lossless", use_watermark=True)
        self.assertEqual(cfg.mode, "lossless")
        self.assertEqual(cfg.video_codec, "copy")
        self.assertEqual(cfg.audio_codec, "copy")
        self.assertFalse(cfg.use_watermark)
        self.assertEqual(cfg.get_ffmpeg_args_list(), [
            "-c:v", "copy",
            "-c:a", "copy",
            "-c:s", "copy"
        ])

    def test_lossless_aliases(self):
        """Aliases like 'losslessy', 'remux', 'original', 'copy' should normalize to lossless."""
        for alias in ["losslessy", "original", "remux", "copy"]:
            cfg = resolve_encoding_config(mode=alias)
            self.assertEqual(cfg.mode, "lossless", f"Failed for alias: {alias}")
            self.assertEqual(cfg.video_codec, "copy")

    def test_legacy_original_quality_flag(self):
        """Legacy original_quality=True in config should map to lossless mode."""
        cfg = resolve_encoding_config(original_quality=True, use_watermark=True)
        self.assertEqual(cfg.mode, "lossless")
        self.assertEqual(cfg.video_codec, "copy")
        self.assertFalse(cfg.use_watermark)

    def test_custom_mode(self):
        """Custom mode should preserve user-configured codecs."""
        cfg = resolve_encoding_config(
            mode="custom",
            encoding_code="libx264",
            audio_codec="aac",
            crf=23,
            preset="fast"
        )
        self.assertEqual(cfg.mode, "custom")
        self.assertEqual(cfg.video_codec, "libx264")
        self.assertEqual(cfg.audio_codec, "aac")
        self.assertIn("-crf", cfg.extra_video_args)
        self.assertIn("23", cfg.extra_video_args)

    def test_filter_complex(self):
        """get_filter_complex should return valid drawtext filter."""
        fc = get_filter_complex()
        self.assertIn("drawtext", fc)
        self.assertIn("fontfile", fc)
        self.assertIn("ToonTamilIndia", fc)


if __name__ == "__main__":
    unittest.main()
