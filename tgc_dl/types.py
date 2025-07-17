import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from bs4 import BeautifulSoup, Tag
from requests_cache import CachedSession

from .exceptions import CourseTitleNotFound, LectureIdNotFound, ProfessorNameNotFound

session = CachedSession(
    "the_great_courses_plus",
    backend="sqlite",
    expire_after=timedelta(days=3),
)


HEADERS = {
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "empty",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",
    "DNT": "1",
    "Accept": "*/*",
    "Origin": "https://www.thegreatcoursesplus.com",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Referer": "https://www.thegreatcoursesplus.com",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7,da;q=0.6,es;q=0.5",
}


class Course:
    """
    Represents a course page and extracts relevant information from its HTML.
    Args:
        url (str): The URL of the course page.
        cookies (dict[str, str]): Cookies required for authentication.
    Attributes:
        url (str): The URL of the course.
        cookies (dict[str, str]): Authentication cookies.
        title (str): The cleaned course title.
        professor_name (str): The name of the professor, or empty string if not found.
        guidebook_url (str): URL to the course guidebook, or None if not found.
        description (str): The course description.
        ids (str): The base lecture ID string.
        lectures (list[Lecture]): List of Lecture objects parsed from the course page.
    Raises:
        CourseTitleNotFound: If the course title cannot be found.
        LectureIdNotFound: If lecture IDs cannot be found or parsed.
    Notes:
        - Extracts course title, professor name, guidebook URL, description, and lectures.
        - Handles variations in HTML structure for professor name and guidebook.
        - Parses lecture information including ID, index, title, description, and manifest URL.
        - Logs warnings if lecture parsing fails or manifest URL is missing.
    """

    def __init__(self, url: str, cookies: dict[str, str]):
        self.url = url
        self.cookies = cookies

        course_html = session.get(self.url, cookies=cookies, headers=HEADERS).text
        soup = BeautifulSoup(course_html, "html.parser")

        # Course Title
        title_tag = soup.find("div", class_="course-info-container")
        if (
            isinstance(title_tag, Tag)
            and title_tag.h1
            and hasattr(title_tag.h1, "text")
        ):
            self.title = self._clean_filename(title_tag.h1.text.strip())
        else:
            raise CourseTitleNotFound("Could not find the course title.")

        # with Path.cwd().joinpath(f"{self.title}.html").open("wb") as f:
        #     f.write(soup.prettify(encoding="utf-8", formatter="html5"))  # type: ignore

        # Professor Name
        prof_tag = soup.find("a", class_="professor-name")
        if isinstance(prof_tag, Tag) and hasattr(prof_tag, "text"):
            self.professor_name = prof_tag.get_text(strip=True)
        else:
            # Fallback for different structure
            if isinstance(prof_tag, Tag) and prof_tag.string:
                self.professor_name = prof_tag.string.strip()
            else:
                # self.professor_name = ""  # Or raise ProfessorNameNotFound("Could not find professor name.")
                raise ProfessorNameNotFound("Could not find professor name.")

        # Course Guidebook
        guidebook_tag = soup.find(
            "a",
            string="Guidebook",
        )
        guidebook_tag = soup.find("a", class_="guidebook-btn")
        if isinstance(guidebook_tag, Tag) and "Guidebook" in guidebook_tag.get_text():
            guidebook_tag = guidebook_tag.get("href")
        else:
            guidebook_tag = None
        # print(f"{guidebook_tag=}")
        self.guidebook_url = str(guidebook_tag)

        # Course Description
        description_tag = soup.select_one("#overview-section-content > div > p")
        if (
            isinstance(description_tag, Tag)
            and hasattr(description_tag, "string")
            and description_tag.string
        ):
            self.description = description_tag.string.strip()

        lectures_objs = soup.find_all("div", attrs={"data-lec-id": re.compile(".+")})
        # Lecture IDs
        if lectures_objs:
            first_lecture_obj = lectures_objs[0]
            if isinstance(first_lecture_obj, Tag):
                first_lecture_id_val = first_lecture_obj.get("data-lec-id")
                if isinstance(first_lecture_id_val, str):
                    self.ids = (
                        re.sub(r"\-L\d+", "", first_lecture_id_val)
                        .replace("ZV", "")
                        .strip()
                    )
                else:
                    raise LectureIdNotFound(
                        "Could not extract lecture ID string from the first lecture."
                    )
            else:
                raise LectureIdNotFound("First lecture object is not a valid tag.")
        else:
            raise LectureIdNotFound("Could not find any lecture IDs.")

        # Create Course directory path
        self.name_formatted_with_id = f"{self.title} (#{self.ids})"
        self.directory_path = f"{self.name_formatted_with_id} ~ {self.professor_name}"

        # Search for rbBitPlayer script
        rb_bit_player_script = soup.find("script", string=re.compile(r"rbBitPlayer"))
        base_url = None
        manifest_param = None

        if rb_bit_player_script and rb_bit_player_script.text:
            base_url_match = re.search(
                r'"baseUrl":\s*"(.*?)"', rb_bit_player_script.text
            )
            manifest_param_match = re.search(
                r'"manifestParam":\s*"(.*?)"', rb_bit_player_script.text
            )

            if base_url_match:
                base_url = base_url_match.group(1)
            if manifest_param_match:
                manifest_param = manifest_param_match.group(1)

        # First, check if there is a Trailer on the page, as that increases the start by 1
        start_child = 1
        if trailers := soup.find_all(class_="play-trailer"):
            if len(trailers) >= 1:
                start_child += 1

        # Then, get the Description of all the Lectures
        lecture_descriptions = []
        for item in range(start_child, len(lectures_objs)):
            lec_description = soup.select_one(
                f"#lectures-list > div:nth-child({item}) > div.media-body > div:nth-child(1) > p"
            )
            if (
                isinstance(lec_description, Tag)
                and hasattr(lec_description, "string")
                and lec_description.string
            ):
                lecture_descriptions.append(lec_description.string.strip())

        lectures = []
        for i, lecture_div in enumerate(lectures_objs):
            if not isinstance(lecture_div, Tag):
                continue

            lec_id = lecture_div.get("data-lec-id")
            lec_idx = lecture_div.get("data-idx")
            lec_video_id = lecture_div.get("data-video-id")

            # The title is in an alt attribute of an img tag inside the div
            img_tag = lecture_div.find("img")
            lec_title = img_tag.get("alt") if isinstance(img_tag, Tag) else None

            manifest_url = None
            if base_url and manifest_param and lec_video_id:
                manifest_url = f"{base_url}{lec_video_id}/{manifest_param}"

            if (
                isinstance(lec_id, str)
                and isinstance(lec_idx, str)
                and isinstance(lec_title, str)
            ):
                if not manifest_url:
                    print(f"Warning: Could not find manifest URL for lecture {lec_id}")

                try:
                    description = lecture_descriptions[i]
                except IndexError:
                    description = ""

                lecture_obj = Lecture(
                    ids=lec_id.strip(),
                    number=int(lec_idx),
                    number_formatted=lec_idx.zfill(2),
                    title=lec_title.strip(),
                    title_formatted_filename=self._clean_filename(
                        lec_title.strip(), replace_colons_as_underscores=True
                    ),
                    description=description,
                    manifest_url=manifest_url,
                )
                lectures.append(lecture_obj)
            else:
                # Maybe log a warning here that a lecture could not be parsed
                print(
                    f"Warning: Could not parse a lecture. Details: id={lec_id}, idx={lec_idx}, title={lec_title}"
                )

        self.lectures = lectures

    def _clean_filename(
        self,
        filename: str,
        replace_colons_as_underscores: bool = False,
        replace_colons_as_dashes: bool = False,
    ) -> str:
        """
        Cleans a filename string by replacing or removing invalid characters and optionally replacing colons.
        Args:
            filename (str): The filename to clean.
            replace_colons_as_underscores (bool, optional): If True, replaces colons (:) with underscores (_).
            replace_colons_as_dashes (bool, optional): If True, replaces colons (:) with dashes (-).
                Only one of these options can be True at a time.
        Raises:
            ValueError: If both `replace_colons_as_underscores` and `replace_colons_as_dashes` are True.
        Returns:
            str: The cleaned filename, truncated to a maximum of 255 characters if necessary.
        """
        if replace_colons_as_underscores and replace_colons_as_dashes:
            raise ValueError(
                "Only one of 'replace_colons_as_underscores' or 'replace_colons_as_dashes' can be provided."
            )

        filename_cleaned = re.sub(r'[/\\%;*|"<>]', "_", filename)
        if replace_colons_as_underscores:
            filename_cleaned = filename_cleaned.replace(":", "_")
        else:
            # filename_cleaned = filename_cleaned.replace(": ", " - ")
            filename_cleaned = re.sub(r"(\w)\: (\S)", r"\1 - \2", filename_cleaned)
            filename_cleaned = filename_cleaned.replace(":", "-")
            # filename_cleaned = filename_cleaned.replace(":", "_")

        char_limit = 255
        if len(filename_cleaned) > char_limit:
            print(
                f"Warning, filename truncated because it was over {char_limit} characters. Filenames might no longer be unique."
            )

        return filename_cleaned[:char_limit]


