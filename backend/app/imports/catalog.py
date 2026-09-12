"""Football-Data 公开历史 CSV 文件的集中目录。"""

from datetime import date

from app.imports.models import SourceFile

# www 地址会返回重定向；只生成 Football-Data 当前公开的规范非 www 地址，
# 下载器因此无需无边界地跟随任意外部重定向。
FOOTBALL_DATA_URL_TEMPLATE = "https://football-data.co.uk/mmz4281/{season}/{code}.csv"
SPLIT_YEAR = "split_year"
CALENDAR_YEAR = "calendar_year"

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
    split_year_seasons = _completed_split_year_seasons(today, seasons)
    calendar_year_seasons = _completed_calendar_year_seasons(today, seasons)

    return tuple(
        SourceFile(
            source="football_data",
            competition_code=code,
            competition_name=name,
            country_code=country_code,
            season=season,
            url=FOOTBALL_DATA_URL_TEMPLATE.format(season=season, code=code),
        )
        for code, name, country_code, season_style in COMPETITIONS
        for season in (
            split_year_seasons
            if season_style == SPLIT_YEAR
            else calendar_year_seasons
        )
    )


def _completed_split_year_seasons(today: date, seasons: int) -> tuple[str, ...]:
    """按欧洲赛季边界计算已结束的 ``YYZZ`` 赛季编号。"""
    latest_end_year = today.year if today.month >= 7 else today.year - 1
    return tuple(
        f"{(end_year - 1) % 100:02d}{end_year % 100:02d}"
        for end_year in range(latest_end_year, latest_end_year - seasons, -1)
    )


def _completed_calendar_year_seasons(today: date, seasons: int) -> tuple[str, ...]:
    """日历年联赛只有完整结束后才会被默认范围选中。"""
    return tuple(str(year) for year in range(today.year - 1, today.year - seasons - 1, -1))
