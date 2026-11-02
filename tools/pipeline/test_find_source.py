import os
import shutil
import tempfile
import unittest

from tools.pipeline.find_source import SourceLookupError, find_source


class FindSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "project")
        self.uploads = os.path.join(self.root, "uploads", "hearth")
        os.makedirs(self.uploads)
        self.roots = (self.root, self.uploads)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def touch(self, folder, name):
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(b"x")
        return path

    def test_full_id_in_project_root(self):
        path = self.touch(self.root, "6a7883b922f3bf53872c93f3.mp4")
        self.assertEqual(find_source("6a7883b922f3bf53872c93f3", self.roots), path)

    def test_prefix_in_uploads_without_extension(self):
        path = self.touch(self.uploads, "6a2d673972d4c0af3466b84b")
        self.assertEqual(find_source("6a2d", self.roots), path)

    def test_match_is_case_insensitive(self):
        path = self.touch(self.root, "6a7883b922f3bf53872c93f3.mp4")
        self.assertEqual(find_source("6A7", self.roots), path)

    def test_surrounding_whitespace_is_ignored(self):
        path = self.touch(self.root, "6a7883b922f3bf53872c93f3.mp4")
        self.assertEqual(find_source("  6a7 ", self.roots), path)

    def test_no_match_fails_loudly(self):
        self.touch(self.root, "6a7883b922f3bf53872c93f3.mp4")
        with self.assertRaisesRegex(SourceLookupError, "no source file found"):
            find_source("68f", self.roots)

    def test_two_matches_fail_loudly(self):
        self.touch(self.root, "6887385acd24b90ef57fdcc0.mp4")
        self.touch(self.root, "6887385acd24b90ef57fdcc0 (1).mp4")
        with self.assertRaisesRegex(SourceLookupError, "2 source files match"):
            find_source("6887385acd24b90ef57fdcc0", self.roots)

    def test_two_matches_across_folders_fail_loudly(self):
        self.touch(self.root, "6a2d673972d4c0af3466b84b.mp4")
        self.touch(self.uploads, "6a2d673972d4c0af3466b84b")
        with self.assertRaisesRegex(SourceLookupError, "2 source files match"):
            find_source("6a2d", self.roots)

    def test_longer_id_resolves_collision(self):
        a = self.touch(self.root, "6a2d673972d4c0af3466b84b.mp4")
        self.touch(self.root, "6a2d000000000000000000ff.mp4")
        self.assertEqual(find_source("6a2d6739", self.roots), a)

    def test_non_video_files_are_ignored(self):
        self.touch(self.root, "6a7883b922f3bf53872c93f3.txt")
        self.touch(self.root, "6a7883b922f3bf53872c93f3.json")
        with self.assertRaises(SourceLookupError):
            find_source("6a7883b9", self.roots)

    def test_subfolder_outputs_are_not_searched(self):
        build = os.path.join(self.root, "clips", "6a78")
        os.makedirs(build)
        self.touch(build, "6a7883b922f3bf53872c93f3_build_v1.mp4")
        with self.assertRaises(SourceLookupError):
            find_source("6a7883b9", self.roots)

    def test_missing_root_is_skipped(self):
        path = self.touch(self.root, "6a7883b922f3bf53872c93f3.mp4")
        missing = os.path.join(self.tmp, "does-not-exist")
        self.assertEqual(find_source("6a7", (missing, self.root)), path)

    def test_short_query_is_rejected(self):
        self.touch(self.root, "6a7883b922f3bf53872c93f3.mp4")
        with self.assertRaisesRegex(SourceLookupError, "too short"):
            find_source("6a", self.roots)

    def test_empty_query_is_rejected(self):
        with self.assertRaises(SourceLookupError):
            find_source("", self.roots)

    def test_non_hex_query_is_rejected(self):
        self.touch(self.root, "6a7883b922f3bf53872c93f3.mp4")
        with self.assertRaisesRegex(SourceLookupError, "hex"):
            find_source("naf", self.roots)

    def test_non_text_query_is_rejected(self):
        with self.assertRaises(SourceLookupError):
            find_source(None, self.roots)


if __name__ == "__main__":
    unittest.main()
