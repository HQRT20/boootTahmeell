import re
import logging
from typing import List, Tuple

from media_modules._utils import UA, get_requests_cookies, get_playwright_cookies, download_url, find_brave_exe

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

log = logging.getLogger("downloader.twitter.playwright")

def playwright_twitter(url: str) -> Tuple[List[str], str]:
    if not PLAYWRIGHT_AVAILABLE:
        return [], ""

    title = "Twitter Media"
    try:
        with sync_playwright() as p:
            launch_args = {'headless': True, 'args': ['--disable-blink-features=Automation', '--no-sandbox']}
            brave = find_brave_exe()
            browser = None
            if brave:
                try:
                    browser = p.chromium.launch(executable_path=brave, **launch_args)
                except Exception:
                    pass
            if not browser:
                for channel in ('chrome', 'msedge', 'chromium'):
                    try:
                        browser = p.chromium.launch(channel=channel, **launch_args)
                        break
                    except Exception:
                        continue
            if not browser:
                try:
                    browser = p.chromium.launch(**launch_args)
                except Exception as e:
                    log.debug("playwright launch failed: %s", e)
                    return [], ""

            context = None
            try:
                context = browser.new_context(viewport={'width': 1280, 'height': 900}, user_agent=UA)
                pw_cookies = get_playwright_cookies()
                if pw_cookies:
                    context.add_cookies(pw_cookies)
                page = context.new_page()
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(3500)

                media_urls = []
                for el in page.query_selector_all('img[src*="pbs.twimg.com/media"], video[src*="video.twimg.com"]'):
                    src = el.get_attribute('src')
                    if src:
                        media_urls.append(src)
                for el in page.query_selector_all('video source[src]'):
                    src = el.get_attribute('src')
                    if src:
                        media_urls.append(src)

                content = page.content()
                media_urls += re.findall(r'https://pbs\.twimg\.com/media/[A-Za-z0-9_\-]+\?[^"\'\s]+', content)
                media_urls += re.findall(r'https://video\.twimg\.com/[^"\'\s]+\.mp4[^"\'\s]*', content)

                try:
                    title = (page.title() or title).split(' / ')[0][:100]
                except Exception:
                    pass

                cookies = get_requests_cookies()
                files: List[str] = []
                seen = set()
                for mu in media_urls:
                    key = mu.split('?')[0]
                    if key in seen:
                        continue
                    seen.add(key)
                    f = download_url(mu, "tw_pw", cookies=cookies, referer="https://twitter.com/")
                    if f:
                        files.append(f)
                    if len(files) >= 10:
                        break
                return files, title
            finally:
                try:
                    if context:
                        context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        log.debug("playwright twitter failed: %s", e)
    return [], ""
