"""網址解析的單元測試，不需要網路。執行：python -m unittest test_downloader"""

import unittest

from downloader import TweetVideoError, parse_tweet_url


class ParseTweetUrlTest(unittest.TestCase):
    def test_normalizes_hosts_and_query(self):
        for raw in [
            "https://twitter.com/SpaceX/status/1732824684683784516",
            "https://mobile.twitter.com/SpaceX/status/1732824684683784516?s=20",
            "x.com/SpaceX/status/1732824684683784516",
            "https://vxtwitter.com/SpaceX/status/1732824684683784516/",
            "  https://X.com/SpaceX/status/1732824684683784516#m  ",
        ]:
            ref = parse_tweet_url(raw)
            self.assertEqual(ref.url, "https://x.com/SpaceX/status/1732824684683784516", raw)
            self.assertIsNone(ref.index)

    def test_web_status_path(self):
        ref = parse_tweet_url("https://twitter.com/i/web/status/123")
        self.assertEqual(ref.url, "https://x.com/i/status/123")

    def test_video_index(self):
        ref = parse_tweet_url("https://x.com/user/status/123/video/2")
        self.assertEqual((ref.tweet_id, ref.index), ("123", 2))

    def test_rejects_other_sites_and_paths(self):
        for raw in [
            "https://youtube.com/watch?v=abc",
            "https://x.com.evil.example/user/status/123",
            "https://x.com/SpaceX",
            "https://x.com/user/status/abc",
            "ftp://x.com/user/status/123",
        ]:
            with self.assertRaises(TweetVideoError, msg=raw):
                parse_tweet_url(raw)


if __name__ == "__main__":
    unittest.main()
