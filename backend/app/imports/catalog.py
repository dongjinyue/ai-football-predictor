"""Football-Data 公开历史 CSV 文件的集中目录。"""

from datetime import date

from app.imports.models import SourceFile

# www 地址会返回重定向；只生成 Football-Data 当前公开的规范非 www 地址，
# 下载器因此无需无边界地跟随任意外部重定向。
FOOTBALL_DATA_URL_TEMPLATE = "https://football-data.co.uk/mmz4281/{season}/{code}.csv"
FOOTBALL_DATA_COMBINED_URL_TEMPLATE = "https://football-data.co.uk/new/{code}.csv"
SPLIT_YEAR = "split_year"
CALENDAR_YEAR = "calendar_year"
SEASONAL_SCOPE = "seasonal"
COMBINED_SCOPE = "combined"
HISTORICAL_START_YEAR = 2000
HISTORICAL_END_YEAR = 2020

# Extra Leagues（额外联赛）在 Football-Data 的 new/目录提供整合文件，
# 不应再按 mmz4281/{赛季}/{代码}.csv 逐年请求。
COMBINED_COMPETITION_CODES = frozenset(
    {
        "ARG", "AUT", "BRA", "CHN", "DNK", "FIN", "IRL", "JPN",
        "MEX", "NOR", "POL", "ROU", "RUS", "SWE", "SWZ", "USA",
    }
)

# 每项只在此处定义一次，避免下载器、解析器或 API 各自维护联赛地址。
COMPETITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("E0", "English Premier League", "ENG", SPLIT_YEAR),
    ("E1", "English Championship", "ENG", SPLIT_YEAR),
    ("E2", "English League One", "ENG", SPLIT_YEAR),
    ("E3", "English League Two", "ENG", SPLIT_YEAR),
    ("EC", "English National League", "ENG", SPLIT_YEAR),
    ("SC0", "Scottish Premiership", "SCO", SPLIT_YEAR),
    ("SC1", "Scottish Championship", "SCO", SPLIT_YEAR),
    ("SC2", "Scottish League One", "SCO", SPLIT_YEAR),
    ("SC3", "Scottish League Two", "SCO", SPLIT_YEAR),
    ("D1", "German Bundesliga", "DEU", SPLIT_YEAR),
    ("D2", "German 2. Bundesliga", "DEU", SPLIT_YEAR),
    ("I1", "Italian Serie A", "ITA", SPLIT_YEAR),
    ("I2", "Italian Serie B", "ITA", SPLIT_YEAR),
    ("SP1", "Spanish La Liga", "ESP", SPLIT_YEAR),
    ("SP2", "Spanish Segunda Division", "ESP", SPLIT_YEAR),
    ("F1", "French Ligue 1", "FRA", SPLIT_YEAR),
    ("F2", "French Ligue 2", "FRA", SPLIT_YEAR),
    ("N1", "Dutch Eredivisie", "NLD", SPLIT_YEAR),
    ("B1", "Belgian First Division A", "BEL", SPLIT_YEAR),
    ("P1", "Portuguese Primeira Liga", "PRT", SPLIT_YEAR),
    ("T1", "Turkish Super Lig", "TUR", SPLIT_YEAR),
    ("G1", "Greek Super League", "GRC", SPLIT_YEAR),
    ("ARG", "Argentine Primera Division", "ARG", CALENDAR_YEAR),
    ("AUT", "Austrian Bundesliga", "AUT", SPLIT_YEAR),
    ("BRA", "Brazilian Serie A", "BRA", CALENDAR_YEAR),
    ("CHN", "Chinese Super League", "CHN", CALENDAR_YEAR),
    ("DNK", "Danish Superliga", "DNK", SPLIT_YEAR),
    ("FIN", "Finnish Veikkausliiga", "FIN", CALENDAR_YEAR),
    ("IRL", "Irish Premier Division", "IRL", CALENDAR_YEAR),
    ("JPN", "Japanese J-League", "JPN", CALENDAR_YEAR),
    ("MEX", "Mexican Liga MX", "MEX", SPLIT_YEAR),
    ("NOR", "Norwegian Eliteserien", "NOR", CALENDAR_YEAR),
    ("POL", "Polish Ekstraklasa", "POL", SPLIT_YEAR),
    ("ROU", "Romanian Liga 1", "ROU", SPLIT_YEAR),
    ("RUS", "Russian Premier League", "RUS", SPLIT_YEAR),
    ("SWE", "Swedish Allsvenskan", "SWE", CALENDAR_YEAR),
    ("SWZ", "Swiss Super League", "CHE", SPLIT_YEAR),
    ("USA", "Major League Soccer", "USA", CALENDAR_YEAR),
)