@dataclass
class Lecture:
    """
    Represents a lecture with associated metadata.

    Attributes:
        ids (str): Unique identifier(s) for the lecture.
        number (int): The lecture's sequence number.
        number_formatted (str): Formatted representation of the lecture number (not shown in repr).
        title (str): Title of the lecture.
        title_formatted_filename (str): Title formatted for use as a filename.
        description (str): Description of the lecture (defaults to empty string, not shown in repr).
        manifest_url (Optional[str]): URL to the lecture's manifest (defaults to None, not shown in repr).
        lecture_uri (Optional[str]): URI for the lecture (defaults to None, not shown in repr, not set during initialization).
    """

    ids: str
    number: int
    number_formatted: str = field(repr=False)
    title: str
    title_formatted_filename: str
    description: str = field(default="", repr=False)
    manifest_url: Optional[str] = field(default=None, repr=False)
    lecture_uri: Optional[str] = field(default=None, repr=False, init=False)


@dataclass
class Video:
    """
    Represents a video with associated metadata.

    Attributes:
        video_height (int): The height of the video in pixels. Defaults to 0.
        url_video (Optional[str]): The URL of the video stream. Defaults to None.
        url_audio (Optional[str]): The URL of the audio stream. Defaults to None.
        audio_channels (Optional[int]): The number of audio channels. Defaults to None.
    """

    video_height: int = 0
    url_video: Optional[str] = None
    url_audio: Optional[str] = None
    audio_channels: Optional[int] = None


@dataclass
class LineCount:
    """
    LineCount class tracks counts for different line types: output, error, opening, and frame.
    Attributes:
        out (int): Count of output lines.
        err (int): Count of error lines.
        opening (int): Count of opening lines.
        frame (int): Count of frame lines.
    Methods:
        __getitem__(key): Allows dictionary-like access to 'opening' and 'frame' attributes.
            Args:
                key (str): The attribute name ('opening' or 'frame').
            Returns:
                int: The value of the requested attribute.
            Raises:
                KeyError: If the key is not 'opening' or 'frame'.
    """

    out: int = 0
    err: int = 0
    opening: int = 0
    frame: int = 0

    def __getitem__(self, key):
        """
        Allows accessing attributes of the Product dataclass using dictionary-like indexing.
        """
        if key == "opening":
            return self.opening
        elif key == "frame":
            return self.frame
        else:
            raise KeyError(f"Invalid key: {key}")
