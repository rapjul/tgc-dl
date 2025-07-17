#! /usr/bin/env python3

import logging
import os
from datetime import timedelta
from http import cookiejar
from pathlib import Path
from sys import modules
from typing import Annotated, Optional

import typer
from requests_cache import CachedSession
from rich.logging import RichHandler

from .download import download
from .types import Course, Lecture

app = typer.Typer(
    help="'The Great Courses Plus' Downloader",
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    # pretty_exceptions_enable=False,
)

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


@app.command()
def main(
    courses: Annotated[
        list[str],
        typer.Argument(
            help="Course URL(s)",
        ),
    ],
    cookies_file: Annotated[
        Path,
        typer.Option(
            "--cookies-file",
            "-c",
            help="Path to the 'cookies.txt' file",
            file_okay=True,
            dir_okay=False,
            # show_default=False,
        ),
    ] = Path.cwd().joinpath("tgcp-cookies.txt"),
    output_directory: Annotated[
        Path,
        typer.Option(
            "--output-directory",
            "-o",
            help="Path to where the downloads will be stored",
            file_okay=False,
            dir_okay=True,
        ),
    ] = Path.cwd(),
    quality: Annotated[
        int,
        typer.Option(
            "--quality",
            "-q",
            help="Quality of the video to download",
            min=360,
            max=1080,
        ),
    ] = 1080,
    lecture_range: Annotated[
        Optional[str],
        typer.Option(
            "--lecture-range",
            "-r",
            help="Download a specific range of lectures (e.g., '1-5', '3', '1,3,5'). Only applicable when downloading a single course.",
            show_default=False,
        ),
    ] = None,
    offset: Annotated[
        Optional[int],
        typer.Option(
            "--offset",
            help="[DEPRECATED] Start lecture offset",
            hidden=True,  # Hide from help message
            show_default=False,
        ),
    ] = None,
    streaming_output: Annotated[
        bool,
        typer.Option(
            "--streaming-output",
            "-s",
            help="Stream the output from FFMPEG as it is running",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            "-d",
            help="Print debug statements",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Dry-run; does not download anything",
        ),
    ] = False,
):
    if debug or dry_run:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    if "rich" in modules:
        handlers = [
            RichHandler(
                rich_tracebacks=False,
                markup=False,
            )
        ]
    else:
        handlers = [logging.StreamHandler()]
    logging.basicConfig(
        format="%(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %I:%M:%S %p",
        level=loglevel,
        handlers=handlers,
    )
    logger = logging.getLogger()

    if offset is not None:
        logger.warning(
            "The --offset option is deprecated. Please use --lecture-range instead."
        )

    if lecture_range and len(courses) > 1:
        logger.error(
            "The --lecture-range option can only be used when downloading a single course."
        )
        raise typer.Exit(code=1)

    output_directory = output_directory.resolve()
    if not output_directory.exists():
        output_directory.mkdir(parents=True)
    logger.info(f"{output_directory=}")

    cookies = get_cookies(cookies_file, logger)

    try:
        for course_url in courses:
            course = Course(course_url, cookies)

            logger.info("\n")
            logger.info(f"# '{course.title}' (Course ID: {course.ids})")
            if course.guidebook_url is not None and len(course.guidebook_url) > 0:
                logger.info("\t(This Course includes a Guidebook PDF file)")
            logger.info(f"There are {len(course.lectures)} Lectures in this Course.")

            lectures_to_download: list[Lecture] = []
            if lecture_range:
                # Parse lecture_range
                selected_lecture_numbers: set[int] = set()
                parts = lecture_range.split(",")
                for part in parts:
                    if "-" in part:
                        start_str, end_str = part.split("-")
                        try:
                            start = int(start_str)
                            end = int(end_str)
                            selected_lecture_numbers.update(range(start, end + 1))
                        except ValueError:
                            logger.error(f"Invalid range format: {part}")
                            raise typer.Exit(code=1)
                    else:
                        try:
                            selected_lecture_numbers.add(int(part))
                        except ValueError:
                            logger.error(f"Invalid lecture number: {part}")
                            raise typer.Exit(code=1)

                for lecture in course.lectures:
                    if lecture.number in selected_lecture_numbers:
                        lectures_to_download.append(lecture)

                if not lectures_to_download:
                    logger.warning(
                        f"No lectures found for the specified range: '{lecture_range}'. Exiting."
                    )
                    raise typer.Exit(code=0)

            else:
                lectures_to_download = course.lectures

            for lecture in lectures_to_download:
                logger.info(f'{lecture.number:02}) "{lecture.title}"')

            if dry_run:
                course_dict = course.__dict__.copy()
                del course_dict["cookies"]
                del course_dict["lectures"]
                logger.debug(f"{course_dict=}")

                for lecture in lectures_to_download:
                    logger.debug(f"\nLecture {lecture.number:02}:\n{lecture.__dict__}")

                logger.debug("\n\n")
                continue

            course_output_directory = output_directory.joinpath(course.directory_path)
            if not course_output_directory.exists():
                course_output_directory.mkdir(parents=True)

            os.chdir(course_output_directory)

            download(
                course=course,
                lectures_to_download=lectures_to_download,
                output_directory=course_output_directory,
                quality=quality,
                logger=logger,
                cookies=cookies,
                streaming_output=streaming_output,
            )
    except KeyboardInterrupt:
        quit()


if __name__ == "__main__":
    app()