def build_default_requests(today: date, seasons: int = 5) -> tuple[SourceFile, ...]:
    """返回每个已配置联赛最近若干个已完成赛季的唯一下载请求。"""
    if seasons < 1:
        raise ValueError("seasons_must_be_positive")
    split_year_seasons = _completed_split_year_seasons(today, seasons)
    calendar_year_seasons = _completed_calendar_year_seasons(today, seasons)
    split_start, split_end = _completed_split_year_bounds(today, seasons)
    calendar_start, calendar_end = _completed_calendar_year_bounds(today, seasons)

    requests: list[SourceFile] = []
    for code, name, country_code, season_style in COMPETITIONS:
        if code in COMBINED_COMPETITION_CODES:
            start_year, end_year = (
                (split_start, split_end)
                if season_style == SPLIT_YEAR
                else (calendar_start, calendar_end)
            )
            requests.append(
                SourceFile(
                    source="football_data",
                    competition_code=code,
                    competition_name=name,
                    country_code=country_code,
                    season=f"{start_year}-{end_year}",
                    url=FOOTBALL_DATA_COMBINED_URL_TEMPLATE.format(code=code),
                    source_scope=COMBINED_SCOPE,
                    start_year=start_year,
                    end_year=end_year,
                    season_style=season_style,
                )
            )
            continue
        seasons_for_competition = (
            split_year_seasons
            if season_style == SPLIT_YEAR
            else calendar_year_seasons
        )
        requests.extend(
            SourceFile(
                source="football_data",
                competition_code=code,
                competition_name=name,
                country_code=country_code,
                season=season,
                url=FOOTBALL_DATA_URL_TEMPLATE.format(season=season, code=code),
                source_scope=SEASONAL_SCOPE,
                season_style=season_style,
            )
            for season in seasons_for_competition
        )
    return tuple(requests)


def build_historical_requests(
    start_year: int,
    end_year: int,
    competition_codes: tuple[str, ...] | None = None,
) -> tuple[SourceFile, ...]:
    """按用户选择的日历范围生成所有联赛的公开源文件请求。

    欧洲联赛使用结束年份编码：2000/01 到 2019/20 对应 ``0001`` 到 ``1920``；
    日历年联赛则直接使用 ``2000`` 到 ``2020``。范围只负责生成稳定 URL，某些
    年份若源站没有文件，会在导入任务中作为单文件失败记录，不会让整批任务中断。
    """
    if not HISTORICAL_START_YEAR <= start_year <= end_year <= HISTORICAL_END_YEAR:
        raise ValueError("historical_year_range_out_of_bounds")

    requested_codes = competition_codes or tuple(item[0] for item in COMPETITIONS)
    competition_by_code = {item[0]: item for item in COMPETITIONS}
    unknown_codes = set(requested_codes) - set(competition_by_code)
    if unknown_codes:
        raise ValueError("unknown_competition_code")

    requests: list[SourceFile] = []
    for code in requested_codes:
        _, name, country_code, season_style = competition_by_code[code]
        if code in COMBINED_COMPETITION_CODES:
            requests.append(
                SourceFile(
                    source="football_data",
                    competition_code=code,
                    competition_name=name,
                    country_code=country_code,
                    season=f"{start_year}-{end_year}",
                    url=FOOTBALL_DATA_COMBINED_URL_TEMPLATE.format(code=code),
                    source_scope=COMBINED_SCOPE,
                    start_year=start_year,
                    end_year=end_year,
                    season_style=season_style,
                )
            )
            continue
        seasons = (
            tuple(
                f"{(year - 1) % 100:02d}{year % 100:02d}"
                for year in range(start_year + 1, end_year + 1)
            )
            if season_style == SPLIT_YEAR
            else tuple(str(year) for year in range(start_year, end_year + 1))
        )
        requests.extend(
            SourceFile(
                source="football_data",
                competition_code=code,
                competition_name=name,
                country_code=country_code,
                season=season,
                url=FOOTBALL_DATA_URL_TEMPLATE.format(season=season, code=code),
                source_scope=SEASONAL_SCOPE,
                season_style=season_style,
            )
            for season in seasons
        )
    return tuple(requests)


def _completed_split_year_seasons(today: date, seasons: int) -> tuple[str, ...]:
    """按欧洲赛季边界计算已结束的 ``YYZZ`` 赛季编号。"""
    latest_end_year = today.year if today.month >= 7 else today.year - 1
    return tuple(
        f"{(end_year - 1) % 100:02d}{end_year % 100:02d}"
        for end_year in range(latest_end_year, latest_end_year - seasons, -1)
    )


def _completed_split_year_bounds(today: date, seasons: int) -> tuple[int, int]:
    """返回最近若干完整欧洲赛季覆盖的起止年份。"""
    latest_end_year = today.year if today.month >= 7 else today.year - 1
    return latest_end_year - seasons, latest_end_year


def _completed_calendar_year_seasons(today: date, seasons: int) -> tuple[str, ...]:
    """日历年联赛只有完整结束后才会被默认范围选中。"""
    return tuple(str(year) for year in range(today.year - 1, today.year - seasons - 1, -1))


def _completed_calendar_year_bounds(today: date, seasons: int) -> tuple[int, int]:
    """返回最近若干个完整日历年的起止年份。"""
    return today.year - seasons, today.year - 1
