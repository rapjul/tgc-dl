import json
import logging
import re
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import requests
from m3u8 import parse as m3u8_parse
from more_itertools import unique
from requests_cache import CachedSession
from rich import print
from typer import Exit
from typing_extensions import deprecated

from .types import HEADERS, Course, Lecture, LineCount, Video

session = CachedSession(
    "the_great_courses_plus",
    backend="sqlite",
    expire_after=timedelta(days=3),
)


def download(
    course: Course,
    lectures_to_download: list[Lecture],
    output_directory: Path,
    quality: int,
    cookies: dict,
    logger: logging.Logger,
    streaming_output: bool = True,
) -> None:
    """
    Downloads all lectures and guidebook for a given course.

    This function checks if each lecture has already been downloaded (in either MKV or MP4 format).
    If not, it fetches the manifest URL for the lecture, parses the m3u8 playlist to select the highest
    available video resolution and corresponding audio track, and downloads the lecture using the selected streams.
    Args:
        course (Course): The course object containing lecture information.
        lectures_to_download (List[Lecture]): A list of Lecture objects to download.
        output_directory (Path): Directory where downloaded files will be saved.
        quality (int): Desired video quality (height in pixels).
        cookies (dict): Dictionary of cookies for authentication with the server.
        logger (logging.Logger): Logger instance for logging progress and errors.
        streaming_output (bool, optional): If True, enables streaming output during download. Defaults to True.
    Returns:
        None
    Raises:
        Exception: If more than one audio link is found or no audio links are found in the manifest.
    """
    download_guidebook(
        course=course, output_directory=output_directory, logger=logger, cookies=cookies
    )

    logger.info("Grabbing Lectures...")
    lecture: Lecture
    for lecture in lectures_to_download:
        if is_lecture_downloaded(
            course, lecture, output_directory, file_extension="mkv"
        ) or is_lecture_downloaded(
            course, lecture, output_directory, file_extension="mp4"
        ):
            logger.info(
                f'Lecture {lecture.number_formatted}) "{lecture.title}" already downloaded. Skipping.'
            )
            continue

        logger.info(
            f'Grabbing Lecture {lecture.number_formatted} - "{lecture.title}"...'
        )
        logger.debug(f"Manifest URL: '{lecture.manifest_url}'")

        if not lecture.manifest_url:
            logger.error(
                f"Skipping lecture {lecture.number_formatted} because manifest URL is missing."
            )
            continue

        # The manifest URL now directly points to the m3u8 playlist
        try:
            logger.debug(
                f"Attempting to fetch manifest for lecture {lecture.number_formatted}"
            )
            lecture_manifest_response = session.get(
                lecture.manifest_url, cookies=cookies, headers=HEADERS
            )
            lecture_manifest_response.raise_for_status()  # Raise an exception for HTTP errors
            logger.debug(
                f"Successfully fetched manifest for lecture {lecture.number_formatted}"
            )

            playlist_dict = m3u8_parse(lecture_manifest_response.text)
            logger.debug(playlist_dict)
            lecture_uri: str = lecture_manifest_response.url.removesuffix("master.m3u8")
            # logger.debug(f"{lecture_uri=}")
            lecture.lecture_uri = lecture_uri
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Network or HTTP error downloading lecture {lecture.number_formatted}: {e}"
            )
            continue
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while processing lecture {lecture.number_formatted}: {e}"
            )
            continue

        # headers = []
        # for key, value in HEADERS.items():
        #     temp = '"' + key + ":" + value + '"'
        #     # headers.append('--header')
        #     headers.append("--header=" + temp)

        selected_video = Video()

        playlist: dict
        for playlist in playlist_dict["playlists"]:
            # Check if it's a video playlist by looking for 'resolution' in 'stream_info'
            if "stream_info" in playlist and "resolution" in playlist["stream_info"]:
                video_url = lecture_uri + playlist["uri"]

                resolution = playlist["stream_info"]["resolution"]
                # Extract height from resolution string (e.g., "854x480" -> 480)
                if (
                    resolution := int(resolution.split("x")[1])
                ) > selected_video.video_height:
                    selected_video.video_height = resolution
                    selected_video.url_video = video_url
                    # logger.debug(f"{resolution=}: {video_url=}")
                # logger.debug(f"{resolution=}", f"{largest_video_resolution=}")

        audio_tracks: list[dict] = [
            media_track
            for media_track in playlist_dict["media"]
            if media_track["type"] == "AUDIO"
        ]
        # logger.debug(f"{audio_tracks=}")
        if len(audio_tracks) == 1:
            audio_channels = audio_tracks[0]["channels"]
            audio_link = lecture_uri + audio_tracks[0]["uri"]
            selected_video.url_audio = audio_link
            selected_video.audio_channels = audio_channels
        elif len(audio_tracks) >= 2:
            raise Exception(
                "MoreThanOneAudioLinkError", "Too many audio links were found."
            )
        else:
            raise Exception("NoAudioLinksError", "No audio links found.")
        logger.debug(f"{selected_video=}")

        if selected_video.url_video is None:
            logger.warning(
                f"No video link found for Lecture {lecture.number_formatted}."
            )
            continue
        if selected_video.url_audio is None:
            logger.warning(
                f"No audio link found for Lecture {lecture.number_formatted}."
            )
            continue

        download_lecture(
            course=course,
            lecture=lecture,
            video=selected_video,
            output_directory=output_directory,
            logger=logger,
            streaming_output=streaming_output,
            use_ffmpeg=False,
        )
        # aria_out = download_file(
        #     course,
        #     selected_video,
        #     lecture,
        #     cookies,
        #     headers=HEADERS,
        #     logger=logger,
        # )


