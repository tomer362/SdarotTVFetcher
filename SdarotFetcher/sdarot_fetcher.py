import asyncio
import json
from pathlib import Path

import aiofiles
import aiohttp
from bs4 import BeautifulSoup
from pathvalidate import sanitize_filename


class BaseFetcher(object):
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/72.0.3626.121 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.sdarot.services/watch"
    }

    USER_AGENT_HEADER = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/72.0.3626.121 Safari/537.36"
    }

    @staticmethod
    async def _fetch_post(session, url, headers=None, data=None, cookies=None):
        return session.post(url, headers=headers, data=data, cookies=cookies)

    @staticmethod
    async def _fetch(session, url):
        return session.get(url)

    @staticmethod
    async def _fetch_stream_to_file(url, output_path, data=None, headers=None, cookies=None):
        async with aiohttp.ClientSession() as session:
            async with session.get(url, data=data, headers=headers, cookies=cookies, timeout=None) as response:
                async with aiofiles.open(output_path, "wb") as f:
                    while True:
                        chunk = await response.content.read(1024 * 4)
                        if not chunk:
                            break
                        await f.write(chunk)


class EpisodeFetcher(BaseFetcher):
    def __init__(self, sdarot_root_url, sid, season, episode):
        self.__sdarot_root_url = sdarot_root_url
        self.__ajax_watch_page = "https://{}//ajax/watch".format(self.__sdarot_root_url)
        self.sid = sid
        self.season = season
        self.episode = episode

    async def __create_new_pre_watch_token(self):
        form_data = {"preWatch": "true", "SID": self.sid, "season": self.season, "ep": self.episode}
        print (form_data)

        async with aiohttp.ClientSession() as session:
            async with await self._fetch_post(session, self.__ajax_watch_page, headers=self.HEADERS,
                                              data=form_data) as response:
                response_text = await response.text()
            response_cookies = response.cookies

        return response_text, response_cookies

    async def __get_episode_metadata(self, pre_watch_token, cookies):
        form_data = {"watch": "false", "token": pre_watch_token, "serie": self.sid, "season": self.season,
                     "episode": self.episode, "type": "episode"}
        print (form_data)

        async with aiohttp.ClientSession() as session:
            async with await self._fetch_post(session, self.__ajax_watch_page, headers=self.HEADERS, data=form_data,
                                              cookies=cookies) as response:
                if response.status != 200:
                    raise Exception("Couldn't fetch rest api, got status code: {}".format(response.status))

                response_metadata = json.loads(await response.text())

        return response_metadata

    def __format_episode_source_url(self, cdn_domain_name, watch_number, vid_number, video_token, video_time,
                                    video_uid):
        print("https://{}/w/episode/{}/{}.mp4?token={}&time={}&uid={}".format(cdn_domain_name, watch_number,
                                                                                   vid_number,
                                                                                   video_token, video_time, video_uid))
        return "https://{}/w/episode/{}/{}.mp4?token={}&time={}&uid={}".format(cdn_domain_name, watch_number,
                                                                                   vid_number,
                                                                                   video_token, video_time, video_uid)

    def __get_episode_source_url_from_metadata(self, episode_metadata):
        temp_list = [[key, value] for key, value in episode_metadata["watch"].items()]
        watch_number = temp_list[0][0]
        video_token = temp_list[0][1]

        cdn_domain_name = episode_metadata["url"]
        vid_number = episode_metadata["VID"]
        video_time = episode_metadata["time"]
        video_uid = episode_metadata["uid"]

        return self.__format_episode_source_url(cdn_domain_name, watch_number, vid_number, video_token, video_time,
                                                video_uid)

    async def get_episode_url(self):
        pre_watch_token, cookies = await self.__create_new_pre_watch_token()
        await asyncio.sleep(31)
        episode_metadata = await self.__get_episode_metadata(pre_watch_token, cookies)

        return self.__get_episode_source_url_from_metadata(episode_metadata), episode_metadata, cookies

    async def download_episode(self, output_path):
        episode_url, metadata, cookies = await self.get_episode_url()

        await self._fetch_stream_to_file(episode_url, output_path, data={"time": metadata["time"], "token": metadata["watch"]["480"], "uid": metadata["uid"]}, headers=self.USER_AGENT_HEADER, cookies=cookies)


