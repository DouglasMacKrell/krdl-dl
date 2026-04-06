#!/usr/bin/env python3
"""Tests for krdl_selenium download completion logic (no browser)."""

import time
from pathlib import Path

import pytest

from csvdl_core import Job
from krdl_selenium import (
    KrdlSeleniumDownloader,
    _canonical_episode_key,
    _container_ext_try_order,
    _container_from_download_href,
    _is_hd_filename,
    _krdl_show_base_url,
    _krdl_show_url_for_file_extension,
    _parse_krdl_size_bytes,
    build_gap_fill_rows,
    discover_canonical_keys_on_disk,
    filter_by_quality_preference,
    filter_scrape_rows_not_on_disk,
    pick_episodes_from_unified_scrape,
)

_MIB = 1024**2


@pytest.fixture
def dl(tmp_path: Path) -> KrdlSeleniumDownloader:
    return KrdlSeleniumDownloader(tmp_path, headless=True)


class TestSavedFilePath:
    def test_exact_match(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        name = "Episode_01.mkv"
        p = tmp_path / name
        p.write_bytes(b"x")
        assert dl._saved_file_path(name) == p

    def test_case_insensitive_basename(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        (tmp_path / "Episode_01.MKV").write_bytes(b"data")
        found = dl._saved_file_path("episode_01.mkv")
        assert found is not None
        assert found.name.lower() == "episode_01.mkv"

    def test_missing_returns_none(self, dl: KrdlSeleniumDownloader):
        assert dl._saved_file_path("nope.mkv") is None


class TestNamedPartialPath:
    def test_exact_crdownload(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        fn = "Show_01.mkv"
        partial = tmp_path / f"{fn}.crdownload"
        partial.write_bytes(b"partial")
        assert dl._named_partial_path(fn) == partial

    def test_case_insensitive_crdownload(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        (tmp_path / "Show_01.MKV.crdownload").write_bytes(b"p")
        found = dl._named_partial_path("show_01.mkv")
        assert found is not None
        assert found.name.lower().endswith(".mkv.crdownload")


class TestIsDownloadFinished:
    def _info(self, filename: str) -> dict:
        return {
            "filename": filename,
            "job": Job(url="https://example.com/x/mkv", name=filename),
            "start_time": 0.0,
            "url": "https://example.com/x/mkv",
        }

    def test_complete_when_file_present(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        fn = "done.mkv"
        (tmp_path / fn).write_bytes(b"12345")
        info = self._info(fn)
        assert dl._is_download_finished(info) is True
        assert "completed" in info

    def test_not_complete_while_partial(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        fn = "busy.mkv"
        (tmp_path / f"{fn}.crdownload").write_bytes(b"growing")
        info = self._info(fn)
        assert dl._is_download_finished(info) is False

    def test_complete_after_partial_removed(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        """Second folder check: file appears when no named .crdownload."""
        fn = "late.mkv"
        info = self._info(fn)
        assert dl._is_download_finished(info) is False
        (tmp_path / fn).write_bytes(b"done")
        assert dl._is_download_finished(info) is True

    def test_final_file_wins_if_partial_still_present(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        """If the .mkv exists, we are done even if a stale .crdownload remains."""
        fn = "x.mkv"
        (tmp_path / fn).write_bytes(b"full")
        (tmp_path / f"{fn}.crdownload").write_bytes(b"stale")
        info = self._info(fn)
        assert dl._is_download_finished(info) is True

    def test_completed_file_found_when_table_name_has_nbsp(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        """Scraped table text may use NBSP where Chrome uses a normal space — still detect done."""
        on_disk = "[FJ-Earthly] Rumble_01_[ABC12345].mkv"
        (tmp_path / on_disk).write_bytes(b"ok")
        info = self._info("[FJ-Earthly]\u00a0Rumble_01_[ABC12345].mkv")
        assert dl._is_download_finished(info) is True

    def test_named_partial_matches_with_nbsp_expected(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        """Named .crdownload is found when the expected basename differs only by NBSP vs space."""
        partial_path = tmp_path / "[x] y.mkv.crdownload"
        partial_path.write_bytes(b"growing")
        info = self._info("[x]\u00a0y.mkv")
        assert dl._is_download_finished(info) is False
        assert dl._named_partial_path(info["filename"]) == partial_path

    def test_not_complete_while_claimed_chrome_partial(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        fn = "episode.mkv"
        (tmp_path / "Unconfirmed 999.crdownload").write_bytes(b"growing")
        info = self._info(fn)
        info["claimed_crdownloads"] = {"Unconfirmed 999.crdownload"}
        assert dl._is_download_finished(info) is False

    def test_complete_when_mkv_appears_after_claimed_partial(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        fn = "episode.mkv"
        info = self._info(fn)
        info["claimed_crdownloads"] = {"Unconfirmed 999.crdownload"}
        assert dl._is_download_finished(info) is False
        (tmp_path / fn).write_bytes(b"done")
        assert dl._is_download_finished(info) is True


class TestTinyPreviewComplete:
    def test_ep000_always_tiny(self, dl: KrdlSeleniumDownloader):
        fn = "[X]_Show_00_[abcd1234].mkv"
        assert _canonical_episode_key(fn) == "ep:000"
        assert dl._is_tiny_preview_complete(fn) is True

    def test_small_file_on_disk(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        fn = "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv"
        assert _canonical_episode_key(fn) == "ep:001"
        (tmp_path / fn).write_bytes(b"x" * 4096)
        assert dl._is_tiny_preview_complete(fn) is True

    def test_large_file_not_tiny(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        fn = "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv"
        (tmp_path / fn).write_bytes(b"z" * (70 * _MIB))
        assert dl._is_tiny_preview_complete(fn) is False

    def test_missing_file_not_tiny_unless_ep000(self, dl: KrdlSeleniumDownloader):
        assert dl._is_tiny_preview_complete("[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv") is False


class TestAbandonStalled:
    def test_abandon_after_long_time_no_file_no_named_partial(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        job = Job(url="u", name="ghost.mkv", status="QUEUED")
        info = {
            "job": job,
            "filename": "ghost.mkv",
            "start_time": time.time() - 950,
            "url": "u",
        }
        assert dl._should_abandon_stalled_download(info) is True
        assert job.status == "FAIL"

    def test_abandon_when_claimed_crdownload_vanished(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        job = Job(url="u", name="gone.mkv", status="QUEUED")
        info = {
            "job": job,
            "filename": "gone.mkv",
            "start_time": time.time() - 30,
            "url": "u",
            "claimed_crdownloads": {"Unconfirmed 12345.crdownload"},
            "claim_vanished_since": time.time() - 305,
        }
        assert dl._should_abandon_stalled_download(info) is True
        assert job.status == "FAIL"

    def test_abandon_when_claimed_vanished_much_sooner_after_byte_progress(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        job = Job(url="u", name="x.mkv", status="QUEUED")
        info = {
            "job": job,
            "filename": "x.mkv",
            "start_time": time.time() - 120,
            "url": "u",
            "claimed_crdownloads": {"x.mkv.crdownload"},
            "claim_vanished_since": time.time() - 80,
            "last_size": 50_000_000,
        }
        assert (
            dl._should_abandon_stalled_download(
                info,
                vanished_partial_grace_sec=300.0,
                vanished_after_progress_grace_sec=75.0,
            )
            is True
        )
        assert job.status == "FAIL"

    def test_no_abandon_vanished_before_progress_grace_without_bytes(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        job = Job(url="u", name="x.mkv", status="QUEUED")
        info = {
            "job": job,
            "filename": "x.mkv",
            "start_time": time.time() - 120,
            "url": "u",
            "claimed_crdownloads": {"x.mkv.crdownload"},
            "claim_vanished_since": time.time() - 80,
        }
        assert (
            dl._should_abandon_stalled_download(
                info,
                vanished_partial_grace_sec=300.0,
                vanished_after_progress_grace_sec=75.0,
            )
            is False
        )

    def test_abandon_frozen_named_partial(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        job = Job(url="u", name="stuck.mkv", status="QUEUED")
        p = tmp_path / "stuck.mkv.crdownload"
        p.write_bytes(b"x")
        info = {
            "job": job,
            "filename": "stuck.mkv",
            "start_time": time.time() - 10000,
            "url": "u",
            "stall_size": 1,
            "stall_since": time.time() - 500,
        }
        assert dl._should_abandon_stalled_download(info) is True
        assert job.status == "FAIL"


class TestPickEpisodesUnifiedScrape:
    def test_combined_table_prefers_mkv_then_mp4_for_missing_episode(self):
        """Same table: E01–E02 mkv + mp4 dupes; E03 only mp4 → E03 is mp4, E01–E02 mkv."""
        mkv_ep1 = "[G]_Show_01_[aaaaaaaa].mkv"
        mkv_ep2 = "[G]_Show_02_[bbbbbbbb].mkv"
        mp4_ep3 = "[G]_Show_03_[cccccccc].mp4"
        unified = [
            ("https://krdl.moe/download/x1/mkv", mkv_ep1, 100 * _MIB),
            ("https://krdl.moe/download/x2/mkv", mkv_ep2, 100 * _MIB),
            ("https://krdl.moe/download/p1/mp4", mkv_ep1.replace(".mkv", ".mp4"), 500 * _MIB),
            ("https://krdl.moe/download/p2/mp4", mkv_ep2.replace(".mkv", ".mp4"), 500 * _MIB),
            ("https://krdl.moe/download/p3/mp4", mp4_ep3, 200 * _MIB),
        ]
        merged, _ranked, chosen = pick_episodes_from_unified_scrape(
            unified,
            "hd",
            ("mkv", "mp4", "avi"),
            strict_container=False,
        )
        assert len(merged) == 3
        names = {t[1] for t in merged}
        assert mkv_ep1 in names and mkv_ep2 in names
        assert mp4_ep3 in names
        assert chosen[_canonical_episode_key(mkv_ep1)] == "mkv"
        assert chosen[_canonical_episode_key(mkv_ep2)] == "mkv"
        assert chosen[_canonical_episode_key(mp4_ep3)] == "mp4"

    def test_strict_drops_other_containers(self):
        fn = "[G]_Show_01_[aaaaaaaa].mkv"
        unified = [
            ("https://krdl.moe/download/a/mkv", fn, 100 * _MIB),
            ("https://krdl.moe/download/b/mp4", fn.replace(".mkv", ".mp4"), 900 * _MIB),
        ]
        merged, ranked, chosen = pick_episodes_from_unified_scrape(
            unified,
            "hd",
            ("mkv", "mp4", "avi"),
            strict_container=True,
        )
        assert len(merged) == 1
        assert chosen[_canonical_episode_key(fn)] == "mkv"
        assert len(ranked[_canonical_episode_key(fn)]) == 1


class TestContainerFromDownloadHref:
    def test_parses_suffix(self):
        assert _container_from_download_href("https://krdl.moe/download/foo/mkv") == "mkv"
        assert _container_from_download_href("https://krdl.moe/download/foo/mkv?x=1") == "mkv"
        assert _container_from_download_href("https://krdl.moe/download/foo/MP4#frag") == "mp4"
        assert _container_from_download_href("https://example.com/nope") is None


class TestContainerExtTryOrder:
    def test_mkv_preference_chain(self):
        assert _container_ext_try_order("mkv", strict=False) == ("mkv", "mp4", "avi")

    def test_mp4_preference_chain(self):
        assert _container_ext_try_order("mp4", strict=False) == ("mp4", "mkv", "avi")

    def test_avi_preference_chain(self):
        assert _container_ext_try_order("avi", strict=False) == ("avi", "mkv", "mp4")

    def test_strict_single(self):
        assert _container_ext_try_order("mp4", strict=True) == ("mp4",)


class TestKrdlShowUrlForExtension:
    def test_base_show_appends_format(self):
        assert (
            _krdl_show_url_for_file_extension("https://krdl.moe/show/chikyu-sentai-fiveman", "mkv")
            == "https://krdl.moe/show/chikyu-sentai-fiveman/mkv"
        )

    def test_already_suffix_unchanged(self):
        u = "https://krdl.moe/show/chikyu-sentai-fiveman/mkv"
        assert _krdl_show_url_for_file_extension(u, "mkv") == u

    def test_replace_previous_format_segment(self):
        assert (
            _krdl_show_url_for_file_extension(
                "https://krdl.moe/show/chikyu-sentai-fiveman/mp4", "mkv"
            )
            == "https://krdl.moe/show/chikyu-sentai-fiveman/mkv"
        )

    def test_base_url_strips_format(self):
        assert (
            _krdl_show_base_url("https://krdl.moe/show/chikyu-sentai-fiveman/mkv")
            == "https://krdl.moe/show/chikyu-sentai-fiveman"
        )


class TestCanonicalEpisodeKey:
    def test_changeman_tkp_and_guis_share_episode_keys(self):
        tkp = "[TKP]_Dengeki_Sentai_Changeman_-_02_v2_[9f268995].mkv"
        guis = "[G.U.I.S.]_Dengeki_Sentai_Changeman_02_[0833B2A3].mkv"
        assert _canonical_episode_key(tkp) == _canonical_episode_key(guis) == "ep:002"

    def test_battle_fever_sd_and_hd_share_episode_key(self):
        sd = "[BernSubs]Battle_Fever_J_41_[DFCDCDCD].mkv"
        hd = "[BernSubs]_Battle_Fever_J_Ep41_HD_[33c10c6f].mkv"
        assert _canonical_episode_key(sd) == _canonical_episode_key(hd) == "ep:041"

    def test_nemet_dash_number_same_key_as_bern(self):
        n = "[Nemet]_Battle_Fever_J_-_01_[141b608a].mkv"
        b = "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv"
        assert _canonical_episode_key(n) == _canonical_episode_key(b) == "ep:001"

    def test_movie_sd_and_hd_same_key(self):
        sd = "[BernSubs]Battle_Fever_J_Movie_[9AAFA9C5].mkv"
        hd = "[BernSubs]_Battle_Fever_J_The_Movie_HD_[8d42921e].mkv"
        assert _canonical_episode_key(sd) == _canonical_episode_key(hd) == "movie"

    def test_sun_vulcan_movie_variants_same_key(self):
        gsf = "[GSF!]_Taiyo_Sentai_Sun_Vulcan_The_Movie_v2_[ae014c07].mkv"
        zichz = "[Zichz_Scrubbed]_Solar_Sentai_Sun_Vulcan_The_Movie_1080p_[d1ff7205].mkv"
        assert _canonical_episode_key(gsf) == _canonical_episode_key(zichz) == "movie"

    def test_unknown_named_gets_unique_keys(self):
        a = "[SomeGroup]_Weird_Release.mkv"
        b = "[SomeGroup]_Other_Stuff.mkv"
        assert _canonical_episode_key(a) != _canonical_episode_key(b)

    def test_tn_gekiranger_dash_ep_bracket_matches_gs_earthly_numbered(self):
        tn = "[T-N]Jyuken_Sentai_Gekiranger_-_01[FFF99938].avi"
        tn_dvd = "[T-N]Jyuken_Sentai_GekiRanger_-_01DVD[C63B6B81]7thAnniversary.avi"
        gs = "[GS-Earthly]_Beast_Fist_Squadron_Gekiranger_01_[1FC3BFC0].mkv"
        assert (
            _canonical_episode_key(tn)
            == _canonical_episode_key(tn_dvd)
            == _canonical_episode_key(gs)
            == "ep:001"
        )

    def test_tn_gekiranger_hd_mp4_anniversary_same_ep_key(self):
        mp4 = "[T-N]Jyuken_Sentai_Gekiranger_01_HD[E8C4AFAE]7thAnniversary.mp4"
        gs = "[GS-Earthly]_Beast_Fist_Squadron_Gekiranger_01_[1FC3BFC0].mkv"
        assert _canonical_episode_key(mp4) == _canonical_episode_key(gs) == "ep:001"

    def test_tn_gekiranger_movie_bracket_is_movie_key_distinct_from_hong_kong(self):
        tn = "[T-N]Jyuken_Sentai_GekiRanger_-_Movie[68D57B09].avi"
        gs_hk = (
            "[GS-Earthly]_Beast_Fist_Squadron_Gekiranger_-_The_Movie_-_Teamy_Worky!_"
            "Grand_Hong_Kong_Battle!_[5C0ACE3B].mkv"
        )
        assert _canonical_episode_key(tn) == "movie"
        assert _canonical_episode_key(gs_hk) == "movie:hong_kong"

    def test_gekiranger_vs_boukenger_cross_release_key(self):
        tn = "[T-N]JyuKen_Sentai_GekiRanger_Vs_GoGo_Sentai_Boukenger[AEEFCD79]DVD.avi"
        gs = "[GS-Earthly]_Beast_Fist_Squadron_Gekiranger_VS_Boukenger_[5F1E2710].mkv"
        assert _canonical_episode_key(tn) == _canonical_episode_key(gs) == "special:gekiranger_vs_boukenger"

    def test_shinkenger_tn_hd1080_mp4_matches_overtime_mkv(self):
        ot3 = "[Over-Time]_Samurai_Sentai_Shinkenger_-_03_[BD720]_[4B9A1DD2].mkv"
        tn3 = "[T-N]Samurai_Sentai_Shinkenger_03_HD1080[8CFE9BB3]Blu.mp4"
        ot5 = "[Over-Time]_Samurai_Sentai_Shinkenger_-_05_[BD720]_[538E9B69].mkv"
        tn5 = "[T-N]Samurai_Sentai_Shinkenger_05_HD1080Blu[8DA5E4D3].mp4"
        ot1 = "[Over-Time]_Samurai_Sentai_Shinkenger_-_01_[BD720]_[9A13E173][DC].mkv"
        tn1dc = "[T-N]Samurai_Sentai_Shinkenger_01DC_HD1080[BA8D1871]BluV2.mp4"
        assert _canonical_episode_key(ot3) == _canonical_episode_key(tn3) == "ep:003"
        assert _canonical_episode_key(ot5) == _canonical_episode_key(tn5) == "ep:005"
        assert _canonical_episode_key(ot1) == _canonical_episode_key(tn1dc) == "ep:001"


class TestIsHdFilename:
    def test_hd_tag(self):
        assert _is_hd_filename("[BernSubs]_Battle_Fever_J_Ep41_HD_[x].mkv") is True

    def test_sd_not_hd(self):
        assert _is_hd_filename("[BernSubs]Battle_Fever_J_41_[DFCDCDCD].mkv") is False


class TestParseKrdlSizeBytes:
    def test_mib(self):
        assert _parse_krdl_size_bytes("244.85 MiB") == int(244.85 * _MIB)

    def test_gib(self):
        assert _parse_krdl_size_bytes("1.19 GiB") == int(1.19 * 1024**3)

    def test_plain_mib(self):
        assert _parse_krdl_size_bytes("304 MiB") == 304 * _MIB

    def test_unknown_returns_none(self):
        assert _parse_krdl_size_bytes("n/a") is None


class TestFilterByQualityPreference:
    def test_prefers_larger_file_for_hd_mode(self):
        rows = [
            ("u1", "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv", 250 * _MIB),
            ("u2", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", 600 * _MIB),
        ]
        out, _ranked = filter_by_quality_preference(rows, "hd")
        assert out == [("u2", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", 600 * _MIB)]

    def test_larger_non_hd_beats_smaller_hd(self):
        """Site-reported size overrides misleading filenames."""
        rows = [
            ("u_big", "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv", 700 * _MIB),
            ("u_small", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", 300 * _MIB),
        ]
        out, _ranked = filter_by_quality_preference(rows, "hd")
        assert out == [("u_big", "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv", 700 * _MIB)]

    def test_same_size_prefers_hd_marker(self):
        sz = 600 * _MIB
        rows = [
            ("u1", "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv", sz),
            ("u2", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", sz),
        ]
        out, _ranked = filter_by_quality_preference(rows, "hd")
        assert out == [("u2", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", sz)]

    def test_prefers_smaller_file_for_sd_mode(self):
        rows = [
            ("u1", "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv", 250 * _MIB),
            ("u2", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", 600 * _MIB),
        ]
        out, _ranked = filter_by_quality_preference(rows, "sd")
        assert out == [("u1", "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv", 250 * _MIB)]

    def test_falls_back_to_sd_when_no_hd(self):
        rows = [("u1", "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv", 250 * _MIB)]
        out, _ranked = filter_by_quality_preference(rows, "hd")
        assert out == rows

    def test_falls_back_to_hd_when_no_sd(self):
        rows = [("u2", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", 600 * _MIB)]
        out, _ranked = filter_by_quality_preference(rows, "sd")
        assert out == rows

    def test_sd_among_two_non_hd_picks_smaller(self):
        rows = [
            ("u_sd", "[BernSubs]Battle_Fever_J_05_[aaaaaaaa].mkv", 280 * _MIB),
            ("u_nm", "[Nemet]_Battle_Fever_J_-_05_[bbbbbbbb].mkv", 320 * _MIB),
        ]
        out, _ranked = filter_by_quality_preference(rows, "sd")
        assert out == [("u_sd", "[BernSubs]Battle_Fever_J_05_[aaaaaaaa].mkv", 280 * _MIB)]

    def test_three_way_hd_picks_largest(self):
        rows = [
            ("u_sd", "[BernSubs]Battle_Fever_J_07_[aaaaaaaa].mkv", 250 * _MIB),
            ("u_nm", "[Nemet]_Battle_Fever_J_-_07_[bbbbbbbb].mkv", 320 * _MIB),
            ("u_hd", "[BernSubs]_Battle_Fever_J_Ep07_HD_[cccccccc].mkv", 650 * _MIB),
        ]
        out, _ranked = filter_by_quality_preference(rows, "hd")
        assert out == [("u_hd", "[BernSubs]_Battle_Fever_J_Ep07_HD_[cccccccc].mkv", 650 * _MIB)]

    def test_unknown_size_loses_to_known_for_hd(self):
        rows = [
            ("u1", "[BernSubs]Battle_Fever_J_01_[922C3BDB].mkv", None),
            ("u2", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", 100 * _MIB),
        ]
        out, _ranked = filter_by_quality_preference(rows, "hd")
        assert out == [("u2", "[BernSubs]_Battle_Fever_J_Ep01_HD_[eb30230c].mkv", 100 * _MIB)]

    def test_hd_prefers_higher_v_over_larger_base_file(self):
        base = ("ub", "[MF]_Choushinsei_Flashman_01_[0b7b8f86].mkv", 500 * _MIB)
        v2 = ("uv", "[MF]_Choushinsei_Flashman_01_v2_[d270d850].mkv", 100 * _MIB)
        out, _ranked = filter_by_quality_preference([base, v2], "hd")
        assert out == [v2]

    def test_hd_prefers_v3_over_v2_when_both_versioned(self):
        v2 = ("u2", "[X]_Show_01_v2_[aaaaaaaa].mkv", 400 * _MIB)
        v3 = ("u3", "[X]_Show_01_v3_[bbbbbbbb].mkv", 200 * _MIB)
        out, _ranked = filter_by_quality_preference([v2, v3], "hd")
        assert out == [v3]

    def test_sd_prefers_higher_v_then_smaller_size(self):
        base = ("ub", "[X]_Show_01_[aaaaaaaa].mkv", 100 * _MIB)
        v2 = ("uv", "[X]_Show_01_v2_[bbbbbbbb].mkv", 300 * _MIB)
        out, _ranked = filter_by_quality_preference([base, v2], "sd")
        assert out == [v2]

    def test_sd_same_version_prefers_smaller_file(self):
        a = ("a", "[X]_Show_01_[aaaaaaaa].mkv", 200 * _MIB)
        b = ("b", "[X]_Show_01_[bbbbbbbb].mkv", 100 * _MIB)
        out, _ranked = filter_by_quality_preference([a, b], "sd")
        assert out == [b]

    def test_changeman_hd_prefers_larger_tkp_over_guis(self):
        """Site sizes from KRDL: TKP ep02 MKV is larger than G.U.I.S."""
        tkp = ("utk2", "[TKP]_Dengeki_Sentai_Changeman_-_02_v2_[9f268995].mkv", int(294.75 * _MIB))
        guis = ("ug2", "[G.U.I.S.]_Dengeki_Sentai_Changeman_02_[0833B2A3].mkv", int(291.38 * _MIB))
        out, ranked = filter_by_quality_preference([guis, tkp], "hd")
        assert out == [tkp]
        assert ranked["ep:002"][0] == tkp
        assert ranked["ep:002"][1] == guis

    def test_gap_fill_queues_second_release_when_key_missing_on_disk(self, tmp_path):
        tkp = ("utk2", "[TKP]_Dengeki_Sentai_Changeman_-_02_v2_[9f268995].mkv", int(294.75 * _MIB))
        guis = ("ug2", "[G.U.I.S.]_Dengeki_Sentai_Changeman_02_[0833B2A3].mkv", int(291.38 * _MIB))
        t01 = ("u1", "[TKP]_Dengeki_Sentai_Changeman_-_01_v2_[c251747e].mkv", int(293 * _MIB))
        _o, ranked = filter_by_quality_preference([t01, tkp, guis], "hd")
        # Simulate episode 01 on disk only; ep002 missing
        f01 = tmp_path / "[TKP]_Dengeki_Sentai_Changeman_-_01_v2_[c251747e].mkv"
        f01.write_bytes(b"x")
        gap = build_gap_fill_rows(ranked, tmp_path, ("mkv",))
        assert len(gap) == 1
        assert gap[0][1] == guis[1]
        assert discover_canonical_keys_on_disk(tmp_path, "mkv") == {"ep:001"}


class TestFilterScrapeRowsCanonicalDedupe:
    def test_skips_avi_when_mkv_same_episode_key_on_disk(self, tmp_path: Path):
        mk = (
            "[GS-Earthly]_Beast_Fist_Squadron_Gekiranger_08_[aaaaaaaa].mkv",
        )
        av = "[T-N]Jyuken_Sentai_Gekiranger_-_08[FFFFFFFF].avi"
        (tmp_path / mk[0]).write_bytes(b"x")
        rows = [
            ("https://krdl.moe/download/x/avi", av, 100),
            ("https://krdl.moe/download/y/mkv", mk[0], 200),
        ]
        out = filter_scrape_rows_not_on_disk(
            rows,
            tmp_path,
            ("mkv", "mp4", "avi"),
            log_skips=False,
            skip_if_canonical_key_on_disk=True,
        )
        assert out == []

    def test_unique_keys_not_skipped_by_other_unique(self, tmp_path: Path):
        (tmp_path / "promo_a.avi").write_bytes(b"x")
        rows = [("https://krdl.moe/download/p/b.avi", "promo_b.avi", 10)]
        out = filter_scrape_rows_not_on_disk(
            rows,
            tmp_path,
            ("avi",),
            log_skips=False,
            skip_if_canonical_key_on_disk=True,
        )
        assert len(out) == 1
