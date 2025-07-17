# The Great Courses Plus Downloader

A command-line interface (CLI) tool to download courses, lectures, and guidebooks from "The Great Courses Plus" (now Wondrium). This tool allows users to download content for offline viewing, with options for video quality, specific lecture ranges, and output directory customization.

## Features

*   **Course and Lecture Download:** Download entire courses or select specific lectures.
*   **Guidebook Download:** Automatically download accompanying PDF guidebooks when available.
*   **Quality Selection:** Choose your preferred video quality (e.g., 360p, 480p, 720p, 1080p).
*   **Lecture Range Selection:** Download a specific range of lectures (e.g., `1-5`, `3`, `1,3,5`).
*   **Resumable Downloads:** Skips already downloaded lectures.
*   **Flexible Output:** Specify the directory where downloaded content will be saved.
*   **Dry Run Mode:** Preview what would be downloaded without actually downloading files.
*   **Logging:** Detailed logging for debugging and monitoring progress.

## Installation

### Prerequisites

*   Python 3.10+
*   `ffmpeg` (for merging video and audio streams)

You can install `ffmpeg` via your system's package manager (e.g., `brew install ffmpeg` on macOS, `sudo apt-get install ffmpeg` on Debian/Ubuntu) or download it from the [official FFmpeg website](https://ffmpeg.org/download.html).

### Using `pip`

```bash
pip install tgc-dl
```

### From Source

1.  Clone the repository:

    ```bash
    git clone https://github.com/your-username/tgc-dl.git
    cd tgc-dl
    ```

2.  Install dependencies:

    ```bash
    pip install -e .
    ```

## Usage

The `tgc-dl` tool is invoked from the command line.

```bash
tgc-dl [OPTIONS] COURSE_URLS...
```

### Arguments

*   `COURSE_URLS`: One or more URLs of the courses you want to download.

### Options

*   `--cookies-file`, `-c`: Path to the `cookies.txt` file. This file is essential for authentication. (Default: `tgcp-cookies.txt` in the current working directory)
*   `--output-directory`, `-o`: Path to where the downloads will be stored. (Default: Current working directory)
*   `--quality`, `-q`: Quality of the video to download (min: 360, max: 1080). (Default: 1080)
*   `--lecture-range`, `-r`: Download a specific range of lectures (e.g., `'1-5'`, `'3'`, `'1,3,5'`). Only applicable when downloading a single course.
*   `--streaming-output`, `-s`: Stream the output from FFMPEG as it is running. (Default: `False`)
*   `--debug`, `-d`: Print debug statements. (Default: `False`)
*   `--dry-run`, `-n`: Dry-run; does not download anything. (Default: `False`)

### Examples

Download a single course with default settings:

```bash
tgc-dl "https://www.wondrium.com/course/the-history-of-ancient-egypt"
```

Download a course to a specific directory and 720p quality:

```bash
tgc-dl -o /path/to/your/downloads -q 720 "https://www.wondrium.com/course/the-history-of-ancient-egypt"
```

Download specific lectures from a course:

```bash
tgc-dl -r "1-3,5" "https://www.wondrium.com/course/the-history-of-ancient-egypt"
```

Perform a dry run to see what would be downloaded:

```bash
tgc-dl -n "https://www.wondrium.com/course/the-history-of-ancient-egypt"
```

## Obtaining `cookies.txt`

To download content, you need to provide a `cookies.txt` file containing your Wondrium (formerly The Great Courses Plus) session cookies. You can obtain this file using browser extensions like [Export Cookies](https://chrome.google.com/webstore/detail/export-cookies/gncdojndgmmjmjgcljchdgnlglfcfhll) for Chrome or [Cookie Quick Manager](https://addons.mozilla.org/en-US/firefox/addon/cookie-quick-manager/) for Firefox.

1.  Log in to your Wondrium (The Great Courses Plus) account in your web browser.
2.  Use the extension to export your cookies in the "Mozilla `cookies.txt`" format.
3.  Save the file as `tgcp-cookies.txt` in the same directory where you run the `tgc-dl` command, or specify its path using the `--cookies-file` option.

## Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This tool is intended for personal use only. Please respect the terms of service of "The Great Courses Plus" (Wondrium).