def count_digits_in_number(value: int) -> int:
    """
    Counts the number of digits in an integer.

    Args:
        value (int): The integer whose digits are to be counted.

    Returns:
        int: The number of digits in the given integer.
    """
    return len(str(value))


def get_lecture_output_path(
    course: Course,
    lecture: Lecture,
    output_directory: Path,
    file_extension: str = "mp4",
) -> Path:
    """
    Constructs the full output path for a lecture video file.

    Args:
        course (Course): The course object containing course metadata.
        lecture (Lecture): The lecture object containing lecture metadata.
        output_directory (Path): The directory where the video file should be saved.
        file_extension (str, optional): The file extension for the video file (default is "mp4").

    Returns:
        Path: The complete path to the output video file, including the filename.
    """
    video_filename = f"{course.title} (#{course.ids}) S01E{lecture.number_formatted} - {lecture.title_formatted_filename}.{file_extension}"
    return output_directory.joinpath(video_filename)


def is_lecture_downloaded(
    course: Course,
    lecture: Lecture,
    output_directory: Path,
    file_extension: str = "mp4",
) -> bool:
    """Checks if a lecture video file already exists."""
    output_file = get_lecture_output_path(
        course, lecture, output_directory, file_extension
    )
    return output_file.exists()


def download_guidebook(
    course: Course,
    output_directory: Path,
    logger: logging.Logger,
    cookies: dict[str, str],
    headers: dict[str, str] = HEADERS,
) -> None:
    """
    Downloads the guidebook PDF for a given course if available.

    This function checks if the course has a valid guidebook URL, constructs the output filename,
    and downloads the guidebook PDF to the specified output directory. It handles various error
    scenarios, including missing URLs, connection issues, and request exceptions, logging appropriate
    messages for each case.
    Args:
        course (Course): The course object containing guidebook information.
        output_directory (Path): The directory where the guidebook PDF will be saved.
        logger (logging.Logger): Logger instance for logging messages.
        cookies (dict[str, str]): Cookies to be used for the HTTP request.
        headers (dict[str, str], optional): HTTP headers for the request. Defaults to HEADERS.
    Returns:
        None
    Raises:
        SystemExit: If a request or connection error occurs during download.
        ValueError: If the aria2c download (commented out) fails.
    """
    guidebook_url = course.guidebook_url
    logger.debug(f"{guidebook_url=}")
    if not guidebook_url:
        logger.warning(
            "No Guidebook URL found for this course. Skipping Guidebook download."
        )
        return

    guidebook_filename = (
        f"{course.title} (#{course.ids}) ~ {course.professor_name} [Guidebook].pdf"
    )
    output_file = output_directory.joinpath(guidebook_filename)
    logger.debug(f"{output_file=}")

    if output_file.exists():
        logger.info(f"Guidebook PDF already downloaded at '{output_file}'. Skipping.")
        return

    if not output_file.parent.exists():
        output_file.parent.mkdir(parents=True)

    # aria_command = [
    #     "aria2c",
    #     "--continue=true",
    #     "--allow-overwrite=true",
    #     # "--load-cookies=cookies.txt",
    #     "--auto-file-renaming=false",
    #     "--file-allocation=none",
    #     "--summary-interval=0",
    #     "--retry-wait=5",
    #     "--uri-selector=inorder",
    #     "--download-result=hide",
    #     "--console-log-level=error",
    #     "--max-connection-per-server=16",  # '-x'
    #     "--max-concurrent-downloads=16",  # '-j'
    #     "--split=16",  # '-s'
    #     "-o",
    #     str(output_file),
    #     course.guidebook_url,
    # ]
    # aria_process = subprocess.run(aria_command)
    # print("\n")
    # if aria_process.returncode != 0:
    #     aria_process = subprocess.run(aria_command)
    #     print("\n")
    #     if aria_process.returncode != 0:
    #         raise ValueError(f"aria2c failed with exit code {aria_process}")

    if not (
        guidebook_url.startswith(
            "https://www.thegreatcoursesplus.com/pdf/index/index/docName/"
        )
        and guidebook_url.endswith("/")
    ):
        logger.warning(
            "No Guidebook URL found for this course. Skipping Guidebook download."
        )
        return
    if not (
        match := re.search(r"/(?P<id>[^\.]+)\.pdf/", guidebook_url, flags=re.IGNORECASE)
    ):
        logger.warning(
            "No Guidebook URL found for this course. Skipping Guidebook download."
        )
        return

    guidebook_id = match.group(1)
    guidebook_url = (
        f"https://secureimages.teach12.com/CourseGuideBooks/{guidebook_id}.pdf"
    )
    logger.debug(f"{guidebook_url=}")

    from rich.progress import track

    try:
        response = requests.get(
            guidebook_url, cookies=cookies, headers=headers, stream=True
        )
        with output_file.open("wb") as f:
            for chunk in track(
                response.iter_content(chunk_size=5),
                description="Downloading Guidebook...",
                show_speed=False,
            ):
                f.write(chunk)
    except requests.Timeout as e:
        logger.error(
            "RequestTimeoutError: The connection timed-out.\n%s", e, exc_info=True
        )
        exit()
    except requests.ConnectionError as e:
        logger.error(
            "RequestConnectionError: A connection error occurred.\n%s", e, exc_info=True
        )
        exit()
    except requests.RequestException as e:
        logger.error(
            f"RequestException: An error occurred while trying to download this link, '{guidebook_url}'.\n%s",
            e,
            exc_info=True,
        )
        exit()
    except Exception as e:
        logger.error(
            f"An error occurred while trying to download this link, '{guidebook_url}'.\n%s",
            e,
            exc_info=True,
        )
        exit()

    if logger.level == "INFO":
        logger.info("Finished downloading the Guidebook PDF.")
    else:
        logger.debug(f"Finished downloading the Guidebook PDF to '{output_file}'.")


