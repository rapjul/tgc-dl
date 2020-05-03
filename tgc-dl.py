import http
import requests
from bs4 import BeautifulSoup
import argparse
import logging
import os
import yaml
import json
from m3u8 import parse as m3u8_parse
import re
import shutil
import subprocess
from builtins import input
from pycaption import (
    SCCReader, SCCWriter, SRTReader, SRTWriter, DFXPWriter, WebVTTWriter)

HEADERS = {"Connection": "keep-alive",
           "Pragma": "no-cache",
           "Cache-Control": "no-cache",
           "Sec-Fetch-Dest": "empty",
           "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.100 Safari/537.36",
           "DNT": "1",
           "Accept": "*/*",
           "Origin": "https://www.thegreatcoursesplus.com",
           "Sec-Fetch-Site": "cross-site",
           "Sec-Fetch-Mode": "cors",
           "Referer": "https://www.thegreatcoursesplus.com",
           "Accept-Encoding": "gzip, deflate, br",
           "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7,da;q=0.6,es;q=0.5"}


def clean_filename(filename):
    cleaned_filename = re.sub(r'[/\\?%;*|"<>]', '-', filename).replace(':', " -")
    char_limit = 255
    if len(cleaned_filename) > char_limit:
        print(
            "Warning, filename truncated because it was over {}. Filenames may no longer be unique".format(char_limit))
    return cleaned_filename[:char_limit]


def main():
    script_path = os.path.dirname(os.path.realpath(__file__))
    os.chdir(script_path)

    parser = argparse.ArgumentParser(
        description='The Great Courses Plus python ripper'
    )

    parser.add_argument(
        '-c',
        '--course',
        type=str.lower,
        nargs='+',
        required=True,
        help='Course URL',
    )

    parser.add_argument(
        '-q',
        '--quality',
        type=str.lower,
        nargs='+',
        help='Quality',
    )

    parser.add_argument(
        '-o',
        '--offset',
        type=int,
        nargs='+',
        help='Offset',
    )

    parser.add_argument(
        '-d',
        '--debug',
        action='store_true',
        help='Print debug statements'
    )

    parser.add_argument(
        '-l',
        '--list',
        action='store_true',
        help='Print debug statements'
    )

    args = parser.parse_args()

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %I:%M:%S %p',
        level=loglevel
    )

    logger = logging.getLogger()
    if args.quality is not None:
        quality = '480p'
    else:
        quality = '720p'
    if args.offset is not None:
        offset = args.offset[0]
    else:
        offset = 999
    course = Course(args.course[0])
    cookies = get_cookies(logger)
    fill_objects(course, cookies, logger)
    if args.list:
        # download(course, cookies, quality, logger)
        print(course.ids + ' - ' + course.title)
        if len(course.guidebook) > 0:
            print(' (Includes Guidebook)')
        print('\n')
        print(str(len(course.lectures)) + ' lectures')
        print('\n')
        for lecture in course.lectures:
            print(lecture.number + '. ' + lecture.title)
    else:
        download(course, cookies, quality, offset, logger)
        print(course.ids + ' - ' + course.title)
        if len(course.guidebook) > 0:
            print(' (Includes Guidebook)')
        print('\n')
        print(str(len(course.lectures)) + ' lectures')
        print('\n')
        for lecture in course.lectures:
            print(lecture.number + '. ' + lecture.title)

    return 0


def get_cookies(logger):
    """Returns a dict of cookies"""
    if not os.path.isfile('cookies.txt'):
        logger.error('cookies.txt not found')
        logger.error('Export a cookies.txt file in the same folder of this .py file')

    cookie_jar = http.cookiejar.MozillaCookieJar('cookies.txt')
    cookie_jar.load(ignore_discard=True)

    logger.info('cookies.txt loaded')

    cookies = {}
    for cookie in cookie_jar:
        cookies[cookie.name] = cookie.value
    logger.info('Cookies processed')
    return cookies


def fill_objects(course, cookies, logger):
    course_html = requests.get(course.url, cookies=cookies, headers=HEADERS).text
    soup = BeautifulSoup(course_html, 'html.parser')
    lectures_objs = soup.find_all('div', attrs={'data-lec-id': re.compile('.+')})
    guidebook = soup.find_all("a", string="Course GuideBook (PDF)")
    course.ids = re.sub(r'\-L\d+', '', lectures_objs[0].get('data-lec-id')).replace('ZV', '').strip()

    if len(guidebook) != 0:
        course.guidebook = guidebook[0].get('href')
    else:
        course.guidebook = ''
    if len(soup.find_all("span", class_="professor-info-name")) != 0:
        if len(soup.find_all("span", class_="professor-info-name")[0].contents) == 1:
            course.prof = soup.find_all("span", class_="professor-info-name")[0].contents[0].strip()
        else:
            course.prof = soup.find_all("span", class_="professor-info-name")[0].contents[2].strip()
    else:
        course.prof = ''
    course.title = clean_filename(soup.find_all("div", class_="course-info-container")[0].contents[1].text.strip())
    lectures = []
    for lec in lectures_objs:
        lecture = Lecture(
            ids=lec.get('data-lec-id').strip(),
            number=lec.attrs['data-idx'].zfill(2),
            title=clean_filename(lec.contents[1].attrs['alt'].strip()),
            description=''
        )
        lectures.append(lecture)
    course.lectures = lectures