class SeriesFetcher(BaseFetcher):
    AJAX_INDEX_PAGE_FORMAT = "https://{}/ajax/index?search="
    AJAX_EPISODES_LIST_FORMAT = "https://{}/ajax/watch?episodeList={}&season={}"
    SERIES_ROOT_PAGE_FORMAT = "https://{}/watch/{}"

    def __init__(self, sdarot_root_url, series_name):
        self.sdarot_root_url = sdarot_root_url
        self.sdarot_ajax_index_url = self.AJAX_INDEX_PAGE_FORMAT.format(sdarot_root_url)
        self.series_name = series_name

    async def fetch_series_search_results(self):
        async with aiohttp.ClientSession() as session:
            async with await self._fetch(session,
                                         "{}{}".format(self.sdarot_ajax_index_url, self.series_name)) as response:
                if response.status != 200:
                    raise Exception(
                        "Fetch series search results failed, status code is {}".format(response.status))

                result = json.loads(await response.text())
        return result

    async def get_series_season_amount(self):
        results = await self.fetch_series_search_results()
        top_match = results[0]

        async with aiohttp.ClientSession() as session:
            async with await self._fetch(session, self.SERIES_ROOT_PAGE_FORMAT.format(self.sdarot_root_url,
                                                                                      top_match["id"])) as response:
                soup = BeautifulSoup(await response.text(), 'html.parser')

        return len(soup.find_all(id="season")[0].find_all("a"))

    async def get_season_episodes_amount(self, season_number):
        results = await self.fetch_series_search_results()
        top_match = results[0]

        async with aiohttp.ClientSession() as session:
            async with await self._fetch(session,
                                         self.AJAX_EPISODES_LIST_FORMAT.format(self.sdarot_root_url, top_match["id"],
                                                                               season_number)) as response:
                soup = BeautifulSoup(await response.text(), 'html.parser')

        return len(soup.find_all("a"))


class SdarotBulkDownload(BaseFetcher):
    def __init__(self, sdarot_root_url):
        self.sdarot_root_url = sdarot_root_url

    async def execute_async_with_semaphore(self, sem, func):
        async with sem:
            await func

    def download_whole_season(self, output_path, series_name, season):
        loop = asyncio.get_event_loop()

        series_fetcher = SeriesFetcher(self.sdarot_root_url, series_name)
        episodes_number = loop.run_until_complete(series_fetcher.get_season_episodes_amount(season))

        search_result = loop.run_until_complete(series_fetcher.fetch_series_search_results())
        if search_result == 0:
            raise Exception("Found 0 results for {} series".format(series_name))

        if episodes_number == 0:
            return

        series_id = search_result[0]['id']
        series_name = search_result[0]['name']

        tasks = []
        sem = asyncio.Semaphore(3)

        for i in range(1, episodes_number + 1):
            episode_fetcher = EpisodeFetcher(self.sdarot_root_url, series_id, season, i)

            curr_task = self.execute_async_with_semaphore(sem, episode_fetcher.download_episode(
                Path(output_path,
                     sanitize_filename(
                         "{}_{}_{}.mp4".format(
                             series_name,
                             season, i),
                         replacement_text="_"))))
            tasks.append(curr_task)

        loop.run_until_complete(asyncio.gather(*tasks))

    def download_whole_series(self, output_path, series_name):
        loop = asyncio.get_event_loop()
        series_fetcher = SeriesFetcher(self.sdarot_root_url, series_name)

        seasons_number = loop.run_until_complete(series_fetcher.get_series_season_amount())
        if seasons_number == 0:
            raise Exception("Found 0 seasons in the series: {}".format(series_name))

        for curr_season_num in range(1, seasons_number + 1):
            self.download_whole_season(output_path, series_name, curr_season_num)