def get_stream_info(
    file_path_or_url: Path | str,
    logger: logging.Logger,
) -> dict[str, bool] | dict:
    """
    Returns a dictionary with the stream information of the given file.
    """
    try:
        ffprobe_command = [
            "ffprobe",
            "-extension_picky", "0",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(file_path_or_url),
        ]  # fmt: skip
        result = subprocess.run(
            ffprobe_command,
            check=True,
            capture_output=True,
            text=True,
        )

        file_streams = json.loads(result.stdout)["streams"]
        logger.debug(f"{file_streams=}")

        return {
            "video": any(s["codec_type"] == "video" for s in file_streams),
            "audio": any(s["codec_type"] == "audio" for s in file_streams),
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error getting stream info for {file_path_or_url}: {e}")

        return {}


def download_lecture(
    course: Course,
    lecture: Lecture,
    video: Video,
    logger: logging.Logger,
    output_directory: Path,
    format: str = "mkv",
    streaming_output: bool = True,
    use_ffmpeg: bool = True,
) -> None:
    """
    Downloads a lecture video and audio, merges them, and saves the output file in the specified format.

    Depending on the `use_ffmpeg` flag, this function either uses FFmpeg directly or falls back to yt-dlp for downloading and merging streams.

    It supports both MKV and MP4 formats, handles metadata, and provides progress feedback via logging and optional streaming output.
    Args:
        course (Course): The course object containing metadata about the course.
        lecture (Lecture): The lecture object containing metadata about the lecture.
        video (Video): The video object containing URLs and stream information.
        logger (logging.Logger): Logger instance for logging progress and errors.
        output_directory (Path): Directory where the downloaded lecture will be saved.
        format (str, optional): Output file format, either "mkv" or "mp4". Defaults to "mkv".
        streaming_output (bool, optional): If True, streams FFmpeg output to the console. Defaults to True.
        use_ffmpeg (bool, optional): If True, uses FFmpeg for downloading and merging. If False, uses yt-dlp. Defaults to True.
    Returns:
        None
    Raises:
        RuntimeError: If FFmpeg or yt-dlp fails to download or merge the lecture.
        KeyboardInterrupt: If the download process is interrupted by the user.
    Side Effects:
        - Creates directories as needed for output.
        - Logs progress, errors, and status updates.
        - May delete temporary files after merging.
        - Exits the program on certain unrecoverable errors.
    """
    output_file = get_lecture_output_path(
        course, lecture, output_directory, file_extension="mkv"
    )
    logger.debug(
        f"Downloading Lecture {lecture.number_formatted} to '{output_file}'..."
    )
    video_filename = output_file.stem
    if not output_file.parent.exists():
        output_file.parent.mkdir(parents=True)

    if format == "mkv":
        # Only for MKV files
        format_args = [
            "-reserve_index_space", "50k", # Suggested to allocate 50 KB per hour of media
        ]  # fmt: skip
    elif format == "mp4":
        format_args = [
            "-movflags", "+faststart",  # Only for MP4-based files
        ]  # fmt: skip

    if use_ffmpeg:
        ffmpeg_args = [
            "ffmpeg",
            "-f", "hls",  # Explicitly specify HLS demuxer for the input
            # "-strict", "-2",  # Allows non-standard compliant features
            "-extension_picky", "0",  # Might allow '.cmfv' and '.cmfa' files to be downloaded
            "-i", video.url_video,
            "-i", video.url_audio,
            "-c", "copy",
            "-map", "0:v:0",
            "-map", "0:s?",
            "-map", "1:a:0",
            "-disposition:s:0", "default",
            "-metadata", f'title="{video_filename}"',
            "-metadata:s:a:0", "language=eng",
            "-metadata:s:a:0", f'title="{"English Stereo" if video.audio_channels == 2 else "English Mono"}"',
            *format_args,
            str(output_file),
        ]  # fmt: skip

        logger.debug(f"ffmpeg_args list: {ffmpeg_args}")
        command_string = " ".join(ffmpeg_args)  # Keep for logging purposes
        logger.debug(f"FFMPEG command string: {command_string}")

        import select

        try:
            process = subprocess.Popen(
                ffmpeg_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )

            if streaming_output:
                # Read output as it becomes available
                def counts(
                    program_output_string: str, number_of_times: LineCount
                ) -> tuple[bool, LineCount]:
                    checks = (
                        {
                            "save_to": "opening",
                            "check_string": r"Opening 'https?.*' for reading",
                        },
                        {
                            "save_to": "frame",
                            "check_string": r"frame=\s*(\d+) fps=",
                        },
                    )

                    skip = False
                    for check in checks:
                        if match := re.search(
                            check["check_string"], program_output_string
                        ):
                            if program_output_string.startswith("frame="):
                                print(f"{match=}", f"{match.group(1)=}")
                                last_frame = number_of_times.frame
                                if int(match.group(1)) > last_frame:
                                    number_of_times[check["save_to"]]
                                    skip = False
                                else:
                                    skip = True
                            else:
                                number_of_times[check["save_to"]]
                                skip = True

                    return skip, number_of_times

                counted_lines = LineCount()
                while True:
                    # Ensure stdout and stderr are not None before accessing fileno()
                    readable_fds = []
                    if process.stdout:
                        readable_fds.append(process.stdout.fileno())
                    if process.stderr:
                        readable_fds.append(process.stderr.fileno())

                    if not readable_fds:
                        # If both streams are closed, break the loop
                        break

                    ret = select.select(readable_fds, [], [])

                    for fd in ret[0]:
                        if process.stdout and fd == process.stdout.fileno():
                            read = process.stdout.readline()
                            if read:
                                skip, counted_lines = counts(read, counted_lines)
                                if not skip:
                                    print(f"STDOUT: {read.strip()}")
                                    counted_lines.out += 1
                        if process.stderr and fd == process.stderr.fileno():
                            read = process.stderr.readline()
                            if read:
                                skip, counted_lines = counts(read, counted_lines)
                                if not skip:
                                    print(f"STDERR: {read.strip()}")
                                    counted_lines.err += 1

                    if process.poll() is not None:
                        break  # Process has terminated

            stdout, stderr = process.communicate()  # Capture any remaining output

            # downloader = subprocess.run(
            #     ffmpeg_args,
            #     check=False,  # Do not raise an exception for non-zero exit codes
            #     **subprocess_options,
            # )
            if process.returncode != 0:
                if process.returncode == 183:
                    logger.error(f"FFMPEG failed with exit code {process.returncode}.")
                    logger.info("Trying with YT-DLP instead.")
                    download_lecture(
                        course,
                        lecture,
                        video,
                        logger,
                        output_directory,
                        format="mkv",
                        streaming_output=False,
                        use_ffmpeg=False,
                    )
                    exit()
                logger.error(f"FFMPEG failed with exit code {process.returncode}.")
                logger.error(f"STDOUT:\n{stdout}")
                logger.error(f"STDERR:\n{stderr}")
                raise RuntimeError(f"FFMPEG failed with exit code {process.returncode}")
            else:
                logger.debug(f"STDOUT:\n{stdout}")
        except KeyboardInterrupt:
            logger.warning(
                f"Stopped downloading! This program was last downloading Lecture {lecture.number_formatted}."
            )
            quit()
    else:
        import yt_dlp
        from yt_dlp.postprocessor import PostProcessor

        # ℹ️ See help(yt_dlp.postprocessor.PostProcessor)
        class MergePostProcessor(PostProcessor):
            def __init__(self, output_filename: Path, logger: logging.Logger):
                super(MergePostProcessor, self).__init__(downloader=None)
                self._files_to_merge = []
                self._output_filename = output_filename
                self._logger = logger

            def run(self, information):
                """
                This method is called by yt-dlp after a video has been downloaded.
                """
                self._files_to_merge.append(information["filepath"])

                # If we have two files, merge them.
                if len(self._files_to_merge) == 2:
                    self.merge_files()

                # yt-dlp expects a list of files to delete and the modified info dict.
                return [], information

            def merge_files(self):
                """
                Merges the two downloaded files using FFmpeg.
                """
                if len(self._files_to_merge) < 2:
                    return

                output_filename: Path = self._output_filename

                # Get file
                file1 = Path(self._files_to_merge[0])
                file2 = Path(self._files_to_merge[1])
                # logger.debug(f"{file1=}")
                # logger.debug(f"{file2=}")

                # Check which file is only contains video and which only contains audio
                video_file, audio_file = None, None
                for file in [file1, file2]:
                    streams = get_stream_info(file, self._logger)
                    logger.debug(
                        f"Does this file contain a video or audio stream? {streams}"
                    )
                    if streams.get("video") and not streams.get("audio"):
                        video_file = file
                    elif streams.get("audio") and not streams.get("video"):
                        audio_file = file

                if not video_file or not audio_file:
                    logger.error(
                        "Error: Could not identify video and audio files for merging."
                    )
                    return
                # logger.debug(f"{video_file=}")
                # logger.debug(f"{audio_file=}")

                # Ensure the output file doesn't already exist
                if output_filename.exists():
                    output_filename.unlink()

                logger.debug(
                    f"Merging '{video_file}' and '{audio_file}' into '{output_filename}'."
                )

                # Construct the FFmpeg command
                ffmpeg_args = [
                    "ffmpeg",
                    # "-f", "concat",
                    # "-safe", "0",
                    "-i", str(video_file),
                    "-i", str(audio_file),
                    "-c", "copy",
                    "-map", "0:v:0",
                    "-map", "0:s?",
                    "-map", "1:a:0",
                    "-disposition:s:0", "default",
                    "-metadata", f'title="{video_filename}"',
                    "-metadata:s:a:0", "language=eng",
                    "-metadata:s:a:0", f'title="{"English Stereo" if video.audio_channels == 2 else "English Mono"}"',
                    *format_args,
                    str(output_filename),
                ]  # fmt: off
                ffmpeg_args_string = " ".join(ffmpeg_args)
                logger.debug(f"{ffmpeg_args_string=}")

                # Execute the FFmpeg command
                try:
                    subprocess.run(
                        ffmpeg_args,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    # logger.debug("✅ Merge successful!")
                    logger.debug("Merge successful!")

                    # Clean up the original files
                    video_file.unlink()
                    audio_file.unlink()
                except subprocess.CalledProcessError as e:
                    # logger.error("❌ Error during merging:")
                    logger.error("Error during merging:")
                    logger.error(e.stderr)

                self._files_to_merge.clear()

        from rich.progress import Progress

        progress = Progress()
        download_tasks = {}

        # Add a cache for stream info
        stream_info_cache = {}
        fragment_totals_cache = {}

        def progress_hook(d: dict):
            if d["status"] == "downloading":
                # logger.debug(f"{d=}")

                filename = Path(d["filename"])
                filename_str = str(filename)

                if filename_str not in stream_info_cache:
                    logger.debug(f"Checking stream info for: {filename_str}")
                    # Get stream info and cache it
                    stream_info_cache[filename_str] = get_stream_info(
                        d["info_dict"]["url"], logger
                    )

                stream_info = stream_info_cache.get(filename_str, {})

                if stream_info.get("audio") and not stream_info.get("video"):
                    task_description = (
                        f"Downloading Lecture {lecture.number_formatted} Audio"
                    )
                elif stream_info.get("video"):
                    task_description = (
                        f"Downloading Lecture {lecture.number_formatted} Video"
                    )
                else:
                    task_description = (
                        f"Downloading File for Lecture {lecture.number_formatted}"
                    )

                if filename_str not in fragment_totals_cache:
                    fragment_totals_cache[filename_str] = count_digits_in_number(
                        d["fragment_count"]
                    )

                fragments_total = fragment_totals_cache.get(filename_str, 0)

                if "fragment_index" in d and "fragment_count" in d:
                    task_description += f" (fragment {d['fragment_index']:0{fragments_total}}/{d['fragment_count']})"

                if filename_str not in download_tasks:
                    download_tasks[filename_str] = progress.add_task(
                        f"[cyan]{task_description}",
                        # total=d.get("total_bytes_estimate"),
                        total=d.get("fragment_count"),
                    )
                progress.update(
                    download_tasks[filename_str],
                    # completed=d.get("downloaded_bytes", 0),
                    completed=d.get("fragment_index", 0),
                    # total=d.get("total_bytes_estimate"),
                    description=f"[cyan]{task_description}",
                )
            elif d["status"] == "finished":
                filename = str(Path(d["filename"]))
                if filename in download_tasks:
                    progress.update(
                        download_tasks[filename],
                        # completed=d.get("total_bytes"),
                        completed=d.get("fragment_count"),
                    )

        # Use yt-dlp to download the lecture
        ydl_opts = {
            # "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",  # Prioritize mp4, then best available
            "outtmpl": str(
                f"{output_file.stem}_%(autonumber)s.%(ext)s"
            ),  # yt-dlp adds the extension automatically
            # ------------------------------- #
            "writethumbnail": False,  # Do not write thumbnails
            "merge_output_format": format,  # Use the specified format (mkv or mp4)
            # ------------------------------- #
            # "cookiefile": "thegreatcoursesplus.com_cookies.txt",  # Use the existing cookies file
            # ------------------------------- #
            "ffmpeg_location": shutil.which("ffmpeg"),  # Ensure ffmpeg is found
            "postprocessors": [
                {"key": "FFmpegMetadata", "add_metadata": True},
            ],
            # ------------------------------- #
            "no_warnings": True,
            # "no_warnings": False,
            "verbose": False,
            # "verbose": True,
            "color": "no_color",  # No color in terminal output
            # ------------------------------- #
            # "quiet": not streaming_output,  # Suppress yt-dlp output if streaming_output is False
            "quiet": True,
            # "logger": logger,  # Use the existing logger
            "progress_hooks": [progress_hook],
        }

        # Add metadata for title and language
        # yt-dlp can handle metadata directly
        # The title will be set by outtmpl, but we can add more specific metadata if needed
        # For language, yt-dlp usually detects it or you can specify it in format selection

        with progress:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.add_post_processor(
                        MergePostProcessor(output_filename=output_file, logger=logger)
                    )
                    ydl.download([video.url_video, video.url_audio])
                logger.info(
                    f'Lecture {lecture.number_formatted}) "{lecture.title}"" downloaded.'
                )
            except yt_dlp.utils.DownloadError as e:
                logger.error(
                    f"YT-DLP download failed for lecture {lecture.number_formatted}: {e}"
                )
                raise RuntimeError(
                    f"YT-DLP download failed for lecture {lecture.number_formatted}"
                ) from e
            except Exception as e:
                logger.error(
                    f"An unexpected error occurred during YT-DLP download for lecture {lecture.number_formatted}: {e}"
                )
                raise RuntimeError(
                    f"Unexpected error during YT-DLP download for lecture {lecture.number_formatted}"
                ) from e
            except KeyboardInterrupt:
                logger.warning(
                    f"Stopped downloading! This program was last downloading Lecture {lecture.number_formatted}."
                )
                raise Exit(code=0)

                # ##  Cleaned up unneeded leftover files
                # extensions = ["part", "ytdl"]
                # found_files = []
                # # Loop through each extension and extend the list with matching files
                # for ext_pattern in extensions:
                #     found_files.extend(
                #         output_directory.glob(f"{output_file.stem}_000*.{ext_pattern}")
                #     )

                # file_path: Path
                # for file_path in found_files:
                #     if file_path.is_file():
                #         file_path.unlink()

                # logger.warning(
                #     f"Stopped downloading Lecture {lecture.number_formatted}. Moving on to Lecture {lecture.number + 1:02}"
                # )


@deprecated("Use the `download_lecture()` function instead.")
def download_file(
    course: Course,
    video: Video,
    lecture: Lecture,
    cookies: dict[str, str],
    headers: dict[str, str],
    logger: logging.Logger,
    output_directory: Path,
    write_m3u_to_files: bool = False,
):
    import os

    # from pycaption import (
    #     DFXPWriter,
    #     SCCReader,
    #     SCCWriter,
    #     SRTReader,
    #     SRTWriter,
    #     WebVTTWriter,
    # )

    output_file = get_lecture_output_path(
        course, lecture, output_directory, file_extension="mp4"
    )
    video_file = output_file.name
    if not output_file.parent.exists():
        output_file.parent.mkdir(parents=True)

    if video.url_video is None:
        logger.warning(f"No video link found for Lecture {lecture.number_formatted}.")
        return
    if video.url_audio is None:
        logger.warning(f"No audio link found for Lecture {lecture.number_formatted}.")
        return

    segments_data = session.get(video.url_video, cookies=cookies, headers=HEADERS)
    m3u_segments = m3u8_parse(segments_data.text)
    # logger.debug(m3u_segments)
    if write_m3u_to_files:
        write_file_path = output_directory.joinpath(
            f"{course.ids}_L{lecture.number}_video.json"
        )
        with write_file_path.open("w") as f:
            json.dump(m3u_segments, f, indent=4, skipkeys=False)

    lecture_uri = "/".join(video.url_video.removesuffix(".m3u8").split("/")[0:-1])
    logger.info(f"{lecture_uri=}")
    # exit()

    course_directory = f"{course.ids}_L{lecture.number}"

    segment_files = []
    segment_links = []
    for index, item in enumerate(m3u_segments["segments"]):
        segment_links.append(f"{lecture_uri}/{item['uri']}")
        segment_files.append(
            Path.cwd().joinpath(f"{course_directory}/" + f"video_segment{index + 1}.ts")
        )

        # r = requests.get(item['uri'], allow_redirects=True, cookies=cookies, headers=HEADERS)
        # open(course.ids + lecture.number + str(index) + '.ts', 'wb').write(r.content)

    segment_links = list(unique(segment_links))

    # segment_file = output_directory.joinpath(f"{course.ids} {lecture.number}.txt")
    segment_file = Path.cwd().joinpath(f"{course_directory}.txt")
    with segment_file.open("w") as f:
        for link in segment_links:
            f.write(f"{link}\n")

    # logger.debug(f"{segment_files}")
    # logger.debug(f"{segment_links}")
    # exit()

    aria_command = [
        "aria2c",
        # "--enable-color=false",
        "--enable-color=true",
        # "--load-cookies=cookies.txt",
        "--continue=true",
        # "--allow-overwrite=false",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--file-allocation=none",
        "--summary-interval=0",
        "--retry-wait=5",
        f"--out='{video_file}'",
        "--uri-selector=inorder",
        "--console-log-level=warn",
        "--allow-piece-length-change=true",
        "--download-result=hide",
        # "--download-result=full",
        f"--dir='{course_directory}'",
        "--max-connection-per-server=16",  # '-x16'
        "--max-concurrent-downloads=16",  # '-j16'
        "--split=16",  # '-s16'
    ]
    aria_command += headers
    aria_command += ["-i", f"'{segment_file}'"]

    # # aria_command = ['ccextractor', video_file]
    # # aria_command += headers
    # # aria_command += '-o', '"' + video_file + '"'

    logger.debug("Starting aria2c with these parameters:")
    aria_command_string = " ".join(map(str, aria_command))
    logger.debug(f"{aria_command=}")
    logger.debug(f"{aria_command_string=}")

    aria_process = subprocess.call(aria_command_string, shell=True)
    if aria_process != 0:
        aria_process = subprocess.call(aria_command)
        if aria_process != 0:
            raise ValueError("aria2c failed with exit code {}".format(aria_process))
    if aria_process == 0:
        logger.info("")
        logger.info("Preparing to mux video files")

    with open(video_file, "wb") as output:
        for segment in segment_files:
            if os.path.isfile(segment):
                file = open(segment, "rb")
                shutil.copyfileobj(file, output)
                file.close()
                os.remove(segment)
    os.rmdir(course_directory)
    os.remove(segment_file.name)
    # # logger.info("Extracting CC subs")
    # # aria_command = ["ccextractor", "-quiet", video_file]
    # # aria_process = subprocess.call(aria_command)

    # # if os.stat(video_file.replace(".mp4", ".srt")).st_size < 5:
    # #     os.remove(video_file.replace(".mp4", ".srt"))

    mkvmerge_exec = "mkvmerge"
    if os.path.isfile(video_file.replace(".mp4", ".srt")):
        params = [
            video_file,
            "--language",
            "0:eng",
            "--track-name",
            "0:Subtitle",
            "--sub-charset",
            "0:UTF-8",
            video_file.replace(".mp4", ".srt"),
        ]
        mkvmerge_command = [
            mkvmerge_exec,
            "-o",
            video_file.replace(".mp4", ".mkv"),
        ]
    else:
        params = [video_file]
        mkvmerge_command = [mkvmerge_exec, "-o", video_file.replace(".mp4", ".mkv")]

    mkvmerge_command += params

    logger.info(mkvmerge_command)

    mkvmerge_out = subprocess.call(mkvmerge_command)
    # if mkvmerge_out > 1:
    #     if mkvmerge_out == 2:
    #         shutil.move(video_file.replace('.mp4', '.en.srt'), video_file.replace('.mp4', '.en.scc'))
    #         with open(video_file.replace('.mp4', '.en.scc'), 'r') as scc:
    #             scc_data = scc.read()
    #         scc_sub = SCCReader().read(scc_data)
    #         srt_results = SRTWriter().write(scc_sub)
    #         text_file = open(video_file.replace('.mp4', '.en.srt'), "w")
    #         text_file.write(srt_results)
    #         text_file.close()
    #         mkvmerge_out = subprocess.call(mkvmerge_command)
    #     if mkvmerge_out != 0:
    #         raise ValueError(
    #             'mkvmerge failed with exit code {}'.format(mkvmerge_out)
    #         )

    mkvpropedit_cmd = [
        "mkvpropedit",
        video_file.replace(".mp4", ".mkv"),
        "--edit",
        "track:a1",
        "--set",
        "language=eng",
    ]

    mkvpropedit_out = subprocess.call(mkvpropedit_cmd)
    if mkvpropedit_out != 0:
        mkvpropedit_out = subprocess.call(mkvpropedit_cmd)
        if mkvpropedit_out != 0:
            raise ValueError(
                "mkvpropedit failed with exit code {}".format(mkvpropedit_out)
            )

    if not os.path.exists(course.title):
        logger.info("Creating folder: %s", os.path.abspath(course.title))
        os.makedirs(course.title)
    logger.info(
        "\nMoving %s to %s",
        video_file.replace(".mp4", ".mkv"),
        os.path.abspath(course.title),
    )
    shutil.move(video_file.replace(".mp4", ".mkv"), course.title)

    # if video_subs:
    #     logger.info(
    #         '\nMoving %s to %s',
    #         video_file.replace('.mp4', '.en.srt'),
    #         os.path.abspath(course.title)
    #     )
    #     shutil.move(video_file.replace('.mp4', '.en.srt'), course.title)
    os.remove(video_file)
    if os.path.isfile(video_file.replace(".mp4", ".srt")):
        os.remove(video_file.replace(".mp4", ".srt"))
    return aria_process
