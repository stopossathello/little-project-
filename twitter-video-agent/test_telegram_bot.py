"""bot 訊息解析的單元測試，不需要網路。執行：python -m unittest test_telegram_bot"""

import unittest

from telegram_bot import find_tweets, parse_options


class FindTweetsTest(unittest.TestCase):
    def test_finds_links_in_text(self):
        refs = find_tweets(
            "看這個 https://x.com/SpaceX/status/1732824684683784516?s=46&t=abc，"
            "還有（twitter.com/user/status/123/video/2）"
        )
        self.assertEqual(
            [(r.url, r.index) for r in refs],
            [("https://x.com/SpaceX/status/1732824684683784516", None), ("https://x.com/user/status/123", 2)],
        )

    def test_link_right_after_chinese_text(self):
        refs = find_tweets("幫我抓x.com/a/status/9謝謝，還有https://x.com/b/status/8。")
        self.assertEqual([r.tweet_id for r in refs], ["9", "8"])

    def test_deduplicates_and_includes_hidden_links(self):
        refs = find_tweets(
            "https://x.com/a/status/1 https://twitter.com/a/status/1",
            ["https://x.com/b/status/2"],
        )
        self.assertEqual([r.tweet_id for r in refs], ["1", "2"])

    def test_ignores_other_sites(self):
        self.assertEqual(find_tweets("https://netflix.com/user/status/1 https://youtube.com/watch?v=1"), [])
        self.assertEqual(find_tweets("https://x.com/SpaceX"), [])


class ParseOptionsTest(unittest.TestCase):
    def test_height_and_audio(self):
        self.assertEqual(parse_options("https://x.com/a/status/1 720p"), (720, False))
        self.assertEqual(parse_options("只要音訊 https://x.com/a/status/1"), (None, True))
        self.assertEqual(parse_options("https://x.com/a/status/1"), (None, False))

    def test_ignores_numbers_inside_links(self):
        self.assertEqual(parse_options("https://x.com/user720p/status/1080"), (None, False))


if __name__ == "__main__":
    unittest.main()