def download(course, cookies, quality, offset, logger):
    logger.info('Grabbing lectures')
    numb = 1
    for lecture in course.lectures:
        if numb < offset != 999:
            numb += 1
            logger.info('Ignoring lecture ' + lecture.number + ' due to offset')
        else:
            numb += 1
            logger.info('Grabbing lecture ' + lecture.number)
            lecture_html = requests.get(
                'https://link.theplatform.com/s/jESqeC/media/guid/2661884195/' + lecture.ids + '?manifest=m3u',
                cookies=cookies, headers=HEADERS)
            lecture_manifest = requests.get(lecture_html.url, cookies=cookies, headers=HEADERS)
            play_list_json = m3u8_parse(lecture_manifest.text)
            m3u_download = ''
            headers = []
            for key, value in HEADERS.items():
                temp = '"' + key + ':' + value + '"'
                #headers.append('--header')
                headers.append('--header=' + temp)
            best = sd = 0
            for playlist in play_list_json['playlists']:
                if 'index_0' in playlist['uri']:
                    m3u_download = playlist['uri']
            # for playlist in play_list_json['playlists']:
            #     if playlist['stream_info']['resolution'][-3:] == '480' and playlist['stream_info']['bandwidth'] > best and sd == 0:
            #         best = playlist['stream_info']['bandwidth']
            #         m3u_download = playlist['uri']

            aria_out = download_file(course, m3u_download, lecture, cookies, headers, logger)

    aria_command = [
        'aria2c',
        '--allow-overwrite=true',
        '--load-cookies=cookies.txt',
        '--auto-file-renaming=false',
        '--file-allocation=none',
        '--summary-interval=0',
        '--retry-wait=5',
        '--uri-selector=inorder',
        '--download-result=hide',
        '--console-log-level=error',
        '-s16',
        '-j16',
        '-x16',
        '-o',
        course.title + ' Guidebook.pdf',
        course.guidebook
    ]
    aria_out = subprocess.call(aria_command)
    if aria_out != 0:
        aria_out = subprocess.call(aria_command)
        if aria_out != 0:
            raise ValueError(
                'aria2c failed with exit code {}'.format(aria_out)
            )
    logger.info(
        '\nMoving %s to %s',
        course.title + ' Guidebook.pdf',
        os.path.abspath(course.title)
    )
    shutil.move(course.title + ' Guidebook.pdf', course.title)
    logger.info('Finished successfully')
    return


