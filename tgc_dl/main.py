#! /usr/bin/env python3

import argparse
import logging
import os
from datetime import timedelta
from http import cookiejar
from pathlib import Path
from sys import modules
from typing import TYPE_CHECKING, Any

from requests_cache import CachedSession
from rich.logging import RichHandler

from .download import download
from .types import Course

if TYPE_CHECKING:
    from .types import Lecture


session = CachedSession(
    "the_great_courses_plus",
    backend="sqlite",
    expire_after=timedelta(days=3),
)


def get_cookies(file_path: Path, logger: logging.Logger):
    """
    Loads cookies from a Mozilla 'cookies.txt' file and returns them as a dictionary.
    Args:
        file_path (Path): The path to the 'cookies.txt' file.
        logger (logging.Logger): Logger instance for logging messages.
    Returns:
        dict: A dictionary mapping cookie names to their values.
    Logs:
        - Error if the 'cookies.txt' file is not found.
        - Info when the file is loaded and cookies are processed.
    """
    if not file_path.is_file():
        logger.error("'cookies.txt' not found")
        logger.error(
            "Please export a 'cookies.txt' file in the same folder of this Python file."
        )

    cookie_jar = cookiejar.MozillaCookieJar(file_path)
    cookie_jar.load(ignore_discard=True)

    logger.info("'cookies.txt' loaded")

    cookies = {}
    for cookie in cookie_jar:
        cookies[cookie.name] = cookie.value
    logger.info("Cookies processed")
    return cookies


# Custom type function to enforce min and max constraints
def _int_within_range(value: Any) -> int:
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Value must be an integer, but got '{value}' of type '{type(value)}'."
        )

    if not (360 <= ivalue <= 1080):  # Min of 360p; Max of 1080p
        raise argparse.ArgumentTypeError(
            f"Value must be between, and including, 360 and 1080, but got {ivalue}."
        )
    return ivalue


def main():
    parser = argparse.ArgumentParser(description="'The Great Courses Plus' Downloader")
    parser.add_argument(
        "courses",
        type=str.lower,
        nargs="+",
        help="Course URL(s)",
    )
    parser.add_argument(
        "-o",
        "--output-directory",
        type=Path,
        help="Path to where the downloads will be stored",
        default=Path.cwd(),
    )

    parser.add_argument(
        "-c",
        "--cookies-file",
        type=Path,
        help="Path to the 'cookies.txt' file",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=_int_within_range,
        nargs="+",
        help="Quality",
        default=1080,
    )

    parser.add_argument(
        # "-o",
        "--offset",
        type=int,
        nargs="+",
        help="Offset",
    )

    parser.add_argument(
        "-s",
        "--streaming-output",
        action="store_true",
        help="Stream the output from FFMPEG as it is running",
        default=False,
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Print debug statements",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Dry-run; does not download anything",
    )

    args = parser.parse_args()

    if args.debug or args.dry_run:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    if "rich" in modules:
        handlers = [
            RichHandler(
                rich_tracebacks=False,
                markup=False,
                # markup=True,
                # show_time=False,
            )
        ]
    else:
        handlers = [logging.StreamHandler()]
    logging.basicConfig(
        # format="%(levelname)s - %(asctime)s - %(name)s - %(message)s",
        format="%(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %I:%M:%S %p",
        level=loglevel,
        handlers=handlers,
    )
    logger = logging.getLogger()

    quality: int = args.quality

    if args.offset is not None:
        offset = args.offset[0]
    else:
        offset = 999

    output_directory: Path = args.output_directory.resolve()
    if not output_directory.exists():
        output_directory.mkdir(parents=True)
    logger.info(f"{output_directory=}")

    cookies = get_cookies(args.cookies_file, logger)

    # print(f"{args.courses=}")
    # print(f"{quality=}")
    # exit()

    try:
        lecture: Lecture
        for course in args.courses:
            # logger.debug(f"{course=}")
            course = Course(course, cookies)

            logger.info("\n")
            logger.info(f"# '{course.title}' (Course ID: {course.ids})")
            if course.guidebook_url is not None and len(course.guidebook_url) > 0:
                logger.info("\t(This Course includes a Guidebook PDF file)")
            # print("\n")
            logger.info(f"There are {len(course.lectures)} Lectures in this Course.")
            # print("\n")

            for lecture in course.lectures:
                logger.info(f"{lecture.number:02}) '{lecture.title}'")

            if args.dry_run:
                course_dict = course.__dict__.copy()  # Copy the dictionary object to avoid deleting the real keys and values
                del course_dict["cookies"]
                del course_dict["lectures"]
                # logger.debug("\n")
                logger.debug(f"{course_dict=}")

                for lecture in course.lectures:
                    # logger.debug("\n")
                    logger.debug(f"\nLecture {lecture.number:02}:\n{lecture.__dict__}")

                logger.debug("\n\n")
                continue

            course_output_directory = output_directory.joinpath(course.directory_path)
            if not course_output_directory.exists():
                course_output_directory.mkdir(parents=True)

            os.chdir(course_output_directory)

            streaming_output = True  # Define streaming_output
            download(
                course=course,
                output_directory=course_output_directory,
                quality=quality,
                logger=logger,
                cookies=cookies,
                offset=offset,
                streaming_output=streaming_output,
            )
    except KeyboardInterrupt:
        quit()


if __name__ == "__main__":
    main()
