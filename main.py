import json
from SdarotFetcher.sdarot_fetcher import SdarotBulkDownload, EpisodeFetcher, SeriesFetcher

if __name__ == '__main__':
    with open(r"./config.json", encoding="utf-8") as json_file:
        config_json = json.load(json_file)

    bulk_downloader = SdarotBulkDownload(config_json["sdarot_url"])
    bulk_downloader.download_whole_series(r"./", config_json["series_name"])