def download_file(course, video_url, lecture, cookies, headers, logger):
    video_file_pre = course.title + ' TGC(' + course.ids + ') S01E' + lecture.number + ' - ' + lecture.title + 'no.mp4'
    video_file = course.title + ' TGC(' + course.ids + ') S01E' + lecture.number + ' - ' + lecture.title + '.mp4'
    segment_url = requests.get(video_url, cookies=cookies, headers=HEADERS)
    m3u_segs = m3u8_parse(segment_url.text)
    segments_files = []

    with open(course.ids + lecture.number + '.txt', 'w') as f:
        for index, item in enumerate(m3u_segs['segments']):
            f.write("%s\n" % item['uri'])
            segments_files.append(course.ids + lecture.number + '/segment' + str(index+1) + '_0_av.ts')
        # r = requests.get(item['uri'], allow_redirects=True, cookies=cookies, headers=HEADERS)

        # open(course.ids + lecture.number + str(index) + '.ts', 'wb').write(r.content)

    # for index, item in enumerate(segments_files):

    aria_command = [
        'aria2c',
        '--enable-color=false',
        '--load-cookies=cookies.txt',
        '--allow-overwrite=true',
        '--auto-file-renaming=false',
        '--file-allocation=none',
        '--summary-interval=0',
        '--retry-wait=5',
        '--uri-selector=inorder',
        '--console-log-level=warn',
        '--allow-piece-length-change=true',
        '--download-result=hide',
        '--dir=' + course.ids + lecture.number,
        '-x16',
        '-j16',
        '-s16'
        ]
    aria_command += headers
    aria_command += [
        '-i',
        course.ids + lecture.number + '.txt']


    # aria_command = ['ccextractor', video_file]
    # aria_command += headers
    # aria_command += '-o', '"' + video_file + '"'

    # if proxies:
    #     aria_command.append('--all-proxy={}'.format(proxies))
    #
    # if custom_dns:
    #     aria_command.append(
    #         '--async-dns-server=' + ','.join(custom_dns)
    #     )
    #
    # aria_command_video = aria_command.copy()
    # aria_command_video.append(video_url)
    # aria_command_subs = aria_command.copy()
    # aria_command_subs[14] = aria_command_subs[14].replace('no.mp4', '.en.srt')
    # aria_command_subs.append(video_subs)
    #
    logger.debug('Starting aria2c with params:')
    logger.debug(aria_command)

    aria_out = subprocess.call(' '.join(map(str, aria_command)), shell=True)
    if aria_out != 0:
        aria_out = subprocess.call(aria_command)
        if aria_out != 0:
            raise ValueError(
                'aria2c failed with exit code {}'.format(aria_out)
            )
    # if video_subs:
    #     aria_out = subprocess.call(aria_command_subs)
    #     if aria_out != 0:
    #
    #         aria_out = subprocess.call(aria_command_subs)
    #         if aria_out != 0:
    #             raise ValueError(
    #                 'aria2c failed with exit code {}'.format(aria_out)
    #             )
    #
    # if aria_out == 0:
    #     logger.info("")
    #     logger.info("Preparing to mux video files")
    #
    if aria_out == 0:
        logger.info("")
        logger.info("Preparing to mux video files")

    with open(video_file, "wb") as output:
        for segment in segments_files:
            if os.path.isfile(segment):
                file = open(segment, "rb")
                shutil.copyfileobj(file, output)
                file.close()
                os.remove(segment)
    os.rmdir(course.ids + lecture.number)
    os.remove(course.ids + lecture.number + '.txt')
    logger.info("Extracting CC subs")
    aria_command = ['ccextractor', '-quiet', video_file]
    aria_out = subprocess.call(aria_command)

    if os.stat(video_file.replace('.mp4', '.srt')).st_size < 5:
        os.remove(video_file.replace('.mp4', '.srt'))

    mkvmerge_exec = 'mkvmerge'
    if os.path.isfile(video_file.replace('.mp4', '.srt')):
        params = [video_file,
                  '--language',
                  '0:eng',
                  '--track-name',
                  '0:Subtitle',
                  '--sub-charset',
                  '0:UTF-8',
                  video_file.replace('.mp4', '.srt')]
        mkvmerge_command = [
            mkvmerge_exec,
            '-o',
            video_file.replace('.mp4', '.mkv'),
        ]
    else:
        params = [video_file]
        mkvmerge_command = [
            mkvmerge_exec,
            '-o',
            video_file.replace('.mp4', '.mkv')
        ]

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
    #
    mkvpropedit_cmd = [
        'mkvpropedit',
        video_file.replace('.mp4', '.mkv'),
        '--edit',
        'track:a1',
        '--set',
        'language=eng'
    ]

    mkvpropedit_out = subprocess.call(mkvpropedit_cmd)
    if mkvpropedit_out != 0:
        mkvpropedit_out = subprocess.call(mkvpropedit_cmd)
        if mkvpropedit_out != 0:
            raise ValueError(
                'mkvpropedit failed with exit code {}'.format(mkvpropedit_out)
            )
    #
    if not os.path.exists(course.title):
        logger.info('Creating folder: %s',
                    os.path.abspath(course.title))
        os.makedirs(course.title)
    logger.info(
        '\nMoving %s to %s',
        video_file.replace('.mp4', '.mkv'),
        os.path.abspath(course.title)
    )
    shutil.move(video_file.replace('.mp4', '.mkv'), course.title)
    #
    # if video_subs:
    #     logger.info(
    #         '\nMoving %s to %s',
    #         video_file.replace('.mp4', '.en.srt'),
    #         os.path.abspath(course.title)
    #     )
    #     shutil.move(video_file.replace('.mp4', '.en.srt'), course.title)
    os.remove(video_file)
    if os.path.isfile(video_file.replace('.mp4', '.srt')):
        os.remove(video_file.replace('.mp4', '.srt'))
    return aria_out


class Course:
    def __init__(self, url, ids="", prof="", title="", guidebook="", lectures=""):
        self.url = url
        self.ids = ids
        self.prof = prof
        self.title = title
        self.guidebook = guidebook
        self.lectures = lectures


class Lecture:
    def __init__(self, ids, number, title, description):
        self.ids = ids
        self.number = number
        self.title = title
        self.description = description


if __name__ == '__main__':
    main()
